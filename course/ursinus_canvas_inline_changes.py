#!/usr/bin/env python3
"""
ursinus_canvas_inline_changes.py -- apply a small, explicit set of edits to a live
Canvas shell, described inline on stdin.

Why this exists
---------------
The other Canvas scripts beside this one are each shaped by one source of truth:
`ursinus_canvas.py` rebuilds a shell from the syllabus, `canvas_sync_rubrics.py`
replaces rubrics from the syllabus, `ursinus_canvas_update_schedule_inplace.py`
re-derives dates from the syllabus. All of them answer the question "make Canvas
match the repository."

That is the wrong tool for the times you know exactly what you want changed and
the repository is not the reason. A section was cancelled. A due date slipped by
a week after an email. An assignment needs unpublishing before students see it.
A module needs one item moved. Re-deriving the whole shell to move one date is
how graded work gets destroyed by a script that was only trying to help.

This script takes a list of operations, describes what each one would do against
the live shell, and refuses to write anything until you pass --apply. It never
consults the syllabus, so it never "helpfully" reverts an edit you made in the
Canvas UI. It is deliberately narrow: assignments, assignment groups, modules,
module items, due dates, and detaching a rubric. It does not create rubrics;
`canvas_sync_rubrics.py`, beside this file, is that tool.

Two modes
---------
**--generate** compares the repository you are standing in against a live Canvas
shell and writes a change document to stdout. Run it from the repo root; it reads
`_pages/syllabus.md` (or --markdown) and reports every assignment whose due date,
points, or page link has drifted from the shell, plus assignments the syllabus
does not account for. Nothing is written to Canvas in this mode.

    python code/course/ursinus_canvas_inline_changes.py --generate -c 12345 > changes.yaml
    python code/course/ursinus_canvas_inline_changes.py --generate -c 12345 \
        | python code/course/ursinus_canvas_inline_changes.py -c 12345 --apply

Without --generate the script *applies* a change document, which it reads from
stdin unless --file names one.

Input
-----
The change document arrives on stdin (or via --file). Any of these parse:

    YAML       changes:
                 - op: assignment.due
                   name: "Project: Final Project Proposal"
                   due: 2026-10-29

    JSON       {"changes": [{"op": "assignment.due", ...}]}

    dict-style {'changes': [{'op': 'assignment.due', ...}]}

A bare list of operations, with no `changes:` key, is also accepted. Every
operation is a mapping with an `op` and whatever that op needs.

Operations
----------
    assignment.create   name, points, [due], [group], [published], [description],
                        [url], [submission_types], [position]
    assignment.update   name (or id), then any of: rename, points, due, unlock,
                        lock, group, published, description, url, position,
                        omit_from_final_grade
    assignment.due      name (or id), due            -- shorthand for the above
    assignment.delete   name (or id)
    rubric.detach       name (or id)                 -- drop the rubric from an assignment
    group.create        name, [weight], [position]
    group.update        name (or id), [rename], [weight], [position]
    group.delete        name (or id), [move_to]
    module.create       name, [position], [published]
    module.update       name (or id), [rename], [position], [published]
    module.delete       name (or id)
    item.add            module, title, type, [content: assignment name], [position],
                        [url], [indent], [published]
    item.remove         module, title
    item.move           module, title, position (or to_module)

Due dates
---------
`due: 2026-10-29` means "the student-facing due day is October 29", and is
converted with the same convention `ursinus_canvas.py` uses: 11:59 PM local on
that day, expressed as 03:59:59Z (daylight time) or 04:59:59Z (standard time) on
the following morning. Pass a full `2026-10-30T03:59:59Z` instead and it is sent
verbatim. `due: null` clears the due date.

Usage
-----
    # dry run: resolve every operation against the live shell and print the plan
    python code/course/ursinus_canvas_inline_changes.py -c 12345 < changes.yaml

    # same, reading the document from a file
    python code/course/ursinus_canvas_inline_changes.py -c 12345 -f changes.yaml

    # commit it
    python code/course/ursinus_canvas_inline_changes.py -c 12345 --apply < changes.yaml

    # here-document, for a couple of edits you do not want to keep
    python code/course/ursinus_canvas_inline_changes.py -c 12345 --apply <<'EOF'
    changes:
      - op: assignment.due
        name: "Project: Final Project Proposal"
        due: 2026-10-29
    EOF

The course id and API key are prompted for if not passed. The key is also read
from $CANVAS_API_KEY.

Safety
------
Dry run is the default and prints, for every operation, what it resolved to and
what it would change. `assignment.delete` additionally reports how many
submissions exist and refuses to run if there are any, unless you pass
--allow-delete-with-submissions. Deleting a Canvas assignment deletes its
submissions and grades with it, and no flag brings them back.

What --generate compares
------------------------
Assignments only: due date, points, and the page link in the description, plus a
commented-out delete for anything in Canvas the syllabus does not name. Modules
and module items are not diffed, because reconciling them safely means deciding
what a reordered module means for released content; `rebuild_all_modules` in
`ursinus_canvas_update_schedule_inplace.py` is the tool that takes that on. Every
delete it emits is commented out and annotated with its submission count, so a
generated document can never destroy student work by being piped straight back in.

Requires `canvasapi`. PyYAML is used when present; without it, JSON and
dict-style input still parse. --generate additionally needs `python-frontmatter`,
`python-dateutil`, and `pytz`, which the sibling schedule script already requires.
"""

import argparse
import ast
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from urllib import parse, request

DEFAULT_API_URL = "https://ursinus.instructure.com/"

# Matches ursinus_canvas.py: a deliverable listed on day D is due 11:59 PM local
# that day, which is 03:59:59Z (EDT) or 04:59:59Z (EST) on D+1.
DUE_TIME_DST = "03:59:59"
DUE_TIME_ST = "04:59:59"
DUE_DATE_OFFSET = 1
LOCAL_TZ = "US/Eastern"

OPS = (
    "assignment.create", "assignment.update", "assignment.due", "assignment.delete",
    "rubric.detach",
    "group.create", "group.update", "group.delete",
    "module.create", "module.update", "module.delete",
    "item.add", "item.remove", "item.move",
)


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


def as_bool(value):
    """Accept real booleans, and the strings people actually type."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in ("true", "yes", "y", "1", "on", "published"):
        return True
    if text in ("false", "no", "n", "0", "off", "unpublished"):
        return False
    die("%r is not a true/false value" % value)


def is_dst(when):
    """True if US/Eastern is on daylight time on this date."""
    try:
        import pytz
        return bool(pytz.timezone(LOCAL_TZ).localize(when).dst())
    except ImportError:
        pass
    try:
        from zoneinfo import ZoneInfo
        return bool(when.replace(tzinfo=ZoneInfo(LOCAL_TZ)).dst())
    except Exception:
        # Second Sunday in March to first Sunday in November, close enough to
        # warn on and never silently wrong by more than an hour.
        return 3 < when.month < 11


# --------------------------------------------------------------------------
# input parsing
# --------------------------------------------------------------------------

def parse_document(text):
    """Parse YAML, JSON, or a Python dict literal into a list of operations."""
    text = text.strip()
    if not text:
        die("no change document on stdin (or --file); nothing to do")

    doc, errors = None, []

    try:
        import yaml
        doc = yaml.safe_load(text)
    except ImportError:
        errors.append("PyYAML not installed, so YAML input is unavailable")
    except Exception as exc:
        errors.append("as YAML: %s" % exc)

    if doc is None:
        try:
            doc = json.loads(text)
        except Exception as exc:
            errors.append("as JSON: %s" % exc)

    if doc is None:
        try:
            doc = ast.literal_eval(text)
        except Exception as exc:
            errors.append("as a Python literal: %s" % exc)

    if doc is None:
        die("could not parse the change document:\n  %s" % "\n  ".join(errors))

    if isinstance(doc, dict):
        changes = doc.get("changes", doc.get("operations"))
        if changes is None:
            # a single bare operation
            changes = [doc] if "op" in doc else None
        if changes is None:
            die("the document has no 'changes' list and is not itself an operation")
    elif isinstance(doc, list):
        changes = doc
    else:
        die("expected a mapping or a list, got %s" % type(doc).__name__)

    if isinstance(changes, list) and not changes:
        # `changes: []` is what --generate emits when nothing has drifted. Piping
        # that straight back in should be a clean no-op, not an error.
        print("The change document contains no operations; nothing to do.")
        sys.exit(0)
    if not changes:
        die("the change document contains no operations")

    normalized = []
    for idx, change in enumerate(changes):
        if not isinstance(change, dict):
            die("operation %d is %s, not a mapping" % (idx + 1, type(change).__name__))
        op = (change.get("op") or change.get("operation") or "").strip()
        if not op:
            die("operation %d has no 'op'" % (idx + 1))
        if op not in OPS:
            die("operation %d: unknown op %r\nknown ops:\n  %s"
                % (idx + 1, op, "\n  ".join(OPS)))
        change = dict(change)
        change["op"] = op
        change["_index"] = idx + 1
        normalized.append(change)
    return normalized


def canvas_due(value, field="due"):
    """Convert a change document's date into what Canvas wants.

    A bare date is the student-facing due day and gets the boilerplate's
    11:59 PM local convention. Anything already carrying a time is sent as-is.
    None clears the date.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.strftime("%Y-%m-%d")
    else:
        value = str(value).strip()
        if not value:
            return None

    if "T" in value:  # already an instant; trust the author
        return value

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            day = datetime.strptime(value, fmt)
            break
        except ValueError:
            day = None
    if day is None:
        die("%s: %r is not a date I recognize (try 2026-10-29)" % (field, value))

    stamp = day + timedelta(days=DUE_DATE_OFFSET)
    clock = DUE_TIME_DST if is_dst(day) else DUE_TIME_ST
    return "%sT%sZ" % (stamp.strftime("%Y-%m-%d"), clock)


def describe_due(iso):
    """Render a Canvas timestamp back as the day a student would say it is due."""
    if not iso:
        return "(none)"
    try:
        stamp = datetime.strptime(iso.replace(".000Z", "Z"), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return iso
    if stamp.hour <= 5:  # the 11:59 PM local convention, rendered back
        return "%s 11:59 PM local (%s)" % (
            (stamp - timedelta(days=1)).strftime("%a %Y-%m-%d"), iso)
    return "%s (%s)" % (stamp.strftime("%a %Y-%m-%d %H:%M"), iso)


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
        self._groups = None
        self._modules = None

    # -- raw HTTP, for what canvasapi does not expose ----------------------

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

    # -- caches ------------------------------------------------------------

    def assignments(self, refresh=False):
        if self._assignments is None or refresh:
            self._assignments = list(self.course.get_assignments())
        return self._assignments

    def groups(self, refresh=False):
        if self._groups is None or refresh:
            self._groups = list(self.course.get_assignment_groups())
        return self._groups

    def modules(self, refresh=False):
        if self._modules is None or refresh:
            self._modules = list(self.course.get_modules())
        return self._modules

    # -- resolution --------------------------------------------------------

    @staticmethod
    def _label(item):
        """What this object is called.

        Assignments, groups, and modules carry "name"; a canvasapi ModuleItem
        carries "title" and no "name" at all, so reading .name directly here
        raised AttributeError on every item.remove and item.move.
        """
        for attr in ("name", "title"):
            value = getattr(item, attr, None)
            if value is not None:
                return str(value)
        return ""

    @classmethod
    def _resolve(cls, items, needle, label):
        """Exact name, then case-insensitive, then a unique substring."""
        needle = str(needle).strip()
        exact = [i for i in items if cls._label(i).strip() == needle]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            die("%r matches %d %ss by exact name; pass an id instead"
                % (needle, len(exact), label))

        lowered = [i for i in items if cls._label(i).strip().lower() == needle.lower()]
        if len(lowered) == 1:
            return lowered[0]

        partial = [i for i in items if needle.lower() in cls._label(i).lower()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            die("%r matches %d %ss:\n  %s\nName one exactly, or pass an id."
                % (needle, len(partial), label,
                   "\n  ".join(sorted(cls._label(p) for p in partial))))
        return None

    def find_assignment(self, change):
        if change.get("id"):
            return self.course.get_assignment(int(change["id"]))
        return self._resolve(self.assignments(), change["name"], "assignment")

    def find_group(self, needle):
        return self._resolve(self.groups(), needle, "assignment group")

    def find_module(self, needle):
        return self._resolve(self.modules(), needle, "module")

    def find_item(self, module, title):
        items = list(module.get_module_items())
        return self._resolve(items, title, "module item"), items

    def submission_count(self, assignment):
        """How much student work would go with this assignment."""
        try:
            sleep_for_rate_limit()
            return sum(
                1 for s in assignment.get_submissions()
                if getattr(s, "workflow_state", "unsubmitted") != "unsubmitted"
            )
        except Exception as exc:
            warn("could not read submissions for %r: %s" % (assignment.name, exc))
            return None

    def rubric_meta(self, assignment_id):
        sleep_for_rate_limit()
        raw = self._http(
            "/api/v1/courses/%s/assignments/%s" % (self.course.id, assignment_id)
        ).read()
        data = json.loads(raw.decode("utf-8"))
        settings = data.get("rubric_settings") or {}
        return {
            "rubric_id": settings.get("id"),
            "association_id": settings.get("rubric_association_id"),
            "title": settings.get("title"),
            "criteria_count": len(data.get("rubric") or []),
        }

    def detach_rubric(self, meta):
        if meta.get("association_id"):
            sleep_for_rate_limit()
            self._http("/api/v1/courses/%s/rubric_associations/%s"
                       % (self.course.id, meta["association_id"]), method="DELETE")
        if meta.get("rubric_id"):
            sleep_for_rate_limit()
            self._http("/api/v1/courses/%s/rubrics/%s"
                       % (self.course.id, meta["rubric_id"]), method="DELETE")


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------

ASSIGNMENT_FIELDS = (
    # (document key, Canvas field, transform)
    ("rename", "name", None),
    ("points", "points_possible", float),
    ("due", "due_at", canvas_due),
    ("unlock", "unlock_at", canvas_due),
    ("lock", "lock_at", canvas_due),
    ("published", "published", as_bool),
    ("description", "description", None),
    ("position", "position", int),
    ("omit_from_final_grade", "omit_from_final_grade", as_bool),
    ("submission_types", "submission_types", None),
)


def assignment_payload(canvas, change):
    """Build the Canvas assignment payload from a change, and a human summary."""
    payload, summary = {}, []

    for key, field, transform in ASSIGNMENT_FIELDS:
        if key not in change:
            continue
        value = change[key]
        if transform is canvas_due:
            value = canvas_due(value, key)
            summary.append("%s -> %s" % (key, describe_due(value)))
        else:
            if transform is not None and value is not None:
                value = transform(value)
            summary.append("%s -> %r" % (key, value))
        payload[field] = value

    if "url" in change:
        # Same shape ursinus_canvas.py writes, so a description edited here still
        # looks like every other assignment in the shell.
        url = change["url"]
        label = change.get("link_text") or change.get("rename") or change.get("name") or ""
        payload["description"] = '%s (<a href="%s">%s</a>)' % (label, url, url)
        summary.append("url -> %s" % url)

    if "group" in change:
        group = canvas.find_group(change["group"])
        if group is None:
            die("no assignment group named %r" % change["group"])
        payload["assignment_group_id"] = group.id
        summary.append("group -> %s (%s)" % (group.name, group.id))

    return payload, summary


def plan_operation(canvas, change):
    """Resolve one operation against the live shell.

    Returns (description_lines, apply_callable). The callable is what --apply
    runs; everything expensive or ambiguous is resolved here, before any write.
    """
    op = change["op"]
    lines = []

    # ---------------- assignments ----------------

    if op == "assignment.create":
        name = change.get("name")
        if not name:
            die("op %d (assignment.create): 'name' is required" % change["_index"])
        existing = canvas._resolve(canvas.assignments(), name, "assignment")
        if existing is not None:
            die("assignment %r already exists (id %s); use assignment.update"
                % (name, existing.id))
        payload, summary = assignment_payload(canvas, change)
        payload["name"] = name
        payload.setdefault("points_possible", float(change.get("points", 100)))
        payload.setdefault("published", as_bool(change.get("published", False)))
        payload.setdefault("submission_types", change.get("submission_types") or ["online_upload"])
        lines.append("create assignment %r" % name)
        lines.append("  %d points, %spublished, submission %s"
                     % (payload["points_possible"],
                        "" if payload["published"] else "un",
                        ",".join(payload["submission_types"])))
        for s in summary:
            if not s.startswith(("points ", "published ")):
                lines.append("  %s" % s)

        def do():
            sleep_for_rate_limit()
            created = canvas.course.create_assignment(payload)
            canvas.assignments(refresh=True)
            return "created assignment %s (id %s)" % (created.name, created.id)

        return lines, do

    if op in ("assignment.update", "assignment.due", "rubric.detach", "assignment.delete"):
        assignment = canvas.find_assignment(change)
        if assignment is None:
            die("op %d (%s): no assignment matches %r"
                % (change["_index"], op, change.get("name") or change.get("id")))

        if op == "assignment.delete":
            count = canvas.submission_count(assignment)
            change["_submissions"] = count
            lines.append("DELETE assignment %r (id %s)" % (assignment.name, assignment.id))
            if count is None:
                lines.append("  submissions unknown (could not read)")
            else:
                lines.append("  %d submission(s) would be deleted with it" % count)

            def do():
                sleep_for_rate_limit()
                assignment.delete()
                canvas.assignments(refresh=True)
                return "deleted assignment %r" % assignment.name

            return lines, do

        if op == "rubric.detach":
            meta = canvas.rubric_meta(assignment.id)
            lines.append("detach rubric from %r (id %s)" % (assignment.name, assignment.id))
            if not meta["rubric_id"]:
                lines.append("  no rubric attached; nothing to do")

                def do():
                    return "no rubric on %r; skipped" % assignment.name

                return lines, do
            lines.append("  rubric %s %r (%d criteria), association %s"
                         % (meta["rubric_id"], meta["title"],
                            meta["criteria_count"], meta["association_id"]))
            lines.append("  NOTE any rubric assessments recorded against it are discarded")

            def do():
                canvas.detach_rubric(meta)
                return "detached rubric %s from %r" % (meta["rubric_id"], assignment.name)

            return lines, do

        if op == "assignment.due":
            change = dict(change)
            change["due"] = change.get("due")

        payload, summary = assignment_payload(canvas, change)
        if not payload:
            die("op %d (%s): nothing to change on %r"
                % (change["_index"], op, assignment.name))

        lines.append("update assignment %r (id %s)" % (assignment.name, assignment.id))
        if "due_at" in payload:
            lines.append("  due   %s" % describe_due(getattr(assignment, "due_at", None)))
            lines.append("     -> %s" % describe_due(payload["due_at"]))
            summary = [s for s in summary if not s.startswith("due ->")]
        for s in summary:
            lines.append("  %s" % s)

        def do():
            sleep_for_rate_limit()
            assignment.edit(assignment=payload)
            canvas.assignments(refresh=True)
            return "updated %r" % assignment.name

        return lines, do

    # ---------------- assignment groups ----------------

    if op == "group.create":
        name = change["name"]
        if canvas.find_group(name) is not None:
            die("assignment group %r already exists" % name)
        payload = {"name": name}
        if "weight" in change:
            payload["group_weight"] = float(change["weight"])
        if "position" in change:
            payload["position"] = int(change["position"])
        lines.append("create assignment group %r %s" % (name, payload))

        def do():
            sleep_for_rate_limit()
            created = canvas.course.create_assignment_group(**payload)
            canvas.groups(refresh=True)
            return "created group %r (id %s)" % (created.name, created.id)

        return lines, do

    if op in ("group.update", "group.delete"):
        group = canvas.find_group(change.get("name") or change.get("id"))
        if group is None:
            die("op %d (%s): no assignment group matches %r"
                % (change["_index"], op, change.get("name") or change.get("id")))

        if op == "group.delete":
            lines.append("DELETE assignment group %r (id %s)" % (group.name, group.id))
            move_to = None
            if change.get("move_to"):
                move_to = canvas.find_group(change["move_to"])
                if move_to is None:
                    die("no assignment group named %r to move into" % change["move_to"])
                lines.append("  assignments move to %r (id %s)" % (move_to.name, move_to.id))
            else:
                lines.append("  WARNING no move_to given; Canvas deletes the assignments in it")

            def do():
                sleep_for_rate_limit()
                if move_to:
                    group.delete(move_assignments_to=move_to.id)
                else:
                    group.delete()
                canvas.groups(refresh=True)
                return "deleted group %r" % group.name

            return lines, do

        payload = {}
        if "rename" in change:
            payload["name"] = change["rename"]
        if "weight" in change:
            payload["group_weight"] = float(change["weight"])
        if "position" in change:
            payload["position"] = int(change["position"])
        if not payload:
            die("op %d (group.update): nothing to change" % change["_index"])
        lines.append("update assignment group %r (id %s): %s" % (group.name, group.id, payload))

        def do():
            sleep_for_rate_limit()
            group.edit(**payload)
            canvas.groups(refresh=True)
            return "updated group %r" % group.name

        return lines, do

    # ---------------- modules ----------------

    if op == "module.create":
        name = change["name"]
        if canvas.find_module(name) is not None:
            die("module %r already exists" % name)
        payload = {"name": name}
        if "position" in change:
            payload["position"] = int(change["position"])
        lines.append("create module %r %s" % (name, payload))
        publish = as_bool(change.get("published", False))
        if publish:
            lines.append("  and publish it")

        def do():
            sleep_for_rate_limit()
            created = canvas.course.create_module(module=payload)
            if publish:
                created.edit(module={"published": True})
            canvas.modules(refresh=True)
            return "created module %r (id %s)" % (created.name, created.id)

        return lines, do

    if op in ("module.update", "module.delete"):
        module = canvas.find_module(change.get("name") or change.get("id"))
        if module is None:
            die("op %d (%s): no module matches %r"
                % (change["_index"], op, change.get("name") or change.get("id")))

        if op == "module.delete":
            items = list(module.get_module_items())
            lines.append("DELETE module %r (id %s) and its %d item(s)"
                         % (module.name, module.id, len(items)))
            lines.append("  (module items only; the assignments they point at survive)")

            def do():
                sleep_for_rate_limit()
                module.delete()
                canvas.modules(refresh=True)
                return "deleted module %r" % module.name

            return lines, do

        payload = {}
        if "rename" in change:
            payload["name"] = change["rename"]
        if "position" in change:
            payload["position"] = int(change["position"])
        if "published" in change:
            payload["published"] = as_bool(change["published"])
        if not payload:
            die("op %d (module.update): nothing to change" % change["_index"])
        lines.append("update module %r (id %s): %s" % (module.name, module.id, payload))

        def do():
            sleep_for_rate_limit()
            module.edit(module=payload)
            canvas.modules(refresh=True)
            return "updated module %r" % module.name

        return lines, do

    # ---------------- module items ----------------

    module = canvas.find_module(change["module"])
    if module is None:
        die("op %d (%s): no module matches %r" % (change["_index"], op, change["module"]))

    if op == "item.add":
        payload = {"title": change["title"], "type": change.get("type", "Assignment")}
        if change.get("content"):
            target = canvas._resolve(canvas.assignments(), change["content"], "assignment")
            if target is None:
                die("no assignment named %r to point the item at" % change["content"])
            payload["content_id"] = target.id
        if change.get("url"):
            payload["external_url"] = change["url"]
        if "position" in change:
            payload["position"] = int(change["position"])
        if "indent" in change:
            payload["indent"] = int(change["indent"])
        payload["published"] = as_bool(change.get("published", True))
        lines.append("add item %r to module %r" % (payload["title"], module.name))
        lines.append("  %s" % payload)

        def do():
            sleep_for_rate_limit()
            created = module.create_module_item(module_item=payload)
            return "added item %r to %r" % (created.title, module.name)

        return lines, do

    item, _ = canvas.find_item(module, change["title"])
    if item is None:
        die("op %d (%s): no item %r in module %r"
            % (change["_index"], op, change["title"], module.name))

    if op == "item.remove":
        lines.append("remove item %r from module %r" % (item.title, module.name))
        lines.append("  (the assignment it points at is not deleted)")

        def do():
            sleep_for_rate_limit()
            item.delete()
            return "removed %r from %r" % (item.title, module.name)

        return lines, do

    # item.move
    if change.get("to_module"):
        destination = canvas.find_module(change["to_module"])
        if destination is None:
            die("no module named %r to move into" % change["to_module"])
        payload = {"title": item.title, "type": item.type,
                   "published": getattr(item, "published", True)}
        if getattr(item, "content_id", None):
            payload["content_id"] = item.content_id
        if "position" in change:
            payload["position"] = int(change["position"])
        lines.append("move item %r from %r to %r" % (item.title, module.name, destination.name))

        def do():
            sleep_for_rate_limit()
            destination.create_module_item(module_item=payload)
            item.delete()
            return "moved %r to %r" % (payload["title"], destination.name)

        return lines, do

    position = int(change["position"])
    lines.append("move item %r in %r to position %d (from %s)"
                 % (item.title, module.name, position, getattr(item, "position", "?")))

    def do():
        sleep_for_rate_limit()
        item.edit(module_item={"position": position})
        return "moved %r to position %d" % (item.title, position)

    return lines, do


# --------------------------------------------------------------------------
# --generate: compare the repository to the live shell
# --------------------------------------------------------------------------

DEFAULT_SYLLABUS = os.path.join("_pages", "syllabus.md")


def addslash(text):
    return text if text.endswith("/") else text + "/"


def meeting_dates(markdown_path):
    """(week, ordinal) -> calendar date, from the sibling schedule script.

    That script already knows how to walk the meeting pattern around holidays,
    and re-deriving it here is how the two would drift apart.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import ursinus_canvas_update_schedule_inplace as schedule
    except ImportError as exc:
        die("--generate needs ursinus_canvas_update_schedule_inplace.py beside this "
            "script, and its dependencies: %s" % exc)

    with open(markdown_path, "r", encoding="utf-8") as fh:
        frontmatter_dict, _ = schedule._split_frontmatter(fh.read())
    plan = schedule._extract_plan(frontmatter_dict)
    return ({(m.week, m.ordinal_in_week): m.date for m in plan.meetings},
            frontmatter_dict)


def syllabus_expectations(markdown_path):
    """What the repository says every Canvas assignment should look like.

    Names follow ursinus_canvas.py: strip a trailing " Due", skip "Handed Out"
    rows and quizzes. Those are the names that created the shell, so they are the
    names that have to match it.
    """
    meetings, doc = meeting_dates(markdown_path)
    info = doc.get("info") or {}
    homepage = addslash(str(info.get("course_homepage") or ""))

    expected = {}
    for item in doc.get("schedule", []) or []:
        try:
            week, ordinal = int(item.get("week")), int(item.get("date"))
        except (TypeError, ValueError):
            continue
        day = meetings.get((week, ordinal))
        for deliverable in item.get("deliverables", []) or []:
            dtitle = (deliverable.get("dtitle") or "").strip()
            if not dtitle:
                continue
            name = rchop(dtitle, " Due")
            lowered = name.lower()
            if " handed out" in lowered or "quiz:" in lowered:
                continue
            dlink = deliverable.get("dlink")
            expected[name] = {
                "name": name,
                "points": float(deliverable.get("points", 100)),
                "day": day,
                "url": (homepage + str(dlink)) if dlink and homepage else None,
            }
    return expected, info


def yaml_quote(value):
    if value is None:
        return "null"
    text = str(value)
    return '"%s"' % text.replace("\\", "\\\\").replace('"', '\\"')


def generate(canvas, markdown_path):
    """Emit a change document describing repo-vs-Canvas drift."""
    if not os.path.exists(markdown_path):
        die("no syllabus at %s (run this from the repository root, or pass --markdown)"
            % markdown_path)

    expected, _ = syllabus_expectations(markdown_path)
    if not expected:
        die("no deliverables found in %s" % markdown_path)

    live = {}
    for assignment in canvas.assignments():
        live[(assignment.name or "").strip()] = assignment

    out, counts = [], {"create": 0, "due": 0, "points": 0, "url": 0, "orphan": 0}

    for name in sorted(expected):
        want = expected[name]
        want_due = canvas_due(want["day"].strftime("%Y-%m-%d")) if want["day"] else None
        assignment = live.get(name)

        if assignment is None:
            counts["create"] += 1
            out.append("  - op: assignment.create")
            out.append("    name: %s" % yaml_quote(name))
            out.append("    points: %g" % want["points"])
            if want["day"]:
                out.append("    due: %s" % want["day"].strftime("%Y-%m-%d"))
            if want["url"]:
                out.append("    url: %s" % yaml_quote(want["url"]))
            out.append("    published: true")
            out.append("")
            continue

        have_due = getattr(assignment, "due_at", None)
        if want_due and (have_due or "").replace(".000Z", "Z") != want_due:
            counts["due"] += 1
            out.append("  - op: assignment.due")
            out.append("    name: %s" % yaml_quote(name))
            out.append("    due: %s   # Canvas has %s"
                       % (want["day"].strftime("%Y-%m-%d"), describe_due(have_due)))
            out.append("")

        have_points = getattr(assignment, "points_possible", None)
        if have_points is not None and abs(float(have_points) - want["points"]) > 0.001:
            counts["points"] += 1
            out.append("  - op: assignment.update")
            out.append("    name: %s" % yaml_quote(name))
            out.append("    points: %g   # Canvas has %g" % (want["points"], float(have_points)))
            out.append("")

        description = getattr(assignment, "description", None) or ""
        if want["url"] and want["url"] not in description:
            counts["url"] += 1
            out.append("  - op: assignment.update")
            out.append("    name: %s" % yaml_quote(name))
            out.append("    url: %s" % yaml_quote(want["url"]))
            out.append("")

    orphans = sorted(set(live) - set(expected))

    print("# Generated by ursinus_canvas_inline_changes.py --generate")
    print("# repository: %s" % markdown_path)
    print("# course:     %s (%s)" % (canvas.course.id, getattr(canvas.course, "name", "?")))
    print("# drift:      %d to create, %d due date(s), %d points, %d link(s), %d unaccounted"
          % (counts["create"], counts["due"], counts["points"], counts["url"], len(orphans)))
    print("#")
    print("# Assignments only. Modules and module items are not diffed.")
    print("# Review before applying; this is a description of drift, not a decision.")

    if out:
        print("changes:")
        for line in out:
            print(line)
    else:
        print("# No assignment drift: Canvas matches the repository.")
        print("changes: []")

    if orphans:
        print("# %d Canvas assignment(s) the syllabus does not name." % len(orphans))
        print("# Uncomment to delete. Deleting an assignment deletes its submissions")
        print("# and grades with it, so the submission counts below are the whole story.")
        for name in orphans:
            assignment = live[name]
            count = canvas.submission_count(assignment)
            label = "unknown" if count is None else "%d" % count
            print("#   - op: assignment.delete")
            print("#     name: %s   # %s submission(s)" % (yaml_quote(name), label))
    return 0


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def connect(args):
    """Open the course, prompting for whatever was not passed.

    Prompts and progress go to stderr, so `--generate | --apply` works in a pipe.
    """
    course_id = args.courseid
    if course_id is None:
        try:
            print("Enter the Canvas course id: ", end="", file=sys.stderr, flush=True)
            course_id = int(input().strip())
        except (ValueError, EOFError):
            die("a numeric course id is required")

    api_key = args.apikey or os.environ.get("CANVAS_API_KEY")
    if not api_key:
        try:
            print("Enter API key (from %sprofile/settings): " % args.api_url,
                  end="", file=sys.stderr, flush=True)
            api_key = input().strip()
        except EOFError:
            api_key = ""
    if not api_key:
        die("an API key is required")

    try:
        return Canvas(args.api_url, api_key, course_id)
    except ImportError:
        die("canvasapi is not installed: pip install canvasapi")
    except Exception as exc:
        die("could not open course %s: %s" % (course_id, exc))


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Apply an inline list of changes to a live Canvas shell.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The change document is read from stdin unless --file is given.",
    )
    p.add_argument("-c", "--courseid", type=int, default=None,
                   help="numeric Canvas course id (prompted if omitted)")
    p.add_argument("-a", "--apikey", default=None,
                   help="Canvas API key (prompted if omitted; also $CANVAS_API_KEY)")
    p.add_argument("-f", "--file", default=None,
                   help="read the change document from this file instead of stdin")
    p.add_argument("-g", "--generate", action="store_true",
                   help="compare this repository to the live shell and write a change "
                        "document to stdout instead of applying one")
    p.add_argument("-m", "--markdown", default=DEFAULT_SYLLABUS,
                   help="syllabus to compare against under --generate (default: %s, "
                        "relative to the current directory)" % DEFAULT_SYLLABUS)
    p.add_argument("--api-url", default=DEFAULT_API_URL,
                   help="Canvas base URL (default: %s)" % DEFAULT_API_URL)
    p.add_argument("--apply", action="store_true",
                   help="actually write to Canvas (default is a dry run)")
    p.add_argument("--allow-delete-with-submissions", action="store_true",
                   help="permit assignment.delete on an assignment that has submissions")
    p.add_argument("--check", action="store_true",
                   help="parse and validate the document locally; contact Canvas not at all")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.generate and args.file:
        die("--generate writes a change document; it does not read one. Drop --file.")

    if args.generate:
        canvas = connect(args)
        return generate(canvas, args.markdown)

    if args.file:
        if not os.path.exists(args.file):
            die("no such file: %s" % args.file)
        with open(args.file, "r", encoding="utf-8") as fh:
            text = fh.read()
    else:
        if sys.stdin.isatty():
            die("no change document: pipe one in on stdin, pass --file, or use "
                "--generate to write one from this repository")
        text = sys.stdin.read()

    changes = parse_document(text)
    print("Parsed %d operation(s):" % len(changes))
    for change in changes:
        label = change.get("name") or change.get("title") or change.get("module") or ""
        print("  %2d. %-18s %s" % (change["_index"], change["op"], label))
    print()

    if args.check:
        for change in changes:
            if "due" in change:
                print("  %s -> %s" % (change.get("name", change["op"]),
                                      describe_due(canvas_due(change["due"]))))
        print("--check: parsed locally; Canvas was not contacted.")
        return 0

    canvas = connect(args)
    print("Course %s: %s\n" % (canvas.course.id, getattr(canvas.course, "name", "?")))

    # Resolve everything before writing anything.
    plan = []
    for change in changes:
        lines, action = plan_operation(canvas, change)
        plan.append((change, lines, action))
        print("%2d. %s" % (change["_index"], lines[0]))
        for line in lines[1:]:
            print("    %s" % line)
    print()

    risky = [
        c for c, _, _ in plan
        if c["op"] == "assignment.delete" and c.get("_submissions") != 0
    ]
    if risky and not args.allow_delete_with_submissions:
        die("refusing to delete %d assignment(s) that have submissions: %s\n"
            "Those submissions and their grades go with them. Re-run with "
            "--allow-delete-with-submissions only if you have confirmed that is acceptable."
            % (len(risky), ", ".join(str(c.get("name") or c.get("id")) for c in risky)))

    if not args.apply:
        print("Dry run: nothing was written. Re-run with --apply to commit these %d change(s)."
              % len(plan))
        return 0

    print("Applying %d change(s):" % len(plan))
    failures = 0
    for change, _, action in plan:
        try:
            print("  %2d. %s" % (change["_index"], action()))
        except Exception as exc:
            failures += 1
            print("  %2d. FAILED (%s): %s" % (change["_index"], change["op"], exc),
                  file=sys.stderr)

    if failures:
        print("\n%d of %d operation(s) failed; the rest were applied."
              % (failures, len(plan)), file=sys.stderr)
        return 1

    print("\nAll %d change(s) applied." % len(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
