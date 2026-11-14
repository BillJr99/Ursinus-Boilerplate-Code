"""code-viz flex/bison tracer.

Builds a scanner and parser from a .y grammar (and a .l scanner when there is one) with bison's
parse tracing on, runs it on an input string, and turns bison's own trace (stderr) into steps:
the token read, the action (shift, reduce by rule N, accept, error), the state stack and the
remaining input. It also returns bison's state graph (DOT, from --graph) and the grammar rules, and
builds the parse tree from the shift and reduce sequence.

Usage:  python3 bisontrace.py DIR_OR_Y_FILE --input "2*3+4" > trace.json
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

ENABLE = "extern int yydebug;\n__attribute__((constructor)) static void cviz_on(void) { yydebug = 1; }\n"


def run(cmd, cwd, inp=None, timeout=20):
    return subprocess.run(cmd, cwd=cwd, input=inp, capture_output=True, text=True, timeout=timeout)


def build(src_dir):
    ys = glob.glob(os.path.join(src_dir, "*.y"))
    ls = glob.glob(os.path.join(src_dir, "*.l"))
    if not ys:
        raise SystemExit("no .y grammar found")
    work = tempfile.mkdtemp(prefix="cviz-bison-")
    for f in glob.glob(os.path.join(src_dir, "*")):
        if os.path.isfile(f):
            with open(f, "rb") as a, open(os.path.join(work, os.path.basename(f)), "wb") as b:
                b.write(a.read())
    y = os.path.basename(ys[0])
    r = run(["bison", "-t", "-d", "-v", "--report=all", f"--graph=parser.dot", "-o", "parser.tab.c", y], work)
    if r.returncode != 0:
        raise SystemExit("bison failed: " + r.stderr[-800:])
    # the scanner usually includes the bison header by its default name (y.tab.h or NAME.tab.h)
    base = os.path.splitext(y)[0]
    for alias in ("y.tab.h", f"{base}.tab.h"):
        if not os.path.exists(os.path.join(work, alias)):
            os.symlink("parser.tab.h", os.path.join(work, alias))
    cfiles = ["parser.tab.c"]
    if ls:
        r = run(["flex", "-o", "lex.yy.c", os.path.basename(ls[0])], work)
        if r.returncode != 0:
            raise SystemExit("flex failed: " + r.stderr[-800:])
        cfiles.append("lex.yy.c")
    extra = [os.path.basename(f) for f in glob.glob(os.path.join(work, "*.c"))
             if os.path.basename(f) not in ("parser.tab.c", "lex.yy.c") and "main(" in open(f, errors="replace").read()
             or os.path.basename(f) in ("ast.c", "eval.c")]
    with open(os.path.join(work, "cviz_on.c"), "w") as fh:
        fh.write(ENABLE)
    r = run(["gcc", "-g", "-o", "parser", *cfiles, *sorted(set(extra)), "cviz_on.c", "-lm"], work)
    if r.returncode != 0:
        r = run(["gcc", "-g", "-o", "parser", *cfiles, "cviz_on.c", "-lm", "-lfl"], work)
    if r.returncode != 0:
        raise SystemExit("gcc failed: " + r.stderr[-800:])
    return work, y


def rules(work):
    out = {}
    try:
        txt = open(os.path.join(work, "parser.output"), errors="replace").read()
    except OSError:
        return out
    gram = txt.split("Grammar", 1)[-1].split("Terminals", 1)[0]
    lhs = None
    for line in gram.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+):\s*(.*)$", line)
        if m:
            lhs = m.group(2)
            out[m.group(1)] = f"{lhs} → {m.group(3).strip() or 'ε'}"
            continue
        m = re.match(r"\s*(\d+)\s+\|\s*(.*)$", line)
        if m and lhs:
            out[m.group(1)] = f"{lhs} → {m.group(2).strip() or 'ε'}"
    return out


def parse_trace(err, rule_text):
    steps, stack, tok = [], [0], None
    tree_stack = []
    for line in err.splitlines():
        line = line.strip()
        m = re.match(r'(?:Reading a token: )?Next token is token ("[^"]+"|\S+)', line)
        if m:
            tok = m.group(1)
            continue
        if line.startswith("Now at end of input"):
            tok = "end of input"
            continue
        m = re.match(r'Shifting token ("[^"]+"|\S+)', line)
        if m:
            tree_stack.append({"s": m.group(1), "kids": []})
            steps.append({"action": f"shift {m.group(1)}", "token": tok, "stack": list(stack), "tree": list(tree_stack)})
            continue
        m = re.match(r"Reducing stack (?:\d+ )?by rule (\d+)", line)
        if m:
            rid = m.group(1)
            text = rule_text.get(rid, f"rule {rid}")
            rhs = text.split("→", 1)[-1].split()
            n = 0 if rhs == ["ε"] else len([x for x in rhs if x not in ("%empty",)])
            kids = tree_stack[len(tree_stack) - n:] if n else []
            del tree_stack[len(tree_stack) - n:]
            tree_stack.append({"s": text.split("→")[0].strip(), "kids": kids})
            steps.append({"action": f"reduce by rule {rid}: {text}", "token": tok, "stack": list(stack), "tree": list(tree_stack)})
            continue
        m = re.match(r"Stack now ([\d ]+)", line)
        if m:
            stack = [int(x) for x in m.group(1).split()]
            if steps:
                steps[-1]["stack_after"] = list(stack)
            continue
        m = re.match(r"Entering state (\d+)", line)
        if m and steps:
            steps[-1]["state"] = int(m.group(1))
            continue
        if line.startswith("Stack now") or not line:
            continue
        if "syntax error" in line or line.startswith("Error"):
            steps.append({"action": line, "token": tok, "stack": list(stack), "tree": list(tree_stack)})
        if line.startswith("Accepting") or "accept" in line.lower() and "Cleanup" not in line:
            steps.append({"action": "accept", "token": tok, "stack": list(stack), "tree": list(tree_stack)})
    return steps


def trace(path, inp):
    src_dir = path if os.path.isdir(path) else os.path.dirname(path) or "."
    work, y = build(src_dir)
    r = run(["./parser"], work, inp=inp + ("\n" if not inp.endswith("\n") else ""))
    rt = rules(work)
    steps = parse_trace(r.stderr, rt)
    dot = open(os.path.join(work, "parser.dot"), errors="replace").read() if os.path.exists(os.path.join(work, "parser.dot")) else ""
    files = {}
    for f in sorted(glob.glob(os.path.join(src_dir, "*"))):
        if f.endswith((".y", ".l")) and os.path.getsize(f) < 60000:
            files[os.path.basename(f)] = open(f, errors="replace").read()
    stdout = r.stdout
    return {"version": 1, "kind": "bison", "language": "flexbison", "source": files.get(y, ""), "files": files,
            "input": inp, "rules": rt, "steps": steps, "graph": dot, "stdout": stdout, "error": None,
            "truncated": False}


if __name__ == "__main__":
    a = sys.argv
    inp = a[a.index("--input") + 1] if "--input" in a else ""
    try:
        out = trace(a[1], inp)
    except SystemExit as e:
        out = {"version": 1, "kind": "bison", "error": str(e), "steps": [], "stdout": ""}
    json.dump(out, sys.stdout)
