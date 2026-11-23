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
      - dtitle: "Lab 1 due"
        points: 10
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
LAB = "Lab 1 due"     # a lowercase " due" stays on the name, in the deploy and here alike

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

        self.deploy(SYLLABUS)

    def deploy(self, text):
        """The shell a full deploy writes from this syllabus."""
        with open(self.syllabus, "w", encoding="utf-8") as fh:
            fh.write(text)
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
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(changes.generate(self.canvas(), self.syllabus, **kwargs), 0)
        text = out.getvalue()
        self.stderr = err.getvalue()
        doc = yaml.safe_load(text)
        # Suggestions must stay valid YAML once uncommented.
        uncommented = "\n".join(line[2:] if line.startswith("#   ") else line
                                 for line in text.splitlines())
        self.assertIsInstance(yaml.safe_load(uncommented)["changes"] or [], list)
        return text, doc["changes"] or []

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
            "position": 3, "published": True}])
        self.assertEqual(self.suggestions(text), [])

    def test_changed_url_yields_an_item_update(self):
        self.item(INTRO, "Chapter 1").external_url = "https://example.org/old"
        text, ops = self.generate()
        self.assertEqual(ops, [{"op": "item.update", "module": INTRO, "title": "Chapter 1",
                                "url": "https://example.org/ch1"}])
        self.assertIn("Canvas has https://example.org/old", text)

    def test_unpublished_item_is_only_suggested_and_retitled_link_is_active(self):
        self.item(INTRO, "Think about it").published = False
        self.item(INTRO, "Chapter 1").title = "Ch. 1"
        text, ops = self.generate()
        self.assertEqual(ops, [{"op": "item.update", "module": INTRO, "title": "Ch. 1",
                                "rename": "Chapter 1"}])
        self.assertIn("is unpublished in Canvas; publish?", text)
        self.assertEqual(self.suggestions(text), ["#   - op: item.update"])

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
        self.assertEqual(self.suggestions(text), ["#   - op: item.add"] * 3)
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
                              if not (getattr(e, "content_id", None) == essay.id
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
                         (3, True, HOMEPAGE + "/readings/ch2"))
        self.assertEqual(edits, [{"external_url": "https://example.org/ch1"}])


    # -- review findings (one test each) --------------------------------------

    def test_1_new_session_cannot_steal_a_module_matched_by_name(self):
        live = FakeModule("Mon, Nov 03, 2025 - Topic Y", True)
        plan = [{"name": "Mon, Nov 03, 2025 - Topic X", "tag": None},
                {"name": "Mon, Nov 03, 2025 - Topic Y", "tag": None}]
        pairs, leftover, by_date = changes.match_modules(changes.Canvas, plan, [live])
        self.assertEqual([hit for _, hit in pairs], [None, live])
        self.assertEqual((leftover, by_date), ([], set()))

    def test_1_date_fallback_needs_one_planned_and_one_live_module(self):
        a, b = FakeModule("Mon, Nov 03, 2025 - A", True), FakeModule("Mon, Nov 03, 2025 - B", True)
        plan = [{"name": "Mon, Nov 03, 2025 - C", "tag": None}]
        pairs, _, _ = changes.match_modules(changes.Canvas, plan, [a, b])
        self.assertEqual(pairs[0][1], None)
        pairs, _, by_date = changes.match_modules(changes.Canvas, plan, [a])
        self.assertIs(pairs[0][1], a)
        self.assertEqual(by_date, {id(plan[0])})

    def test_1_topics_shifted_a_day_are_only_suggested(self):
        self.module(RECURSION).name = "Wed, Aug 26, 2026 - Introduction"
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertIn("#   - op: module.update", self.suggestions(text))
        self.assertIn("topics may have moved", text)

    def test_1_many_date_renames_are_only_suggested(self):
        self.module(RECURSION).name = "Wed, Aug 26, 2026 - Something else"
        with patch.object(changes, "DATE_RENAME_LIMIT", 0):
            text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertIn("match the plan only by date", text)

    def test_2_unpublished_module_and_assignment_item_are_only_suggested(self):
        self.module(RECURSION).published = False
        self.item(RECURSION, ESSAY).published = False
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertIn("is unpublished in Canvas; publish?", text)
        self.assertIn("publishing it publishes the assignment too", text)
        self.assertEqual(sorted(self.suggestions(text)),
                         ["#   - op: item.update", "#   - op: module.update"])

    def test_3_urls_are_compared_normalized(self):
        self.item(RECURSION, "Chapter 2").external_url = "HTTPS://Example.EDU/course/readings/ch%32/"
        _, ops = self.generate()
        self.assertEqual(ops, [])

    def test_3_homepage_mismatch_holds_back_every_url_update(self):
        for module in self.course.modules:
            for entry in module.entries:
                url = getattr(entry, "external_url", "") or ""
                if url.startswith(HOMEPAGE):
                    entry.external_url = url.replace(HOMEPAGE, "https://other.example/c")
        text, ops = self.generate()
        self.assertEqual([op for op in ops if op["op"] == "item.update"], [])
        self.assertIn("Link updates held back", text)
        self.assertIn("--homepage", self.stderr)
        # passing --homepage says the comparison is deliberate, so the updates are active
        _, ops = self.generate(homepage=HOMEPAGE)
        self.assertTrue([op for op in ops if op["op"] == "item.update"])

    def test_3_many_url_updates_are_held_back(self):
        self.item(INTRO, "Chapter 1").external_url = "https://example.org/old"
        with patch.object(changes, "URL_UPDATE_LIMIT", 0):
            text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertIn("likelier a homepage mismatch", text)

    def test_4_assignment_item_moved_by_hand_is_only_suggested_back(self):
        essay = self.item(RECURSION, ESSAY)
        self.module(RECURSION).entries.remove(essay)
        self.module(INTRO).entries.append(essay)
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertIn('#     to_module: "%s"' % RECURSION, text)

    def test_5_empty_resource_link_is_skipped_with_a_comment(self):
        self.deploy(SYLLABUS.replace("  late_penalty_per_period", '  chatlink: ""\n  late_penalty_per_period'))
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertIn("has no link in the syllabus", text)
        resources = self.module("Resources")
        resources.entries.remove(self.item("Resources", "Access the Class Group Chat"))
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertIn("skipped", text)

    def test_6_positions_are_left_off_when_an_assignment_op_touches_the_module(self):
        next(a for a in self.course.assignments if a.name == ESSAY).due_at = "2026-09-03T03:59:59Z"
        self.module(RECURSION).entries.remove(self.item(RECURSION, "Chapter 2"))
        text, ops = self.generate()
        self.assertEqual([op["op"] for op in ops], ["assignment.due", "item.add"])
        self.assertNotIn("position", ops[1])
        self.assertIn("so this is appended", text)

    def test_7_suggestions_only_document_is_block_yaml_and_applies_as_a_no_op(self):
        self.module(INTRO).create_module_item({"title": "Bonus", "type": "SubHeader",
                                               "published": True})
        text, _ = self.generate()
        self.assertNotIn("changes: []", text)
        self.assertIn("\nchanges:\n", text)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as stop:
                changes.parse_document(text)
        self.assertEqual(stop.exception.code, 0)

    def test_8_lowercase_due_names_match_the_deploy(self):
        self.assertIn(LAB, [a.name for a in self.course.assignments])
        expected, _ = changes.syllabus_expectations(self.syllabus)
        self.assertIn(LAB, expected)
        self.assertNotIn("Lab 1", expected)
        _, ops = self.generate()
        self.assertEqual(ops, [])


    # -- re-review: adding to what is hidden ---------------------------------

    def test_add_into_an_unpublished_module_is_only_suggested_and_not_counted(self):
        self.module(RECURSION).published = False
        self.module(RECURSION).entries.remove(self.item(RECURSION, "Chapter 2"))
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertIn("is unpublished in Canvas; adding", text)
        self.assertIn("#   - op: item.add", self.suggestions(text))
        self.assertIn("# items:      0 to add,", text)

    def test_add_of_an_unpublished_assignment_item_is_only_suggested(self):
        essay = next(a for a in self.course.assignments if a.name == ESSAY)
        essay.published = False
        self.module(RECURSION).entries.remove(self.item(RECURSION, ESSAY))
        text, ops = self.generate()
        self.assertEqual(ops, [])
        self.assertIn("would publish it", text)
        self.assertIn("# items:      0 to add,", text)

    def test_missing_module_items_are_not_counted_as_adds(self):
        self.course.modules.remove(self.module(RECURSION))
        text, _ = self.generate()
        self.assertIn("# items:      0 to add,", text)

    def test_item_add_leaves_the_module_published_state_unless_asked(self):
        module = self.module(RECURSION)
        module.published = False
        canvas = self.canvas()
        with patch.object(changes, "sleep_for_rate_limit"):
            lines, action = changes.plan_operation(canvas, {
                "op": "item.add", "module": RECURSION, "title": "Extra",
                "type": "SubHeader", "_index": 1})
            action()
            self.assertIs(module.published, False)
            self.assertIn("stays so", " ".join(lines))
            lines, action = changes.plan_operation(canvas, {
                "op": "item.add", "module": RECURSION, "title": "Extra 2",
                "type": "SubHeader", "publish_module": True, "_index": 2})
            action()
        self.assertIs(module.published, True)
        self.assertIn("and publish module", " ".join(lines))


class CanvasLikeModule(FakeModule):
    """Models what course 22336 showed: create_module_item ignores "published" (a new
    item starts unpublished), only item.edit sets it, and publishing a module publishes
    the items in it."""

    def create_module_item(self, module_item):
        fields = dict(module_item)
        fields.pop("published", None)
        item = super().create_module_item(fields)
        item.published = False

        def edit(module_item):
            if "published" in module_item:
                item.published = module_item["published"]
        item.edit = edit
        return item

    def edit(self, module):
        super().edit(module)
        if module.get("published"):
            for entry in self.entries:
                entry.published = True


class AddItemPublishTests(unittest.TestCase):
    def setUp(self):
        self.canvas = changes.Canvas.__new__(changes.Canvas)
        self.canvas._items, self.canvas.unfiled = {}, []
        self.module = CanvasLikeModule("Wed, Aug 26, 2026 - Recursion", published=True)
        self.canvas._modules = [self.module]
        sleep = patch.object(changes, "sleep_for_rate_limit")
        sleep.start()
        self.addCleanup(sleep.stop)

    def add(self, change):
        change = dict({"op": "item.add", "module": self.module.name, "type": "ExternalUrl",
                       "url": "https://example.org/r", "_index": 1}, **change)
        with contextlib.redirect_stdout(io.StringIO()):
            _, action = changes.plan_operation(self.canvas, change)
            action()
        return next(i for i in self.module.entries if i.title == change["title"])

    def test_item_add_into_a_published_module_ends_published(self):
        self.assertIs(self.add({"title": "Reading", "published": True}).published, True)

    def test_item_add_without_published_ends_published(self):
        self.assertIs(self.add({"title": "Reading"}).published, True)

    def test_item_add_published_false_stays_unpublished(self):
        self.assertIs(self.add({"title": "Hidden", "published": False}).published, False)
        self.assertIs(self.module.published, True)

    def test_filing_that_publishes_the_module_keeps_a_hidden_item_hidden(self):
        # the assignment.create filing and the item.move fallback both publish the module
        created = self.canvas.add_item(self.module, {"title": "A", "type": "Assignment",
                                                     "content_id": 7, "published": False})
        self.assertIs(created.published, False)
        created = self.canvas.add_item(self.module, {"title": "B", "type": "SubHeader",
                                                     "published": True})
        self.assertIs(created.published, True)

    def test_move_fallback_recreates_the_item_published(self):
        source = CanvasLikeModule("Source", published=True)
        old = source.create_module_item({"title": "Moved", "type": "SubHeader"})
        old.published = True
        self.canvas._modules.append(source)
        with contextlib.redirect_stderr(io.StringIO()):
            moved = self.canvas.move_item(old, source, self.module,
                                          changes.move_payload(old, "Moved"), keep_id=False)
        self.assertIs(moved.published, True)
        self.assertNotIn(old, source.entries)


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
