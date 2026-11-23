"""Offline checks for --generate's modules-page comparison. Also runnable with Python.

A fake course stands in for Canvas. The "in sync" shell is built by running the real
deploy (ursinus_canvas.process_markdown) against it, so these tests also hold the deploy
and --generate to the same plan. Needs canvasapi, python-frontmatter, pytz, requests,
PyYAML, and python-dateutil installed; nothing contacts Canvas.
"""
import contextlib
import copy
import io
import itertools
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

import ursinus_canvas as deploy
import ursinus_canvas_inline_changes as changes

HOMEPAGE = "https://example.edu/course"

SYLLABUS = """---
info:
  course_number: CS 100
  course_title: Testing
  course_start_date: 2026/08/24
  course_end_date: 2026/12/11
  course_homepage: %s
  class_notebook: https://onenote.example/notebook
  late_penalty_per_period: 10
  late_penalty_period: day
  class_meets_days:
    isM: true
    isT: false
    isW: true
    isR: false
    isF: false
    isS: false
    isU: false
  class_meets_locations: []
schedule:
  - week: 0
    date: 0
    title: Introduction
    link: activities/intro
    deliverables:
      - dtitle: "Written Assignment: Essay Handed Out"
        dlink: assignments/essay
    readings:
      - rtitle: Chapter 1
        rlink: https://example.org/ch1
      - rtitle: Think about it
  - week: 0
    date: 1
    title: Recursion
    deliverables:
      - dtitle: "Written Assignment: Essay Due"
        dlink: assignments/essay
        points: 50
    readings:
      - rtitle: Chapter 2
        rlink: readings/ch2
      - rtitle: Style guide
        rlink: https://example.org/style
        module: resource
---
""" % HOMEPAGE

INTRO = "Mon, Aug 24, 2026 - Introduction"
RECURSION = "Wed, Aug 26, 2026 - Recursion"
ESSAY = "Written Assignment: Essay"

_ids = itertools.count(100)


class FakeModule:
    """A Canvas module, as both canvasapi callers in this repo use one."""

    def __init__(self, name, published=False):
        self.id, self.name, self.published = next(_ids), name, published
        self.position = None
        self.entries = []

    def create_module_item(self, module_item):
        fields = dict(module_item)
        position = fields.pop("position", None)
        item = SimpleNamespace(id=next(_ids), **fields)
        item.delete = lambda: self.entries.remove(item)
        index = len(self.entries) if position is None else int(position) - 1
        self.entries.insert(index, item)
        for number, entry in enumerate(self.entries, 1):
            entry.position = number
        return item

    def get_module_items(self):
        return list(self.entries)

    def edit(self, module):
        for key, value in module.items():
            setattr(self, key, value)


class FakeAssignment(SimpleNamespace):
    def get_submissions(self, **kwargs):
        return []


class FakeCourse:
    id, name = 4242, "CS 100 Testing"

    def __init__(self):
        self.modules, self.assignments = [], []

    def update(self, **kwargs):
        pass

    def create_module(self, inputdict):
        module = FakeModule(inputdict["name"], inputdict.get("published", False))
        self.modules.append(module)
        return module

    def create_assignment(self, inputdict):
        assignment = FakeAssignment(id=next(_ids), name=inputdict["name"],
                                    due_at=inputdict.get("due_at"),
                                    lock_at=inputdict.get("lock_at"),
                                    points_possible=inputdict.get("points_possible"),
                                    description=inputdict.get("description"))
        self.assignments.append(assignment)
        return assignment


def quiet(*names):
    """Patch out every deploy step that is not modules or assignments."""
    return [patch.object(deploy, name, return_value=None) for name in names]


class GenerateModulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "_pages"))
        self.syllabus = os.path.join(self.tmp.name, "_pages", "syllabus.md")
        with open(self.syllabus, "w", encoding="utf-8") as fh:
            fh.write(SYLLABUS)
        here = os.getcwd()
        os.chdir(self.tmp.name)            # no stray _config.yml is read
        self.addCleanup(os.chdir, here)

        network = patch("socket.socket.connect", side_effect=AssertionError("no network"))
        network.start()
        self.addCleanup(network.stop)
        for patcher in quiet("delete_old_data", "add_discussion_topic", "create_calendar_event",
                             "create_late_policy", "reconcile_attendance_grade",
                             "add_assignments_to_groups", "delete_assignment_group_by_name",
                             "create_assignmentgroup", "create_rubric"):
            patcher.start()
            self.addCleanup(patcher.stop)

        # The shell a full deploy writes from this syllabus.
        self.course = FakeCourse()
        with contextlib.redirect_stdout(io.StringIO()):
            deploy.process_markdown(self.syllabus, None, self.course, self.course.id, HOMEPAGE)

    # -- helpers -----------------------------------------------------------

    def canvas(self):
        canvas = changes.Canvas.__new__(changes.Canvas)
        canvas.course = self.course
        canvas._assignments = list(self.course.assignments)
        canvas._modules = list(self.course.modules)
        canvas._groups, canvas._items, canvas._lock_at = None, {}, False
        canvas.modules_enabled, canvas.last_class_date, canvas.unfiled = True, None, []
        return canvas

    def generate(self, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(changes.generate(self.canvas(), self.syllabus, **kwargs), 0)
        text = out.getvalue()
        doc = yaml.safe_load(text)
        return text, doc["changes"]

    def module(self, name):
        return next(m for m in self.course.modules if m.name == name)

    def item(self, module, title):
        return next(i for i in self.module(module).entries if i.title == title)

    @staticmethod
    def suggestions(text):
        return [line for line in text.splitlines() if line.startswith("#   - op:")]

    # -- the deploy and the plan agree ---------------------------------------

    def test_deploy_writes_exactly_the_plan(self):
        with contextlib.redirect_stdout(io.StringIO()):
            plan = changes.deploy_module_plan(self.syllabus)
        self.assertEqual([m["name"] for m in plan["modules"]],
                         ["Resources", INTRO, RECURSION])
        self.assertEqual([m.name for m in self.course.modules],
                         [m["name"] for m in plan["modules"]])
        for planned, live in zip(plan["modules"], self.course.modules):
            got = [{k: v for k, v in vars(i).items()
                    if k not in ("id", "position", "delete", "content_id")}
                   for i in live.entries]
            self.assertEqual(got, [e["payload"] for e in planned["items"]], planned["name"])
        reading = self.item(INTRO, "Chapter 1")
        self.assertEqual((reading.type, reading.new_tab, reading.published),
                         ("ExternalUrl", True, True))

    # -- generate ------------------------------------------------------------

    def test_in_sync_shell_yields_no_changes(self):
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertIn("# No drift: Canvas matches the repository.", text)
        self.assertEqual(self.suggestions(text), [])

    def test_missing_reading_yields_one_item_add_with_the_deploy_fields(self):
        self.module(RECURSION).entries.remove(self.item(RECURSION, "Chapter 2"))
        text, ops = self.generate()
        self.assertEqual(ops, [{
            "op": "item.add", "module": RECURSION, "title": "Chapter 2",
            "type": "ExternalUrl", "url": HOMEPAGE + "/readings/ch2", "new_tab": True,
            "position": 2, "published": True}])
        self.assertEqual(self.suggestions(text), [])

    def test_changed_url_yields_an_item_update(self):
        self.item(INTRO, "Chapter 1").external_url = "https://example.org/old"
        text, ops = self.generate()
        self.assertEqual(ops, [{"op": "item.update", "module": INTRO, "title": "Chapter 1",
                                "url": "https://example.org/ch1"}])
        self.assertIn("Canvas has https://example.org/old", text)

    def test_unpublished_item_and_retitled_link(self):
        self.item(INTRO, "Think about it").published = False
        self.item(INTRO, "Chapter 1").title = "Ch. 1"
        _, ops = self.generate()
        self.assertIn({"op": "item.update", "module": INTRO, "title": "Think about it",
                       "published": True}, ops)
        self.assertIn({"op": "item.update", "module": INTRO, "title": "Ch. 1",
                       "rename": "Chapter 1"}, ops)
        self.assertEqual(len(ops), 2)

    def test_extra_live_item_is_only_a_commented_remove(self):
        self.module(INTRO).create_module_item({"title": "Bonus", "type": "SubHeader",
                                               "published": True})
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertEqual(self.suggestions(text), ["#   - op: item.remove"])
        self.assertIn('#     title: "Bonus"', text)

    def test_extra_live_module_is_only_a_commented_delete(self):
        self.course.modules.append(FakeModule("Fri, Aug 28, 2026 - Extra", True))
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertEqual(self.suggestions(text), ["#   - op: module.delete"])

    def test_missing_module_yields_module_create_and_commented_items(self):
        self.course.modules.remove(self.module(RECURSION))
        text, ops = self.generate()
        self.assertEqual(ops, [{"op": "module.create", "name": RECURSION, "position": 3,
                                "published": True}])
        # its items wait for a second pass, the assignment's item among them
        self.assertEqual(self.suggestions(text), ["#   - op: item.add"] * 2)
        self.assertIn('#     content: "%s"' % ESSAY, text)

    def test_renamed_module_is_matched_by_date_and_renamed(self):
        self.module(RECURSION).name = "Wed, Aug 26, 2026 - Recursion (moved)"
        _, ops = self.generate()
        self.assertEqual(ops, [{"op": "module.update",
                                "name": "Wed, Aug 26, 2026 - Recursion (moved)",
                                "rename": RECURSION}])

    def test_reorder_is_only_suggested(self):
        entries = self.module(INTRO).entries
        entries.reverse()
        for number, entry in enumerate(entries, 1):
            entry.position = number
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertTrue(self.suggestions(text))
        self.assertTrue(all(s == "#   - op: item.move" for s in self.suggestions(text)))

    def test_assignments_are_unaffected(self):
        essay = next(a for a in self.course.assignments if a.name == ESSAY)
        essay.points_possible = 40
        with_modules, ops = self.generate()
        without_modules, ops_without = self.generate(modules=False)
        self.assertEqual(ops, ops_without)
        self.assertEqual(ops, [{"op": "assignment.update", "name": ESSAY, "points": 50}])
        self.assertIn("--no-modules: the modules page was not compared", without_modules)

    def test_assignment_being_created_is_not_filed_twice(self):
        essay = next(a for a in self.course.assignments if a.name == ESSAY)
        self.course.assignments.remove(essay)
        for module in self.course.modules:
            module.entries = [e for e in module.entries
                              if not (getattr(e, "type", None) == "Assignment"
                                      or e.title.endswith("Handed Out"))]
        text, ops = self.generate()
        self.assertEqual([op["op"] for op in ops], ["assignment.create"])
        self.assertEqual(self.suggestions(text), [])

    def test_generated_document_resolves_and_applies(self):
        self.module(RECURSION).entries.remove(self.item(RECURSION, "Chapter 2"))
        self.item(INTRO, "Chapter 1").external_url = "https://example.org/old"
        text, _ = self.generate()
        parsed = changes.parse_document(text)
        changes.check_dependencies(parsed)
        canvas = self.canvas()
        with patch.object(changes, "sleep_for_rate_limit"), \
                contextlib.redirect_stdout(io.StringIO()):
            actions = [changes.plan_operation(canvas, c)[1] for c in parsed]
            edits = []
            self.item(INTRO, "Chapter 1").edit = lambda module_item: edits.append(module_item)
            for action in actions:
                action()
        added = self.item(RECURSION, "Chapter 2")
        self.assertEqual((added.position, added.new_tab, added.external_url),
                         (2, True, HOMEPAGE + "/readings/ch2"))
        self.assertEqual(edits, [{"external_url": "https://example.org/ch1"}])


class ItemOpsTests(unittest.TestCase):
    def test_item_ops_into_a_module_created_in_the_same_document_are_refused(self):
        doc = changes.parse_document(
            '{"changes": [{"op": "module.create", "name": "New"},'
            ' {"op": "item.add", "module": "New", "title": "x", "type": "SubHeader"}]}')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit):
                changes.check_dependencies(doc)
        self.assertIn("creates in this same run", err.getvalue())

    def test_item_update_rename_only_is_unchanged(self):
        self.assertEqual(changes.item_update_fields({"rename": " New "}), {"title": "New"})

    def test_item_update_requires_a_field(self):
        self.assertEqual(changes.item_update_fields({"title": "x"}), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
