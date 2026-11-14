"""code-viz languages module (langs.py): SQL, Java, JavaScript, MIPS assembly and VHDL, plus the C
adjustments for programs that fork or start threads. Imported by `code-viz` (it sits beside it).

Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 4 Labels and ids,
7 Kinds of visualization (sql, java, js, mips, wave) and 2 Architecture (Runners).

What lives here, so that code-viz itself only calls a few hooks:
  ALIASES          extra fence names: sqlite -> sql, javascript/node/mjs -> js, vhd -> vhdl, s/spim -> mips
  EXT              file extensions for the new languages (the driver renames Java files itself)
  RUNNER_OF        (viz, lang) -> runner for the new step views: sql (python runner, sqlite3), mips
                   (mips runner, with SPIM as a reference), wave (vhdl runner, GHDL), java (java runner)
  PLAIN_RUNNER     lang -> runner for output-only examples: java, js (node runner), vhdl, mips
  SETUP_LANGS      languages whose labels may carry setup= besides Python: sql (earlier blocks that
                   create the tables this one uses) and vhdl (earlier blocks that define the entities a
                   testbench instantiates)
  BROWSER_TRACERS  tracers the static site copies into viz/tracers for Pyodide (student mode Edit and
                   run): sqltrace.py and mipstrace.py
  suggest(b, base) the label code-viz suggests for a block (base is code-viz's own suggestion)
  setup_deps(b, earlier)  setup= ids for an SQL or VHDL block (None when it cannot run: a table or
                   entity defined nowhere above it)
  manifest(root, course, slug)  manifest entries for files under files/: MIPS programs (.s, .asm)
                   and VHDL designs (folders or .zip files holding .vhd files with a testbench)
  script_blocks(lines, page, ...)  code embedded as <script type="syntaxhighlighter" class="brush: X">
                   <![CDATA[ ... ]]></script>, the form the activity layout's models (YAML front matter)
                   and some older pages use; returned in the same shape as fenced blocks, with
                   "html": True so labels and links are written at the script's indentation and the
                   link is an HTML <a> (models are raw HTML, not Markdown)
  html_link(info, vid)  that link

Suggestion rules (what `catalog` and `label` offer; `label --try` then keeps only what runs):
  sql   any complete SQLite statement block -> viz=sql (tables before and after every statement)
  java  a block with output (System.out) that is a whole program, a set of methods, or statements;
        not one that reads System.in (no input known) or uses a GUI -> viz=java (frames and objects,
        stepped with the Java debugger; falls back to output only where stepping fails)
  js    a block with console.log and no browser or network objects (document, window, fetch, $,
        require of a package) -> viz=plain, lang=js
  c     code-viz's own C rule (plus blocks fenced without a language that have #include and
        int main), but a program that calls fork, exec*, pthread_create, signal or
        reads input runs output only (viz=plain), since gdb stepping across processes and threads
        is unreliable
  mips  a block (fenced as mips, asm, s or with no language) with MIPS registers ($t0, $sp, ...)
        and a main label or syscall -> viz=mips (registers and memory, instruction by instruction)
  vhdl  a block that declares an entity and an architecture, or a testbench (an entity with no
        ports) -> viz=wave (the testbench's signals over simulation time, from GHDL's VCD output)
"""
import os
import re
import sqlite3
import textwrap
import zipfile

ALIASES = {"sqlite": "sql", "sqlite3": "sql", "javascript": "js", "node": "js", "nodejs": "js", "mjs": "js",
           "vhd": "vhdl", "s": "mips", "spim": "mips"}
EXT = {"sql": "sql", "java": "java", "js": "js", "vhdl": "vhd", "mips": "s"}
RUNNER_OF = {("sql", "sql"): "python", ("mips", "mips"): "mips", ("wave", "vhdl"): "vhdl", ("java", "java"): "java"}
PLAIN_RUNNER = {"java": "java", "js": "node", "vhdl": "vhdl", "mips": "mips", "sql": "python"}
SETUP_LANGS = ("sql", "vhdl")
BROWSER_TRACERS = ("sqltrace.py", "mipstrace.py")
FILE_VIZ = {"sql": "sql", "java": "java", "js": "plain", "s": "mips", "asm": "mips", "vhd": "wave", "vhdl": "wave"}   # code-viz run <file>
FILE_LANG = {"sql": "sql", "java": "java", "js": "js", "s": "mips", "asm": "mips", "vhd": "vhdl", "vhdl": "vhdl"}

MIPS_REG = re.compile(r"\$(zero|at|v[01]|a[0-3]|t[0-9]|s[0-7]|k[01]|gp|sp|fp|ra|[0-9]{1,2})\b")
JS_BROWSER = re.compile(r"\b(document|window|localStorage|navigator|alert|prompt|fetch|XMLHttpRequest)\b|\$\(|require\(\s*['\"](?!(fs|path|os|util|assert|events)['\"])")
C_MULTI = re.compile(r"\b(fork|execv|execvp|execl|execlp|execve|pthread_create|signal|sigaction|scanf|fgets|getchar|read)\s*\(")
SQL_NAMES = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE(?:\s+IF\s+(?:NOT\s+)?EXISTS)?|REFERENCES)\s+[\"`\[]?(\w+)", re.I)
SQL_CREATES = re.compile(r"\bCREATE\s+(?:TEMP\w*\s+)?(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?(\w+)", re.I)
VHDL_ENTITY = re.compile(r"\bentity\s+(\w+)\s+is\b", re.I)
VHDL_USES = re.compile(r"\b(?:entity\s+work\.(\w+)|component\s+(\w+))", re.I)


SCRIPT_OPEN = re.compile(r'^(\s*)<script\s+type="syntaxhighlighter"\s+class="brush:\s*([A-Za-z0-9+#]+)[^"]*"\s*>\s*<!\[CDATA\[(.*)$')
BRUSH = {"python": "python", "py": "python", "cpp": "cpp", "c": "c", "java": "java", "js": "js", "jscript": "js",
         "javascript": "js", "sql": "sql", "mips": "mips", "asm": "mips", "bash": "shell", "shell": "shell", "vhdl": "vhdl",
         "scheme": "scheme", "prolog": "prolog"}
LOOKS_JAVA = re.compile(r"System\.out\.|\bpublic\s+(static\s+)?(void|int|double|String|boolean|class)\b|String\[\]")


def script_blocks(lines, page, LABEL, parse_label, HEADING=None):
    """Code embedded as <script type="syntaxhighlighter" class="brush: X"><![CDATA[ ... ]]></script>.

    The code is dedented (its YAML indentation removed). brush: cpp holding Java (CS173 highlights Java
    with the C++ brush) is read as Java. A label is an HTML comment on the line above the <script> line,
    at any indentation."""
    out, heading = [], ""
    i = 0
    while i < len(lines):
        if HEADING is not None:
            h = HEADING.match(lines[i])
            if h:
                heading = h.group(1)
        m = SCRIPT_OPEN.match(lines[i])
        if not m:
            i += 1
            continue
        ind, brush, first = m.group(1), m.group(2).lower(), m.group(3)
        body, j = [], i
        if "]]></script>" in first:
            body.append(first.split("]]></script>")[0])
        else:
            if first.strip():
                body.append(first)
            j = i + 1
            while j < len(lines) and "]]></script>" not in lines[j]:
                body.append(lines[j])
                j += 1
            if j < len(lines):
                tail = lines[j].split("]]></script>")[0]
                if tail.strip():
                    body.append(tail)
        code = textwrap.dedent("\n".join(body).replace("\t", "    ")).strip("\n")
        lang = BRUSH.get(brush, brush)
        if lang == "cpp" and LOOKS_JAVA.search(code) and "#include" not in code:
            lang = "java"
        label = None
        if i > 0 and LABEL.match(lines[i - 1]):
            label = parse_label(LABEL.match(lines[i - 1]).group(1))
        out.append({"start": i, "end": j, "lang": lang, "code": code, "label": label, "page": page,
                    "indent": ind, "heading": heading, "html": True})
        i = j + 1
    return out


def html_link(info, vid, mark):
    return f'<a href="{info["url"]}/viz/#{vid}">Visualize this example</a> {mark}'


def looks_mips(code):
    regs = len(MIPS_REG.findall(code))
    return regs >= 2 and (re.search(r"^\s*main\s*:", code, re.M) is not None or "syscall" in code) \
        and re.search(r"^\s*(\.text|\.data|[a-z]+\s+\$)", code, re.M) is not None


def sql_ok(code):
    body = re.sub(r"--[^\n]*", "", code).strip()
    return bool(body) and sqlite3.complete_statement(body if body.endswith(";") else body + ";") \
        and re.match(r"(?is)\s*(select|insert|update|delete|create|drop|alter|with|replace|pragma|begin)\b", body) is not None


def suggest(b, base):
    """The suggestion for block b. base is code-viz's own (None when it found nothing)."""
    code, lang = b["code"], ALIASES.get(b["lang"], b["lang"])
    n = len([l for l in code.splitlines() if l.strip()])
    if lang in ("", "text", "none", "asm", "mips") and n >= 2 and looks_mips(code):
        return {"viz": "mips", "lang": "mips"}
    if lang == "sql" and sql_ok(code):
        return {"viz": "sql", "lang": "sql"}
    if lang == "java" and n >= 2 and "System.out" in code and "System.in" not in code \
            and not re.search(r"\b(javax\.swing|java\.awt|JFrame|Applet|javafx)\b", code):
        return {"viz": "java", "lang": "java"}
    if lang == "js" and n >= 1 and "console.log" in code and not JS_BROWSER.search(code):
        return {"viz": "plain", "lang": "js"}
    if lang == "vhdl" and VHDL_ENTITY.search(code) and (re.search(r"\barchitecture\b", code, re.I)):
        return {"viz": "wave", "lang": "vhdl"}
    if lang in ("", "text", "none") and "#include" in code and re.search(r"\bint\s+main\s*\(", code):
        # a C program fenced without a language (CS376 has many)
        base = {"viz": "c", "lang": "cpp" if re.search(r"#include\s*<(iostream|vector|string)>|std::", code) else "c"}
    if base and base.get("viz") == "c" and C_MULTI.search(code):
        return {"viz": "plain", "lang": base["lang"]}
    return base


def _sql_refs(code):
    body = re.sub(r"--[^\n]*", "", code)
    made = {m.lower() for m in SQL_CREATES.findall(body)}
    used = {m.lower() for m in SQL_NAMES.findall(body)} - made
    return used - {"select", "values", "set", "where"}, made


def setup_deps(b, earlier):
    """setup= blocks for an SQL or VHDL block: the earlier blocks on the page it depends on.
    [] when it needs none, None when something it uses is defined nowhere above it."""
    lang = ALIASES.get(b["lang"], b["lang"])
    same = [x for x in earlier if ALIASES.get(x["lang"], x["lang"]) == lang and x["start"] < b["start"]]
    if lang == "sql":
        need, _ = _sql_refs(b["code"])
        deps, seen = [], set()
        while need:
            name = need.pop()
            makers = [x for x in same if name in _sql_refs(x["code"])[1]]
            if not makers:
                return None
            # the block that creates the table, and every later block above b that changes it
            first = makers[-1]
            for x in same:
                if x["start"] >= first["start"] and id(x) not in seen and \
                        (name in _sql_refs(x["code"])[1] or re.search(rf"\b(INTO|UPDATE|FROM)\s+[\"`\[]?{name}\b", x["code"], re.I)) \
                        and re.search(r"(?i)\b(create|insert|update|delete|alter|replace)\b", x["code"]):
                    seen.add(id(x))
                    deps.append(x)
                    more, _ = _sql_refs(x["code"])
                    need |= {m for m in more if m != name and all(m not in _sql_refs(d["code"])[1] for d in deps)}
        return sorted(deps, key=lambda x: x["start"])
    if lang == "vhdl":
        mine = {e.lower() for e in VHDL_ENTITY.findall(b["code"])}
        need = {(a or c).lower() for a, c in VHDL_USES.findall(b["code"])} - mine
        deps = []
        for name in need:
            makers = [x for x in same if name in {e.lower() for e in VHDL_ENTITY.findall(x["code"])}]
            if not makers:
                return None
            deps.append(makers[-1])
        return sorted({id(d): d for d in deps}.values(), key=lambda x: x["start"])
    return []


def _vhdl_has_testbench(texts):
    for t in texts:
        for m in re.finditer(r"\bentity\s+(\w+)\s+is\b(.*?)\bend\b", t, re.I | re.S):
            if not re.search(r"\bport\s*\(", m.group(2), re.I):
                return True
    return False


def manifest(root, course, slug):
    """Manifest entries under files/: MIPS programs and VHDL designs that have a testbench."""
    out = []
    for dp, dn, fn in os.walk(os.path.join(root, "files")):
        if "/." in dp or "node_modules" in dp:
            continue
        rel = os.path.relpath(dp, root)
        for f in sorted(fn):
            p = os.path.join(dp, f)
            if f.endswith((".s", ".asm")) and os.path.getsize(p) < 40000:
                code = open(p, errors="replace").read()
                if looks_mips(code):
                    out.append({"id": f"{course}-{slug(os.path.join(rel, f).replace('files/', '', 1))}", "viz": "mips",
                                "lang": "mips", "file": os.path.join(rel, f), "input": ""})
            elif f.endswith(".zip") and os.path.getsize(p) < 5_000_000:
                try:
                    z = zipfile.ZipFile(p)
                    vhd = [n for n in z.namelist() if n.endswith((".vhd", ".vhdl")) and "/." not in "/" + n]
                    if vhd and _vhdl_has_testbench([z.read(n).decode("utf-8", "replace") for n in vhd]):
                        out.append({"id": f"{course}-{slug(os.path.join(rel, f).replace('files/', '', 1))}", "viz": "wave",
                                    "lang": "vhdl", "file": os.path.join(rel, f), "input": ""})
                except (zipfile.BadZipFile, OSError):
                    pass
        vhd = [f for f in fn if f.endswith((".vhd", ".vhdl"))]
        if vhd and _vhdl_has_testbench([open(os.path.join(dp, f), errors="replace").read() for f in vhd]):
            out.append({"id": f"{course}-{slug(rel.replace('files/', '', 1).replace('/', '-'))}", "viz": "wave",
                        "lang": "vhdl", "file": rel, "input": ""})
    seen, uniq = set(), []
    for e in out:          # the same file name in two folders (CS274's replit/ and replits/): first one only
        if e["id"] not in seen:
            seen.add(e["id"])
            uniq.append(e)
    return uniq
