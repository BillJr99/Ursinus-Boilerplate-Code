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
the live shell, and refuses to write anything until you pass --apply. Applying a
change document never consults the syllabus, so it never "helpfully" reverts an
edit you made in the Canvas UI; --generate is the one mode that reads the
repository, and it only writes to stdout. It is deliberately narrow: assignments,
assignment groups, modules, module items, due dates, and rubrics on the
assignments you name. `canvas_sync_rubrics.py`, beside this file, is still the
tool for replacing rubrics in bulk from the repository.

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
    assignment.create   name, points, [due], [handout], [group], [published],
                        [description], [url], [submission_types],
                        [allowed_extensions], [lock], [unlock], [position],
                        [rubricpath], [module], [handout_module]
    assignment.update   name (or id), then any of: rename, points, due, handout,
                        unlock, lock, group, published, description, url,
                        submission_types, allowed_extensions, position,
                        omit_from_final_grade, module, handout_module
    assignment.due      name (or id), due            -- shorthand for the above
    assignment.delete   name (or id)
    rubric.detach       name (or id)                 -- drop the rubric from an assignment
    rubric.replace      name (or id), rubricpath, [points]
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
verbatim. `due: null` clears the due date. `unlock`, `lock`, and `handout` read
the same way.

Submission types
----------------
`submission_types` accepts either vocabulary, and which one it is decides what
happens:

    submission_types: written                 the syllabus's token, mapped by
                                              get_submission_spec below to
                                              online_upload + online_text_entry and
                                              pdf doc docx txt plus the archives
    submission_types: ["online_upload"]       Canvas's own names, sent verbatim
    submission_types: on_paper                also Canvas's own name, sent verbatim

The tokens are `written`, `presentation`, `zip`, `onpaper`, and `noupload`, and a
deliverable may name more than one. Anything that is neither a token nor one of
Canvas's names stops the run rather than defaulting to an unrestricted upload:
here, unlike in the bulk publisher, an unrecognized word is a typo in a
hand-written edit and quietly widening the upload rules is the wrong answer to it.

`allowed_extensions: [pdf, ipynb]` overrides whatever the token produced.
`allowed_extensions: []` takes the restriction off, which needs a form parameter
canvasapi cannot express, so it is sent by hand and the assignment is read back
afterwards; you are told what Canvas actually ended up with, not what was asked
for.

Available until
---------------
Every assignment a full deploy writes is available until the last day of class.
An assignment created here gets the same date, read off the assignments already in
the shell rather than out of the syllabus: they were given that date by the deploy
that put them there, so the shell already knows the answer and nothing has to open
the repository to ask. Pass `--last-class-date 2026-12-11` when the shell cannot
answer, or `lock:` on the operation to set one outright. A default that would fall
before the assignment's own due date is refused rather than applied. Only
`assignment.create` gets a default; an update changes what it names and no more.

Rubrics
-------
`rubric.replace` replaces the rubric on an existing assignment from an assignment
page's `info.rubric` block, using the payload `canvas_sync_rubrics.py` builds, so
the result is identical to what that script or a full deploy would write.
`assignment.create` takes the same `rubricpath` and attaches the rubric as it
creates the assignment, which `rubric.replace` cannot do for an assignment that
does not exist yet.

Replacing or detaching a rubric deletes it, and every per-criterion score recorded
against it goes with it. Both operations report how many, and the run refuses
unless you pass --force-graded.

The modules page
----------------
An assignment created here is filed on the modules page the way a full deploy
files one: as an `Assignment` item in the module for the day it is due, and, when
the operation carries `handout:`, as a `<name> Handed Out` entry in the module for
the day it is handed out. Moving a due date moves the item; renaming the
assignment retitles it; deleting the assignment removes both.

Modules are matched by the date header a deploy writes at the front of their names
("Wed, Oct 29, 2026 - Recursion"). A module with no such header, which is how the
standing "Resources" module reads, is never a target and never has items taken out
of it, so a deliberate placement stays where it was put. A day with no module is
reported and skipped, and the count is repeated at the end of the run so that a
missing item cannot hide behind "all changes applied"; pass `module:` naming a
module outright to place it anyway. `--no-modules` turns all of this off.

Adding an item publishes its module, the way a deploy does, and an assignment or
module created here is published unless the operation says `published: false`. An
item filed into a module nobody can see is not filed at all. The dry run names
every module that would be published, so an unpublished week you meant to keep
back is visible before anything is written.

One document, one pass
----------------------
Every operation is resolved against the live shell before any of them writes, so
an operation cannot see what an earlier one in the same document created or moved.
Documents that would need that are refused by name rather than half-applied: split
them into two runs.

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
what it would change, including every module item it would add, move, retitle, or
remove.

`assignment.delete` reports how many submissions exist and refuses to run if there
are any, unless you pass --allow-delete-with-submissions. Deleting a Canvas
assignment deletes its submissions and grades with it, and no flag brings them
back.

`rubric.replace` and `rubric.detach` report how many rubric assessments exist and
refuse to run if there are any, unless you pass --force-graded.

What --generate compares
------------------------
Assignments only: due date, points, and the page link in the description, plus a
commented-out delete for anything in Canvas the syllabus does not name and a
commented-out rubric replacement for anything whose rubric lives in the
repository. Existing module items are not diffed, because reconciling them safely
means deciding what a reordered module means for released content;
`rebuild_all_modules` in `ursinus_canvas_update_schedule_inplace.py` is the tool
that takes that on. An assignment being *created*, though, carries the day it is
due and the day it is handed out, so applying the document files it on the modules
page where a full deploy would have put it.

Every delete and every rubric replacement it emits is commented out and annotated
with what it would cost, so a generated document can never destroy student work by
being piped straight back in.

Requires `canvasapi`. PyYAML is used when present; without it, JSON and
dict-style input still parse. --generate additionally needs `python-frontmatter`,
`python-dateutil`, and `pytz`, which the sibling schedule script already requires;
so does anything naming a `rubricpath`, which has to read the assignment page.
--check needs none of them, except that it can only validate a rubric file when
`python-frontmatter` is installed, and says so when it cannot.

`canvas_sync_rubrics.py` beside this file is imported rather than reimplemented,
so that a rubric written here is identical to one that script writes.

The submission_types token table is the one thing deliberately duplicated:
`get_submission_spec` below is a copy of `ursinus_canvas.py`'s, kept here so that
this script needs none of that module's dependencies. Change one and change the
other, or an assignment created here and one created by a deploy will disagree
about what a student may upload.
"""

import argparse
import ast
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from urllib import parse, request

DEFAULT_API_URL = "https://ursinus.instructure.com/"

# Matches ursinus_canvas.py: a deliverable listed on day D is due 11:59 PM local
# that day, which is 03:59:59Z (EDT) or 04:59:59Z (EST) on D+1.
DUE_TIME_DST = "03:59:59"
DUE_TIME_ST = "04:59:59"
DUE_DATE_OFFSET = 1
LOCAL_TZ = "US/Eastern"

# Module names a deploy writes: "Wed, Oct 29, 2025 - Recursion". The date header is the whole
# mechanism behind the module maintenance below, and it has to match ursinus_canvas.py exactly
# (see its coursedtstr, and _date_header in ursinus_canvas_update_schedule_inplace.py).
MODULE_DATE_FORMAT = "%a, %b %d, %Y"
MODULE_NAME_SEPARATOR = " - "

# What a deploy titles the module item for a deliverable that is handed out on a given day,
# relative to the assignment's own name (ursinus_canvas.py writes the raw dtitle, which is the
# assignment name with this suffix still on it).
HANDOUT_SUFFIX = " Handed Out"

# ---------------------------------------------------------------------------
# The submission_types token table.
#
# This is a copy of what ursinus_canvas.py holds, kept here rather than imported so that this
# script stays standalone: importing that module pulls in canvasapi, frontmatter, requests,
# pytz, and yaml, and --check is documented to run with none of them installed.
#
# KEEP THE TWO IN STEP. These tokens are the contract between a deliverable in the syllabus
# and the Canvas assignment it becomes. If get_submission_spec changes in ursinus_canvas.py,
# change it here too, or an assignment created by this script and one created by a full deploy
# will disagree about what a student is allowed to upload.
# ---------------------------------------------------------------------------

# Upload extension sets, selected by the tokens in a deliverable's submission_types string.
# A deliverable naming none of these tokens is left unrestricted, so that any file type can
# be submitted; see get_submission_spec below.
EXTENSIONS_WRITTEN = ['pdf', 'doc', 'docx', 'txt']
EXTENSIONS_ARCHIVE = ['zip', 'bz2', 'tar', 'gz', 'rar', '7z']
EXTENSIONS_PRESENTATION = ['ppt', 'pptx']

# The tokens get_submission_spec recognizes, in the order its docstring lists them. Used to
# tell a free-text token string apart from a list of Canvas's own submission type names.
SUBMISSION_TOKENS = ("onpaper", "noupload", "written", "presentation", "zip")

# What Canvas itself calls its submission types. A change document naming one of these directly
# is speaking Canvas's vocabulary, not the syllabus's, and must not go through the token
# mapping below.
CANVAS_SUBMISSION_TYPES = (
    "online_upload", "online_text_entry", "online_url", "online_quiz",
    "on_paper", "discussion_topic", "external_tool", "media_recording",
    "student_annotation", "none", "not_graded",
)


def get_submission_spec(submissiontypes):
    """Map a deliverable's submission_types string onto Canvas submission types and extensions.

    Returns (submission_types, allowed_extensions), where allowed_extensions is None when no
    restriction should be sent at all.  The tokens are matched as substrings of one free-text
    string, so a deliverable may name more than one and their extension sets accumulate:
    "written presentation" accepts everything either tag allows.

    An unrecognized or empty string yields an unrestricted upload.  That is the deliberate
    default in ursinus_canvas.py: a deliverable whose author did not think to tag it should not
    silently refuse the PDF, image, or notebook a student tries to hand in.  This script is
    stricter about what it will accept before getting here (see resolve_submission_spec), but
    the mapping itself is identical.

    onpaper       -> on_paper
    noupload      -> online_text_entry
    written       -> online_upload + online_text_entry; pdf doc docx txt + the archives
    presentation  -> online_upload; pdf doc docx txt ppt pptx
    zip           -> online_upload; zip bz2 tar gz rar 7z
    (none)        -> online_upload; no extension restriction
    """
    submissiontypes = str(submissiontypes or "").lower()

    # These two describe how the work arrives rather than what file it is, so they short-circuit
    if "onpaper" in submissiontypes:
        return (['on_paper'], None)

    if "noupload" in submissiontypes:
        return (['online_text_entry'], None)

    types = ['online_upload']
    extensions = []

    # Accumulate in a stable order, and let a deliverable name several tags at once
    if "written" in submissiontypes:
        types.append('online_text_entry')
        extensions = extensions + EXTENSIONS_WRITTEN + EXTENSIONS_ARCHIVE

    if "presentation" in submissiontypes:
        extensions = extensions + EXTENSIONS_WRITTEN + EXTENSIONS_PRESENTATION

    if "zip" in submissiontypes:
        extensions = extensions + EXTENSIONS_ARCHIVE

    # Preserve first-seen order while dropping the overlap between the sets above
    deduped = []
    for extension in extensions:
        if not (extension in deduped):
            deduped.append(extension)

    # None rather than [], so that callers omit the key entirely: what an empty list does on
    # the wire depends on how it is encoded, and "no restriction" has to be expressed by not
    # asking for one rather than by asking for an empty one
    if len(deduped) == 0:
        return (types, None)

    return (types, deduped)

OPS = (
    "assignment.create", "assignment.update", "assignment.due", "assignment.delete",
    "rubric.detach", "rubric.replace",
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
# sibling modules
# --------------------------------------------------------------------------

def _sibling_path():
    """Put this script's directory on sys.path, so the modules beside it import."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    return here


def rubric_module(required=True):
    """canvas_sync_rubrics, which owns the rubric payload this script writes.

    Reusing it is the point: two implementations of the same rubric shape would
    drift, and a rubric replaced by this script has to be byte-identical to one
    replaced by that one. Its module-scope imports are all standard library, so
    this is cheap; only read_rubric needs python-frontmatter, and only when called.
    """
    _sibling_path()
    try:
        import canvas_sync_rubrics
        return canvas_sync_rubrics
    except ImportError as exc:
        if required:
            die("canvas_sync_rubrics.py has to sit beside this script: %s" % exc)
        return None


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
        # PyYAML turns an unquoted 2026-12-12T04:59:59Z into a datetime before this ever
        # sees it. A datetime carrying a clock is already the instant somebody meant, and
        # putting it back through the "bare day" path below would shift it a second day.
        if (value.hour, value.minute, value.second) != (0, 0, 0):
            return value.strftime("%Y-%m-%dT%H:%M:%SZ")
        value = value.strftime("%Y-%m-%d")
    elif hasattr(value, "year") and not isinstance(value, str):
        value = value.strftime("%Y-%m-%d")   # a plain YAML date
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


def student_day(value):
    """The calendar day a student would call this the due day, as a date.

    Modules are filed by that day, not by the instant Canvas stores. A bare date in
    a change document already is the student-facing day. A full timestamp, whether
    it came from the document or back off the shell, has been pushed past midnight
    by the 11:59 PM convention, so an hour at or before 05:00Z belongs to the day
    before -- the same reading describe_due above applies. Returns None for
    anything that is not a date at all.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _student_day_of(value)
    if hasattr(value, "year") and not isinstance(value, str):  # a date already
        return value

    text = str(value).strip()
    if not text:
        return None

    if "T" in text:
        text = text.replace(".000Z", "Z")
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                return _student_day_of(datetime.strptime(text, fmt))
            except ValueError:
                continue
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _student_day_of(stamp):
    """Roll an early-morning instant back to the day it is really the deadline for.

    Midnight is left alone: canvas_due treats a midnight datetime as a bare day
    rather than an instant, and the two have to agree or a due date would land in
    one module and be described as belonging to another.
    """
    if (stamp.hour, stamp.minute, stamp.second) == (0, 0, 0):
        return stamp.date()
    if stamp.hour <= 5:
        return (stamp - timedelta(days=1)).date()
    return stamp.date()


def date_header(day):
    """How a deploy writes a day at the front of a module name."""
    return day.strftime(MODULE_DATE_FORMAT)


def module_date(name):
    """The day a module's name says it is, or None when it does not say one.

    The standing modules a deploy creates -- "Resources", "Overarching Class
    Participation Activities" -- carry no date header, so they fall out of every
    date lookup here and are never moved into or out of. That is deliberate: an
    item filed there was filed there on purpose.
    """
    head = str(name or "").split(MODULE_NAME_SEPARATOR)[0].strip()
    try:
        return datetime.strptime(head, MODULE_DATE_FORMAT).date()
    except ValueError:
        return None


def as_extension_list(value):
    """Accept a YAML list, a comma-separated string, or nothing."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        items = [str(v).strip().lstrip(".") for v in value]
    else:
        items = [part.strip().lstrip(".") for part in str(value).replace(",", " ").split()]
    return [i for i in items if i]


# What resolve_submission_spec returns for allowed_extensions when the operation says the
# restriction should come off. Distinct from None, which means "the operation said nothing
# about extensions, so leave whatever is there alone".
CLEAR_EXTENSIONS = object()


def resolve_submission_spec(change):
    """(submission_types, allowed_extensions, notes) for one operation.

    Either of two vocabularies may appear under `submission_types`, and which one
    it is has to be decided rather than guessed, because guessing wrong quietly
    changes how students hand work in.

      * a list, or a string naming only Canvas's own types ("on_paper",
        "online_upload online_text_entry"), is Canvas's vocabulary and is sent
        verbatim. That is what every change document written before this feature
        existed contains.
      * a string naming one of the syllabus's tokens ("written", "presentation",
        "zip", "onpaper", "noupload") goes through the shared token table, so an
        assignment created here and one created by a full deploy agree on both the
        submission types and the file extensions a student may upload.
      * anything else is a typo and stops the run. The bulk publisher defaults an
        unrecognized token to an unrestricted upload on purpose, because a
        mistagged deliverable should still accept work; here, where the document
        was hand-written for one edit, an unrecognized token is a mistake and
        silently widening the upload rules is the wrong answer to it.

    `allowed_extensions`, when the operation names it, wins over whatever the token
    produced. Its returned value is a list to set, CLEAR_EXTENSIONS to take the
    restriction off, or None to leave the assignment's alone.
    """
    notes = []
    types = None
    extensions = None

    if "submission_types" in change:
        raw = change["submission_types"]
        if isinstance(raw, (list, tuple)):
            types = [str(t).strip() for t in raw if str(t).strip()]
            notes.append("submission_types -> %s" % ",".join(types))
        elif raw is not None and str(raw).strip():
            words = [w for w in str(raw).replace(",", " ").split() if w]
            native = [w for w in words if w in CANVAS_SUBMISSION_TYPES]
            tokens = [w for w in words
                      if any(t in w.lower() for t in SUBMISSION_TOKENS)]

            if native and len(native) == len(words):
                types = native
                notes.append("submission_types -> %s (Canvas's own names)" % ",".join(types))
            elif tokens:
                token = str(raw).strip()
                types, resolved = get_submission_spec(token)
                notes.append("submission_types %r -> %s" % (token, ",".join(types)))
                if resolved is None:
                    # The token says "no restriction". On an assignment that already
                    # carries one, saying nothing would leave the old restriction in
                    # place, so this is a clear rather than a silence.
                    extensions = CLEAR_EXTENSIONS
                    notes.append("allowed_extensions -> (any file type)")
                else:
                    extensions = resolved
                    notes.append("allowed_extensions -> %s" % " ".join(extensions))
            else:
                die("op %d: %r is neither one of Canvas's submission types (%s) nor one "
                    "of the syllabus's tokens (%s). Fix the spelling rather than letting "
                    "this default to an unrestricted upload."
                    % (change.get("_index", 0), str(raw).strip(),
                       ", ".join(CANVAS_SUBMISSION_TYPES),
                       ", ".join(SUBMISSION_TOKENS)))

    if "allowed_extensions" in change:
        named = as_extension_list(change["allowed_extensions"])
        if named:
            extensions = named
            notes.append("allowed_extensions -> %s (overriding)" % " ".join(extensions))
        else:
            extensions = CLEAR_EXTENSIONS
            notes.append("allowed_extensions -> (cleared)")

    return types, extensions, notes


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
        self._items = {}          # module id -> list of module items
        self._lock_at = False     # False means "not looked up yet"; None means "none found"

        # Run-scoped settings, set from the command line once the course is open. They live
        # here because every planner needs them and threading them through plan_operation's
        # signature would touch every branch in it.
        self.modules_enabled = True
        self.last_class_date = None

        # Every item the plan could not place on the modules page, so that a run reporting
        # "all changes applied" cannot also be quietly leaving work off the page students use.
        self.unfiled = []

    # -- raw HTTP, for what canvasapi does not expose ----------------------

    def _http(self, endpoint, method="GET", fields=None):
        """fields may be a dict, or a list of (name, value) pairs when a parameter has to
        repeat -- Canvas's array parameters are sent as repeated name[] keys, which a dict
        cannot express."""
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
            self._items = {}
        return self._modules

    def items(self, module, refresh=False):
        """This module's items, cached.

        One change document can touch the same module several times -- two
        assignments moved onto the same day, a create followed by a delete -- and
        re-reading the module for each of them is both slow and, once a write has
        happened, wrong. Every write below invalidates the entry it touched.
        """
        if refresh or module.id not in self._items:
            self._items[module.id] = list(module.get_module_items())
        return self._items[module.id]

    def forget_items(self, module):
        self._items.pop(module.id, None)

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
        items = self.items(module)
        return self._resolve(items, title, "module item"), items

    # -- the shell's own answers about dates and modules --------------------

    def default_lock_at(self):
        """The close-out date the rest of this course already uses, or None.

        A full deploy writes the identical lock_at on every assignment it creates
        -- the last day of class, at the same 11:59 PM local convention as a due
        date (ursinus_canvas.py, "lock out assignments on the last day of the
        class"). So the most common lock_at in the shell is that date, read back
        off Canvas rather than out of the syllabus, which is what lets an
        assignment created here say "Available until" the same day as its
        neighbours without this script ever opening the repository.
        """
        if self._lock_at is not False:
            return self._lock_at

        stamps = [
            str(getattr(a, "lock_at", None)).replace(".000Z", "Z")
            for a in self.assignments()
            if getattr(a, "lock_at", None)
        ]
        if not stamps:
            self._lock_at = None
            return None

        counts = Counter(stamps)
        # Most common wins; a tie goes to the later date, so a term that was extended
        # mid-course does not pull new assignments back to the old close-out day.
        best = max(counts, key=lambda s: (counts[s], s))
        self._lock_at = (best, counts[best], len(stamps))
        return self._lock_at

    def module_for_date(self, day):
        """The dated module for this calendar day, or None when the shell has none.

        Two modules on one date -- an extra session pinned there with cdate: -- is
        ambiguous, and picking the first would file work into whichever the API
        happened to list first. Say so and let the operation name the module.
        """
        if day is None:
            return None
        hits = [m for m in self.modules() if module_date(self._label(m)) == day]
        if len(hits) > 1:
            die("%d modules are dated %s:\n  %s\nName one with module: in the operation."
                % (len(hits), date_header(day),
                   "\n  ".join(sorted(self._label(m) for m in hits))))
        return hits[0] if hits else None

    def items_for_assignment(self, assignment_id):
        """Every Assignment-type module item pointing at this assignment."""
        found = []
        for module in self.modules():
            for item in self.items(module):
                if getattr(item, "type", None) != "Assignment":
                    continue
                if str(getattr(item, "content_id", "")) == str(assignment_id):
                    found.append((module, item))
        return found

    def handout_items(self, assignment_name):
        """Every module item that is this assignment's "handed out" entry.

        A deploy titles it with the deliverable's dtitle, which is the assignment
        name with " Handed Out" still on the end -- but the suffix has been written
        with varying case over the years, and the item is a subheader or an
        external link, so nothing but its title identifies it. Match on the title
        with that suffix stripped, case-insensitively, rather than reconstructing
        the title and hoping it is spelled the same way.
        """
        needle = str(assignment_name).strip().lower()
        suffix = HANDOUT_SUFFIX.strip().lower()
        found = []
        for module in self.modules():
            for item in self.items(module):
                label = self._label(item).strip()
                lowered = label.lower()
                if not lowered.endswith(suffix):
                    continue
                if lowered[: -len(suffix)].strip() == needle:
                    found.append((module, item))
        return found

    # -- writes ------------------------------------------------------------

    def add_item(self, module, payload):
        """Add an item to a module and publish the module, as a deploy does.

        This matches add_module_item in ursinus_canvas.py. An item filed into a
        module nobody can see is not filed at all, so the module goes out with it;
        the plan says which module will be published before anything is written.
        """
        sleep_for_rate_limit()
        created = module.create_module_item(module_item=payload)
        module.edit(module={"published": True})
        module.published = True
        self.forget_items(module)
        return created

    def move_item(self, item, source, destination, payload):
        """Recreate an item in another module, then drop the original.

        Canvas has no "move this item to that module", so this is the same
        create-then-delete the item.move operation has always used. Creating first
        means a failure leaves the item where it was rather than nowhere -- but it
        also means a failure on the second half leaves it in both places, which a
        student would see, so that case says exactly what to go and fix.
        """
        created = self.add_item(destination, payload)
        try:
            sleep_for_rate_limit()
            item.delete()
        except Exception as exc:
            raise RuntimeError(
                "copied %r into %r but could not remove the original from %r (%s): "
                "it is now in both modules and students see both; remove one by hand"
                % (payload.get("title"), self._label(destination),
                   self._label(source), exc))
        finally:
            self.forget_items(source)
        return created

    def remove_item(self, module, item):
        """Delete a module item, tolerating one that is already gone.

        Deleting an assignment takes its Assignment-type module items with it, so
        by the time this runs the item may not exist. That is success, not failure;
        the handout entry beside it is an unlinked subheader or URL that Canvas
        will not clean up on its own, and that is the one that has to go.
        """
        try:
            sleep_for_rate_limit()
            item.delete()
            return True
        except Exception as exc:
            warn("could not remove module item %r from %r (it may already be gone): %s"
                 % (self._label(item), self._label(module), exc))
            return False
        finally:
            self.forget_items(module)

    def retitle_item(self, module, item, title):
        sleep_for_rate_limit()
        item.edit(module_item={"title": title})
        self.forget_items(module)

    def create_rubric(self, payload):
        sleep_for_rate_limit()
        return self.course.create_rubric(**payload)

    def clear_allowed_extensions(self, assignment_id):
        """Take the upload restriction off an assignment, and report what actually happened.

        Sent by hand rather than through canvasapi: an empty Python list flattens to no
        form parameters at all, so the key never reaches Canvas and the restriction
        survives. A single empty array element does reach it. Canvas's handling of that is
        the part this cannot know in advance, so the assignment is read back afterwards and
        the caller is told the truth rather than the intent.
        """
        sleep_for_rate_limit()
        self._http("/api/v1/courses/%s/assignments/%s" % (self.course.id, assignment_id),
                   method="PUT",
                   fields=[("assignment[allowed_extensions][]", "")])
        sleep_for_rate_limit()
        raw = self._http("/api/v1/courses/%s/assignments/%s"
                         % (self.course.id, assignment_id)).read()
        left = json.loads(raw.decode("utf-8")).get("allowed_extensions") or []
        if left:
            warn("asked Canvas to drop the upload restriction on assignment %s, but it "
                 "still allows only %s; clear it in the Canvas UI"
                 % (assignment_id, " ".join(left)))
            return "upload restriction NOT cleared (still %s)" % " ".join(left)
        return "cleared the upload restriction"

    def grading_exposure(self, assignment):
        """How much grading a rubric replacement would discard.

        Ported from canvas_sync_rubrics.py, which refuses the same replacement for
        the same reason: deleting a rubric deletes every per-criterion score
        recorded against it.
        """
        submitted, assessed = 0, 0
        try:
            sleep_for_rate_limit()
            for sub in assignment.get_submissions(include=["rubric_assessment"]):
                if getattr(sub, "workflow_state", "unsubmitted") != "unsubmitted":
                    submitted += 1
                if getattr(sub, "rubric_assessment", None):
                    assessed += 1
        except Exception as exc:
            warn("could not read submissions for %r: %s" % (assignment.name, exc))
            return (None, None)
        return (submitted, assessed)

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
    # submission_types and allowed_extensions are not in this table: they are decided
    # together by resolve_submission_spec, because a token like "written" sets both.
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

    types, extensions, notes = resolve_submission_spec(change)
    if types is not None:
        payload["submission_types"] = types
    if isinstance(extensions, list):
        payload["allowed_extensions"] = extensions
    summary.extend(notes)

    # A clear cannot ride along in this payload: canvasapi flattens a list into repeated
    # assignment[allowed_extensions][] parameters, and an empty list emits none of them, so
    # the key never reaches Canvas and the old restriction survives a write that reported
    # success. clear_allowed_extensions below sends it as a form parameter that does exist.
    return payload, summary, extensions is CLEAR_EXTENSIONS


# Below this share of the shell's assignments agreeing on a close-out date, the "date the
# rest of the course uses" is not really a consensus and gets a warning rather than silence.
LOCK_CONSENSUS_THRESHOLD = 0.6


def default_lock_at(canvas, due_at):
    """(Canvas timestamp, where it came from) for a new assignment's close-out date.

    Every assignment a full deploy writes is available until the last day of class,
    so one added mid-term should be too, or the Assignments page shows a single
    assignment with no end date beside forty that have one.

    The date is read off the shell rather than out of the syllabus, deliberately:
    this script's whole promise is that applying a change document never consults
    the repository, and there is nothing to consult it for here, since the
    assignments already in Canvas were given that date by the deploy that put them
    there. --last-class-date is for the case where they cannot answer.

    A lock that falls before the due date makes an assignment unsubmittable at the
    moment it is due, so a default that would do that is refused rather than
    applied; an explicit lock: is still honored, because that one was asked for.
    """
    if canvas.last_class_date:
        stamp, source = canvas_due(canvas.last_class_date, "last-class-date"), "--last-class-date"
    else:
        found = canvas.default_lock_at()
        if not found:
            return None, ("no other assignment in this shell carries one; "
                          "pass lock: or --last-class-date")
        stamp, count, total = found
        source = "matching %d of %d assignment(s) already in this shell" % (count, total)
        if count < LOCK_CONSENSUS_THRESHOLD * total:
            warn("only %d of %d assignments in this shell share a close-out date, so %s is a "
                 "guess; pass --last-class-date to be sure" % (count, total, stamp))
            source += " -- a weak majority, check it"

    if due_at and stamp and stamp < due_at:
        return None, ("the shell's close-out date %s is before this assignment's due date, "
                      "which would make it unsubmittable; pass lock: explicitly if that is "
                      "really what you want" % describe_due(stamp))

    return stamp, source


def handout_title(name):
    return "%s%s" % (str(name).strip(), HANDOUT_SUFFIX)


def resolve_target_module(canvas, change, key, day, lines, what):
    """Which module an item belongs in, and a line saying so.

    An explicit module name in the operation wins, which is how an item is filed
    into a standing module ("Resources") that carries no date. Otherwise the day
    picks the module, by the date header a deploy writes at the front of its name.
    A day the shell has no module for is reported and skipped -- not guessed at
    from a neighbouring day, and not fatal, because one off-grid date should not
    block an otherwise good change document.
    """
    named = change.get(key)
    if named:
        module = canvas.find_module(named)
        if module is None:
            die("op %d (%s): no module matches %r"
                % (change["_index"], change["op"], named))
        lines.append("  %s -> module %r" % (what, canvas._label(module)))
        return module

    if day is None:
        return None

    module = canvas.module_for_date(day)
    if module is None:
        lines.append("  %s: no module dated %s; skipping the modules page"
                     % (what, date_header(day)))
        warn("no module dated %s in this shell, so %s was left off the modules page"
             % (date_header(day), what))
        canvas.unfiled.append("%s (no module dated %s)" % (what, date_header(day)))
        return None

    if not getattr(module, "published", True):
        lines.append("  NOTE %r is unpublished and WILL BE PUBLISHED to release the item"
                     % canvas._label(module))

    lines.append("  %s -> module %r" % (what, canvas._label(module)))
    return module


def plan_module_moves(canvas, change, assignment, payload, lines):
    """What the modules page has to do to keep up with this update.

    Returns a list of callables, each returning a one-line report. Everything is
    resolved here, before any write: which item is where now, where it should be,
    and whether a module for that day exists at all.
    """
    if not canvas.modules_enabled:
        return []

    moves = []
    old_name = assignment.name
    new_name = change.get("rename") or old_name

    # A due date that moved takes the assignment's module item with it, so the item sits
    # on the day the work is due rather than the day it used to be due.
    if "due_at" in payload:
        target_day = student_day(change.get("due"))
        if target_day is None:
            target_day = student_day(payload["due_at"])

        destination = None
        if target_day is not None or change.get("module"):
            destination = resolve_target_module(
                canvas, change, "module", target_day, lines, "assignment item")
        elif payload["due_at"] is None:
            # due: null clears the date; there is no day to file it under any more, and
            # moving it somewhere arbitrary would be worse than leaving it alone.
            lines.append("  due date cleared; the module item stays where it is")
        else:
            lines.append("  could not read %r as a day, so the modules page was left alone"
                         % change.get("due"))
            warn("could not read %r as a day; %r was left where it is on the modules page"
                 % (change.get("due"), assignment.name))
        if destination is not None:
            for module, item in canvas.items_for_assignment(assignment.id):
                if module.id == destination.id:
                    lines.append("  assignment item is already in %r"
                                 % canvas._label(destination))
                    continue
                if module_date(canvas._label(module)) is None:
                    # A standing module ("Resources") is a deliberate placement, not a
                    # date that drifted. Leave it where its author put it.
                    lines.append("  assignment item stays in %r (not a dated module)"
                                 % canvas._label(module))
                    continue
                lines.append("  move assignment item %r -> %r"
                             % (canvas._label(module), canvas._label(destination)))
                moves.append(_mover(canvas, module, item, destination, new_name))

    # The handout entry moves the same way, but only when the operation names a new
    # handout day: nothing else in the document implies one.
    if change.get("handout"):
        handout_day = student_day(change["handout"])
        if handout_day is None and not change.get("handout_module"):
            die("op %d: could not read %r as a handout day (try 2026-10-22)"
                % (change["_index"], change["handout"]))
        destination = resolve_target_module(
            canvas, change, "handout_module", handout_day,
            lines, "%r" % handout_title(new_name))
        if destination is not None:
            existing = canvas.handout_items(old_name)
            if not existing:
                lines.append("  no %r item exists yet; adding one"
                             % handout_title(old_name))
                moves.append(_handout_adder(canvas, destination, change, new_name))
            for module, item in existing:
                if module.id == destination.id:
                    lines.append("  handout item is already in %r"
                                 % canvas._label(destination))
                    continue
                lines.append("  move handout item %r -> %r"
                             % (canvas._label(module), canvas._label(destination)))
                moves.append(_mover(canvas, module, item, destination,
                                    handout_title(new_name)))

    # A rename that leaves the module items titled with the old name is how the modules
    # page and the gradebook stop agreeing with each other.
    if change.get("rename") and new_name != old_name:
        for module, item in canvas.items_for_assignment(assignment.id):
            if canvas._label(item).strip() == old_name.strip():
                lines.append("  retitle module item in %r -> %r"
                             % (canvas._label(module), new_name))
                moves.append(_retitler(canvas, module, item, new_name))
        for module, item in canvas.handout_items(old_name):
            lines.append("  retitle module item in %r -> %r"
                         % (canvas._label(module), handout_title(new_name)))
            moves.append(_retitler(canvas, module, item, handout_title(new_name)))

    return moves


def move_payload(item, title):
    """Everything an item carries, as the payload that recreates it in another module.

    A move is a create plus a delete, so anything left out of here is silently lost:
    an indent flattens, and a completion requirement ("students must submit this")
    disappears from a module that had one, which changes what the module says a
    student has to do. A url left out is worse than silent -- Canvas refuses to
    create an ExternalUrl item with no external_url, so the move fails outright.

    Both movers build their payload here so that neither can drift into copying less
    than the other.
    """
    payload = {"title": title,
               "type": getattr(item, "type", "Assignment"),
               "published": getattr(item, "published", True)}
    for attr in ("content_id", "external_url", "page_url", "indent", "position"):
        value = getattr(item, attr, None)
        if value is not None:
            payload[attr] = value
    if payload.get("external_url"):
        payload["new_tab"] = getattr(item, "new_tab", True)

    requirement = getattr(item, "completion_requirement", None) or {}
    if requirement.get("type"):
        payload["completion_requirement[type]"] = requirement["type"]
        if requirement.get("min_score") is not None:
            payload["completion_requirement[min_score]"] = requirement["min_score"]

    return payload


def _mover(canvas, source, item, destination, title):
    payload = move_payload(item, title)

    def run():
        canvas.move_item(item, source, destination, payload)
        return "moved %r to %r" % (title, canvas._label(destination))

    return run


def _handout_adder(canvas, destination, change, name):
    payload = {"title": handout_title(name), "published": True}
    url = change.get("url")
    if url:
        payload["type"] = "ExternalUrl"
        payload["external_url"] = url
        payload["new_tab"] = True
    else:
        payload["type"] = "SubHeader"

    def run():
        canvas.add_item(destination, payload)
        return "added %r to %r" % (payload["title"], canvas._label(destination))

    return run


def _retitler(canvas, module, item, title):
    def run():
        canvas.retitle_item(module, item, title)
        return "retitled a module item in %r to %r" % (canvas._label(module), title)

    return run


def plan_rubric(change, assignment_name, points, lines, offline=False):
    """Read and validate a rubric file now, so that --apply only writes.

    Returns a callable taking the assignment id and building the Canvas payload, or
    None when the operation names no rubric.
    """
    rubricpath = change.get("rubricpath")
    if not rubricpath:
        return None

    if not os.path.exists(rubricpath):
        die("op %d (%s): no rubric file at %s (paths are relative to the current directory)"
            % (change["_index"], change["op"], rubricpath))

    rubrics = rubric_module(required=not offline)
    if rubrics is None:
        return None

    try:
        rubric = rubrics.read_rubric(rubricpath)
    except ImportError as exc:
        if offline:
            lines.append("  rubric %s not validated: %s" % (rubricpath, exc))
            warn("python-frontmatter is not installed, so %s was not validated" % rubricpath)
            return None
        die("reading %s needs python-frontmatter: %s" % (rubricpath, exc))
    except Exception as exc:
        die("op %d: could not read the rubric in %s: %s" % (change["_index"], rubricpath, exc))

    problems = rubrics.validate_rubric(rubric, rubricpath)
    if problems:
        die("op %d: %s does not describe a usable rubric:\n  %s"
            % (change["_index"], rubricpath, "\n  ".join(problems)))

    lines.append("  rubric %s: %d criteria over %g points"
                 % (rubricpath, len(rubric), points))

    def build(assignment_id):
        return rubrics.build_rubric_payload(rubric, assignment_id, assignment_name, points)

    return build


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
        payload, summary, clear_extensions = assignment_payload(canvas, change)
        payload["name"] = name
        payload.setdefault("points_possible", float(change.get("points", 100)))
        payload.setdefault("published", as_bool(change.get("published", True)))
        payload.setdefault("submission_types", ["online_upload"])
        lines.append("create assignment %r" % name)
        lines.append("  %d points, %spublished, submission %s"
                     % (payload["points_possible"],
                        "" if payload["published"] else "un",
                        ",".join(payload["submission_types"])))
        if payload.get("allowed_extensions"):
            lines.append("  uploads limited to %s" % " ".join(payload["allowed_extensions"]))
        for s in summary:
            if not s.startswith(("points ", "published ", "submission_types ",
                                 "allowed_extensions ")):
                lines.append("  %s" % s)

        # Available until the last day of class, the way every assignment a full deploy
        # writes is. Only on create: an update should change what it names and nothing else.
        if "lock_at" not in payload:
            lock_at, source = default_lock_at(canvas, payload.get("due_at"))
            if lock_at:
                payload["lock_at"] = lock_at
                lines.append("  available until %s [%s]" % (describe_due(lock_at), source))
            else:
                lines.append("  available until: NOT SET (%s)" % source)

        if clear_extensions:
            # Nothing to clear on an assignment that does not exist yet: not sending the
            # key is exactly what "no restriction" means at creation time.
            payload.pop("allowed_extensions", None)

        rubric_for = plan_rubric(change, name,
                                 float(payload["points_possible"]), lines)

        due_module = handout_module = None
        if canvas.modules_enabled:
            due_module = resolve_target_module(
                canvas, change, "module", student_day(change.get("due")),
                lines, "assignment item")
            if change.get("handout"):
                handout_module = resolve_target_module(
                    canvas, change, "handout_module", student_day(change["handout"]),
                    lines, "%r" % handout_title(name))

        def do():
            sleep_for_rate_limit()
            created = canvas.course.create_assignment(payload)
            canvas.assignments(refresh=True)
            done = ["created assignment %s (id %s)" % (created.name, created.id)]

            # The rubric goes on here rather than as its own operation because every
            # operation is resolved against the shell before any write, and an
            # assignment created by this very run cannot be resolved beforehand.
            if rubric_for is not None:
                try:
                    canvas.create_rubric(rubric_for(created.id))
                    done.append("attached its rubric")
                except Exception as exc:
                    warn("created %r but could not attach its rubric: %s" % (created.name, exc))
                    done.append("RUBRIC FAILED (%s)" % exc)

            # The assignment exists now, so a module failure must not be reported as
            # though the whole operation failed and can simply be re-run.
            if due_module is not None:
                try:
                    canvas.add_item(due_module, {
                        "title": name,
                        "type": "Assignment",
                        "content_id": created.id,
                        "published": True,
                    })
                    done.append("filed it under %r" % canvas._label(due_module))
                except Exception as exc:
                    warn("created %r but could not file it under %r: %s"
                         % (name, canvas._label(due_module), exc))
                    canvas.unfiled.append("%s (%s)" % (name, exc))
                    done.append("MODULE ITEM FAILED (%s)" % exc)

            if handout_module is not None:
                item = {"title": handout_title(name), "published": True}
                url = change.get("url")
                if url:
                    item["type"] = "ExternalUrl"
                    item["external_url"] = url
                    item["new_tab"] = True
                else:
                    item["type"] = "SubHeader"
                try:
                    canvas.add_item(handout_module, item)
                    done.append("added %r to %r"
                                % (item["title"], canvas._label(handout_module)))
                except Exception as exc:
                    warn("could not add %r to %r: %s"
                         % (item["title"], canvas._label(handout_module), exc))
                    canvas.unfiled.append("%s (%s)" % (item["title"], exc))
                    done.append("HANDOUT ITEM FAILED (%s)" % exc)

            return "; ".join(done)

        return lines, do

    if op in ("assignment.update", "assignment.due", "rubric.detach", "rubric.replace",
              "assignment.delete"):
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

            stale = []
            if canvas.modules_enabled:
                stale = (canvas.items_for_assignment(assignment.id)
                         + canvas.handout_items(assignment.name))
                for module, item in stale:
                    lines.append("  also removes module item %r from %r"
                                 % (canvas._label(item), canvas._label(module)))
                if not stale:
                    lines.append("  no module items point at it")

            def do():
                # Module items first, while the assignment still exists to identify them.
                # Canvas drops the Assignment-type item itself when the assignment goes, so
                # removing it here is belt and braces; the handout entry beside it is an
                # unlinked subheader or URL that nothing else would ever clean up.
                removed = 0
                for module, item in stale:
                    if canvas.remove_item(module, item):
                        removed += 1
                sleep_for_rate_limit()
                assignment.delete()
                canvas.assignments(refresh=True)
                canvas.modules(refresh=True)   # drops the item caches with them
                if removed:
                    return "deleted assignment %r and %d module item(s)" % (assignment.name, removed)
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
            submitted, assessed = canvas.grading_exposure(assignment)
            change["_assessments"] = assessed
            if submitted is None:
                lines.append("  grading exposure unknown (could not read submissions)")
            else:
                lines.append("  %d submission(s), %d carrying rubric assessments"
                             % (submitted, assessed))
            if assessed:
                lines.append("  WARNING detaching this rubric DISCARDS %d rubric assessment(s)"
                             % assessed)

            def do():
                canvas.detach_rubric(meta)
                return "detached rubric %s from %r" % (meta["rubric_id"], assignment.name)

            return lines, do

        if op == "rubric.replace":
            if not change.get("rubricpath"):
                die("op %d (rubric.replace): 'rubricpath' is required -- the markdown page "
                    "whose info.rubric block holds the rubric" % change["_index"])

            points = float(change.get("points")
                           or getattr(assignment, "points_possible", None) or 100)
            lines.append("replace rubric on %r (id %s)" % (assignment.name, assignment.id))

            meta = canvas.rubric_meta(assignment.id)
            if meta["rubric_id"]:
                lines.append("  Canvas has rubric %s %r (%d criteria)"
                             % (meta["rubric_id"], meta["title"], meta["criteria_count"]))
            else:
                lines.append("  Canvas has no rubric on it yet; this only creates one")

            build = plan_rubric(change, assignment.name, points, lines)

            submitted, assessed = canvas.grading_exposure(assignment)
            change["_assessments"] = assessed
            if submitted is None:
                lines.append("  grading exposure unknown (could not read submissions)")
            else:
                lines.append("  %d submission(s), %d carrying rubric assessments"
                             % (submitted, assessed))
            if assessed:
                lines.append("  WARNING replacing this rubric DISCARDS %d rubric assessment(s)"
                             % assessed)

            def do():
                if meta["rubric_id"]:
                    canvas.detach_rubric(meta)
                canvas.create_rubric(build(assignment.id))
                return "replaced the rubric on %r" % assignment.name

            return lines, do

        if op == "assignment.due":
            change = dict(change)
            change["due"] = change.get("due")

        payload, summary, clear_extensions = assignment_payload(canvas, change)
        if not payload and not (canvas.modules_enabled and change.get("handout")):
            die("op %d (%s): nothing to change on %r"
                % (change["_index"], op, assignment.name))

        lines.append("update assignment %r (id %s)" % (assignment.name, assignment.id))
        if "due_at" in payload:
            lines.append("  due   %s" % describe_due(getattr(assignment, "due_at", None)))
            lines.append("     -> %s" % describe_due(payload["due_at"]))
            summary = [s for s in summary if not s.startswith("due ->")]
        for s in summary:
            lines.append("  %s" % s)

        moves = plan_module_moves(canvas, change, assignment, payload, lines)

        def do():
            if payload:
                sleep_for_rate_limit()
                assignment.edit(assignment=payload)
                canvas.assignments(refresh=True)
            done = ["updated %r" % assignment.name] if payload else []
            if clear_extensions:
                done.append(canvas.clear_allowed_extensions(assignment.id))
            for move in moves:
                # A module item that could not be moved should not abort the rest: the
                # assignment edit above has already landed, and the remaining moves are
                # independent of each other.
                try:
                    done.append(move())
                except Exception as exc:
                    warn("%r: %s" % (assignment.name, exc))
                    done.append("MODULE ITEM FAILED (%s)" % exc)
            return "; ".join(d for d in done if d) or "nothing to do on %r" % assignment.name

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
        publish = as_bool(change.get("published", True))
        lines.append("  and publish it" if publish else "  and leave it unpublished")

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
            created = canvas.add_item(module, payload)
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
            canvas.forget_items(module)
            return "removed %r from %r" % (item.title, module.name)

        return lines, do

    # item.move
    if change.get("to_module"):
        destination = canvas.find_module(change["to_module"])
        if destination is None:
            die("no module named %r to move into" % change["to_module"])
        payload = move_payload(item, item.title)
        if "position" in change:
            payload["position"] = int(change["position"])
        lines.append("move item %r from %r to %r" % (item.title, module.name, destination.name))

        def do():
            canvas.move_item(item, module, destination, payload)
            return "moved %r to %r" % (payload["title"], destination.name)

        return lines, do

    position = int(change["position"])
    lines.append("move item %r in %r to position %d (from %s)"
                 % (item.title, module.name, position, getattr(item, "position", "?")))

    def do():
        sleep_for_rate_limit()
        item.edit(module_item={"position": position})
        canvas.forget_items(module)
        return "moved %r to position %d" % (item.title, position)

    return lines, do


# --------------------------------------------------------------------------
# --generate: compare the repository to the live shell
# --------------------------------------------------------------------------

DEFAULT_SYLLABUS = os.path.join("_pages", "syllabus.md")


def addslash(text):
    return text if text.endswith("/") else text + "/"


def strip_marker(title):
    """A deliverable's base name: the title without its trailing Due / Handed Out.

    Only the trailing marker comes off. The leading label ("Written Assignment: ")
    stays, because that prefix is what ursinus_canvas.py reads to decide which
    assignment group the assignment belongs in, and the names it produced are the
    names in the shell this is being compared against.
    """
    text = str(title or "").strip()
    for marker in (" Handed Out", " Due"):
        if text.lower().endswith(marker.lower()):
            return text[: -len(marker)].strip()
    return text


def meeting_dates(markdown_path):
    """(week, ordinal) -> calendar date, from the sibling schedule script.

    That script already knows how to walk the meeting pattern, and re-deriving it
    here is how the two would drift apart. It does not honor cdate:, though, and
    ursinus_canvas.py does -- a session pinned to a literal calendar date names its
    module by that date -- so cdate entries are overlaid here.
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
    days = {(m.week, m.ordinal_in_week): m.date for m in plan.meetings}

    for item in frontmatter_dict.get("schedule", []) or []:
        cdate = str(item.get("cdate") or "").strip()
        if not cdate:
            continue
        pinned = student_day(cdate)
        if pinned is None:
            warn("could not read cdate %r in the schedule; leaving that entry on the "
                 "computed meeting grid" % cdate)
            continue
        try:
            days[(int(item.get("week")), int(item.get("date", 0)))] = pinned
        except (TypeError, ValueError):
            continue

    return days, frontmatter_dict


def syllabus_expectations(markdown_path):
    """What the repository says every Canvas assignment should look like.

    Names follow ursinus_canvas.py: strip a trailing " Due", skip quizzes. Those
    are the names that created the shell, so they are the names that have to match
    it. "Handed Out" rows do not become assignments either, but they do say which
    day the assignment is handed out on, so they are collected rather than dropped.
    """
    meetings, doc = meeting_dates(markdown_path)
    info = doc.get("info") or {}
    homepage = addslash(str(info.get("course_homepage") or ""))

    expected = {}
    handouts = {}
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
            if "quiz:" in dtitle.lower():
                continue

            name = strip_marker(dtitle)
            if dtitle.lower().endswith(" handed out"):
                handouts[name] = day
                continue

            dlink = deliverable.get("dlink")
            expected[name] = {
                "name": name,
                "points": float(deliverable.get("points", 100)),
                "day": day,
                "url": (homepage + str(dlink)) if dlink and homepage else None,
                "submission_types": (deliverable.get("submission_types") or "").strip() or None,
                "rubricpath": deliverable.get("rubricpath") or None,
                "module": standing_module_name(deliverable),
            }

    for name, day in handouts.items():
        if name in expected:
            expected[name]["handout"] = day

    return expected, info


def standing_module_name(deliverable):
    """The standing module a deliverable is tagged into, by its real Canvas name.

    A deliverable carrying module: resource or module: overarching is filed into a
    module that stands above the term rather than onto its own day, and the tag has
    to be translated into the module's actual name for the change document to
    resolve it. The vocabulary is ursinus_canvas.py's; unknown tags are left to it
    to complain about.
    """
    tag = str((deliverable or {}).get("module") or "").strip().lower()
    if tag in ("resource", "resources"):
        return "Resources"
    if tag in ("overarching", "participation", "overarching participation"):
        return "Overarching Class Participation Activities"
    return None


def course_end_lock(info):
    """The close-out instant a full deploy writes, as a literal timestamp.

    ursinus_canvas.py shifts course_end_date forward a day and then reads the
    daylight-saving clock off the *shifted* date, while canvas_due here reads it
    off the day given. Those differ by an hour for a term ending the day before a
    clock change, so this emits the finished instant rather than a bare date: a
    generated document should reproduce the publisher's value exactly, or every
    later diff reports an hour of drift that is not really there.
    """
    end = str((info or {}).get("course_end_date") or "").strip()
    if not end:
        return None
    day = student_day(end)
    if day is None:
        warn("could not read course_end_date %r; no lock date was emitted" % end)
        return None
    shifted = datetime(day.year, day.month, day.day) + timedelta(days=DUE_DATE_OFFSET)
    clock = DUE_TIME_DST if is_dst(shifted) else DUE_TIME_ST
    return "%sT%sZ" % (shifted.strftime("%Y-%m-%d"), clock)


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

    expected, info = syllabus_expectations(markdown_path)
    if not expected:
        die("no deliverables found in %s" % markdown_path)

    lock = course_end_lock(info)
    module_days = {module_date(canvas._label(m)) for m in canvas.modules()}
    module_days.discard(None)

    live = {}
    for assignment in canvas.assignments():
        live[(assignment.name or "").strip()] = assignment

    out, deferred = [], []
    counts = {"create": 0, "due": 0, "points": 0, "url": 0, "orphan": 0,
              "nomodule": 0, "rubric": 0}

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
            if want.get("handout"):
                out.append("    handout: %s" % want["handout"].strftime("%Y-%m-%d"))
            if want["url"]:
                out.append("    url: %s" % yaml_quote(want["url"]))
            if want.get("submission_types"):
                out.append("    submission_types: %s" % yaml_quote(want["submission_types"]))
            if want.get("module"):
                out.append("    module: %s" % yaml_quote(want["module"]))
            if want.get("rubricpath"):
                # Safe uncommented: an assignment that does not exist has no rubric, and
                # therefore no rubric assessments, to lose.
                out.append("    rubricpath: %s" % yaml_quote(want["rubricpath"]))
            if lock:
                # Quoted: unquoted, PyYAML reads it back as a datetime rather than a string.
                out.append("    lock: %s   # the last day of class" % yaml_quote(lock))
            out.append("    published: true")
            out.append("")
            # An assignment tagged into a standing module does not want a dated one, so
            # its due day having no module is not a problem to report.
            checks = [] if want.get("module") else [(want["day"], "due")]
            checks.append((want.get("handout"), "handed out"))
            for day, what in checks:
                if day and module_days and day not in module_days:
                    counts["nomodule"] += 1
                    out.append("# note: no module in this shell is dated %s, so %r will not "
                               "be filed on the modules page when it is %s"
                               % (date_header(day), name, what))
                    out.append("")
            continue

        if want.get("rubricpath"):
            counts["rubric"] += 1
            deferred.append((name, want["rubricpath"], assignment))

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
    print("# Nothing about the modules page is diffed here: an assignment being created")
    print("# carries the day it is due and the day it is handed out, so that applying this")
    print("# files it where a full deploy would have, but existing module items are never")
    print("# reordered, re-placed, or removed by anything in this document.")
    print("# Review before applying; this is a description of drift, not a decision.")

    dated = [want["day"] for want in expected.values()
             if want["day"] and not want.get("module")]
    misfits = sorted(d for d in dated if d not in module_days)
    if module_days and dated and len(misfits) > len(dated) / 2:
        print("#")
        print("# WARNING %d of %d deliverable days do not match any module in this shell."
              % (len(misfits), len(dated)))
        print("# The meeting dates computed here come from the schedule script, which counts")
        print("# weeks from the Monday of the week course_start_date falls in, while the")
        print("# deploy that named these modules counted from course_start_date itself. They")
        print("# agree only when the term starts on a Monday. Check course_start_date before")
        print("# trusting the due dates below, not just the module placement.")

    if out:
        print("changes:")
        for line in out:
            print(line)
    else:
        print("# No assignment drift: Canvas matches the repository.")
        print("changes: []")

    if deferred:
        print("# %d assignment(s) already in Canvas have a rubric in the repository."
              % len(deferred))
        print("# Uncomment to replace. Replacing a rubric deletes it, and any per-criterion")
        print("# scores recorded against it go with it, so the counts below are the whole story.")
        for name, rubricpath, assignment in deferred:
            _, assessed = canvas.grading_exposure(assignment)
            label = "unknown" if assessed is None else "%d" % assessed
            print("#   - op: rubric.replace")
            print("#     name: %s" % yaml_quote(name))
            print("#     rubricpath: %s   # %s rubric assessment(s) would be discarded"
                  % (yaml_quote(rubricpath), label))

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

def check_dependencies(changes):
    """Refuse a document whose operations depend on each other's writes.

    Every operation is resolved against the live shell before any of them runs, so
    an operation that needs to see what an earlier one created or moved is
    resolving against a shell that does not have it yet. The failures are quiet
    ones -- a module item moved by operation 2 and then retitled by operation 5 is
    retitled at an id operation 2 deleted -- so they are caught here and named
    rather than discovered afterwards from the modules page.

    The fix is always the same: run the document in two passes, or fold the two
    operations into one.
    """
    # What each operation writes that a later one might need to have seen.
    creates = {}          # assignment name -> operation number
    disturbs = {}         # assignment name -> operation number, for item-level surgery
    new_modules = []      # operation numbers creating a module

    def key(change):
        return str(change.get("name") or "").strip().lower()

    for change in changes:
        op, idx, name = change["op"], change["_index"], key(change)

        if op == "module.create":
            new_modules.append(idx)

        if name:
            if name in creates:
                die("operation %d names %r, which operation %d creates in this same run. "
                    "Every operation is resolved before any of them writes, so the second "
                    "one cannot see the first one's assignment. Split this into two "
                    "documents." % (idx, change.get("name"), creates[name]))
            if name in disturbs and op != "assignment.delete":
                die("operation %d and operation %d both act on %r, and the earlier one "
                    "rearranges its module items. The later one was resolved against the "
                    "modules page as it looks now, not as operation %d leaves it. Fold "
                    "them into one operation, or split this into two documents."
                    % (idx, disturbs[name], change.get("name"), disturbs[name]))

        if op == "assignment.create" and name:
            creates[name] = idx
        elif op in ("assignment.update", "assignment.due") and name:
            if any(k in change for k in ("due", "handout", "rename")):
                disturbs[name] = idx
        elif op == "assignment.delete" and name:
            disturbs[name] = idx

    if new_modules and any(c["op"] in ("assignment.create", "assignment.update",
                                       "assignment.due") for c in changes):
        warn("this document creates a module and also files assignments onto the modules "
             "page. A module created here does not exist yet when the other operations are "
             "resolved, so anything due on its day will be reported as having no module. "
             "Create the module in a separate run first.")


def report_unfiled(canvas):
    """Say what never made it onto the modules page.

    Warnings scroll past. A run that ends "All 6 change(s) applied" while two of
    them are missing from the page students navigate has told the truth about
    Canvas and a lie about the course, so the count is repeated at the end where
    the summary is.
    """
    if not canvas.unfiled:
        return
    print("\n%d item(s) were NOT placed on the modules page:" % len(canvas.unfiled),
          file=sys.stderr)
    for entry in canvas.unfiled:
        print("  %s" % entry, file=sys.stderr)
    print("Add them by hand, or create the missing module and re-run with module: naming it.",
          file=sys.stderr)


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
    p.add_argument("--force-graded", action="store_true",
                   help="permit rubric.replace on a rubric that already carries rubric "
                        "assessments, discarding them")
    p.add_argument("--no-modules", action="store_true",
                   help="do not touch the modules page: skip filing a new assignment under "
                        "its due day, moving it when its due date moves, and removing its "
                        "items when it is deleted")
    p.add_argument("--last-class-date", default=None, metavar="YYYY-MM-DD",
                   help="the last day of class, used as the 'available until' date for "
                        "assignments this run creates. Without it the date is read off the "
                        "assignments already in the shell.")
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
    check_dependencies(changes)
    print("Parsed %d operation(s):" % len(changes))
    for change in changes:
        label = change.get("name") or change.get("title") or change.get("module") or ""
        print("  %2d. %-18s %s" % (change["_index"], change["op"], label))
    print()

    if args.check:
        for change in changes:
            label = change.get("name") or change.get("title") or change["op"]
            for key in ("due", "unlock", "lock", "handout"):
                if change.get(key) is not None and key in change:
                    if key == "handout":
                        day = student_day(change[key])
                        print("  %s: handed out %s -> module dated %s"
                              % (label, change[key],
                                 date_header(day) if day else "(unreadable date)"))
                    else:
                        print("  %s: %s -> %s"
                              % (label, key, describe_due(canvas_due(change[key], key))))
            types, extensions, notes = resolve_submission_spec(change)
            for note in notes:
                print("  %s: %s" % (label, note))
            if change.get("rubricpath"):
                built = plan_rubric(change, str(label),
                                    float(change.get("points") or 100), [], offline=True)
                print("  %s: rubric %s %s"
                      % (label, change["rubricpath"],
                         "reads and validates" if built else "NOT validated (see the warning)"))
        if args.last_class_date:
            print("  available until %s"
                  % describe_due(canvas_due(args.last_class_date, "last-class-date")))
        print("--check: parsed locally; Canvas was not contacted.")
        return 0

    canvas = connect(args)
    canvas.modules_enabled = not args.no_modules
    canvas.last_class_date = args.last_class_date
    print("Course %s: %s\n" % (canvas.course.id, getattr(canvas.course, "name", "?")))
    if args.no_modules:
        print("--no-modules: the modules page will not be touched.\n")

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

    graded = [
        c for c, _, _ in plan
        if c["op"] in ("rubric.replace", "rubric.detach") and c.get("_assessments")
    ]
    if graded and not args.force_graded:
        die("refusing to touch %d rubric(s) that already carry rubric assessments: %s\n"
            "Replacing or detaching a rubric deletes it, and the per-criterion scores "
            "recorded against it go with it. Re-run with --force-graded only if you have "
            "confirmed that is acceptable."
            % (len(graded), ", ".join(str(c.get("name") or c.get("id")) for c in graded)))

    if not args.apply:
        print("Dry run: nothing was written. Re-run with --apply to commit these %d change(s)."
              % len(plan))
        report_unfiled(canvas)
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
        report_unfiled(canvas)
        return 1

    print("\nAll %d change(s) applied." % len(plan))
    report_unfiled(canvas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
