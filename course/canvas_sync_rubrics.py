#!/usr/bin/env python3
"""
canvas_sync_rubrics.py -- replace Canvas rubrics for a *named subset* of assignments.

Why this exists
---------------
`ursinus_canvas_update_rubrics.py`, beside this file, already replaces rubrics
without touching assignments, modules, or events. What it does not do is scope: it
rewrites *every* rubric in the course. Replacing a rubric deletes it,
and deleting a rubric discards any rubric assessments recorded against it, so an
unscoped run against a live mid-term shell can silently destroy per-criterion scores
on assignments you never meant to touch.

This script does the same replacement, for only the assignments you name, and refuses
by default to clobber a rubric that has already been used for grading. It is dry-run
by default.

The rubric payload it builds is deliberately identical to the boilerplate's
(`build_rubric_payload_exact`), including the 25/50/85/100 percent rating scale, so
the two scripts cannot produce different rubrics from the same source markdown.

Selecting assignments
---------------------
    --only <selector>     repeatable. Matches a deliverable's `dlink`
                          (e.g. Assignments/AgentSystemDesign), its `rubricpath`, or
                          the Canvas assignment name.
    --changed [<ref>]     select every deliverable whose `rubricpath` file differs
                          from <ref>. The default, HEAD, means "what I have edited but
                          not yet committed", which is the usual case: you just changed
                          some rubrics and want those pushed. After committing, name a
                          ref instead (`--changed origin/gh-pages`) or use --only.

One of the two is required. There is no "all" mode on purpose; if you want every
rubric replaced, ursinus_canvas_update_rubrics.py already does that and you should
mean it.

Usage
-----
Run these from the root of a course website repository, where this repository is
mounted as the `code` submodule.

    # dry run: what would change, and what it would cost
    python code/course/canvas_sync_rubrics.py \
        --markdown _pages/syllabus.md \
        --courseid 12345 \
        --only Assignments/AgentSystemDesign

    # same, but derive the set from what you have edited and not yet committed
    python code/course/canvas_sync_rubrics.py -m _pages/syllabus.md -c 12345 --changed

    # commit it
    python code/course/canvas_sync_rubrics.py -m _pages/syllabus.md -c 12345 \
        --only Assignments/AgentSystemDesign --apply

    # parse and validate the local rubric only; no Canvas, no credentials
    python code/course/canvas_sync_rubrics.py -m _pages/syllabus.md --only Assignments/AgentSystemDesign --list

Requires `canvasapi` and `python-frontmatter` for anything that contacts Canvas.
`--list` needs only `python-frontmatter`.
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time
import traceback
from urllib import parse, request

DEFAULT_API_URL = "https://ursinus.instructure.com/"
DEFAULT_DIFF_BASE = "HEAD"

# The shared rating scale. Do not change these independently of
# ursinus_canvas_update_rubrics.py, or the two scripts will disagree.
RATING_SCALE = [
    ("Pre-Emerging", "preemerging", 0.25),
    ("Beginning", "beginning", 0.50),
    ("Progressing", "progressing", 0.85),
    ("Proficient", "proficient", 1.00),
]


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def rchop(s, suffix):
    return s[: -len(suffix)] if (suffix and s.endswith(suffix)) else s


def sleep_for_rate_limit():
    time.sleep(random.randint(2, 6))


def die(msg, code=2):
    print("error: %s" % msg, file=sys.stderr)
    sys.exit(code)


def warn(msg):
    print("warning: %s" % msg, file=sys.stderr)


# --------------------------------------------------------------------------
# syllabus parsing
# --------------------------------------------------------------------------

def load_deliverables(markdown_path):
    """Return the deliverables in the syllabus that name a rubricpath.

    Mirrors the boilerplate's filtering: strip a trailing " Due", skip
    "... Handed Out" rows and quizzes. Deduplicates on (name, rubricpath), because a
    deliverable appears twice in the schedule (handed out and due) and resolves to
    one Canvas assignment.
    """
    import frontmatter

    with open(markdown_path, "r", encoding="utf-8") as fh:
        post = frontmatter.loads(fh.read())
    doc = post.to_dict()

    found = []
    seen = set()
    for item in doc.get("schedule", []) or []:
        for deliverable in item.get("deliverables", []) or []:
            dtitle = (deliverable.get("dtitle") or "").strip()
            if not dtitle:
                continue
            name = rchop(dtitle, " Due")
            lowered = name.lower()
            if " handed out" in lowered or "quiz:" in lowered:
                continue

            rubricpath = deliverable.get("rubricpath")
            if not rubricpath:
                continue

            key = (name, rubricpath)
            if key in seen:
                continue
            seen.add(key)

            found.append({
                "name": name,
                "dlink": deliverable.get("dlink"),
                "rubricpath": rubricpath,
                "points": int(deliverable.get("points", 100)),
            })
    return found


def changed_rubric_files(base_ref):
    """Files that differ from base_ref, plus anything uncommitted, via git."""
    if base_ref == "HEAD":
        # working tree only; no merge-base to compute
        merge_base = "HEAD"
    else:
        try:
            merge_base = subprocess.check_output(
                ["git", "merge-base", base_ref, "HEAD"], text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            warn("no merge-base with %s; diffing against it directly" % base_ref)
            merge_base = base_ref

    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", merge_base, "--"], text=True
        )
    except subprocess.CalledProcessError as exc:
        die("git diff failed: %s" % exc)

    tracked = set(p.strip() for p in out.splitlines() if p.strip())

    # include uncommitted work too; the usual case is running this right after editing
    try:
        out = subprocess.check_output(["git", "status", "--porcelain"], text=True)
        for line in out.splitlines():
            path = line[3:].strip()
            if path:
                tracked.add(path)
    except subprocess.CalledProcessError:
        pass

    return tracked


def rubric_at_ref(ref, path):
    """The info.rubric block as it stood at `ref`, or None if unreadable."""
    import frontmatter

    try:
        blob = subprocess.check_output(
            ["git", "show", "%s:%s" % (ref, path)], text=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return None  # new file, or not tracked at that ref
    try:
        return (frontmatter.loads(blob).to_dict().get("info") or {}).get("rubric")
    except Exception:
        return None


def select(deliverables, only, changed_paths, base_ref=None):
    """Filter deliverables by --only selectors and/or --changed paths.

    A file can change without its rubric changing: an edit to the body prose, a goal
    bullet, or a time estimate touches the file but leaves info.rubric alone. Replacing
    a rubric is destructive, so under --changed we compare the rubric itself against the
    base ref and skip the ones that are byte-identical. --only is an explicit request and
    is never filtered this way.
    """
    chosen, unmatched, unchanged = [], [], []

    if changed_paths is not None:
        normalized = set(os.path.normpath(p) for p in changed_paths)
        for d in deliverables:
            if os.path.normpath(d["rubricpath"]) not in normalized:
                continue
            if base_ref:
                before = rubric_at_ref(base_ref, d["rubricpath"])
                try:
                    after = read_rubric(d["rubricpath"])
                except Exception:
                    after = None
                if before is not None and after is not None and before == after:
                    unchanged.append(d["name"])
                    continue
            chosen.append(d)

    for selector in only or []:
        s = selector.strip().strip("/")
        hits = [
            d for d in deliverables
            if s == (d.get("dlink") or "").strip("/")
            or os.path.normpath(s) == os.path.normpath(d["rubricpath"])
            or s.lower() == d["name"].lower()
        ]
        if not hits:
            unmatched.append(selector)
            continue
        for h in hits:
            if h not in chosen:
                chosen.append(h)
            if h["name"] in unchanged:
                unchanged.remove(h["name"])

    return chosen, unmatched, unchanged


# --------------------------------------------------------------------------
# rubric payload (byte-compatible with the boilerplate)
# --------------------------------------------------------------------------

def read_rubric(rubricpath):
    """Return the rubric rows from a assignment page's info block."""
    import frontmatter

    with open(rubricpath, "r", encoding="utf-8") as fh:
        doc = frontmatter.loads(fh.read()).to_dict()

    info = doc.get("info") or {}
    rubric = info.get("rubric")
    if not rubric:
        raise ValueError("no info.rubric found in %s" % rubricpath)
    return rubric


def validate_rubric(rubric, rubricpath):
    """Catch the mistakes that are cheap here and expensive in Canvas."""
    problems = []

    total = 0.0
    for idx, row in enumerate(rubric):
        where = "%s row %d" % (rubricpath, idx + 1)
        if "weight" not in row:
            problems.append("%s: no weight" % where)
        else:
            try:
                total += float(row["weight"])
            except (TypeError, ValueError):
                problems.append("%s: weight %r is not a number" % (where, row["weight"]))
        if not row.get("description"):
            problems.append("%s: no description" % where)
        for _, key, _ in RATING_SCALE:
            if not row.get(key):
                problems.append("%s: no '%s' level" % (where, key))

    if abs(total - 100.0) > 0.001:
        problems.append("%s: weights sum to %g, not 100" % (rubricpath, total))

    return problems


def build_rubric_payload(rubric, assignment_id, assignment_name, points):
    """Identical in shape to the boilerplate's build_rubric_payload_exact."""
    payload = {
        "rubric_association_id": assignment_id,
        "rubric": {
            "title": assignment_name + " Rubric",
            "points_possible": points,
            "free_form_criterion_comments": False,
            "skip_updating_points_possible": False,
            "read_only": False,
            "reusable": True,
            "criteria": {},
        },
        "rubric_association": {
            "use_for_grading": True,
            "purpose": "grading",
            "association_id": assignment_id,
            "association_type": "Assignment",
            "bookmarked": True,
        },
    }

    for idx, criterion in enumerate(rubric):
        criterion_points = points * float(criterion["weight"]) / 100.0
        ratings = {}
        for rating_idx, (label, key, fraction) in enumerate(RATING_SCALE):
            ratings[rating_idx] = {
                "description": label,
                "long_description": criterion[key],
                "points": criterion_points * fraction,
            }
        payload["rubric"]["criteria"][idx] = {
            "description": criterion["description"],
            "long_description": criterion["description"],
            "criterion_use_range": True,
            "points": criterion_points,
            "ratings": ratings,
        }

    return payload


# --------------------------------------------------------------------------
# Canvas
# --------------------------------------------------------------------------

class Canvas(object):
    """Thin wrapper over canvasapi plus the raw endpoints it does not surface."""

    def __init__(self, api_url, api_key, course_id):
        from canvasapi import Canvas as CanvasAPI

        self.api_url = api_url
        self.api_key = api_key
        self._canvas = CanvasAPI(api_url, api_key)
        self.course = self._canvas.get_course(course_id)
        self._assignments = None

    def _http(self, endpoint, method="GET", fields=None):
        headers = {"Authorization": "Bearer %s" % self.api_key}
        data = None
        if fields is not None:
            data = parse.urlencode(fields).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = request.Request(
            rchop(self.api_url, "/") + endpoint, data=data, headers=headers, method=method
        )
        return request.urlopen(req)

    def assignments(self):
        if self._assignments is None:
            self._assignments = list(self.course.get_assignments())
        return self._assignments

    def find_assignment(self, name):
        target = name.strip()
        for a in self.assignments():
            if a.name.strip() == target:
                return a
        return None

    def rubric_meta(self, assignment_id):
        """Current rubric id, association id, criteria count, and points."""
        sleep_for_rate_limit()
        raw = self._http("/api/v1/courses/%s/assignments/%s" % (self.course.id, assignment_id)).read()
        data = json.loads(raw.decode("utf-8"))
        settings = data.get("rubric_settings") or {}
        criteria = data.get("rubric") or []
        return {
            "rubric_id": settings.get("id"),
            "association_id": settings.get("rubric_association_id"),
            "criteria_count": len(criteria),
            "points": settings.get("points_possible"),
            "title": settings.get("title"),
        }

    def grading_exposure(self, assignment):
        """How much grading would be lost: (submissions, rubric assessments)."""
        submitted = 0
        assessed = 0
        try:
            sleep_for_rate_limit()
            for sub in assignment.get_submissions(include=["rubric_assessment"]):
                if getattr(sub, "workflow_state", "unsubmitted") != "unsubmitted":
                    submitted += 1
                if getattr(sub, "rubric_assessment", None):
                    assessed += 1
        except Exception as exc:  # a shell with no submissions yet, or no permission
            warn("could not read submissions for '%s': %s" % (assignment.name, exc))
            return (None, None)
        return (submitted, assessed)

    def delete_rubric(self, meta):
        if meta.get("association_id"):
            sleep_for_rate_limit()
            self._http(
                "/api/v1/courses/%s/rubric_associations/%s" % (self.course.id, meta["association_id"]),
                method="DELETE",
            )
            print("    deleted rubric association %s" % meta["association_id"])
        if meta.get("rubric_id"):
            sleep_for_rate_limit()
            self._http(
                "/api/v1/courses/%s/rubrics/%s" % (self.course.id, meta["rubric_id"]),
                method="DELETE",
            )
            print("    deleted rubric %s" % meta["rubric_id"])

    def create_rubric(self, payload):
        sleep_for_rate_limit()
        self.course.create_rubric(**payload)


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def describe(deliverable, rubric, meta, exposure):
    """One assignment's before-and-after, printed before anything is written."""
    print("  %s" % deliverable["name"])
    print("    source        %s (%d points)" % (deliverable["rubricpath"], deliverable["points"]))

    if meta is None:
        print("    current       (assignment not matched in Canvas)")
    elif meta["rubric_id"]:
        print("    current       %d criteria, %s points, %r"
              % (meta["criteria_count"], meta["points"], meta["title"]))
    else:
        print("    current       no rubric attached")

    weights = ", ".join(str(row.get("weight")) for row in rubric)
    print("    new           %d criteria, weights %s" % (len(rubric), weights))

    if meta and meta["rubric_id"] and meta["criteria_count"] != len(rubric):
        print("    NOTE          criteria count changes %d -> %d"
              % (meta["criteria_count"], len(rubric)))

    if exposure is not None:
        submitted, assessed = exposure
        if submitted is None:
            print("    grading       unknown (could not read submissions)")
        else:
            print("    grading       %d submissions, %d graded through this rubric"
                  % (submitted, assessed))
            if assessed:
                print("    WARNING       replacing this rubric DISCARDS %d rubric assessment(s)"
                      % assessed)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Replace Canvas rubrics for a named subset of assignments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-m", "--markdown", required=True, help="path to _pages/syllabus.md")
    p.add_argument("-c", "--courseid", type=int, default=None, help="numeric Canvas course id")
    p.add_argument("-a", "--apikey", default=None, help="Canvas API key (prompted if omitted)")
    p.add_argument("-u", "--userid", default=None, help="Canvas user id, used only to verify the token")
    p.add_argument("--api-url", default=DEFAULT_API_URL, help="Canvas base URL (default: %s)" % DEFAULT_API_URL)
    p.add_argument("--only", action="append", metavar="SELECTOR",
                   help="assignment to update, by dlink, rubricpath, or Canvas name. Repeatable.")
    p.add_argument("--changed", nargs="?", const=DEFAULT_DIFF_BASE, default=None, metavar="REF",
                   help="select every deliverable whose rubric file changed vs REF. Default %s, "
                        "meaning uncommitted edits in the working tree." % DEFAULT_DIFF_BASE)
    p.add_argument("--apply", action="store_true", help="actually write to Canvas (default is a dry run)")
    p.add_argument("--force-graded", action="store_true",
                   help="replace a rubric even though it already carries rubric assessments")
    p.add_argument("--list", action="store_true",
                   help="resolve and validate locally, contact Canvas not at all")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not args.only and args.changed is None:
        die("pass --only <selector> or --changed. There is no all-rubrics mode here; "
            "ursinus_canvas_update_rubrics.py, beside this script, is that tool.")

    if not os.path.exists(args.markdown):
        die("no such syllabus: %s" % args.markdown)

    deliverables = load_deliverables(args.markdown)
    if not deliverables:
        die("no deliverables with a rubricpath found in %s" % args.markdown)

    changed = changed_rubric_files(args.changed) if args.changed is not None else None
    chosen, unmatched, unchanged = select(deliverables, args.only, changed, args.changed)

    if unchanged:
        print("Skipping %d file(s) that changed but whose rubric did not: %s\n"
              % (len(unchanged), ", ".join(unchanged)))

    if unmatched:
        die("no deliverable matches: %s\nknown dlinks:\n  %s"
            % (", ".join(unmatched),
               "\n  ".join(sorted(set(d.get("dlink") or d["rubricpath"] for d in deliverables)))))

    if not chosen:
        print("Nothing selected; no rubric files changed. Nothing to do.")
        return 0

    # Parse and validate every rubric before touching Canvas at all.
    problems = []
    for d in chosen:
        if not os.path.exists(d["rubricpath"]):
            problems.append("%s: file not found" % d["rubricpath"])
            continue
        try:
            d["rubric"] = read_rubric(d["rubricpath"])
        except Exception as exc:
            problems.append("%s: %s" % (d["rubricpath"], exc))
            continue
        problems.extend(validate_rubric(d["rubric"], d["rubricpath"]))

    if problems:
        for problem in problems:
            print("  - %s" % problem, file=sys.stderr)
        die("%d rubric problem(s); nothing was sent to Canvas" % len(problems))

    print("Selected %d assignment(s):" % len(chosen))

    if args.list:
        for d in chosen:
            describe(d, d["rubric"], None, None)
        print("\n--list: local validation only; Canvas was not contacted.")
        return 0

    if args.courseid is None:
        die("--courseid is required unless you pass --list")

    api_key = args.apikey or os.environ.get("CANVAS_API_KEY")
    if not api_key:
        api_key = input("Enter API key (from %sprofile/settings): " % args.api_url).strip()
    if not api_key:
        die("an API key is required")

    try:
        canvas = Canvas(args.api_url, api_key, args.courseid)
    except ImportError:
        die("canvasapi is not installed: pip install canvasapi python-frontmatter")
    except Exception as exc:
        die("could not open course %s: %s" % (args.courseid, exc))

    if args.userid:
        try:
            canvas._canvas.get_user(args.userid)
        except Exception as exc:
            warn("could not verify user %s: %s" % (args.userid, exc))

    # Resolve, report, and decide, before any write.
    plan, missing, blocked = [], [], []
    for d in chosen:
        assignment = canvas.find_assignment(d["name"])
        if assignment is None:
            missing.append(d["name"])
            describe(d, d["rubric"], None, None)
            continue

        meta = canvas.rubric_meta(assignment.id)
        exposure = canvas.grading_exposure(assignment)
        describe(d, d["rubric"], meta, exposure)

        _, assessed = exposure
        if assessed and not args.force_graded:
            blocked.append(d["name"])
            continue

        plan.append((d, assignment, meta))

    if missing:
        die("not found in Canvas: %s\nCreate them with the full deploy first; this script "
            "does not create assignments." % ", ".join(missing))

    if blocked:
        die("refusing to replace %d rubric(s) already used for grading: %s\n"
            "Those per-criterion scores would be lost. Re-run with --force-graded only if "
            "you have confirmed that is acceptable." % (len(blocked), ", ".join(blocked)))

    if not args.apply:
        print("\nDry run. %d rubric(s) would be replaced. Re-run with --apply to commit."
              % len(plan))
        return 0

    failures = 0
    for d, assignment, meta in plan:
        print("\n  replacing rubric for '%s'" % assignment.name)
        try:
            canvas.delete_rubric(meta)
            payload = build_rubric_payload(d["rubric"], assignment.id, assignment.name, d["points"])
            canvas.create_rubric(payload)
            print("    recreated from %s" % d["rubricpath"])
        except Exception as exc:
            failures += 1
            print("    FAILED: %s" % exc, file=sys.stderr)
            traceback.print_exc()

    if failures:
        die("%d of %d replacement(s) failed" % (failures, len(plan)), code=1)

    print("\nReplaced %d rubric(s)." % len(plan))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
