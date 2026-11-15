"""Unit tests for code-viz modes (modes.py): the tour and session validators, masking, plain text,
chunk joining and drift comparison. Pure Python, no Docker. Manual: `code-viz readme`, section 20.

Run in a throwaway container (never on a teaching machine's own Python):
  docker run --rm -v $PWD:/w -w /w python:3.12-slim python3 -m unittest discover -s course/viz/tests -v
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import modes as M  # noqa: E402

CODE = "def f(x):\n    return x + 1\n\nprint(f(2))"


class TourTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "viz", "traces"))
        import gzip
        with gzip.open(os.path.join(self.root, "viz", "traces", "ex-1.json.gz"), "wt") as f:
            json.dump({"steps": [{"line": 1}, {"line": 4}, {"line": 2}]}, f)
        self.codes = {"ex-1": CODE, "ex-2": CODE + "\nprint(3)", "sh-1": "import secret\nsecret.call()\nprint(1)"}

    def tour(self, steps, **kw):
        return M.normalize_tour(dict({"version": 1, "example": "ex-1", "title": "t", "steps": steps}, **kw))

    def test_good_tour(self):
        t = self.tour([{"kind": "reveal", "lines": "1-2", "note": "the function"},
                       {"kind": "predict", "question": "what prints?", "answer": "3"},
                       {"kind": "run", "trace_step": 2, "description": "here"}])
        self.assertEqual(M.check_tour(t, "ex-1", None, self.codes, self.root), [])
        self.assertEqual(t["steps"][0]["description"], "the function")
        self.assertFalse(t["reviewed"])

    def test_bad_steps(self):
        cases = [
            ([{"kind": "wiggle"}], "must be one of"),
            ([{"kind": "focus", "lines": "9", "description": "x"}], "past the code"),
            ([{"kind": "focus", "lines": "0", "description": "x"}], "does not match"),
            ([{"kind": "run", "trace_step": 3, "description": "x"}], "has 3 step"),
            ([{"kind": "predict"}], "needs a question"),
            ([{"kind": "stage", "stage": "nope", "description": "x"}], "no labeled example"),
            ([{"kind": "focus", "lines": "1"}], "says nothing"),
        ]
        for steps, want in cases:
            errs = M.check_tour(self.tour(steps), "ex-1", None, self.codes, self.root)
            self.assertTrue(any(want in e for e in errs), (steps, errs))

    def test_line_alias_and_non_object(self):
        t = self.tour([{"kind": "focus", "line": 4, "description": "print"}])
        self.assertEqual(t["steps"][0]["lines"], "4")
        self.assertTrue(M.validate(M.normalize_tour([1, 2]), "tour"))

    def test_stage_uses_its_own_trace(self):
        t = self.tour([{"kind": "stage", "stage": "ex-2", "description": "more"},
                       {"kind": "focus", "lines": "5", "description": "new line"},
                       {"kind": "run", "trace_step": 0, "description": "x"}])
        errs = M.check_tour(t, "ex-1", None, self.codes, self.root)
        self.assertTrue(any("ex-2 has no committed trace" in e for e in errs), errs)
        self.assertFalse(any("past the code" in e for e in errs), errs)

    def test_publish_show_entry_and_withdrawal(self):
        os.makedirs(os.path.join(self.root, "codeviz", "tours"))
        p = os.path.join(self.root, "codeviz", "tours", "sh-1.json")
        json.dump({"version": 1, "example": "sh-1", "title": "t", "steps": [{"kind": "reveal", "lines": "1", "description": "d"}]}, open(p, "w"))
        meta = {"sh-1": {"viz": "show", "lang": "python", "page": "p.md", "line": 3, "page_url": ""}}
        entries = []
        probs, n = M.publish(self.root, self.codes, [], entries, meta)
        self.assertEqual((probs, n), ([], 1))
        self.assertEqual(entries[0]["modes"], ["explain"])
        pub = json.load(open(os.path.join(self.root, "viz", "tours", "sh-1.json")))
        self.assertEqual(pub["code"], self.codes["sh-1"])
        os.rename(p, p + ".off")          # the source goes away: the published tour is withdrawn
        entries2 = list(entries)
        M.publish(self.root, self.codes, [], entries2, meta)
        self.assertFalse(os.path.exists(os.path.join(self.root, "viz", "tours", "sh-1.json")))
        self.assertEqual(entries2, [])

    def test_repo_without_codeviz_untouched(self):
        entries = [{"id": "ex-1", "viz": "env"}]
        M.publish(self.root, self.codes, [], entries, {})
        self.assertNotIn("modes", entries[0])
        self.assertFalse(os.path.exists(os.path.join(self.root, "viz", "tours")))


class SkeletonTests(unittest.TestCase):
    def block(self, code, lang="python", viz="env", vid="ex-1"):
        return {"label": {"id": vid, "viz": viz}, "lang": lang, "code": code, "page": "p.md", "start": 0}

    def test_python_structure_and_facts(self):
        code = "import math\n\ndef fib(n):\n    if n <= 1:\n        return n\n    return fib(n - 1) + fib(n - 2)\n\nfor i in range(3):\n    print(fib(i))"
        t = M.skeleton_tour(tempfile.mkdtemp(), self.block(code), "Fibonacci")
        notes = [s.get("description", "") for s in t["steps"]]
        self.assertIn("Line 1 imports `math`.", notes)
        self.assertIn("Lines 3-6 define `fib(n)`, which calls itself.", notes)
        self.assertIn("Line 4 checks `n <= 1`.", notes)
        self.assertTrue(any(n.startswith("Lines 8-9 run the main code and print") for n in notes))
        self.assertEqual((t["source"], t["reviewed"]), ("skeleton", False))
        self.assertFalse(any(s["kind"] == "predict" for s in t["steps"]))

    def test_no_fact_without_evidence(self):
        t = M.skeleton_tour(tempfile.mkdtemp(), self.block("def add(a, b):\n    return a + b\n\nprint(add(1, 2))"), "")
        self.assertIn("Lines 1-2 define `add(a, b)`.", [s.get("description") for s in t["steps"]])

    def test_show_has_no_run_steps_and_other_languages(self):
        t = M.skeleton_tour(tempfile.mkdtemp(), self.block("int main() {\n  for (int i = 0; i < 3; i++) {\n    puts(\"x\");\n  }\n  return 0;\n}", "c", "show"), "")
        kinds = {s["kind"] for s in t["steps"]}
        self.assertEqual(kinds, {"reveal", "focus"})
        self.assertIn("Lines 1-6 define `main`.", [s.get("description") for s in t["steps"]])
        mips = M.skeleton_tour(tempfile.mkdtemp(), self.block("main:\n  li $v0, 10\n  syscall\nval:\n  .word 5", "mips", "show"), "")
        self.assertIn("Lines 4-5 hold the data labeled `val`.", [s.get("description") for s in mips["steps"]])


class SessionTests(unittest.TestCase):
    def doc(self, **scn):
        return {"version": 1, "id": "s-1", "title": "t", "scenario": dict({"commands": ["ls"]}, **scn)}

    def test_scenario_checks(self):
        self.assertEqual(M.check_session(self.doc(images=["alpine:3.20"], network="none", shell={"image": "gcc:14"})), [])
        self.assertTrue(M.check_session(self.doc(network="lan")))
        self.assertTrue(M.check_session(self.doc(shell={"image": "gcc"})))      # no tag
        self.assertTrue(M.check_session({"_error": "bad yaml"}))
        self.assertTrue(M.check_session([1]))

    def test_stale_recording(self):
        d = self.doc()
        rec = dict(d, steps=[{"cmd": "ls", "output": "", "exit": 0}], recorded={"scenario_sha": M.scenario_sha(d["scenario"])})
        self.assertEqual(M.check_session(d, rec), [])
        d2 = self.doc(commands=["ls -l"])
        self.assertTrue(any(e.startswith("stale") for e in M.check_session(d2, rec)))

    def test_block_commands(self):
        self.assertEqual(M.block_commands("# setup\n$ docker run \\\n   alpine ls\n\necho hi"),
                         ["docker run alpine ls", "echo hi"])


class MaskTests(unittest.TestCase):
    def test_ids_times_names_work(self):
        m = M.Masker("/work", {"eager_turing"}, [{"pattern": r"port \d+", "label": "port <p-{n}>"}])
        long = "0123456789abcdef" * 4
        out = m(f"{long} then {long[:12]} at 2026-11-14T10:00:00Z, Up 3 seconds, 2 minutes ago, eager_turing in /work/x, port 8080")
        self.assertEqual(out, "<id-1> then <id-1> at <time>, Up <time>, <time> ago, <name-1> in ~/x, port <p-1>")

    def test_ls_dates(self):
        m = M.Masker("/work", set(), [])
        self.assertEqual(m("-rw-r--r-- 1 1000 1000 3 Nov 15 00:23 mine.txt and Jan  3  2025 old"),
                         "-rw-r--r-- 1 1000 1000 3 <date> mine.txt and <date> old")

    def test_plain_and_eof_echo(self):
        self.assertEqual(M.plain("^@\x1b[32mgreen\x1b[0m\r\n10%\r50%\r100%\r\n"), "green\n100%\n")
        self.assertEqual(M.strip_eof_echo("^D^@x\n^@y"), "x\ny")

    def test_coalesce(self):
        self.assertEqual(M.coalesce([[0.0, "ab"], [0.01, "cd"], [0.5, "e"]]), [[0.0, "abcd"], [0.5, "e"]])

    def test_compare(self):
        a = {"steps": [{"cmd": "x", "output": "1", "exit": 0, "state": {}}], "branches": [{"name": "b", "steps": []}]}
        b = {"steps": [{"cmd": "x", "output": "2", "exit": 0, "state": {}}], "branches": [{"name": "c", "steps": []}]}
        d = M.compare(a, b)
        self.assertTrue(any("output changed" in x for x in d))
        self.assertTrue(any("branch b: removed" in x for x in d) and any("branch c: added" in x for x in d))



class TerminalTests(unittest.TestCase):
    def test_cast_preserves_output_and_marker_timing(self):
        recording = {"title": "Demo", "recorded": {"cols": 80, "rows": 24},
                     "markers": [{"step": 1, "title": "Read", "note": "Read the file."}],
                     "steps": [{"cmd": "printf hi", "duration": 1, "cast": [[0.2, "hi"]]},
                               {"cmd": "cat demo", "duration": 0.5, "cast": [[0.1, "hello\r\n"]]}]}
        rows = [json.loads(line) for line in M.terminal_cast(recording).splitlines()]
        self.assertEqual(rows[0]["version"], 2)
        self.assertNotIn("timestamp", rows[0])
        self.assertEqual(rows[0]["width"], 80)
        self.assertIn([0.2, "o", "hi"], rows)
        self.assertIn([1.001, "m", "Read"], rows)
        self.assertIn([1.101, "o", "hello\r\n"], rows)
        self.assertEqual([r[0] for r in rows[1:]], sorted(r[0] for r in rows[1:]))

    def test_marker_bounds(self):
        doc = {"version": 1, "id": "demo", "title": "Demo", "terminal": True,
               "scenario": {"commands": ["echo hello"]},
               "markers": [{"step": 1, "title": "Bad", "note": "Outside commands."}]}
        self.assertIn("marker step is past the last command", M.check_session(doc))
        doc["markers"][0]["step"] = 0
        self.assertEqual(M.check_session(doc), [])

    def test_terminal_publish_opt_in_and_stale(self):
        import gzip
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "codeviz", "sessions"))
            os.makedirs(os.path.join(root, "viz", "sessions"))
            doc = {"version": 1, "id": "demo", "title": "Demo", "scenario": {"commands": ["echo hello"]}}
            source = os.path.join(root, "codeviz", "sessions", "demo.json")
            target = os.path.join(root, "viz", "sessions", "demo.json.gz")
            rec = dict(doc, steps=[{"cmd": "echo hello", "output": "hello\n", "exit": 0}],
                       recorded={"scenario_sha": M.scenario_sha(doc["scenario"])})
            with gzip.open(target, "wt") as f:
                json.dump(rec, f)
            with open(source, "w") as f:
                json.dump(doc, f)
            entries = []
            self.assertEqual(M.publish(root, {}, [], entries)[0], [])
            self.assertEqual(entries[0]["modes"], ["simulate"])
            doc["terminal"] = True
            with open(source, "w") as f:
                json.dump(doc, f)
            self.assertEqual(M.publish(root, {}, [], entries)[0], [])
            self.assertEqual(entries[0]["modes"], ["simulate", "terminal"])
            self.assertTrue(os.path.isfile(os.path.join(root, "viz", "terminals", "demo.cast")))
            doc["scenario"]["commands"] = ["echo changed"]
            with open(source, "w") as f:
                json.dump(doc, f)
            self.assertTrue(M.publish(root, {}, [], entries)[0])
            self.assertNotIn("terminal", entries[0]["modes"])


if __name__ == "__main__":
    unittest.main()
