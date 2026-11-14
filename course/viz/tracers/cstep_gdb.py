"""code-viz C/C++ stepper, run inside gdb (gdb -batch -x cstep_gdb.py).

Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 8 Reading the viewer (c), 14 Trace format, 18 Known problems.

Steps through the program's own source lines from main, recording at each line the call stack
(function, line, local variables and arguments with their values and addresses). Pointer values
are recorded as addresses, and each local's own address is recorded, so the viewer can draw a
pointer as an arrow to the variable it points at. Library code is stepped over.

Environment: CVIZ_PROG (the compiled binary), CVIZ_SRC (source file names, comma separated),
CVIZ_OUT (trace JSON path), CVIZ_STDOUT (program output file), CVIZ_MAX (step cap).

PIPELINE
  driver.py (c runner) compiles the example with gcc or g++ -g -O0, then runs
  gdb -batch -x cstep_gdb.py with the environment below; the JSON it writes becomes the trace.

TRACE FIELDS WRITTEN
  steps: {line, file, stack: [{func, line, vars: {name: {v|ptr|array|struct, type, addr}}}], out};
  driver.py adds kind "c", language c|cpp, source, stdout, error, truncated.

ENVIRONMENT  CVIZ_PROG, CVIZ_SRC, CVIZ_OUT, CVIZ_STDOUT, CVIZ_MAX (step cap, default 800).

EXAMPLE (inside the c runner)
  g++ -g -O0 move.cpp -o prog && CVIZ_PROG=./prog CVIZ_SRC=move.cpp CVIZ_OUT=t.json \
    CVIZ_STDOUT=out.txt CVIZ_MAX=800 gdb -batch -x cstep_gdb.py

LIMITS AND KNOWN PROBLEMS
  - Programs that read stdin interactively or loop for long stop at the step cap or the timeout.
  - cs374-tutorial-c-for-flex-bison-1 produces no gdb steps (its main is in generated code).
"""
import json
import os

import gdb  # noqa: provided by gdb

PROG = os.environ["CVIZ_PROG"]
SRCS = {os.path.basename(s) for s in os.environ.get("CVIZ_SRC", "").split(",") if s}
OUT = os.environ["CVIZ_OUT"]
MAX = int(os.environ.get("CVIZ_MAX", "400"))

gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute(f"file {PROG}")
gdb.execute("break main")
gdb.execute(f"run > {os.environ['CVIZ_STDOUT']} 2>&1 < /dev/null")


def value(v):
    t = v.type.strip_typedefs()
    try:
        if t.code in (gdb.TYPE_CODE_REF, getattr(gdb, "TYPE_CODE_RVALUE_REF", -1)):
            # a reference: drawn like a pointer, to the object it refers to
            try:
                return {"ptr": hex(int(v.referenced_value().address)), "type": str(v.type), "ref": True}
            except gdb.error:
                return {"v": "<reference>", "type": str(v.type)}
        if t.code == gdb.TYPE_CODE_PTR:
            addr = int(v)
            out = {"ptr": hex(addr), "type": str(v.type)}
            if addr and t.target().strip_typedefs().code == gdb.TYPE_CODE_INT and str(t.target()) in ("char", "const char"):
                try:
                    out["str"] = v.string(length=80)
                except gdb.error:
                    pass
            return out
        if t.code == gdb.TYPE_CODE_ARRAY:
            n = t.range()[1] - t.range()[0] + 1
            return {"array": [value(v[i]) for i in range(min(n, 32))], "type": str(v.type)}
        if t.code == gdb.TYPE_CODE_STRUCT:
            return {"struct": {f.name: value(v[f.name]) for f in t.fields() if f.name}, "type": str(v.type)}
        return {"v": str(v), "type": str(v.type)}
    except gdb.error as e:
        return {"v": f"<{e}>"}


def frame_vars(f):
    out = {}
    try:
        block = f.block()
    except RuntimeError:
        return out
    while block is not None:
        for sym in block:
            if (sym.is_variable or sym.is_argument) and sym.name not in out:
                try:
                    v = sym.value(f)
                    rec = value(v)
                    try:
                        # a reference's "address" is its referent's: it has no storage of its own to draw
                        rec["addr"] = hex(int(v.address)) if v.address is not None and not rec.get("ref") else None
                    except gdb.error:
                        pass
                    out[sym.name] = rec
                except (gdb.error, RuntimeError):
                    pass
        if block.function is not None:
            break
        block = block.superblock
    return out


def user_frame(f):
    sal = f.find_sal()
    return sal.symtab is not None and os.path.basename(sal.symtab.filename) in SRCS


steps = []
while len(steps) < MAX:
    try:
        f = gdb.selected_frame()
    except gdb.error:
        break
    if not user_frame(f):
        try:
            gdb.execute("finish", to_string=True)
            continue
        except gdb.error:
            break
    stack, g = [], f
    while g is not None:
        if user_frame(g):
            sal = g.find_sal()
            stack.append({"func": g.name() or "?", "line": sal.line, "file": os.path.basename(sal.symtab.filename),
                          "vars": frame_vars(g)})
        g = g.older()
    stack.reverse()
    try:
        out_len = os.path.getsize(os.environ["CVIZ_STDOUT"])
    except OSError:
        out_len = 0
    steps.append({"line": f.find_sal().line, "file": os.path.basename(f.find_sal().symtab.filename),
                  "stack": stack, "out": out_len})
    try:
        gdb.execute("step", to_string=True)
    except gdb.error:
        break

with open(OUT, "w") as fh:
    json.dump({"steps": steps, "truncated": len(steps) >= MAX}, fh)
gdb.execute("kill")
