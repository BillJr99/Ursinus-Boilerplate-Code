"""code-viz driver extension for SQL, Java, JavaScript, MIPS and VHDL (langrun.py), run inside a runner
container by driver.py: driver._one() calls run(job, ...) first and uses its trace when it returns one.

Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 2 Architecture
(Runners, Tracers), 7 Kinds of visualization and 14 Trace format.

DISPATCH (job["viz"], job["lang"])
  sql  (viz sql or plain)  sqltrace.py in the python runner (sqlite3): tables after every statement;
                           setup= statements run first, unrecorded.
  js   (plain)             node main.js in the node runner; output only.
  java (viz java)          javac -g, then JdiTrace (tracers/JdiTrace.java, compiled once per container
                           into /tmp/cviz-jdi) launches the program under the Java debugger and records
                           frames and objects at every line of the example's own classes. If stepping
                           fails (or the program reads input), the example runs output only and the trace
                           says why. Fragments are wrapped first (below).
  java (plain)             javac and java, output only.
  mips (viz mips/plain)    mipstrace.py (registers and memory per instruction), and SPIM as the
                           reference: when SPIM's output differs, the trace is marked approximate and
                           shows SPIM's output (reference_stdout holds it either way).
  vhdl (viz wave/plain)    GHDL: import every .vhd file (the block, its setup= blocks, or a manifest
                           folder or .zip), make and run the testbench (the entity with no ports, the one
                           named *_tb or *tb when there are several) with --vcd, then read the VCD into
                           signals over time. args="--stop-time=5us" changes the default stop time (2 us).

JAVA FRAGMENTS (never changing what the example does)
  A block with a top-level class, interface, enum or record is compiled as it is, in a file named after
  its public class (Main.java when none is public); the class with main is run. A block of methods (no
  class) is wrapped in "public class Main { ... }". A block of statements is wrapped in a main method
  inside Main. import lines move above the wrapper. The trace keeps the block's own text as "source"
  and maps every line back to it, so the viewer shows and highlights the block, not the wrapper.

LIMITS
  Java stepping records the example's own classes only (library code is not stepped), at most
  max_steps lines and 60 objects per step; collections from java.util are shown by type and size.
  Programs that read System.in get no input. VHDL without a testbench is not run (there is nothing to
  simulate, and code-viz does not invent testbenches).
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile

JAVA_DECL = re.compile(r"^\s*(?:(?:public|final|abstract|sealed|non-sealed|static)\s+)*(class|interface|enum|record)\s+(\w+)", re.M)
JAVA_METHOD = re.compile(r"^\s*(?:(?:public|private|protected|static|final|synchronized)\s+)+[\w<>\[\],\s]+\s+\w+\s*\([^;]*\)\s*(?:throws [\w.,\s]+)?\{", re.M)


def run(job, sh, tracer, SRC, T):
    v, lang = job["viz"], job["lang"]
    if lang == "sql":
        st = ("--setup", os.path.join(SRC, job["setup"])) if job.get("setup") else ()
        return tracer("sqltrace.py", job, ("--max-steps", str(job.get("max_steps", 400))) + st)
    if lang == "js":
        path = os.path.join(SRC, job["file"])
        r = sh(["node", os.path.basename(path)], job.get("timeout", 20), os.path.dirname(path), job.get("input"))
        return {"kind": "plain", "language": "js", "source": open(path, encoding="utf-8").read(),
                "stdout": r.stdout + (r.stderr if r.returncode else ""), "steps": [],
                "error": None if r.returncode == 0 else f"exit {r.returncode}"}
    if lang == "java":
        return java(job, sh, SRC, T)
    if lang == "mips":
        return mips(job, sh, tracer, SRC)
    if lang == "vhdl":
        return vhdl(job, sh, SRC)
    return None


# ---------------------------------------------------------------- Java
def java_prepare(code):
    """(files {name: text}, main class, line map: wrapped line -> block line) for a Java block."""
    lines = code.split("\n")
    imports = [i for i, l in enumerate(lines) if re.match(r"^\s*(import|package)\s+[\w.*]+\s*;", l)]
    body = [i for i in range(len(lines)) if i not in imports]
    decls = JAVA_DECL.findall(code)
    out, lmap = [], {}

    def emit(text, src=None):
        out.append(text)
        if src is not None:
            lmap[len(out)] = src + 1

    for i in imports:
        if not lines[i].strip().startswith("package"):
            emit(lines[i], i)
    if decls:
        for i in body:
            emit(lines[i], i)
        pub = re.search(r"^\s*public\s+(?:(?:final|abstract)\s+)*(?:class|interface|enum|record)\s+(\w+)", code, re.M)
        name = pub.group(1) if pub else "Main"
        # the class holding main: the last top-level (unindented) declaration before "static void main"
        mpos = code.find("static void main")
        top = [m for m in JAVA_DECL.finditer(code) if not code[m.start():m.end()].startswith((" ", "\t"))]
        before = [m.group(2) for m in top if m.start() < mpos] if mpos >= 0 else []
        main = before[-1] if before else name
    elif JAVA_METHOD.search(code):
        emit("public class Main {")
        for i in body:
            emit(lines[i], i)
        emit("}")
        name = main = "Main"
    else:
        emit("public class Main {")
        emit("public static void main(String[] args) throws Exception {")
        for i in body:
            emit(lines[i], i)
        emit("}")
        emit("}")
        name = main = "Main"
    return {name + ".java": "\n".join(out) + "\n"}, main, lmap


def java(job, sh, SRC, T):
    path = os.path.join(SRC, job["file"])
    code = open(path, encoding="utf-8").read()
    files, main, lmap = java_prepare(code)
    work = tempfile.mkdtemp(prefix="cviz-java-")
    for f, text in files.items():
        open(os.path.join(work, f), "w", encoding="utf-8").write(text)
    os.makedirs(os.path.join(work, "out"))
    c = sh(["javac", "-g", "-encoding", "UTF-8", "-d", "out", *files], 60, work)
    base = {"kind": "plain", "language": "java", "source": code, "steps": []}
    if c.returncode != 0:
        return dict(base, stdout="", error="compile failed: " + remap_javac(c.stderr, lmap)[-800:])
    to = max(int(job.get("timeout", 20)), 30)
    if job["viz"] == "java" and "System.in" not in code:
        jdi = "/tmp/cviz-jdi"
        if not os.path.exists(os.path.join(jdi, "JdiTrace.class")):
            os.makedirs(jdi, exist_ok=True)
            b = sh(["javac", "-d", jdi, os.path.join(T, "JdiTrace.java")], 120, jdi)
            if b.returncode != 0:
                raise RuntimeError("JdiTrace did not compile: " + b.stderr[-400:])
        users = sorted(os.path.splitext(f)[0].replace(os.sep, ".") for f in walk_classes(os.path.join(work, "out")))
        r = sh(["java", "-Xmx256m", "-cp", jdi, "JdiTrace", os.path.join(work, "out"), main, str(job.get("max_steps", 800)),
                ",".join(users)], to + 30, work, job.get("input"))
        try:
            t = json.loads(r.stdout)
        except ValueError:
            t = None
        if t is not None and t.get("steps"):
            for s in t["steps"]:
                s["line"] = lmap.get(s.get("line"), s.get("line"))
                for f in s.get("stack", []):
                    f["line"] = lmap.get(f.get("line"), f.get("line"))
            t.update({"kind": "env", "language": "java", "source": code})
            return t
        note = (t or {}).get("error") or (r.stderr or "no steps recorded")[-300:]
        base["note"] = "stepping failed, output only: " + note
    r = sh(["java", "-Xmx256m", "-cp", "out", main], to, work, job.get("input"))
    return dict(base, stdout=r.stdout + (r.stderr if r.returncode else ""),
                error=None if r.returncode == 0 else f"exit {r.returncode}")


def walk_classes(d):
    for dp, _, fn in os.walk(d):
        for f in fn:
            if f.endswith(".class") and "$$" not in f and "$Lambda" not in f:   # inner classes (Outer$Node) are the example's own
                yield os.path.relpath(os.path.join(dp, f), d)


def remap_javac(err, lmap):
    return re.sub(r"(\w+\.java):(\d+):", lambda m: f"line {lmap.get(int(m.group(2)), m.group(2))}:", err)


# ---------------------------------------------------------------- MIPS
def mips(job, sh, tracer, SRC):
    path = os.path.join(SRC, job["file"])
    inp = job.get("input") or ""
    t = tracer("mipstrace.py", job, ("--max-steps", str(job.get("max_steps", 800)), "--input", inp))
    if shutil.which("spim"):
        try:
            r = sh(["spim", "-quiet", "-file", path], min(int(job.get("timeout", 20)), 15), os.path.dirname(path), inp + "\n")
        except subprocess.TimeoutExpired:
            r = None   # SPIM still running (waiting for input it will not get): keep the simulator's run
            t["reference_note"] = "SPIM did not finish in 15 s (the program may wait for more input)"
        if r is not None:
            ref = spim_output(r.stdout)
            t["reference_stdout"] = ref
            if ref.strip() != (t.get("stdout") or "").strip():
                t["approximate"] = True
                t["stdout"] = ref
    if job["viz"] == "plain":
        t["kind"] = "mips"
    return t


SPIM_BANNER = ("SPIM Version", "Copyright 1990-", "All Rights Reserved.", "See the file README", "Loaded:")


def spim_output(text):
    """SPIM's program output without its start-up banner (printed even with -quiet in 8.0)."""
    lines = text.split("\n")
    while lines and lines[0].startswith(SPIM_BANNER):
        lines.pop(0)
    return "\n".join(lines)


# ---------------------------------------------------------------- VHDL
VCD_VAR = re.compile(r"\$var\s+\S+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[[^\]]*\])?\s+\$end")


def vhdl_sources(job, SRC, work):
    path = os.path.join(SRC, job["file"])
    names = []
    if job.get("setup"):
        shutil.copy(os.path.join(SRC, job["setup"]), os.path.join(work, "setup.vhd"))
        names.append("setup.vhd")
    if os.path.isdir(path):
        for f in sorted(os.listdir(path)):
            if f.endswith((".vhd", ".vhdl")):
                shutil.copy(os.path.join(path, f), work)
                names.append(f)
    elif path.endswith(".zip"):
        z = zipfile.ZipFile(path)
        for n in z.namelist():
            if n.endswith((".vhd", ".vhdl")) and "/." not in "/" + n:
                f = os.path.basename(n)
                open(os.path.join(work, f), "wb").write(z.read(n))
                names.append(f)
    else:
        shutil.copy(path, os.path.join(work, "main.vhd"))
        names.append("main.vhd")
    return names


def vhdl(job, sh, SRC):
    work = tempfile.mkdtemp(prefix="cviz-vhdl-")
    names = vhdl_sources(job, SRC, work)
    texts = {n: open(os.path.join(work, n), encoding="utf-8", errors="replace").read() for n in names}
    own = [n for n in names if n != "setup.vhd"]
    shown = texts[own[0]] if len(own) == 1 else "\n".join(f"-- ===== {n} =====\n{texts[n]}" for n in own)
    tops = []
    for text in texts.values():
        for m in re.finditer(r"\bentity\s+(\w+)\s+is\b(.*?)\bend\b", text, re.I | re.S):
            if not re.search(r"\bport\s*\(", m.group(2), re.I):
                tops.append(m.group(1))
    base = {"kind": "wave", "language": "vhdl", "source": shown, "steps": [], "signals": []}
    if not tops:
        # A design without a testbench: analyze it (so a testbench block below can use it through
        # setup=), and say plainly that nothing is simulated here. code-viz never invents a testbench.
        ents = [e for t in texts.values() for e in re.findall(r"\bentity\s+(\w+)\s+is\b", t, re.I)]
        for std in (["--std=08"], ["--std=93c", "-fexplicit", "--ieee=synopsys"]):
            a = sh(["ghdl", "-a", *std, f"--workdir={tempfile.mkdtemp(dir=work)}", *names], 60, work)
            if a.returncode == 0:
                return dict(base, stdout=f"GHDL analyzed entity {', '.join(ents)} without errors. There is no testbench "
                                         "in this block, so nothing is simulated here.\n", analyzed_only=True)
        return dict(base, stdout="", error="ghdl could not analyze the design: " + (a.stderr or "")[-800:])
    top = sorted(tops, key=lambda x: (not re.search(r"tb$", x, re.I), x))[0]
    stop = "--stop-time=2us"
    for a in shlex.split(job.get("args") or ""):
        if a.startswith("--stop-time="):
            stop = a
    last = None
    for std in (["--std=08"], ["--std=93c", "-fexplicit", "--ieee=synopsys"]):
        wd = tempfile.mkdtemp(dir=work, prefix="w")
        opts = std + [f"--workdir={wd}"]
        i = sh(["ghdl", "-i", *opts, *names], 60, work)
        m = sh(["ghdl", "-m", *opts, top], 120, work) if i.returncode == 0 else i
        if m.returncode != 0:
            last = (i.stderr + m.stderr)[-800:]
            continue
        r = sh(["ghdl", "-r", *opts, top, "--vcd=wave.vcd", stop], job.get("timeout", 20), work)
        vcd = os.path.join(work, "wave.vcd")
        sig, times, end = read_vcd(open(vcd, errors="replace").read()) if os.path.exists(vcd) else ([], [], 0)
        out = r.stdout + (r.stderr if r.returncode else "")
        steps = [{"t": t, "changed": [s["name"] for s in sig if any(c[0] == t for c in s["changes"])]} for t in times]
        return dict(base, stdout=out, signals=sig, steps=steps, end=end, top=top, std=std[0].split("=")[1],
                    error=None if r.returncode == 0 else f"ghdl exit {r.returncode}")
    return dict(base, stdout="", error="ghdl could not build the design: " + (last or ""))


def read_vcd(text):
    """Signals of the testbench's own scope (top level) with their changes, the change times, the end time."""
    sig, by, scope, t = [], {}, [], 0
    times, end = [], 0
    header = True
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if header:
            if line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                scope.pop()
            elif line.startswith("$var"):
                m = VCD_VAR.match(line)
                if m and len(scope) <= 1:
                    s = {"name": m.group(3), "width": int(m.group(1)), "changes": []}
                    by.setdefault(m.group(2), []).append(s)
                    sig.append(s)
            elif line.startswith("$enddefinitions"):
                header = False
            continue
        if line.startswith("#"):
            t = int(line[1:])
            end = max(end, t)
            continue
        if line[0] in "bB":
            val, _, ident = line[1:].partition(" ")
        elif line[0] in "rR":
            continue
        elif line.startswith("$"):
            continue
        else:
            val, ident = line[0], line[1:]
        for s in by.get(ident.strip(), []):
            if not s["changes"] or s["changes"][-1][1] != val:
                s["changes"].append([t, val])
                if not times or times[-1] != t:
                    times.append(t)
    return sig, times, end
