"""code-viz Python step tracer.

Runs one Python program under sys.settrace and records, for every line executed in the program
itself: the line, the call stack (each frame's local variables), the objects those variables point
to (lists, dicts, tuples, sets, instances, functions and their closures), and the output so far.
Pure Python with no imports beyond the standard library, so the same file runs in the runner
container and in the browser (Pyodide) for live editing.

Usage:  python3 pytrace.py PROGRAM.py [--max-steps N] > trace.json
In Pyodide: trace_source(code_string, max_steps) returns the trace as a dict.
"""
import io
import json
import sys
import types

PRIMS = (int, float, bool, str, type(None), complex)
SKIP_NAMES = {"__builtins__", "__name__", "__doc__", "__package__", "__loader__", "__spec__",
              "__file__", "__cached__", "__annotations__"}


class Tracer:
    def __init__(self, filename, max_steps=800):
        self.filename = filename
        self.max_steps = max_steps
        self.steps = []
        self.out = io.StringIO()
        self.frame_ids = {}
        self.next_frame = 1
        self.zombies = {}      # frame id -> last snapshot of a returned frame whose cells live on
        self.truncated = False

    # ---- encoding ----------------------------------------------------------------------------
    def enc(self, v, heap, depth=0):
        if isinstance(v, PRIMS):
            if isinstance(v, float) and v != v:
                return {"p": "nan"}
            if isinstance(v, str) and len(v) > 200:
                return {"p": v[:200] + "..."}
            if isinstance(v, complex):
                return {"p": repr(v)}
            return {"p": v}
        ref = id(v)
        if ref not in heap and depth < 6 and len(heap) < 400:
            heap[ref] = None  # reserve, so cycles terminate
            heap[ref] = self.enc_obj(v, heap, depth + 1)
        return {"r": ref}

    def enc_obj(self, v, heap, depth):
        if isinstance(v, (list, tuple, set, frozenset)):
            items = list(v)[:60]
            kind = type(v).__name__
            return {"t": kind, "items": [self.enc(x, heap, depth) for x in items], "more": max(0, len(v) - 60)}
        if isinstance(v, dict):
            items = list(v.items())[:60]
            return {"t": "dict", "items": [[self.enc(k, heap, depth), self.enc(x, heap, depth)] for k, x in items],
                    "more": max(0, len(v) - 60)}
        if isinstance(v, types.FunctionType):
            code = v.__code__
            params = list(code.co_varnames[:code.co_argcount])
            closure = {}
            if v.__closure__:
                for name, cell in zip(code.co_freevars, v.__closure__):
                    try:
                        closure[name] = self.enc(cell.cell_contents, heap, depth)
                    except ValueError:
                        closure[name] = {"p": "<unset>"}
            parent = v.__qualname__.rsplit(".<locals>.", 1)[0] if ".<locals>." in v.__qualname__ else None
            return {"t": "function", "name": v.__name__, "params": params, "closure": closure, "parent": parent,
                    "line": code.co_firstlineno}
        if isinstance(v, (types.BuiltinFunctionType, types.ModuleType, type)):
            return {"t": "builtin", "name": getattr(v, "__name__", repr(v))}
        if hasattr(v, "__dict__"):
            attrs = {k: self.enc(x, heap, depth) for k, x in list(vars(v).items())[:40] if not k.startswith("__")}
            return {"t": "instance", "class": type(v).__name__, "attrs": attrs}
        return {"t": "other", "repr": repr(v)[:200]}

    # ---- snapshots ---------------------------------------------------------------------------
    def fid(self, frame):
        k = id(frame)
        if k not in self.frame_ids:
            self.frame_ids[k] = self.next_frame
            self.next_frame += 1
        return self.frame_ids[k]

    def snapshot(self, frame, event, retval=None):
        if len(self.steps) >= self.max_steps:
            self.truncated = True
            raise _Stop()
        heap = {}
        stack = []
        f = frame
        while f is not None:
            if f.f_code.co_filename == self.filename:
                loc = {}
                for k, x in list(f.f_locals.items()):
                    if k in SKIP_NAMES or (f.f_code.co_name == "<module>" and isinstance(x, types.ModuleType)):
                        continue
                    loc[k] = self.enc(x, heap)
                stack.append({"id": self.fid(f), "func": "global" if f.f_code.co_name == "<module>" else f.f_code.co_name,
                              "line": f.f_lineno, "vars": loc})
            f = f.f_back
        stack.reverse()
        step = {"line": frame.f_lineno, "event": event, "stack": stack,
                "heap": {str(k): v for k, v in heap.items() if v is not None}, "out": len(self.out.getvalue())}
        if event == "return":
            step["ret"] = self.enc(retval, heap)
            step["heap"] = {str(k): v for k, v in heap.items() if v is not None}
            # keep a returned frame whose variables a live closure still captures
            if any(isinstance(h, dict) and h.get("t") == "function" and h.get("parent") == frame.f_code.co_name
                   for h in heap.values()) or frame.f_code.co_freevars or frame.f_code.co_cellvars:
                self.zombies[self.fid(frame)] = stack[-1] if stack else None
        if self.zombies:
            # a returned frame stays on screen only while a function on the heap still captures from it
            live = {s["id"] for s in stack}
            parents = {h.get("parent") for h in step["heap"].values() if isinstance(h, dict) and h.get("t") == "function" and h.get("closure")}
            keep = [(k, z) for k, z in self.zombies.items() if z and k not in live and z.get("func") in parents]
            step["zombies"] = [z for k, z in keep[-4:]]
        self.steps.append(step)

    def trace(self, frame, event, arg):
        if frame.f_code.co_filename != self.filename:
            return None  # do not trace library code
        if event in ("line", "return", "exception", "call"):
            if event == "call":
                return self.trace
            self.snapshot(frame, event, arg if event == "return" else None)
        return self.trace


class _Stop(Exception):
    pass


def trace_source(src, max_steps=800, filename="<program>"):
    t = Tracer(filename, max_steps)
    code = compile(src, filename, "exec")
    g = {"__name__": "__main__", "__builtins__": __builtins__}
    old, old_argv = sys.stdout, sys.argv
    sys.stdout = t.out
    import os
    import shlex
    sys.argv = [filename] + shlex.split(os.environ.get("CVIZ_ARGS", ""))  # the label's args=, else none
    error = None
    try:
        sys.settrace(t.trace)
        exec(code, g)
    except _Stop:
        pass
    except SystemExit:
        pass
    except BaseException as e:  # the program's own error is part of the trace
        error = f"{type(e).__name__}: {e}"
    finally:
        sys.settrace(None)
        sys.stdout, sys.argv = old, old_argv
    return {"version": 1, "kind": "env", "language": "python", "source": src, "steps": t.steps,
            "stdout": t.out.getvalue(), "error": error, "truncated": t.truncated}


def main(argv):
    path = argv[1]
    max_steps = int(argv[argv.index("--max-steps") + 1]) if "--max-steps" in argv else 800
    src = open(path, encoding="utf-8").read()
    sys.setrecursionlimit(5000)
    result = trace_source(src, max_steps, filename=path)
    json.dump(result, sys.__stdout__)


if __name__ == "__main__":
    main(sys.argv)
