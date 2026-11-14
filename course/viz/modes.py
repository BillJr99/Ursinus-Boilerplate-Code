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
without codeviz/ and without session labels gets nothing new, so its viz/ is unchanged.
"""
import glob
import gzip
import hashlib
import json
import os
import re

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
    """Source conveniences: `note` -> `description`, `line: N` kept (CodeTour) but also as lines."""
    t = json.loads(json.dumps(t))
    for s in t.get("steps", []) if isinstance(t.get("steps"), list) else []:
        if isinstance(s, dict) and "note" in s:
            s.setdefault("description", s.pop("note"))
            s.pop("note", None)
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
    nsteps = trace_steps(root, vid)
    for i, s in enumerate(t["steps"]):
        lines = parse_lines(s.get("lines")) + ([s["line"]] if s.get("line") else [])
        if s.get("stage"):
            sc = codes.get(s["stage"])
            if sc is None:
                errs.append(f"/steps[{i}]/stage: no labeled example {s['stage']!r}")
            else:
                nlines = len(sc.split("\n"))
        bad = [n for n in lines if n > nlines]
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
            elif nsteps is None:
                errs.append(f"/steps[{i}]: run step, but {vid} has no committed trace")
            elif s["trace_step"] >= max(nsteps, 1):
                errs.append(f"/steps[{i}]/trace_step: {s['trace_step']} but the trace has {nsteps} step(s)")
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
    return yaml.safe_load(text)


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
        s = re.sub(r"^\s*\$\s+", "", s) if not cur else s
        if s.endswith("\\"):
            cur += s[:-1] + " "
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

def publish(root, codes, session_blocks, index_entries):
    """Write valid tours to viz/tours/, keep recordings, and add "modes" to index entries.
    Returns (problems, tours_written). Writes nothing when the repo has no tours and no sessions."""
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
        text = json.dumps(t, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        dst = os.path.join(out_dir, fn)
        if not (os.path.exists(dst) and open(dst, encoding="utf-8").read() == text):
            with open(dst, "w", encoding="utf-8") as f:
                f.write(text)
        written.setdefault(vid, []).append(name or "")
    recorded = set()
    for vid, doc in sessions.items():
        rec = load_recording(root, vid)
        errs = check_session(doc, rec)
        if rec is None:
            errs = errs + ["not recorded yet (code-viz record " + vid + ")"]
        if rec is not None and not [e for e in errs if not e.startswith("stale")]:
            recorded.add(vid)
        problems += [f"session {vid}: {e}" for e in errs]
    for e in index_entries:
        modes = ["run"] if e.get("viz") != "session" else []
        if e["id"] in written:
            modes.append("explain")
            names = sorted(written[e["id"]])
            if names != [""]:
                e["tours"] = names
        if e["id"] in recorded:
            modes.append("simulate")
        e["modes"] = modes
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
