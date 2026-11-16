"""Offline regression checks for module-item moves. Also runnable with Python."""
import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ursinus_canvas_inline_changes as changes


class FakeModule:
    def __init__(self, module_id, name, events):
        self.id, self.name, self.events = module_id, name, events
        self.entries = []
        self.published = False

    def get_module_items(self):
        self.events.append(("read", self.id))
        return list(self.entries)

    def create_module_item(self, **kwargs):
        self.events.append(("add", self.id, kwargs))
        created = SimpleNamespace(id=901, **kwargs["module_item"])
        self.entries.append(created)
        return created

    def edit(self, **kwargs):
        self.events.append(("publish", self.id, kwargs))


class FakeItem:
    def __init__(self, source, destination, events, behavior="move", delete_error=False):
        self.id, self.title = 71, "Demo link"
        self.type, self.external_url = "ExternalUrl", "https://example.org/demo"
        self.published, self.indent, self.position = False, 2, 3
        self.new_tab = False
        self.source, self.destination, self.events = source, destination, events
        self.behavior, self.delete_error = behavior, delete_error
        source.entries.append(self)

    def edit(self, **kwargs):
        self.events.append(("edit", kwargs))
        if self.behavior == "raise":
            raise RuntimeError("move rejected")
        if self.behavior == "move":
            self.source.entries.remove(self)
            self.destination.entries.append(self)
        elif self.behavior == "wrong_id":
            self.destination.entries.append(SimpleNamespace(id=999))

    def delete(self):
        self.events.append(("delete", self.id))
        if self.delete_error:
            raise RuntimeError("delete rejected")
        self.source.entries.remove(self)


class MoveTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.source = FakeModule(10, "Source", self.events)
        self.destination = FakeModule(20, "Destination", self.events)
        # Bypass construction: no course, credentials or Canvas connection.
        self.canvas = changes.Canvas.__new__(changes.Canvas)
        self.canvas._items = {10: [], 20: []}
        self.canvas._modules = [self.source, self.destination]
        self.sleep = patch.object(changes, "sleep_for_rate_limit")
        self.sleep.start()
        self.network = patch("socket.socket.connect", side_effect=AssertionError("no network"))
        self.network.start()
        self.addCleanup(self.sleep.stop)
        self.addCleanup(self.network.stop)

    def item(self, **kwargs):
        return FakeItem(self.source, self.destination, self.events, **kwargs)

    def test_move_keeps_id_and_attributes_without_create_or_delete(self):
        item = self.item()
        payload = changes.move_payload(item, item.title)
        payload["position"] = 5
        result = self.canvas.move_item(item, self.source, self.destination, payload)
        self.assertIs(result, item)
        self.assertEqual(result.id, 71)
        self.assertIn(("edit", {"module_item": {"module_id": 20, "position": 5}}), self.events)
        self.assertIn(("read", 20), self.events)
        self.assertEqual([e[0] for e in self.events], ["edit", "read"])
        self.assertEqual((item.published, item.indent, item.title, item.external_url, item.new_tab),
                         (False, 2, "Demo link", "https://example.org/demo", False))
        self.assertEqual(self.canvas._items, {})

    def test_position_is_optional(self):
        item = self.item()
        self.canvas.move_item(item, self.source, self.destination, {})
        self.assertEqual(self.events[0], ("edit", {"module_item": {"module_id": 20}}))

    def test_rejected_or_unverified_moves_fall_back(self):
        for behavior in ("raise", "ignored", "wrong_id"):
            with self.subTest(behavior=behavior):
                self.source.entries, self.destination.entries = [], []
                self.events.clear()
                item = self.item(behavior=behavior)
                payload = changes.move_payload(item, item.title)
                with contextlib.redirect_stderr(io.StringIO()) as output:
                    result = self.canvas.move_item(item, self.source, self.destination, payload)
                self.assertEqual(result.id, 901)
                names = [e[0] for e in self.events]
                self.assertLess(names.index("add"), names.index("delete"))
                self.assertIn(("add", 20, {"module_item": payload}), self.events)
                self.assertIn("moved by recreating; new id 901", output.getvalue())
                self.assertTrue(self.destination.published)
                self.assertNotIn(item, self.source.entries)
                self.assertEqual(self.canvas._items, {})

    def test_failed_create_leaves_original(self):
        item = self.item(behavior="raise")
        with patch.object(self.destination, "create_module_item", side_effect=RuntimeError("add rejected")):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "add rejected"):
                    self.canvas.move_item(item, self.source, self.destination, {})
        self.assertIn(item, self.source.entries)
        self.assertNotIn("delete", [e[0] for e in self.events])

    def test_failed_delete_keeps_existing_duplicate_warning(self):
        item = self.item(behavior="raise", delete_error=True)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "it is now in both modules and students see both; remove one by hand"):
                self.canvas.move_item(item, self.source, self.destination,
                                      changes.move_payload(item, item.title))
        self.assertIn(item, self.source.entries)
        self.assertEqual(len(self.destination.entries), 1)
        self.assertNotIn(10, self.canvas._items)

    def test_automatic_assignment_moves_keep_legacy_behavior(self):
        item = self.item()
        run = changes._mover(self.canvas, self.source, item, self.destination, "Renamed")
        self.assertEqual(run(), "moved 'Renamed' to 'Destination'")
        self.assertNotIn("edit", [e[0] for e in self.events])
        self.assertEqual(self.destination.entries[0].title, "Renamed")

    def test_plan_keeps_dry_run_read_only_and_describes_id(self):
        item = self.item()
        self.canvas._items[10] = [item]
        plan, action = changes.plan_operation(self.canvas, {
            "op": "item.move", "module": "Source", "title": item.title,
            "to_module": "Destination", "position": 5, "_index": 1})
        self.assertEqual(plan[0], "move item 'Demo link' from 'Source' to 'Destination' (tries to keep its id; recreates it with a new id if Canvas refuses the move)")
        self.assertEqual(self.events, [])
        self.assertEqual(action(), "moved 'Demo link' to 'Destination'")
        self.assertEqual(self.destination.entries[0].id, 71)


if __name__ == "__main__":
    unittest.main(verbosity=2)
