"""code-viz modes: Explain-mode tours and Simulate-mode sessions (sources, validation, build).

Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 21 (Modes and URL
arguments), 22 (Explain mode and the tour format) and 23 (Simulate mode, sessions and recording).

The viewer shows each example in up to three modes:
  run       the recorded trace (viz/traces/<id>.json.gz), what code-viz always did
  explain   a guided tour (viz/tours/<id>.json, from codeviz/tours/<id>.json)
  simulate  a recorded terminal session (viz/sessions/<id>.json.gz, from a scenario)

Sources are hand-written and live outside viz/ (CI owns viz/ and never edits anything else):
  codeviz/tours/<id>.json            the default tour of example <id>
  codeviz/tours/<id>--<name>.json    a named tour (URL &tour=<name>)
  codeviz/sessions/<id>.json|.yaml   a session scenario (commands, pinned images, network policy)
  a shell block labeled viz=session  its commands are the scenario (id from the label)

The formats are JSON Schemas in schemas/tour.schema.json and schemas/session.schema.json. This module
holds a small validator for the subset of JSON Schema those files use (type, const, enum, required,
properties, additionalProperties, items, minItems, minLength, minimum, pattern, $ref), so the schema
files are the single definition and no jsonschema package is needed. On top of the schema it checks
meaning against the course repo: the example exists, tour lines are inside the example's code, run
steps exist in its trace, stage ids are labeled blocks, and a recording's scenario still matches its
source (otherwise the session is reported stale and should be re-recorded with `code-viz record`).

Publishing (`code-viz build`, through publish()): valid tours are written to viz/tours/<file>.json
with `note` normalized to `description` and lines checked; recordings already in viz/sessions/ are
kept (CI never records); viz/index.json gets a "modes" list per example (["run", "explain",
"simulate"], only those with data) and "tours" (tour names) where there is more than one. A repo
without codeviz/ and without session labels gets nothing new, so its viz/ is unchanged. `code-viz
publish` runs the same step without running any example.

Recording (`code-viz record`, through record()): each run (the main line, then each branch) gets a
fresh Docker-in-Docker sandbox (DIND_IMAGE, pinned) on a network of its own, --internal unless the
scenario asks for the internet. Images are pulled on the host and loaded into the sandbox with docker
save | docker load; a scenario `shell` image is built on the host (setup commands baked in, with
network) and loaded the same way. The recorder container (runners/session, tracers/sessrec.py) runs
the commands under a pseudo-terminal and snapshots the sandbox after each one. Masker then replaces
what varies between runs with stable labels (ids, digests, times, made-up names, temp paths, the work
folder as ~), plain() keeps a plain-text copy of each output for comparison, and compare() lists the
differences for `record --check`. Afterwards the sandbox, its network and the images the recording
pulled are removed; staging folders move to ~/scratch/code-viz on the host.

Drafting (`code-viz tour draft`, through cmd_draft()): one prompt file per example with the code,
the deck text around it, the trace's line visits, the format, and STYLE, Bill's writing rules in short
form. No model is called here.
"""
import glob
import gzip
import hashlib
import json
import os
import re
import time

HERE = os.path.dirname(os.path.realpath(__file__))
SCHEMAS = os.path.join(HERE, "schemas")
TOUR_DIR = os.path.join("codeviz", "tours")
SESSION_DIR = os.path.join("codeviz", "sessions")
TOUR_FILE = re.compile(r"^(?P<id>[A-Za-z0-9][A-Za-z0-9._-]*?)(?:--(?P<name>[a-z0-9][a-z0-9-]*))?\.json$")


# ---- schema validation (the subset the two schema files use) -------------------------------------

def schema(name):
    with open(os.path.join(SCHEMAS, name + ".schema.json"), encoding="utf-8") as f:
        return json.load(f)


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "number": (int, float), "integer": int}


def _check(value, sch, root, path, errs):
    if "$ref" in sch:
        ref = sch["$ref"]
        assert ref.startswith("#/$defs/"), ref
        sch = root["$defs"][ref[len("#/$defs/"):]]
    t = sch.get("type")
    if t:
        py = _TYPES[t]
        ok = isinstance(value, py) and not (t in ("integer", "number") and isinstance(value, bool))
        if not ok:
            errs.append(f"{path or '/'}: expected {t}")
            return
    if "const" in sch and value != sch["const"]:
        errs.append(f"{path}: must be {sch['const']!r}")
    if "enum" in sch and value not in sch["enum"]:
        errs.append(f"{path}: must be one of {', '.join(map(str, sch['enum']))}")
    if isinstance(value, str):
        if len(value) < sch.get("minLength", 0):
            errs.append(f"{path}: empty")
        if "pattern" in sch and not re.search(sch["pattern"], value):
            errs.append(f"{path}: {value!r} does not match {sch['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "minimum" in sch and value < sch["minimum"]:
        errs.append(f"{path}: below {sch['minimum']}")
    if isinstance(value, list):
        if len(value) < sch.get("minItems", 0):
            errs.append(f"{path}: needs at least {sch['minItems']} item(s)")
        if "items" in sch:
            for i, v in enumerate(value):
                _check(v, sch["items"], root, f"{path}[{i}]", errs)
    if isinstance(value, dict):
        for k in sch.get("required", []):
            if k not in value:
                errs.append(f"{path}/{k}: required")
        props = sch.get("properties", {})
        extra = sch.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                _check(v, props[k], root, f"{path}/{k}", errs)
            elif extra is False:
                errs.append(f"{path}/{k}: unknown field")
            elif isinstance(extra, dict):
                _check(v, extra, root, f"{path}/{k}", errs)


def validate(value, name):
    """Schema errors (list of strings, empty when valid) for a tour ('tour') or session ('session')."""
    root = schema(name)
    errs = []
    _check(value, root, root, "", errs)
    return errs


# ---- tours -----------------------------------------------------------------------------------------

def parse_lines(spec):
    """'1-4,9' -> [1, 2, 3, 4, 9] (sorted, unique)."""
    out = set()
    for part in (spec or "").split(","):
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        out.update(range(min(lo, hi), max(lo, hi) + 1))
    return sorted(out)


def normalize_tour(t):
    """Source conveniences: `note` -> `description`; `line: N` (CodeTour) also sets lines "N" when a
    step has no lines. A non-object is returned as it is, so validate() reports it."""
    if not isinstance(t, dict):
        return t
    t = json.loads(json.dumps(t))
    for s in t.get("steps", []) if isinstance(t.get("steps"), list) else []:
        if not isinstance(s, dict):
            continue
        if "note" in s:
            s.setdefault("description", s.pop("note"))
            s.pop("note", None)
        if isinstance(s.get("line"), int) and not isinstance(s.get("line"), bool) and "lines" not in s:
            s["lines"] = str(s["line"])
    t.setdefault("reviewed", False)
    return t


def tour_files(root):
    """[(path, example id, tour name or None)] for every tour source, sorted."""
    out = []
    for p in sorted(glob.glob(os.path.join(root, TOUR_DIR, "*.json"))):
        m = TOUR_FILE.match(os.path.basename(p))
        if m:
            out.append((p, m.group("id"), m.group("name")))
    return out


def trace_steps(root, vid):
    """Number of steps in an example's committed Run-mode trace, or None when it has none."""
    for p in (os.path.join(root, "viz", "traces", vid + ".json.gz"), os.path.join(root, "viz", "traces", vid + ".json")):
        if os.path.exists(p):
            try:
                with (gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") else open(p, encoding="utf-8")) as f:
                    t = json.load(f)
            except (OSError, ValueError):
                return None
            st = t.get("steps")
            if not st and isinstance(t.get("orders"), dict):
                st = t["orders"].get("normal")
            return len(st or [])
    return None


def check_tour(t, vid, name, codes, root):
    """All problems with one normalized tour: schema errors, then meaning. `codes` maps labeled
    example id -> its code text (blocks and notebook cells)."""
    errs = validate(t, "tour")
    if errs:
        return errs
    if t["example"] != vid:
        errs.append(f"/example: {t['example']!r} but the file is named for {vid!r}")
    if (t.get("name") or None) != (name or None):
        errs.append(f"/name: {t.get('name')!r} but the file name says {name!r}")
    code = codes.get(vid)
    if code is None:
        errs.append(f"{vid}: no labeled example with this id")
        return errs
    nlines = len(code.split("\n"))
    cur = vid                          # the block shown: the example, or the latest stage
    nsteps = trace_steps(root, vid)
    for i, s in enumerate(t["steps"]):
        lines = parse_lines(s.get("lines")) + ([s["line"]] if s.get("line") else [])
        if s.get("stage"):
            sc = codes.get(s["stage"])
            if sc is None:
                errs.append(f"/steps[{i}]/stage: no labeled example {s['stage']!r}")
            else:
                cur = s["stage"]
                nlines = len(sc.split("\n"))
                nsteps = trace_steps(root, cur)   # run steps after a stage use that stage's trace
        bad = [n for n in lines if n < 1 or n > nlines]
        if bad:
            errs.append(f"/steps[{i}]: line {bad[0]} is past the code's {nlines} line(s)")
        k = s["kind"]
        if k in ("reveal", "focus") and not lines:
            errs.append(f"/steps[{i}]: {k} needs lines")
        if k == "predict" and not s.get("question"):
            errs.append(f"/steps[{i}]: predict needs a question")
        if k == "run":
            if "trace_step" not in s:
                errs.append(f"/steps[{i}]: run needs trace_step")
            elif not nsteps:
                errs.append(f"/steps[{i}]: run step, but {cur} has no committed trace with steps")
            elif s["trace_step"] >= nsteps:
                errs.append(f"/steps[{i}]/trace_step: {s['trace_step']} but the trace of {cur} has {nsteps} step(s)")
        if k == "stage" and not s.get("stage"):
            errs.append(f"/steps[{i}]: stage needs a stage id")
        if not (s.get("description") or s.get("question") or s.get("title")):
            errs.append(f"/steps[{i}]: says nothing (add a description, question or title)")
    return errs


def load_tours(root, codes):
    """{(id, name): (tour, [problems])} for every tour source."""
    out = {}
    for p, vid, name in tour_files(root):
        try:
            with open(p, encoding="utf-8") as f:
                t = normalize_tour(json.load(f))
        except ValueError as e:
            out[(vid, name)] = (None, [f"not JSON: {e}"])
            continue
        out[(vid, name)] = (t, check_tour(t, vid, name, codes, root))
    return out


# ---- sessions --------------------------------------------------------------------------------------

def _yaml_load(text):
    try:
        import yaml  # PyYAML, present on the runners; JSON scenarios need nothing
    except ImportError as e:
        raise ValueError("a .yaml scenario needs PyYAML (pip install pyyaml); use .json instead") from e
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"not valid YAML: {e}") from e


def scenario_sha(scn):
    return hashlib.sha256(json.dumps(scn, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def block_commands(code):
    """A viz=session shell block's commands: non-blank, non-comment lines, a leading '$ ' dropped,
    and lines ending in a backslash joined to the next."""
    cmds, cur = [], ""
    for line in code.split("\n"):
        s = line.rstrip()
        if not cur and (not s.strip() or s.strip().startswith("#")):
            continue
        s = re.sub(r"^\s*\$\s+", "", s) if not cur else s.strip()
        if s.endswith("\\"):
            cur += s[:-1].rstrip() + " "
            continue
        cmds.append((cur + s).strip())
        cur = ""
    if cur.strip():
        cmds.append(cur.strip())
    return cmds


def session_sources(root, session_blocks):
    """{id: scenario document} from codeviz/sessions/ files and viz=session labeled blocks.
    `session_blocks` is [(id, title, page, code, label)] from code-viz."""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, SESSION_DIR, "*"))):
        base, ext = os.path.splitext(os.path.basename(p))
        if ext not in (".json", ".yaml", ".yml"):
            continue
        with open(p, encoding="utf-8") as f:
            text = f.read()
        try:
            doc = json.loads(text) if ext == ".json" else _yaml_load(text)
        except ValueError as e:
            doc = {"_error": str(e)}
        if isinstance(doc, dict):
            doc.setdefault("id", base)
        else:
            doc = {"_error": "a scenario must be a JSON or YAML object", "id": base}
        out[base] = doc
    for vid, title, page, code, lab in session_blocks:
        if vid in out:
            continue
        scn = {"commands": block_commands(code)}
        for k in ("network", "timeout"):
            if lab.get(k):
                scn[k] = int(lab[k]) if k == "timeout" else lab[k]
        if lab.get("images"):
            scn["images"] = [x for x in lab["images"].split(",") if x]
        out[vid] = {"version": 1, "id": vid, "title": title or vid, "page": page, "scenario": scn}
    return out


def recording_path(root, vid):
    return os.path.join(root, "viz", "sessions", vid + ".json.gz")


def load_recording(root, vid):
    p = recording_path(root, vid)
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def check_session(doc, recording=None):
    """Problems with a session source (and its recording, when given). A recording whose scenario no
    longer matches the source is reported as stale."""
    if not isinstance(doc, dict):
        return ["a scenario must be an object"]
    if "_error" in doc:
        return [doc["_error"]]
    errs = validate(doc, "session")
    if errs:
        return errs
    if recording is not None:
        rerrs = validate(recording, "session")
        errs += [f"recording {e}" for e in rerrs]
        if not rerrs:
            if not recording.get("steps"):
                errs.append("recording has no steps")
            want = scenario_sha(doc["scenario"])
            got = (recording.get("recorded") or {}).get("scenario_sha")
            if got != want:
                errs.append("stale: the scenario changed since it was recorded (code-viz record " + doc["id"] + ")")
    return errs


# ---- publishing into viz/ (code-viz build) -----------------------------------------------------------

def publish(root, codes, session_blocks, index_entries, meta=None):
    """Write valid tours to viz/tours/, keep recordings, and add "modes" to index entries.
    Returns (problems, tours_written). Writes nothing when the repo has no tours and no sessions.

    A published tour also carries the code it explains (`code`, `lang`) and the code of each stage
    (`stages: {id: {code, lang}}`), so Explain mode works without a Run trace: display-only examples
    (viz=show) have none. `meta` maps example id -> {viz, lang, page, line, page_url}."""
    meta = meta or {}
    tours = load_tours(root, codes)
    sessions = session_sources(root, session_blocks)
    problems = []
    if not tours and not sessions and not os.path.isdir(os.path.join(root, "viz", "tours")):
        return problems, 0
    out_dir = os.path.join(root, "viz", "tours")
    written = {}
    for (vid, name), (t, errs) in sorted(tours.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        if errs:
            problems += [f"tour {vid}{'--' + name if name else ''}: {e}" for e in errs]
            continue
        os.makedirs(out_dir, exist_ok=True)
        fn = f"{vid}--{name}.json" if name else f"{vid}.json"
        t = dict(t, code=codes.get(vid, ""), lang=(meta.get(vid) or {}).get("lang", ""))
        stages = {s["stage"] for s in t["steps"] if s.get("stage")}
        if stages:
            t["stages"] = {sid: {"code": codes.get(sid, ""), "lang": (meta.get(sid) or {}).get("lang", "")} for sid in sorted(stages)}
        text = json.dumps(t, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        dst = os.path.join(out_dir, fn)
        if not (os.path.exists(dst) and open(dst, encoding="utf-8").read() == text):
            with open(dst, "w", encoding="utf-8") as f:
                f.write(text)
        written.setdefault(vid, []).append(name or "")
    # Withdraw published tours whose source was removed or no longer passes (viz/ is generated, and
    # git keeps the history, so this is the same as `git rm` of a stale build output).
    keep = {f"{v}--{n}.json" if n else f"{v}.json" for v, ns in written.items() for n in ns}
    for p in glob.glob(os.path.join(out_dir, "*.json")):
        if os.path.basename(p) not in keep:
            os.unlink(p)
    recorded = set()
    for vid, doc in sessions.items():
        rec = load_recording(root, vid)
        errs = check_session(doc, rec)
        if rec is None:
            errs = errs + ["not recorded yet (code-viz record " + vid + ")"]
        if rec is not None and not [e for e in errs if not e.startswith("stale")]:
            recorded.add(vid)
        problems += [f"session {vid}: {e}" for e in errs]
    # Display-only examples (viz=show) have no trace and no build job: give the ones with a tour an
    # index entry of their own, Explain only.
    have = {e["id"] for e in index_entries}
    for vid in sorted(written):
        m = meta.get(vid) or {}
        if vid not in have and m.get("viz") == "show":
            index_entries.append({"id": vid, "viz": "show", "lang": m.get("lang", ""), "page": m.get("page", ""),
                                  "line": m.get("line", 0), "page_url": m.get("page_url", ""), "error": None, "steps": 0})
    for e in index_entries:
        e.pop("tours", None)
        modes = ["run"] if e.get("viz") not in ("session", "show") else []
        if e["id"] in written:
            modes.append("explain")
            names = sorted(written[e["id"]])
            if names != [""]:
                e["tours"] = names
        if e["id"] in recorded:
            modes.append("simulate")
        e["modes"] = modes
    # A display-only or session entry whose tour or recording went away has nothing left to show.
    index_entries[:] = [e for e in index_entries if e["modes"] or e.get("viz") not in ("show", "session")]
    have = {e["id"] for e in index_entries}
    for vid in sorted(recorded - have):
        doc = sessions[vid]
        index_entries.append({"id": vid, "viz": "session", "lang": "shell", "page": doc.get("page", ""),
                              "line": 0, "page_url": "", "error": None, "steps": 0, "modes": ["simulate"]})
    return problems, sum(len(v) for v in written.values())


# ---- drafting prompts (code-viz tour draft) --------------------------------------------------------

# Bill's writing rules, condensed for the model that drafts a tour (from his bill-writing-style
# teaching register, writing-for-clarity, avoid-ai-writing and Elements of Style). code-viz itself
# calls no model; a person or a helper hands this prompt to one and saves the reply.
STYLE = """Writing rules (Bill Mongan's teaching voice):
- Concrete first, principle after: point at the exact line or value, then say what it shows.
- Guide, don't lecture: observe, predict, explain. A predict step asks a real question whose answer
  the code settles; give the answer the class is steered toward.
- Talk to students as "you", or "let's" and "we"; plain, direct sentences; active voice; positive
  form ("keeps", not "does not lose").
- Short: one to three sentences per step. Every sentence says something specific about this code.
- Use the deck's own words and names for things; never invent facts, numbers or behavior. If you are
  not sure what a line does, leave it out rather than guess.
- No filler or hype ("delve", "crucial", "powerful", "seamless", "it's important to note", "in
  conclusion"), no rhetorical questions that are not real predict steps, no summaries of what you
  just said.
- Never use em dashes. Use a comma, a colon, parentheses or a spaced hyphen ( - ).
- No timings, no grading language, no answers to the deck's own graded exercises.
"""


def _context(lines, start, end, before=40, after=20):
    """The deck text around a block: back to the nearest heading (at most `before` lines) and the
    prose after it up to the next code fence (at most `after` lines)."""
    a = start - 1
    while a > 0 and start - a < before and not lines[a].lstrip().startswith("#"):
        a -= 1
    b = end + 1
    while b < len(lines) and b - end < after and not lines[b].lstrip().startswith(("```", "~~~")):
        b += 1
    return "\n".join(lines[max(a, 0):start]).strip(), "\n".join(lines[end + 1:b]).strip()


def _trace_summary(root, vid, limit=40):
    """First visits of each code line in the trace as (step, line) pairs, plus the output."""
    for p in (os.path.join(root, "viz", "traces", vid + ".json.gz"),):
        if not os.path.exists(p):
            return None
        with gzip.open(p, "rt", encoding="utf-8") as f:
            t = json.load(f)
        seen, pairs = set(), []
        for i, s in enumerate(t.get("steps") or []):
            ln = s.get("line") if isinstance(s, dict) else None
            if isinstance(ln, int) and ln not in seen:
                seen.add(ln)
                pairs.append((i, ln))
            if len(pairs) >= limit:
                break
        return {"kind": t.get("kind"), "steps": len(t.get("steps") or []), "first_visits": pairs,
                "stdout": (t.get("stdout") or "")[:1500]}
    return None


def draft_prompt(root, b, info):
    """The prompt text for one labeled block `b` (a code-viz block dict)."""
    vid = b["label"]["id"]
    page = b["page"]
    code = b["code"]
    numbered = "\n".join(f"{i + 1:3d}  {l}" for i, l in enumerate(code.split("\n")))
    before = after = ""
    if page.endswith(".md") and os.path.exists(os.path.join(root, page)):
        lines = open(os.path.join(root, page), encoding="utf-8", errors="replace").read().split("\n")
        before, after = _context(lines, b.get("start", 0), b.get("end", b.get("start", 0)))
    tr = _trace_summary(root, vid)
    trace = "No Run-mode trace is committed for this example, so do not use run steps."
    if tr and tr["first_visits"]:
        trace = (f"Run-mode trace: kind {tr['kind']}, {tr['steps']} steps. First visit of each line as "
                 f"(trace_step, code line): {tr['first_visits']}. Program output (start):\n{tr['stdout']}")
    elif tr:
        trace = f"Run-mode trace: kind {tr['kind']}, {tr['steps']} steps (no line numbers). Output (start):\n{tr['stdout']}"
    return f"""You are drafting a code-viz Explain-mode tour: a guided walkthrough a teacher steps through in
class to read and understand one code example. Reply with ONE JSON object and nothing else (no Markdown
fence, no commentary). It must follow this format (version 1):

{{"version": 1, "example": "{vid}", "title": "<short title>", "description": "<one or two sentences>",
 "reviewed": false, "source": "draft: <your model name>",
 "steps": [ ...4 to 10 steps... ]}}

Each step is one of:
  {{"kind": "reveal", "lines": "1-3", "description": "..."}}     show these lines (added to what is shown)
  {{"kind": "focus", "lines": "5,7-8", "description": "..."}}    highlight these lines, dim the rest
  {{"kind": "predict", "question": "...", "answer": "...", "lines": "9"}}   ask before revealing
  {{"kind": "run", "trace_step": 12, "lines": "9", "description": "..."}}   show the running state
`lines` are 1-based line numbers of the code below ("1-4,9"); never past line {len(code.split(chr(10)))}.
Use `run` only with a trace_step from the list of first visits below. Start with reveal steps that
build the code up in reading order, include at least one predict step, and end with the result the
example demonstrates.

{STYLE}
Course: {info.get('course', '')}. Page: {page}. Example id: {vid}.

Deck text before the example:
<<<
{before}
>>>

The code (line numbers added):
<<<
{numbered}
>>>

Deck text after the example:
<<<
{after}
>>>

{trace}
"""


def cmd_draft(root, a, codes, blocks, info):
    """code-viz tour draft [ids] [--all] [--out DIR]: write one prompt file per example."""
    have = {vid for _, vid, _ in tour_files(root)}
    by_id = {b["label"]["id"]: b for b in blocks if b.get("label") and b["label"].get("id")}
    ids = list(a.ids) or ([v for v in sorted(by_id) if v not in have and by_id[v]["label"].get("viz") != "session"]
                          if a.all else [])
    if not ids:
        print("name example ids, or --all for every labeled example without a tour")
        return 64
    out = a.out or os.path.join(root, "codeviz", "drafts")
    os.makedirs(out, exist_ok=True)
    n = 0
    for vid in ids:
        if vid not in by_id:
            print(f"{vid}: no labeled example with this id")
            continue
        with open(os.path.join(out, vid + ".prompt.txt"), "w", encoding="utf-8") as f:
            f.write(draft_prompt(root, by_id[vid], info))
        n += 1
    print(f"wrote {n} prompt(s) to {out}; save each reply as codeviz/tours/<id>.json, then run code-viz tour check")
    return 0


# ---- recording (code-viz record) -------------------------------------------------------------------

DIND_IMAGE = "docker:27.3.1-dind"   # the throwaway Docker-in-Docker sandbox, pinned
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>]")


def plain(raw):
    """The terminal's output as plain text: control codes removed, \\r\\n made \\n, and a line rewritten
    with \\r (progress bars) kept as its last version."""
    t = ANSI.sub("", raw).replace("\r\n", "\n")
    t = "\n".join(seg.split("\r")[-1] for seg in t.split("\n"))
    t = strip_eof_echo(t)
    return "".join(ch for ch in t if ch in "\n\t" or ord(ch) >= 32)


def strip_eof_echo(t):
    """The terminal's echo of the end-of-input character the recorder types (^D, or ^@ once a program
    put the terminal in raw mode), at the start of the output or of a line; not part of the session."""
    return re.sub(r"(?m)^(?:\^[@D])+", "", t)


class Masker:
    """Replaces what changes from one recording to the next with stable labels, the same label for
    the same value everywhere in a recording (section 23)."""
    BUILTIN = [
        (r"sha256:[0-9a-f]{12,64}", "sha256:<digest-{n}>"),
        (r"\b[0-9a-f]{64}\b", "<id-{n}>"),
        (r"\b[0-9a-f]{12}\b", "<id-{n}>"),
        (r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?(?: [A-Z]{2,5})?\b", "<time>"),
        (r"\b(?:About an? \w+|Less than a second|an? \w+|\d+ \w+?s?) ago\b", "<time> ago"),
        (r"\bUp (?:About an? \w+|Less than a second|\d+ \w+)", "Up <time>"),
        (r"/tmp/tmp[\w.-]+", "/tmp/<tmp-{n}>"),
    ]

    def __init__(self, work, names, extra):
        self.rules = [(re.compile(r"(?<![\w/.-])" + re.escape(work.rstrip("/")) + r"(?=/|\b|$)"), "~")]
        for n in sorted(names, key=len, reverse=True):     # Docker's random container names
            self.rules.append((re.compile(r"\b" + re.escape(n) + r"\b"), "<name-{n}>"))
        for pat, lab in self.BUILTIN + [(m["pattern"], m["label"]) for m in extra or []]:
            self.rules.append((re.compile(pat), lab))
        self.seen = {}

    def _sub(self, lab):
        def f(m):
            v = m.group(0)
            if "{n}" not in lab:
                return lab
            key = (lab, v[:12] if lab.startswith("<id") else v)   # a short id is its long id's first 12
            if key not in self.seen:
                self.seen[key] = sum(1 for k in self.seen if k[0] == lab) + 1
            return lab.replace("{n}", str(self.seen[key]))
        return f

    def __call__(self, x):
        if isinstance(x, str):
            for rx, lab in self.rules:
                x = rx.sub(self._sub(lab), x)
            return x
        if isinstance(x, list):
            return [self(v) for v in x]
        if isinstance(x, dict):
            return {k: self(v) for k, v in x.items()}
        return x


def _random_names(runs, commands):
    """Container names Docker made up (adjective_surname), not ones the commands chose."""
    text = " ".join(commands)
    out = set()
    for steps in runs:
        for st in steps:
            for c in (st.get("state") or {}).get("containers", []):
                n = c.get("name", "")
                if re.fullmatch(r"[a-z]+_[a-z]+", n) and n not in text:
                    out.add(n)
    return out


def record_once(docker, commands, scn, tag, stage_dir, shell_tag, tracers, session_tag, host_shell, ensure_shell=None):
    """One fresh sandbox, the commands run in it, the raw steps back. `host_shell(cmd)` runs a shell
    command on the Docker host (for docker save | docker load)."""
    import shutil
    import tempfile
    net = scn.get("network", "isolated")
    work = scn.get("workdir", "/work")
    local = tempfile.mkdtemp(prefix="code-viz-rec-")
    os.makedirs(os.path.join(local, "work"))
    for rel, content in (scn.get("files") or {}).items():
        p = os.path.join(local, "work", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
    json.dump(dict(scn, commands=commands, workdir=work), open(os.path.join(local, "scenario.json"), "w"))
    shutil.copy(os.path.join(tracers, "sessrec.py"), local)
    rdir = docker.remote_dir(local, f"session-{tag}")
    inet, dind = f"{tag}-int", f"{tag}-dind"
    # Another recording on this host may have removed an image it pulled after this one checked:
    # pull it again (and remove it at cleanup, as this run then pulled it).
    for img in [DIND_IMAGE] + list(scn.get("images") or []):
        if docker.sh(["image", "inspect", img], check=False).returncode != 0:
            docker.sh(["pull", "-q", img], timeout=1800)
            docker.mine.add(img)
    try:
        # The sandbox and the recorder share one network of their own. It is --internal (no way out)
        # unless the scenario asks for the internet; the host's own networks are never touched.
        docker.sh(["network", "create", *([] if net == "internet" else ["--internal"]), "--label", "code-viz=1", inet])
        dnet = ["--network", inet]
        docker.sh(["run", "-d", "--rm", "--privileged", "--name", dind, "--label", "code-viz=1", *dnet,
                   "--network-alias", "sandbox", "-e", "DOCKER_TLS_CERTDIR=", "-v", f"{rdir}/work:{work}", DIND_IMAGE,
                   "--host=tcp://0.0.0.0:2375", "--host=unix:///var/run/docker.sock", "--tls=false"]
                  + (["--bridge=none"] if net == "none" else []))
        for _ in range(60):
            if docker.sh(["exec", dind, "docker", "info"], check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("the Docker-in-Docker sandbox did not start")
        # Images come from the host (pulled there, where downloads work) into the sandbox, so the
        # sandbox itself needs no internet unless the scenario asks for it.
        for img in list(scn.get("images") or []) + ([shell_tag] if shell_tag else []):
            # Another recording on this host (two slots at once) may have removed a code-viz image
            # this one built: build it again before loading it (section 15).
            if img == shell_tag and ensure_shell:
                ensure_shell()
            r = host_shell(f"{docker.prefix()} save {shlex_quote(img)} | {docker.prefix()} exec -i {dind} docker load")  # noqa: E501
            if r.returncode != 0:
                raise RuntimeError(f"could not load {img} into the sandbox: {r.stderr[-300:]}")
        shell_args = []
        if shell_tag:
            snet = ["--network", "none"] if net == "none" else []
            docker.sh(["exec", dind, "docker", "run", "-d", "--name", "cviz-shell", *snet, "-e", f"HOME={work}", "-w", work,
                       "-e", "DOCKER_HOST=unix:///var/run/docker.sock", "-v", "/var/run/docker.sock:/var/run/docker.sock",
                       "-v", f"{work}:{work}", shell_tag, "sleep", "infinity"])
            shell_args = ["--shell", "cviz-shell", "--shell-image", shell_tag.split(":")[0]]
        rnet = ["--network", inet]
        total = 120 + len(commands) * int(scn.get("timeout", 120))
        for attempt in range(3):
            r = docker.sh(["run", "--rm", "--name", f"{tag}-rec" + (f"-{attempt}" if attempt else ""), "--label", "code-viz=1", *rnet,
                           "-e", "DOCKER_HOST=tcp://sandbox:2375", "-v", f"{rdir}:/rec", "-v", f"{rdir}/work:{work}", session_tag,
                           "timeout", str(total), "python3", "/rec/sessrec.py", "/rec/scenario.json", "/rec/out.json", *shell_args],
                          timeout=total + 120, check=False)
            # Another recording's cleanup may remove the shared recorder image between our build and
            # this run (two slots at once), as with runner images: build it again and rerun.
            if r.returncode == 0 or "Unable to find image" not in (r.stderr or ""):
                break
            print("  recorder image was removed by another run; building it again", flush=True)
            session_tag = docker.image("session")
        docker.fetch_dir(rdir, local)
        p = os.path.join(local, "out.json")
        if not os.path.exists(p):
            raise RuntimeError("the recorder wrote nothing: " + (r.stderr or "")[-400:])
        return json.load(open(p))
    finally:
        docker.sh(["rm", "-f", dind], check=False)          # --rm also drops its anonymous volume
        docker.sh(["network", "rm", inet], check=False)
        docker.retire(rdir)
        retire_local(local)


def retire_local(path):
    """Move a local temporary folder to ~/scratch/code-viz (never deleted; Bill's rule)."""
    import shutil
    dst = os.path.join(os.path.expanduser("~"), "scratch", "code-viz")
    try:
        os.makedirs(dst, exist_ok=True)
        shutil.move(path, os.path.join(dst, os.path.basename(path)))
    except OSError:
        pass


def shlex_quote(s):
    import shlex
    return shlex.quote(s)


def record(root, vid, doc, docker, tracers, session_tag, host_shell, today, host_name):
    """Record a session (main line and each branch, each from a fresh sandbox), mask it, and return
    the recording document (not yet written)."""
    import hashlib as _h
    scn = doc["scenario"]
    tag = f"cviz-rec-{re.sub(r'[^a-z0-9-]', '-', vid.lower())[:30]}-{os.getpid()}"
    shell_tag = None
    pulled = []
    for img in [DIND_IMAGE] + list(scn.get("images") or []):
        if docker.sh(["image", "inspect", img], check=False).returncode != 0:
            docker.sh(["pull", "-q", img], timeout=1800)
            pulled.append(img)
    sh = scn.get("shell")
    try:
        if sh:
            base = sh["image"]
            if docker.sh(["image", "inspect", base], check=False).returncode != 0:
                docker.sh(["pull", "-q", base], timeout=1800)
                pulled.append(base)
            shell_tag = f"code-viz-shell:{_h.sha256(json.dumps(sh, sort_keys=True).encode()).hexdigest()[:12]}"
        def ensure_shell():
            """Build the scenario's shell image when it is missing: the first time, or after another
            recording on this host (two slots at once) removed it."""
            if not shell_tag or docker.sh(["image", "inspect", shell_tag], check=False).returncode == 0:
                return
            if docker.sh(["image", "inspect", base], check=False).returncode != 0:
                docker.sh(["pull", "-q", base], timeout=1800)
            import tempfile
            ctx = tempfile.mkdtemp(prefix="code-viz-shell-")
            lines = [f"FROM {base}"] + [f"RUN {c}" for c in sh.get("setup") or []]
            open(os.path.join(ctx, "Dockerfile"), "w").write("\n".join(lines) + "\n")
            rctx = docker.remote_dir(ctx, "shell-image")   # moves to ~/scratch at cleanup
            docker.sh(["build", "-q", "--network", "host", "--label", "code-viz=1", "-t", shell_tag, rctx], timeout=3600)
            docker.mine.add(shell_tag)
            retire_local(ctx)

        ensure_shell()
        runs = [record_once(docker, scn["commands"], scn, tag, None, shell_tag, tracers, session_tag, host_shell, ensure_shell)]
        branches = []
        for b in doc.get("branches") or []:
            cmds = scn["commands"][:b["after"]] + b["commands"]
            got = record_once(docker, cmds, scn, tag + "-" + b["name"][:12], None, shell_tag, tracers, session_tag, host_shell, ensure_shell)
            branches.append((b, got))
            runs.append(got)
    finally:
        for img in pulled:                       # images this recording pulled; ones already there stay
            docker.sh(["rmi", img], check=False)
    names = _random_names([r["steps"] for r in runs], scn["commands"] + [c for b in doc.get("branches") or [] for c in b["commands"]])

    def finish(steps):
        # One masker per run: a branch runs from the start in a fresh sandbox, so its shared prefix
        # numbers ids and names the same way the main line does.
        mask = Masker(scn.get("workdir", "/work"), names, doc.get("masking"))
        out = []
        for st in steps:
            cast = coalesce(st.get("cast") or [[0, st.get("raw", "")]])
            cast = [[t, mask(x)] for t, x in cast]
            if cast:                                  # the echo of the end-of-input character
                cast[0][1] = strip_eof_echo(cast[0][1])
            cast = [c for c in cast if c[1]]
            raw = "".join(x for _, x in cast)
            s = {"cmd": st["cmd"], "output": plain(raw), "exit": st["exit"], "duration": st["duration"],
                 "cast": cast, "state": mask(st["state"])}
            out.append(s)
        return out

    rec = {k: v for k, v in doc.items() if k not in ("steps", "recorded", "branches")}
    rec["steps"] = finish(runs[0]["steps"])
    if branches:
        rec["branches"] = [dict(b, steps=finish(got["steps"])[b["after"]:]) for b, got in branches]
    rec["recorded"] = {"at": today, "host": host_name, "sandbox": DIND_IMAGE, "docker": runs[0].get("docker", ""),
                       "scenario_sha": scenario_sha(scn), "cols": (runs[0].get("term") or {}).get("cols", 100),
                       "rows": (runs[0].get("term") or {}).get("rows", 30)}
    return rec


def coalesce(cast, gap=0.05):
    """Join output chunks less than `gap` seconds apart, so an id or a word split across two reads is
    masked as one, and the recording stays small. Pacing coarser than 50 ms is kept."""
    out = []
    for t, x in cast:
        if out and t - out[-1][0] < gap:
            out[-1][1] += x
        else:
            out.append([t, x])
    return out


def compare(old, new):
    """Differences between two recordings, for record --check (plain output, exit status, state)."""
    diffs = []
    def line(i, a, b, label):
        for k in ("output", "exit"):
            if a.get(k) != b.get(k):
                diffs.append(f"{label} step {i} ({a.get('cmd', '')[:50]}): {k} changed")
        if json.dumps(a.get("state"), sort_keys=True) != json.dumps(b.get("state"), sort_keys=True):
            diffs.append(f"{label} step {i}: Docker state changed")
    os_, ns = old.get("steps") or [], new.get("steps") or []
    if len(os_) != len(ns):
        diffs.append(f"main line: {len(os_)} step(s) recorded before, {len(ns)} now")
    for i, (a, b) in enumerate(zip(os_, ns)):
        line(i, a, b, "main line")
    ob = {b["name"]: b for b in old.get("branches") or []}
    nb = {b["name"]: b for b in new.get("branches") or []}
    for name in sorted(set(ob) | set(nb)):
        if name not in ob or name not in nb:
            diffs.append(f"branch {name}: {'added' if name in nb else 'removed'}")
            continue
        xs, ys = ob[name].get("steps") or [], nb[name].get("steps") or []
        if len(xs) != len(ys):
            diffs.append(f"branch {name}: {len(xs)} step(s) recorded before, {len(ys)} now")
        for i, (x, y) in enumerate(zip(xs, ys)):
            line(i, x, y, f"branch {name}")
    return diffs
