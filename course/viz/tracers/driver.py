"""code-viz batch driver, run inside a runner container.

Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 2 Architecture (Tracers), 15 Where things run and safety.

Reads /work/jobs.json (written by code-viz), runs each example with its tracer under a per-example
timeout, and writes /work/out/<id>.json. The container runs with no network (except the agents
runner, which can reach Ollama only), capped CPU, memory and process count, and is removed after.

Job fields: id, viz (env, lambda, c, bison, automaton, agent, cast, plain), lang, file (relative to
/work/src), input (optional stdin or automaton/bison input), timeout (seconds), max_steps; for
interp= examples also interp_dir (the interpreter's .py files), interp_page, interp_files, entry, and
the trace gets {"interp": {"page", "files", "entry", "source"}}.

PIPELINE
  code-viz (run, build, label --try, serve) groups examples by runner, writes /work/jobs.json and
  /work/src/<files>, and starts one container per runner with this script as its command. The
  container mounts the tracers read-only at /viz/tracers and /work read-write; code-viz copies
  /work/out back and moves the staging folder to ~/scratch/code-viz on the Docker host.

INPUT  /work/jobs.json: [{id, viz, lang, file, input?, args?, timeout, max_steps}]
OUTPUT /work/out/<id>.json, one trace per job (trace format: README.md, "Trace format"). Every
  trace has version, kind, language, source, steps, stdout, error, truncated. This driver adds:
  for Scheme, approximate (true when the model interpreter's output differs from Guile's) and
  reference_stdout (Guile's output); for shell, cast; for plain examples, only stdout and error.

DISPATCH (viz -> tracer)
  env + python -> pytrace.py; env + scheme -> schemetrace.py (and Guile via cviz-repl.scm);
  lambda -> lambdatrace.py; c -> gcc/g++ -g then gdb -batch -x cstep_gdb.py; bison ->
  bisontrace.py; automaton -> automaton.py; agent -> agentrec.py; cast -> shellcast.py;
  plain -> compile or interpret with the runner's toolchain and capture output.

LIMITS AND KNOWN PROBLEMS
  - Each job has its own timeout (default 15 s; the container's total is the sum plus 60 s).
  - Step traces stop at max_steps (default 800) and set truncated; long loops and deep
    recursion (Y vs Z in CS374) end there, so the viewer shows the first 800 steps only.
  - Mini examples with interp= run the page's Python interpreter (job interp_dir, entry) on
    program.mini; without it, files/examples/mininote is built with make when present.
  - Haskell and OCaml run as plain programs only; no examples in CS357 or CS374 qualified yet.

setup= (job["setup"], a file of the setup blocks' code): passed to pytrace and agentrec as --setup,
run before plain Python by SETUP_WRAP, and copied into the trace as {"setup": {"ids", "source"}}.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

T = "/viz/tracers"
SRC = "/work/src"
OUT = "/work/out"


def sh(cmd, timeout, cwd=None, inp=None, env=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, input=inp,
                          env=dict(os.environ, PYTHONHASHSEED="0", **(env or {})))  # same set order every build


def tracer(script, job, extra=()):
    path = os.path.join(SRC, job["file"])
    r = sh([sys.executable, os.path.join(T, script), path, *extra], job.get("timeout", 15), cwd=os.path.dirname(path),
           env={"CVIZ_ARGS": job.get("args", "")})
    if r.returncode != 0 and not r.stdout.strip():
        raise RuntimeError((r.stderr or "tracer failed")[-600:])
    return json.loads(r.stdout)


def plain(job):
    """Run without a step trace; record output only."""
    path = os.path.join(SRC, job["file"])
    d, f = os.path.dirname(path), os.path.basename(path)
    lang, to, inp = job["lang"], job.get("timeout", 20), job.get("input")
    if lang == "haskell":
        r = sh(["runghc", f], to, d, inp)
    elif lang == "ocaml":
        r = sh(["ocaml", f], to, d, inp)
    elif lang == "prolog":
        goals = [l.strip()[2:].strip().rstrip(".") for l in open(path).read().splitlines() if l.strip().startswith("?-")]
        prog = os.path.join(d, "cviz_prog.pl")
        with open(prog, "w") as fh:
            fh.write("\n".join(l for l in open(path).read().splitlines() if not l.strip().startswith("?-")))
        outs = []
        for g in goals or ["true"]:
            r = sh(["swipl", "-q", "-f", prog, "-g", f"forall(({g}), (print_message(informational, format('~w', [ok])), writeln(yes))) -> true ; writeln(no)", "-t", "halt"], to, d)
            outs.append(f"?- {g}.\n{r.stdout}{r.stderr}")
        return {"kind": "plain", "stdout": "".join(outs), "error": None}
    elif lang in ("c", "cpp"):
        exe = os.path.join(tempfile.mkdtemp(), "prog")
        cc = "g++" if lang == "cpp" else "gcc"
        b = sh([cc, "-O0", "-g", f, "-o", exe, "-lm"], to, d)
        if b.returncode != 0:
            raise RuntimeError("compile failed: " + b.stderr[-600:])
        r = sh([exe], to, d, inp)
    elif lang == "mini" and job.get("interp_dir"):
        # interp=: the page's own Python interpreter reads this program as its input file
        work = tempfile.mkdtemp()
        idir = os.path.join(SRC, job["interp_dir"])
        for x in os.listdir(idir):
            shutil.copy(os.path.join(idir, x), work)
        shutil.copy(path, os.path.join(work, "program.mini"))
        cmd = [sys.executable] + [w.replace("{file}", "program.mini") for w in shlex.split(job.get("entry", "runner.py --file {file}"))]
        r = sh(cmd, to, work, inp)
    elif lang == "mini":
        work = tempfile.mkdtemp()
        mdir = os.path.join(SRC, job.get("interpreter", "mini"))
        for x in os.listdir(mdir):
            shutil.copy(os.path.join(mdir, x), work)
        b = sh(["make"], 120, work)
        if b.returncode != 0:
            raise RuntimeError("mini build failed: " + (b.stdout + b.stderr)[-600:])
        exe = next((os.path.join(work, x) for x in ("mininote", "mini", "a.out") if os.path.exists(os.path.join(work, x))), None)
        r = sh([exe, path], to, work) if exe else None
        if r is None:
            raise RuntimeError("mini interpreter binary not found after make")
    elif lang == "shell":
        r = sh(["bash", f], to, d, inp)
    elif job.get("setup"):
        r = sh([sys.executable, "-c", SETUP_WRAP, os.path.join(SRC, job["setup"]), f], to, d, inp)
    else:
        r = sh([sys.executable, f], to, d, inp)
    return {"kind": "plain", "stdout": r.stdout + (r.stderr if r.returncode else ""),
            "error": None if r.returncode == 0 else f"exit {r.returncode}"}


def c_trace(job):
    path = os.path.join(SRC, job["file"])
    d, f = os.path.dirname(path), os.path.basename(path)
    work = tempfile.mkdtemp()
    exe = os.path.join(work, "prog")
    cc = "g++" if job["lang"] == "cpp" else "gcc"
    b = sh([cc, "-O0", "-g", "-fno-omit-frame-pointer", f, "-o", exe, "-lm"], 60, d)
    if b.returncode != 0:
        raise RuntimeError("compile failed: " + b.stderr[-600:])
    out, so = os.path.join(work, "trace.json"), os.path.join(work, "stdout.txt")
    sh(["gdb", "-q", "-batch", "-nx", "-x", os.path.join(T, "cstep_gdb.py")], job.get("timeout", 40), d,
       env={"CVIZ_PROG": exe, "CVIZ_SRC": f, "CVIZ_OUT": out, "CVIZ_STDOUT": so, "CVIZ_MAX": str(job.get("max_steps", 400))})
    data = json.load(open(out)) if os.path.exists(out) else {"steps": []}
    stdout = open(so, errors="replace").read() if os.path.exists(so) else ""
    plain_run = sh([exe], 10, d)
    return {"kind": "c", "language": job["lang"], "source": open(path, errors="replace").read(), "steps": data["steps"],
            "stdout": plain_run.stdout or stdout, "error": None if plain_run.returncode == 0 else f"exit {plain_run.returncode}",
            "truncated": data.get("truncated", False)}


SETUP_WRAP = (  # plain Python with setup=: run the setup silently, then the program in the same globals
    "import io, runpy, sys\n"
    "g = {'__name__': '__main__'}\n"
    "o, sys.stdout = sys.stdout, io.StringIO()\n"
    "exec(compile(open(sys.argv[1]).read(), '<setup>', 'exec'), g)\n"
    "sys.stdout = o\n"
    "sys.argv = sys.argv[2:]\n"
    "g.pop('__name__', None)\n"
    "runpy.run_path(sys.argv[0], init_globals=g, run_name='__main__')\n")


FIG_BYTES = 600_000  # figures kept per example (base64 PNGs); later ones are dropped and counted


def add_figures(t, d):
    """Figures the example drew (cviz_mplbackend, the turtle and ezgraphics stand-ins): fig-NN.png
    files in d become t["figures"] = [{"png": base64, "at": output offset}], in order."""
    import base64
    names = sorted(f for f in os.listdir(d) if f.endswith(".png")) if os.path.isdir(d) else []
    figs, total, dropped = [], 0, 0
    for f in names:
        data = open(os.path.join(d, f), "rb").read()
        meta = os.path.join(d, f[:-4] + ".json")
        at = json.load(open(meta)).get("at", 0) if os.path.exists(meta) else 0
        if total + len(data) > FIG_BYTES:
            dropped += 1
            continue
        total += len(data)
        figs.append({"png": base64.b64encode(data).decode(), "at": at})
    if figs:
        t["figures"] = figs
    if dropped:
        t["figures_dropped"] = dropped
    shutil.rmtree(d, ignore_errors=True)


def one(job):
    """Run one job and add, when the label has setup=, the setup's ids and code to the trace; and the
    figures it drew (section 7, Figures)."""
    figdir = tempfile.mkdtemp(prefix="cviz-figs-")
    os.environ["CVIZ_FIGS"] = figdir
    try:
        t = _one(job)
    finally:
        os.environ.pop("CVIZ_FIGS", None)
    if isinstance(t, dict):
        add_figures(t, figdir)
    if job.get("interp_dir") and isinstance(t, dict):
        # shown collapsed above the program: the interpreter that ran it, file by file
        idir = os.path.join(SRC, job["interp_dir"])
        t["interp"] = {"page": job.get("interp_page", ""), "files": job.get("interp_files", []), "entry": job.get("entry", ""),
                       "source": "\n".join(f"# ===== {f} =====\n" + open(os.path.join(idir, f), encoding="utf-8").read()
                                           for f in job.get("interp_files", []))}
    if job.get("setup") and isinstance(t, dict):
        t["setup"] = {"ids": job.get("setup_ids", []),
                      "source": open(os.path.join(SRC, job["setup"]), encoding="utf-8").read()}
    return t


def _one(job):
    v, lang = job["viz"], job["lang"]
    ms = str(job.get("max_steps", 800))
    st = ("--setup", os.path.join(SRC, job["setup"])) if job.get("setup") else ()
    if v == "env" and lang == "python":
        return tracer("pytrace.py", job, ("--max-steps", ms) + st)
    if v == "env" and lang == "scheme":
        t = tracer("schemetrace.py", job, ("--max-steps", ms))
        path = os.path.join(SRC, job["file"])
        g = sh(["guile", "--no-auto-compile", "-s", os.path.join(T, "cviz-repl.scm"), path], job.get("timeout", 15), os.path.dirname(path))
        t["reference_stdout"] = g.stdout
        if g.stdout.strip() != t.get("stdout", "").strip():
            t["approximate"] = True
            t["stdout"] = g.stdout
        return t
    if v == "lambda":
        return tracer("lambdatrace.py", job, ("--max-steps", ms))
    if v == "c":
        return c_trace(job)
    if v == "bison":
        return tracer("bisontrace.py", job, ("--input", job.get("input", "")))
    if v == "automaton":
        return tracer("automaton.py", job, ("--input", job.get("input", "")))
    if v == "cast":
        return tracer("shellcast.py", job)
    if v == "agent":
        return tracer("agentrec.py", job, st)
    return plain(job)


def main():
    # Python examples draw headlessly: matplotlib through cviz_mplbackend, and `import turtle` /
    # `import ezgraphics` load the stand-ins in tracers/pystubs (section 7, Figures).
    os.environ["MPLBACKEND"] = "module://cviz_mplbackend"
    os.environ["PYTHONPATH"] = os.pathsep.join([T, os.path.join(T, "pystubs")] + [x for x in [os.environ.get("PYTHONPATH")] if x])
    jobs = json.load(open("/work/jobs.json"))
    os.makedirs(OUT, exist_ok=True)
    for job in jobs:
        try:
            res = one(job)
        except subprocess.TimeoutExpired:
            res = {"error": "timeout", "steps": [], "stdout": ""}
        except Exception as e:
            res = {"error": f"{type(e).__name__}: {str(e)[:600]}", "steps": [], "stdout": ""}
        res.setdefault("version", 1)
        res["id"] = job["id"]
        with open(os.path.join(OUT, job["id"] + ".json"), "w") as fh:
            json.dump(res, fh)
        print(job["id"], "error" if res.get("error") else "ok", flush=True)


if __name__ == "__main__":
    main()
