"""code-viz notebooks: Jupyter notebooks under files/ as a source of examples.

Full manual: the header of code-viz (`code-viz readme`, or README.md), section 4 (Notebooks).

A notebook cannot carry `<!-- run: -->` labels, so its examples are listed in viz/notebooks.json:

    {"notebooks": [{"file": "files/lab3/regression.ipynb",
                    "examples": [{"id": "cs477-nb-regression-4", "cell": 4, "viz": "plain"}]}]}

`cell` counts code cells only, from 1, in notebook order (markdown cells are not counted), so the id
stays the same when prose cells change. A page links the notebook when the file name appears on a
boundary; unlabel() removes ids and rewrites the page's link line for the remaining examples. An example runs like a setup= cell: every earlier code cell
of the notebook runs first, untraced and silent, then the cell itself is traced (viz=env) or run
for its output and figures (viz=plain). IPython-only lines (`%magic`, `!shell`) become comments.
Cells that mount Google Drive work because tracers/pystubs has a google.colab stand-in whose
drive.mount does nothing; cells that then read Drive files fail and are not labeled.

`code-viz label --notebooks [--try]` picks the cells that print or plot, runs them (with --try),
and writes viz/notebooks.json; `--links` (or `code-viz links`) adds one line under the first line of
each page that links the notebook:

    [Visualize this notebook's examples](<site>/viz/#<first id>): [cell 4](<site>/viz/#<id>) ... <!-- code-viz link -->

The line goes after the paragraph, list item or table that holds the notebook link (indented to
stay inside a list item, and never inside a table), so the page renders as before.
"""
import json
import os
import re
import sys

INDEX = os.path.join("viz", "notebooks.json")


def write_lines(path, lines, original=None):
    """Write a page's lines back keeping every original line's own ending. Pages are read with
    universal newlines (\\r\\n becomes \\n), and many course pages use CRLF, some only on some lines;
    writing one ending for the whole file would rewrite those lines. Unchanged lines keep the ending
    they had (matched with difflib against the file, or `original` bytes when given); an added line
    takes the ending of the line above it."""
    import difflib
    raw = (original if original is not None else open(path, "rb").read()).decode("utf-8", errors="replace")
    pieces = raw.split("\n")
    ends = ["\r\n" if p.endswith("\r") else "\n" for p in pieces[:-1]]
    norm = [p[:-1] if p.endswith("\r") else p for p in pieces]
    first = ends[0] if ends else "\n"
    out = [None] * len(lines)
    sm = difflib.SequenceMatcher(None, norm, lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                if i1 + k < len(ends):
                    out[j1 + k] = ends[i1 + k]
    prev = first
    for j in range(len(lines)):
        if out[j] is None:
            out[j] = prev
        else:
            prev = out[j]
    text = "".join(l + out[j] for j, l in enumerate(lines[:-1])) + (lines[-1] if lines else "")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def find(root):
    """Notebook paths (relative to root) under files/, sorted; checkpoints are skipped."""
    out = []
    for dp, dn, fn in os.walk(os.path.join(root, "files")):
        dn[:] = sorted(d for d in dn if not d.startswith(".") and d != ".ipynb_checkpoints")
        out += [os.path.relpath(os.path.join(dp, f), root) for f in sorted(fn) if f.endswith(".ipynb")]
    return sorted(out)


def code_cells(root, nb):
    """The notebook's code cells as Python source, IPython-only lines turned into comments."""
    try:
        data = json.load(open(os.path.join(root, nb), encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for c in data.get("cells", []):
        if c.get("cell_type") != "code":
            continue
        src = c.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        src = "\n".join(("# (notebook only) " + l) if l.lstrip().startswith(("%", "!")) else l for l in src.split("\n"))
        out.append(src)
    return out


def load_index(root):
    p = os.path.join(root, INDEX)
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return {"notebooks": []}


def save_index(root, idx):
    idx["notebooks"] = sorted((n for n in idx["notebooks"] if n.get("examples")), key=lambda n: n["file"])
    for n in idx["notebooks"]:
        n["examples"] = sorted(n["examples"], key=lambda e: e["cell"])
    p = os.path.join(root, INDEX)
    if not idx["notebooks"]:
        if os.path.exists(p):
            os.remove(p)
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=1)


def block(nb, cells, k, label):
    """A pseudo-block (the shape code-viz's blocks() returns) for code cell k (1-based)."""
    earlier = [c for c in cells[:k - 1] if c.strip()]
    lab = dict(label)
    if earlier:
        lab["setup_src"] = "\n\n".join(earlier)
        lab["setup_desc"] = f"code cells 1 to {k - 1} of {os.path.basename(nb)}"
    return {"start": k - 1, "end": k - 1, "lang": "python", "code": cells[k - 1], "label": lab, "page": nb,
            "indent": "", "heading": "", "notebook": nb, "cell": k}


def blocks(root, only=None):
    """Labeled pseudo-blocks for every example listed in viz/notebooks.json."""
    out = []
    for n in load_index(root).get("notebooks", []):
        if only and os.path.normpath(only) != os.path.normpath(n["file"]):
            continue
        cells = code_cells(root, n["file"])
        for e in n.get("examples", []):
            if 1 <= e["cell"] <= len(cells):
                out.append(block(n["file"], cells, e["cell"], {"id": e["id"], "viz": e.get("viz", "plain")}))
    return out


def suggest(code):
    """viz for a notebook cell worth showing, or None: env for a small standard-library cell that
    prints, plain for any cell that prints or draws a figure."""
    if not code.strip():
        return None
    draws = re.search(r"\bplt\.|\.plot\(|\bimshow\(|\bsns\.", code)
    prints = re.search(r"\bprint\s*\(", code)
    if not (draws or prints):
        return None
    heavy = re.search(r"^\s*(import|from)\s+(tensorflow|torch|keras|transformers)\b", code, re.M)
    if heavy:
        return None
    lines = [l for l in code.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    mods = set(re.findall(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", code, re.M))
    std = set(getattr(sys, "stdlib_module_names", ()))
    if prints and not draws and len(lines) <= 25 and mods <= std:
        return "env"      # short, prints, only standard-library imports: step through it
    return "plain"


def link_text(info, ids, cells):
    first = f"{info['url']}/viz/#{ids[0]}"
    parts = " ".join(f"[cell {c}]({info['url']}/viz/#{i})" for i, c in zip(ids, cells))
    return f"[Visualize this notebook's examples]({first}): {parts}"


def _slot(lines, i):
    """Where to put the link line for a notebook link on line i: after its paragraph, list item or
    table, with the indent that keeps it inside a list item. Returns (index, indent)."""
    line = lines[i]
    if line.lstrip().startswith("|"):
        j = i
        while j < len(lines) and lines[j].lstrip().startswith("|"):
            j += 1
        return j, re.match(r"^\s*", line).group(0)
    m = re.match(r"^(\s*)([-*+]|\d+[.)])(\s+)", line)
    indent = (m.group(1) + " " * (len(m.group(2)) + len(m.group(3)))) if m else re.match(r"^\s*", line).group(0)
    j = i + 1
    while j < len(lines) and lines[j].strip() and not re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[j]) and not lines[j].lstrip().startswith("#"):
        j += 1
    return j, indent


def add_links(root, info, pages, link_mark, check=False):
    """Add (or with check, list) the missing notebook link lines. Returns the number missing."""
    idx = load_index(root)
    missing = 0
    for n in idx.get("notebooks", []):
        ex = n.get("examples") or []
        if not ex:
            continue
        ids, cells = [e["id"] for e in ex], [e["cell"] for e in ex]
        name = os.path.basename(n["file"])
        hit = None
        for page in pages:
            lines = open(os.path.join(root, page), encoding="utf-8", errors="replace").read().split("\n")
            if any(link_mark in l and f"/viz/#{ids[0]})" in l for l in lines):
                hit = "linked"
                break
            pat = re.compile(r"(?<![\w.-])" + re.escape(name) + r"(?![\w.-])")   # test.ipynb, not my_test.ipynb
            refs = [k for k, l in enumerate(lines) if pat.search(l) and link_mark not in l and not l.lstrip().startswith("<!--")]
            if refs and hit is None:
                hit = (page, lines, refs[0])
        if hit == "linked":
            continue
        if hit is None:
            print(f"  {n['file']}: no page links this notebook; its examples open from the viz/ index only")
            continue
        missing += 1
        page, lines, i = hit
        print(f"  {page}:{i + 1}  {n['file']} ({len(ids)} example(s))")
        if check:
            continue
        j, indent = _slot(lines, i)
        lines[j:j] = ["", indent + link_text(info, ids, cells) + " " + link_mark]
        write_lines(os.path.join(root, page), lines)   # every line keeps its own ending
    return missing


def unlabel(root, gone, info=None, pages=(), link_mark=None):
    """Drop the ids from viz/notebooks.json, remove page link lines that name any of them, and (with
    info) write the link again for the notebook's remaining examples."""
    idx = load_index(root)
    hit = False
    for n in idx.get("notebooks", []):
        before = len(n.get("examples", []))
        n["examples"] = [e for e in n.get("examples", []) if e["id"] not in gone]
        hit = hit or len(n["examples"]) != before
    save_index(root, idx)
    if not (hit and link_mark):
        return
    for page in pages:
        path = os.path.join(root, page)
        lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
        keep = [l for l in lines if not (link_mark in l and "Visualize this notebook's examples" in l
                                         and any(f"/viz/#{g})" in l for g in gone))]
        if len(keep) != len(lines):
            write_lines(path, keep)
    if info:
        add_links(root, info, pages, link_mark)
