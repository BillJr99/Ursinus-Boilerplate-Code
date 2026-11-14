<!-- Generated from the header of code-viz by `code-viz readme --write`. Edit the header, not this file. -->

# code-viz

Run the code examples in a course site in throwaway containers, record what each one does, and step
through it in a static viewer that teachers project and students open on their own phones.

This text is the complete manual. It lives in the header of the `code-viz` command;
`code-viz readme` prints it and `code-viz readme --write` regenerates `README.md` from it, so the two
never disagree. Every other code-viz file has a header for its own part that points back to a section
here.

Contents: 1 What it is, 2 Architecture, 3 Quick start, 4 Labels and ids, 5 Commands,
6 Expected outputs and churn, 7 Kinds of visualization, 8 Reading the viewer, 9 Teacher view and
student mode, 10 QR codes in class and on slides, 11 Live mode in class, 12 Recording agent examples,
13 Tips, 14 Trace format, 15 Where things run and safety, 16 CI, 17 Troubleshooting,
18 Known problems and limits, 19 Output files, 20 Testing code-viz itself, 21 Modes and URL
arguments, 22 Explain mode and the tour format, 23 Simulate mode, sessions and recording.

## 1. What it is

code-viz finds the code blocks in a course's LiaScript decks and tutorials, runs each one in a
throwaway Docker container for its language, records a step-by-step trace, and builds a static
viewer at `<site>/viz/`: the code with the current line highlighted, step controls, the output so
far, and a panel that shows the program's state. The panel is an environment diagram (Python,
Scheme), a lambda term being reduced, a bison LR parse, an automaton reading its input, C memory
with pointers, an agent's model calls and retrieval, or a terminal replay.

It lives in the Ursinus-Boilerplate-Code repo at `course/viz/`, which every course repo carries as
its `code/` submodule, so a course runs it as `code/course/viz/code-viz` from the course repo root.

## 2. Architecture

```
course/viz/
  code-viz        the command (this file): catalog, label, unlabel, run, build, serve, qr, readme
  langs.py        the SQL, Java, JavaScript, MIPS and VHDL rules: fence names, runners, suggestions,
                  setup= for SQL and VHDL, manifest entries for MIPS programs and VHDL designs
  runners/        one Dockerfile per toolchain: python, python-ml (PyTorch, CPU), scheme, c,
                  flexbison, mini, haskell, prolog, ocaml, agents, shell, qr, java, node, mips, vhdl
  tracers/        step tracers that run inside the containers: driver.py (dispatch), pytrace.py,
                  schemetrace.py, lambdatrace.py, cstep_gdb.py, bisontrace.py, automaton.py,
                  agentrec.py, shellcast.py, cviz-repl.scm, langrun.py (SQL, Java, JavaScript, MIPS
                  and VHDL dispatch), sqltrace.py, mipstrace.py, JdiTrace.java. pytrace,
                  schemetrace, lambdatrace, automaton, sqltrace and mipstrace are pure Python, so
                  the viewer also runs them in the browser (Pyodide).
                  cviz_mplbackend.py draws figures headlessly, and pystubs/ holds the turtle,
                  ezgraphics and google.colab stand-ins (section 7, Figures).
  notebooks.py    Jupyter notebooks under files/ as a source of examples (section 4, Notebooks)
  viewer/         the static viewer: index.html, viewer.js, viewer.css, figures.js (figures), and
                  langs.js and langs.css (the SQL, MIPS and VHDL panels, and browser runs for SQL,
                  MIPS and JavaScript)
  screenshot.py   headless-browser screenshots and render checks of a built viewer
  workflow.yml    the GitHub Actions template for course repos ("code-viz check")
  README.md       generated from this header by `code-viz readme --write`
```

The pipeline, left to right:

1. **Catalog.** `code-viz catalog` scans every page under `_pages/` (except submodules such as
   `_pages/Exercises`) for fenced blocks, at column 0 or indented inside a list item. A block is an
   example when a label comment sits on the line above its fence (section 4). Files that are not
   blocks come from `viz/manifest.json` (bison grammars, `.dot` automata) and `viz/notebooks.json`
   (notebook cells).
2. **Runners.** Each example's language picks a runner image, built from `runners/<name>/Dockerfile`
   with `docker build --network host` and labelled `code-viz=1`.
3. **Tracers.** One container per batch runs `tracers/driver.py`, which runs each job with the right
   tracer and writes one trace JSON per example (section 14).
4. **Viewer.** `build` writes `viz/traces/<id>.json.gz`, `viz/index.json`, the viewer files and the
   in-browser tracers into the course repo's `viz/`, which the course's normal Pages build publishes.
5. **CI.** The course repo's "code-viz check" workflow re-runs `build --check` so a deck edit that
   breaks an example fails (section 16).

## 3. Quick start

From a course repo root, with Docker available locally or over SSH (section 15):

```
code/course/viz/code-viz catalog                    # what is labeled, what could be
code/course/viz/code-viz label --try --links        # label the candidates that run cleanly
code/course/viz/code-viz build --check              # traces and viewer into viz/
git add viz _pages && git commit -m "code-viz: build"
```

Then open `<site>/viz/#<id>` to teach from it, and press **QR** to send students to
`<site>/viz/?student=1#<id>` (sections 9 and 10).

## 4. Labels and ids

A block is an example when a hidden comment sits on the line above its opening fence:

    <!-- run: id=cs374-liascript-scope-chains-3 viz=env -->
    ```python
    def make_counter(): ...
    ```
    [Visualize this example](https://billjr99.github.io/Ursinus-CS374-Fall2026/viz/#cs374-liascript-scope-chains-3) <!-- code-viz link -->

LiaScript and Jekyll do not show HTML comments, so students never see the label. Fields:

| field | meaning |
|---|---|
| `id=` | unique name, and the viewer address `<site>/viz/#<id>` |
| `viz=` | `env` (Python, Scheme), `lambda`, `c`, `bison`, `automaton`, `agent`, `cast` (shell), `plain` (output only) |
| `lang=` | `python`, `scheme`, `lambda`, `c`, `cpp`, `haskell`, `prolog`, `ocaml`, `mini`, `shell`, `sql`, `java`, `js`, `mips`, `vhdl` (default: the fence's language; `sqlite`, `javascript`, `node`, `vhd`, `s` and `spim` are read as these) |
| `input="..."` | text given to the program on stdin, to a bison parser, or to an automaton |
| `args="..."` | command line arguments (Python and agent examples) |
| `timeout=N` | seconds for this example (default 20; agents 300) |
| `max_steps=N` | step cap for this example (default 800) |
| `setup=ID[,ID]` | Python, SQL and VHDL: run (or, for VHDL, analyze) these earlier blocks first, untraced and silent (below) |
| `interp=page` | Mini (or any language a page builds an interpreter for): run the page's own Python interpreter with this block as its input program (below); `interp=<path>.md` uses another page's |
| `entry="..."` | with `interp=`: the interpreter's command line, `{file}` standing for the program (default `runner.py --file {file}`) |
| `record` | agent examples: replay the committed recording; never re-run in CI |
| `runner=NAME` | run in `runners/NAME` instead of the language's runner (`python-ml` for PyTorch; `label` adds it); a plain name of letters, digits, `_` and `-` |

**Ids.** `label` makes ids as `<course>-<page>-<n>`: the course from the repo name (`cs374`), the
page's file name lowercased with other characters turned into hyphens (`liascript-scope-chains`),
and the next free number on that page (`cs374-liascript-scope-chains-3`). Ids written by hand can be
anything unique (older CS357 ones look like `cs357-tut-llmjudges-3`). Keep an id once students have its link or QR code; renumbering breaks them. Manifest entries
use the ids written in `viz/manifest.json`.

**Links.** `label --links` writes the "Visualize this example" line, marked `<!-- code-viz link -->`
so `unlabel` can find it; `code-viz links` adds it later to labeled blocks that have none (section 5). It goes after any LiaScript run macro (`@LIA.eval(...)`, `@Pyodide.eval`)
that follows the fence, so the deck's own Run button keeps working.

**Setup cells.** A notebook-style page often has a Setup cell that later cells depend on (CS357's
orchestration workshop: Steps 1 to 3 all call the Setup cell's `llm()` and read its `MESSAGES`).
Such a cell cannot run alone, so it carries `setup=` with the ids of the cells it needs:

    <!-- run: id=cs357-liascript-orchestrationworkshop-4 viz=env setup=cs357-liascript-orchestrationworkshop-1 -->

The setup blocks run first, in the order given, in the same globals, with their output discarded
and nothing recorded; then the cell itself is traced. Each setup block's own `setup=` is resolved
first (so a chain like Setup, Step 1, Step 2 needs only `setup=<step 1 id>` on Step 2, when Step 1
says `setup=<setup id>`), and an id is used once. The stepped lines, the output and the step count
are the cell's own; names the setup defined appear in the global frame, and functions it defined run
without being stepped. The viewer and student mode show the setup code collapsed above the cell
("Setup code from ... (runs first, not stepped)"), and Edit and run re-runs the edited cell after the
same setup. For agent examples the setup's model calls are not recorded. A setup id must be a labeled
block; `catalog` and `label` work these out (section 5).

**Interpreter examples (`interp=`).** CS374's project guide (`tutorial-project-language-guide.md`)
builds an interpreter for the Mini language in Python, one module at a time, and its Mini example
programs need that interpreter to run. A Mini block labeled `interp=page` runs as Python: code-viz
gathers every Python block on the page whose first line is `# name.py` (a new file) or
`# name.py (continued)` (appended to it), in page order, writes those files, saves the Mini block as
`program.mini`, and runs `python runner.py --file program.mini` in the mini runner. So the example
is the input the guide's interpreter reads and runs, and its output is what that interpreter prints:

    <!-- run: id=cs374-tutorial-project-language-guide-2 viz=plain interp=page -->
    ```mini
    fun fib(n) { ... }
    print fib(10);
    ```

Python blocks without a `# name.py` heading (demos, "try it" cells) and `test_*.py` files are left
out. Every module block must carry its heading, `(continued)` included, even when it continues a
class; a block that forgets it silently drops out of the interpreter (the parser's 5.2 to 5.4 blocks
were missing theirs until 2026-11-14). The viewer shows the interpreter's files collapsed above the
program ("Run by the Python interpreter built on ..."). `label` suggests `interp=page` for Mini blocks
on a page that has `# name.py` blocks, and `label --try` keeps only the blocks the interpreter runs
cleanly, so a Mini example that the guide's interpreter cannot parse stays unlabeled and shows up in
the `label --try` count (CS374 Example 4 was one until 2026-11-14: `{ "adult" }` needed its `;`, so
the example was changed to match the parser, and the grammar notes now say how an `if` expression
gets its value). Without `interp=`, a Mini block still uses
`files/examples/mininote` (built with make) when the course has it. To use another command line, set
`entry="mini.py {file}"`. Student mode's Edit and run does not re-run interpreter examples (they need
the runner), so it shows the recorded run.

**Pages.** Every Markdown page under `_pages/` is read: Activities, Tutorials, Labs, Modules,
Assignments, Projects and notes pages, but never a submodule listed in `.gitmodules` (such as
`_pages/Exercises`, which belongs to Ursinus-Exercises). Fences may start at column 0 or be indented
up to 12 spaces, as a code block inside a list item is (its closing fence may be indented up to
three spaces more or less than the opening one); the label and the link line are written with the
same indent, so they stay inside the list item. Ids are unique across the site: two pages with
the same file name in different folders get different numbers. Pages are written back with every
line keeping its own ending (many course pages use CRLF, some only on some lines; an added line takes
the ending of the line above it), and a page is only written when a label or link was added, so a
`label` run that keeps nothing leaves the page byte for byte unchanged and one that labels changes
only the added lines.

**Embedded code blocks.** Code written as `<script type="syntaxhighlighter" class="brush: X">` with
the code inside `<![CDATA[ ... ]]></script>` is read as a block too (langs.py `script_blocks`). That
is the form the activity layout's POGIL models use in a page's YAML front matter (`info.models[].model`)
and some older pages use in their body: CS173's Java (highlighted with `brush: cpp`), CS274's MIPS and
C, CS170's and CS377's Python and SQL. The code is dedented (its YAML indentation removed); the brush
names the language (`cpp` holding Java, with `System.out` or `public static` and no `#include`, is
read as Java). The label is an HTML comment on the line above the `<script>` line and the link an
HTML `<a ...>Visualize this example</a> <!-- code-viz link -->` on the line after `]]></script>`,
both at the script's own indentation, so they stay inside the YAML literal block (`model: |`) and the
front matter still parses; models are written into the page as raw HTML, so the link is HTML, not
Markdown. Check a page after labeling with a YAML parser if it was hand-edited nearby.

**Solutions are never labeled.** A block under a heading containing "Solution" or "Answer key", or
a heading that is just "Key", is not suggested (course pages should not print solutions; such a block
is a page to fix, not an example).

**Site address.** Links and QR codes use `<url>/<repo name>` when the site is on GitHub Pages: the
repo name comes from the git remote, because a parent repo's `_config.yml` often keeps the
`baseurl` of the term it was copied from. In a repo without a remote, `_config.yml`'s `url` and
`baseurl` are used. A repo name without a course number (Ursinus-WebMobile) gives ids starting with
the name (`webmobile-...`).

**Notebooks.** Jupyter notebooks under `files/` are a source of examples. A notebook cannot carry
labels, so its examples are listed in `viz/notebooks.json`:

    {"notebooks": [{"file": "files/notebooks/ab_test_analysis.ipynb",
                    "examples": [{"id": "cs474-nb-ab-test-analysis-2", "cell": 2, "viz": "env"}]}]}

`cell` counts code cells only, from 1. An example runs like a `setup=` cell: every earlier code cell
of the notebook runs first, untraced and silent, then the cell is traced (`viz=env`, for a short
standard-library cell that prints) or run for its output and figures (`viz=plain`). IPython-only
lines (`%matplotlib inline`, `!pip install`) become comments. `google.colab` is a stand-in whose
`drive.mount()` does nothing, so a Colab notebook's setup runs; a cell that then reads Drive files
fails and is not labeled. Cells that import TensorFlow, Keras, PyTorch or transformers are not
suggested. `label --notebooks --try --links` labels the cells that print or draw and run cleanly,
and adds one line under the paragraph, list item or table that holds the first link to the notebook
on any page:

    [Visualize this notebook's examples](<site>/viz/#<first id>): [cell 2](<site>/viz/#<id>) [cell 3](...) <!-- code-viz link -->

The viewer shows the earlier cells collapsed above the cell ("Setup code from code cells 1 to 3 of
..."). A page links the notebook when its file name appears on a boundary (`test.ipynb` does not
match `my_test.ipynb`). `unlabel <id>` removes a notebook example from `viz/notebooks.json`, deletes
the page's link line that named it, and writes the line again for the notebook's remaining examples.

**Manifest.** `viz/manifest.json` lists bison grammars (`files/examples/...`) and automata
(`files/dotty/*.dot`) with their `id`, `viz`, `file`, `input` and optional `timeout`. `build`
generates it from `files/` the first time; edit it afterwards to choose inputs.

## 5. Commands

Global options go before the subcommand:

| option | meaning |
|---|---|
| `--host user@machine` | run containers on that machine over SSH with `sudo -n docker` (default `CODE_VIZ_HOST`, else local Docker) |
| `--keep-images` | keep runner images afterwards (default: removed at the end of the command) |

`code-viz --help` lists the subcommands; `code-viz <subcommand> --help` lists each one's options.

### catalog

Lists labeled examples and suggests labels for blocks that look runnable (known language, only
standard-library or known imports, not a fragment). A Python block that uses names it does not
define is suggested with `setup=` naming the earlier blocks on the same page that define them (an
unlabeled one shows as `lineN`: label it first); a block that uses a name no earlier block defines
is not suggested.

```
code-viz catalog
code-viz catalog --page _pages/Activities/liascript-scope-chains.md
code-viz catalog -v                     # also list every suggestion with its page and line
```

`catalog` writes `viz/catalog.json` (every labeled example and suggestion) only when run without
`--page` and only in a repo that already has labels or a `viz/` folder, so a one-page look never shrinks it.

### label

Applies the suggested labels. Options: `--page`, `--lang`, `--viz` (limit what is labeled), `--try`
(run each candidate first and label only those that run cleanly), `--links` (add the Visualize link),
`--agents` (also label agent examples, recorded rather than re-run), `--ollama-network NET` (for
`--try` on agent examples). Suggested `setup=` fields are written with the label; a block whose
setup block is unlabeled is skipped until that block is labeled, so running `label` twice picks up
chains.

```
code-viz label --try --links
code-viz label --try --links --lang scheme --page _pages/Activities/liascript-scheme.md
code-viz label --agents --try --ollama-network cviz-ollama
code-viz label --notebooks --try --links     # notebook cells (section 4, Notebooks)
```

`--notebooks` labels notebook cells instead of page blocks (`--page` then names one notebook, and
`--viz` limits the kind). `label --try` counts a run as good when it printed, stepped, or drew a
figure.

### links

Adds the "Visualize this example" line (`[Visualize this example](<site>/viz/#<id>)`, marked
`<!-- code-viz link -->`) under every labeled block that has none, for blocks labeled without
`label --links` or by hand. The line goes after the closing fence and after any LiaScript macro
lines (`@LIA.eval(...)`) and `<script>` elements (through their `</script>`, however many lines)
that belong to the block, so the deck's own Run button keeps working; a block whose own link is
anywhere on the page is left alone, so running it twice changes nothing.
Options: `--page` (one page), `--check` (only list the blocks without a link, exit 1 if there are
any). It edits pages, so it is run by hand and committed with the pages; CI never runs it (CI
changes only `viz/`, section 16).

```
code-viz links --check
code-viz links
code-viz links --page _pages/Tutorials/tutorial-project-language-guide.md
```

### unlabel

Removes examples that should not be ones: the label comment, the Visualize link, the trace and the
expected output. QR images in `viz/qr/` are left; move them by hand.

```
code-viz unlabel cs357-tut-llmjudges-3 cs357-tut-llmjudges-4
```

### run

Runs one example (by id, or any file) and writes its trace. A file outside the site is traced and
printed as JSON. Options: `--viz`, `--input`, `--id`, `--ollama-network`.

```
code-viz run cs374-liascript-scope-chains-3
code-viz run files/examples/mininote --viz bison --input "x = 2 * 3 + 4"
code-viz run files/dotty/ends_in_ab.dot --input abab
code-viz run my_closure.py
```

### build

Runs every labeled example and manifest entry and writes the viewer site to `viz/`. Options:

| option | meaning |
|---|---|
| `--page P`, `--lang L` | only that page or language |
| `--check` | exit 1 when an example stopped running (error where it used to run) |
| `--strict` | with `--check`, also exit 1 when an output changed |
| `--update-expected` | accept today's outputs as the expected ones |
| `--record-agents` | re-record agent examples (needs Ollama, section 12) |
| `--ollama-network NET` | the Docker network with the Ollama container |
| `--manifest-only` | only the grammars and automata in `viz/manifest.json` |

```
code-viz build
code-viz build --check
code-viz build --lang python --check --strict
code-viz build --update-expected
code-viz build --record-agents --ollama-network cviz-ollama
```

### serve

Live mode: serves the course repo on a port so examples can be edited and re-run, including
container languages, through `POST /viz/api/run` (section 11). Options: `target` (an id or a file
to trace and open first), `--port` (default 8765), `--input`, `--public` (listen on all interfaces,
not only this machine), `--ollama-network`.

```
code-viz serve                          # http://localhost:8765/viz/
code-viz serve cs374-liascript-scope-chains-9 --port 9000
code-viz serve my_closure.py
code-viz serve --public                 # reachable from other machines on the network
```

### qr

Writes QR codes of examples' student links to `viz/qr/<id>.svg` and `viz/qr/<id>.png`, made in the
throwaway `qr` runner (python:3.12-slim with segno). Ids are checked against the labeled examples
and `viz/index.json`. Options: `--out DIR` (default `viz/qr/`), `--scale N` (pixels per module,
default 10), `--snippet` (also print a Markdown block for a deck), `--print` (only print the links;
no container), `--force` (allow ids that are not labeled examples). The snippet's image address
follows `--out`: the absolute site URL of that folder (a folder under `_pages/` is served without
the `_pages/` prefix). When `--out` is outside the repo, or in a folder the site does not serve (a
name starting with `_` or `.`), the snippet uses the local file path and a note says to copy the
image into the repo.

```
code-viz qr cs374-liascript-scope-chains-9
code-viz qr cs374-liascript-lambdacalculus2-11 --snippet
code-viz qr cs357-liascript-observability-1 --print
code-viz --host bill@10.0.0.26 qr cs374-liascript-scope-chains-9 --scale 14 --out /tmp/qr
```

### readme

Prints this manual. `--write` regenerates `README.md` next to the command from it; `--check` exits 1
when `README.md` differs (edit the header, never `README.md`).

```
code-viz readme | less
code-viz readme --write
```

## 6. Expected outputs and churn

`viz/expected/<id>.out` holds each example's expected output. `build --check` fails when an example
that used to run now errors; with `--strict` it also fails when an output changed. After a deliberate
change, run `build --update-expected` and commit.

Builds are deterministic so the repo stays quiet: traces are written with sorted keys and gzip
`mtime=0`, Python heap objects are numbered in the order first seen (not by memory address),
memory addresses are cut out of object reprs, Python runs with `PYTHONHASHSEED=0` (the same set and
dict-of-set order every time), a
trace whose content did not change is not rewritten, and `viz/index.json` keeps its
"built" time when no example changed. A `build --check` on an unchanged repo leaves `git status`
clean. Two things still churn on purpose: agent outputs (model replies differ on every recording,
so they are never compared) and any example that prints a time, a date, a random number or a memory
address (its output looks changed on every build; see the tips in section 13).

## 7. Kinds of visualization

| viz | languages | what the panel shows |
|---|---|---|
| env | Python | frames with their variables, objects on the heap (lists, dicts, instances), functions with the variables their closures capture, arrows from names to objects and from closures to the frame that defined them; frames kept alive by a closure stay on screen after they return |
| env | Scheme | environments (frames) with parent links, closures with an arrow to their defining environment, the expression being evaluated; output checked against Guile |
| lambda | lambda calculus | the term tree with the next redex highlighted, the reduction sequence, normal and applicative order side by side, and the predefined names the term used |
| bison | flex + bison | the LR state stack, lookahead and action at each step (shift, reduce by rule N, accept), the parse tree as it grows, and bison's state graph with the current state highlighted |
| automaton | DOT (files/dotty) | the automaton with its current state set highlighted as it reads an input string (DFA, NFA, epsilon-NFA); the input can be edited in the page |
| c | C, C++ | stack frames with locals and arguments, arrays as cells, structs, pointers drawn as arrows to the variable they point at (gdb steps the program) |
| agent | Python calling Ollama | a timeline of model calls (model, prompt or messages, reply, tokens, seconds), embeddings, retrieval (the query, every passage ranked with its source and score, top k marked), the prompt assembled from the retrieved passages, tool calls and printed output, with the program line behind each event highlighted; recorded once and replayed |
| cast | shell | a terminal replay of each command and its output |
| sql | SQL (SQLite) | the statement just run, its result (columns and rows), how many rows it changed, and every table; a table the statement changed is shown before and after it |
| java | Java | the call stack with each frame's local variables (and `this`), and the objects they reach (arrays as cells, ArrayList, the example's own objects with their fields) with arrows, line by line through the example's own classes (the Java debugger steps it); output only when stepping fails |
| mips | MIPS assembly | the instruction just run, all 32 registers plus hi and lo (changed ones highlighted, decimal and hex), and memory words (static data with labels, heap, the stack words written), instruction by instruction; output checked against SPIM |
| wave | VHDL | the testbench's signals over simulation time as a waveform (one-bit signals as high and low lines, vectors as labeled bus segments, U/X/Z marked), stepping through the times a signal changed, with every value at that time (GHDL simulates it) |
| plain | Haskell, Prolog, OCaml, Mini, Python that draws, JavaScript, C that forks or starts threads | the program and its output (no step trace); Mini with `interp=` also shows the Python interpreter that ran it |

**Figures.** Every Python example runs with matplotlib's backend set to `tracers/cviz_mplbackend.py`,
so each figure the program shows (`plt.show()`) or leaves open at exit is saved as a PNG and kept in
the trace (`figures`), shown under the Output panel. In a stepped trace (env) a figure appears once
the printed output reaches the point where the program showed it; in plain traces all figures show.
`import turtle` and `import ezgraphics` load headless stand-ins from `tracers/pystubs`: the turtle
stand-in records the drawing and saves it at `done()` or exit; the ezgraphics stand-in records each
`GraphicsWindow` canvas (setFill, setOutline, drawRect/drawRectangle, drawOval, drawLine,
drawPolygon, drawText, drawArc) and saves it at `wait()`, `pause()` (one frame each) or exit, with y
growing downward as in ezgraphics. A call the stand-ins do not support raises AttributeError, so the
example fails visibly and is not labeled. Figures are deterministic (72 dpi, at most 900 pixels wide,
no metadata), at most 8 per example and 600 KB in all (more are counted as `figures_dropped`). Click
a figure to open it full size. `label` suggests `viz=plain` for Python that uses matplotlib,
seaborn, turtle or ezgraphics (stepping through it would draw Figure objects), and `runner=python-ml`
with `timeout=120` for PyTorch. Edit and run in the browser does not capture figures; the recorded
figures stay on screen.

**The newer languages (langs.py).** How each one is found, run and shown:

- **SQL.** Blocks fenced `sql` (or `sqlite`) that hold complete SQLite statements. `sqltrace.py` runs
  them one statement at a time in an in-memory database and records every table after each one; a
  failing statement records its error and the script goes on, as the sqlite3 shell does. Output is
  the shell's default list mode (`a|b`). A block that uses tables an earlier block on the page creates
  gets `setup=` with that block and the earlier blocks that change those tables, found by `label`
  (an SQL block that uses a table no block above creates is not labeled). MySQL or PostgreSQL syntax
  (`AUTO_INCREMENT`, `SERIAL`, `ENGINE=`) fails in SQLite, so `label --try` skips those blocks. Edit
  and run works in the browser (Pyodide's sqlite3).
- **Java.** Blocks fenced `java` with output (`System.out`) that do not read `System.in` or open a
  window. A block with a class is compiled as it is (its file named after its public class); a block
  of methods is wrapped in `public class Main { ... }`, and a block of statements in a `main` method
  inside `Main`, with `import` lines moved above; the wrapper never changes what the code does, and
  the viewer shows and highlights the block's own lines. `JdiTrace.java` runs it under the Java
  debugger and records each line of the example's own classes (library code is not stepped); when
  stepping fails the example runs output only and the trace notes why. Lab starter code with `TODO`
  bodies does not compile, so `label --try` skips it. No browser run.
- **JavaScript.** Blocks fenced `js`, `javascript` or `node` with `console.log` and no browser or
  network objects (`document`, `window`, `fetch`, `$(`, a `require` of a package). They run in Node,
  output only; Edit and run works in the browser (a Web Worker, stopped after 5 seconds).
- **C.** As before (gdb), except that a program that calls `fork`, `exec*`, `pthread_create`,
  `signal` or reads input runs output only: gdb stepping across processes and threads is unreliable.
  Kernel-module code has no `main` and is never suggested.
- **MIPS.** Blocks fenced `mips`, `asm`, `s` or with no language that use MIPS registers (`$t0`, `$sp`)
  and have a `main:` label or a `syscall`, and `.s` and `.asm` files under `files/` (manifest entries,
  section 4). `mipstrace.py` assembles and runs them (the SPIM and MARS subset: directives, the core
  instructions, the usual pseudo-instructions and syscalls 1, 4, 5, 8 to 12, 17 and 34 to 36), with
  MARS's memory layout (text at 0x00400000, data at 0x10010000, `$sp` 0x7fffeffc; SPIM puts `main` 0x24
  higher). SPIM runs the same program in the runner as the reference: when the outputs differ the
  trace is marked approximate and shows SPIM's. `input="5\n7"` answers read syscalls, one line each.
  Edit and run works in the browser (Pyodide).
- **VHDL.** Blocks fenced `vhdl` that declare an entity and an architecture, and folders or `.zip` files
  under `files/` holding `.vhd` files with a testbench (manifest entries). GHDL imports every file (the
  block, its `setup=` blocks, or the folder or zip), builds the testbench (the entity with no ports,
  preferring a name ending in `tb`) with VHDL-2008, or VHDL-93c with the Synopsys libraries when 2008
  fails, and runs it with `--vcd` to 2 us (`args="--stop-time=5us"` changes that). A testbench block
  that instantiates an entity from an earlier block gets `setup=` with that block. A design block
  without a testbench is only analyzed: its trace says it analyzed cleanly and that nothing is
  simulated there (code-viz never writes a testbench). Lab fragments (a port list, one `generate`
  statement) are not suggested. No browser run.

## 8. Reading the viewer

`<site>/viz/` lists every example by page; `#<id>` opens one; `?step=N` opens at step N.

**Controls.** `|<` first step, `<` previous (left arrow key), Play, `>` next (right arrow key), `>|`
last, and the slider. "step i of n" sits beside them; `truncated` means the run hit the step cap.
**Edit** opens the code in a text box with **Run**; **Reset** returns to the original example after a
re-run. **QR** shows the student QR code (teacher view only). A link at the top opens the course
page the example came from (teacher view only).

**Code and output.** The current line is highlighted. The output pane shows only what the program
had printed by this step, so step forward to watch it grow. An error message shows with the
output at the end of the run.

**Panels, by kind:**

- **env, Python.** One box per frame, newest at the bottom, the current frame outlined. A variable
  holding a number or string shows it in place; anything else is an arrow to an object on the right
  (list cells with indexes, dict rows, instances with their attributes). A function object shows
  its parameters and the variables its closure captured, with a "defined in" badge and an arrow to
  that frame. A frame drawn faded has returned but is still alive because a closure refers to it.
- **env, Scheme.** One box per environment, "Global environment" first, each with a "parent E<n>"
  badge. The current environment is outlined; faded ones are not on the current chain. Closures show
  their parameters, body and environment, with an arrow to it. The expression being evaluated is
  above the boxes. The note "diagram from code-viz's Scheme model; output from Guile" means the model's
output differed from Guile's, and the output shown is Guile's.
- **lambda.** The term tree with the redex about to fire highlighted, the reduction sequence below,
  and a switch between normal and applicative order (they can differ, or one can loop). A note lists
  the predefined names the term used (section 13).
- **bison.** Left: the state graph, zoomed on the current state. Right: the stack table (states and
  symbols), the lookahead token and the action (shift, reduce by rule N, accept, error), and the parse
  tree built so far.
- **automaton.** The graph with the current state set highlighted; the input above it shows what has
  been read and what is left, and can be edited to try another string (accepted or rejected shows on
  the last step).
- **c.** One box per stack frame with locals and arguments (type and value). Arrays are rows of
  cells; structs are tables; a pointer is an arrow to the variable it points at.
- **agent.** A timeline of events; the step slider moves through them and the program line that
  caused each one is highlighted. A model call shows the model, the prompt or messages, the reply,
  tokens in and out and seconds. A retrieval shows the query and every passage ranked by score with
  its source, top k marked. A prompt event shows the prompt assembled from those passages.
- **cast.** A terminal that replays each command and its output in time.
- **plain.** The program and its output only.

## 9. Teacher view and student mode

**Teacher view** (`<site>/viz/#<id>`): two columns for a projector. Edit re-runs Python, Scheme and
lambda in the browser; other languages re-run only on a `code-viz serve` server (section 11). The QR
button and the page link are here.

**Student mode** (`<site>/viz/?student=1#<id>`): what students open on their own phone or laptop,
with no setup and nothing installed.

- One column, larger text, the step controls pinned to the bottom of the screen within thumb reach,
  code and output capped in height so the diagram stays close.
- Python, Scheme and lambda examples have **Edit and run**: the code runs in the student's browser
  with Pyodide, using the same tracers as the build, so a student can change a value and step
  through the new run. **Reset** goes back to the original example.
- C, bison, automaton, agent and shell examples replay their recorded run read-only, with the note
  "Recorded run: step through it".
- A student's edits are saved as a draft in their own browser's localStorage
  (`code-viz-draft:<path>:<id>`), so a reload keeps them; Reset deletes the draft. If storage is
  blocked (a private window), drafts are simply not kept.
- Nothing leaves the student's browser: no edits, no runs, no names. The page loads the trace and
  the libraries (Pyodide on first Edit and run) and does everything else locally.
- No QR button and no link out to the course page (the page may hold material the student view
  should not lead to). The page asks search engines not to index it.

## 10. QR codes in class and on slides

**In class:** open the example in the teacher view and press **QR**. A large QR code of the student
link fills the screen, with the link printed under it for anyone who cannot scan. Close, a click
outside the code, or Escape dismisses it. The code is drawn in the browser (qrcode-generator), so it
works offline once the page has loaded.

**On slides and handouts:** `code-viz qr <id> ...` writes `viz/qr/<id>.svg` and `.png`. Commit
`viz/qr/` so the course site serves the images. `--snippet` prints a block to paste into a deck:

```
<!-- code-viz QR for cs374-liascript-scope-chains-9 -->
![Scan to open this example on your phone](https://billjr99.github.io/Ursinus-CS374-Fall2026/viz/qr/cs374-liascript-scope-chains-9.svg)
[Open this example](https://billjr99.github.io/Ursinus-CS374-Fall2026/viz/?student=1#cs374-liascript-scope-chains-9)
```

With `--out files/qr` the image address becomes `<site>/files/qr/<id>.svg`.

Use the SVG on slides (sharp at any size); use the PNG with `--scale 14` or more for print. A code
should be at least about a quarter of the slide's height to scan from the back of a room.

## 11. Live mode in class

`code-viz serve` serves the course repo and adds `POST /viz/api/run`, so Edit and Run also works for
C, bison, automata, shell and (with `--ollama-network`) agent examples, each edit running in a fresh
throwaway container.

Limits and fallback:

- It listens on 127.0.0.1 only. Students can reach it only with `--public` and only when their
  devices are on a network that can reach the machine (campus Wi-Fi often isolates clients). Docker
  has to be reachable from where `serve` runs (locally, or `--host`).
- Every run costs a container start (a second or more, longer for C and bison); a whole class
  pressing Run at once queues on one CPU per container.
- Use it from the teaching machine for live demos. For students, prefer the published student link:
  Python, Scheme and lambda run in their browser without any server, and the rest replay.
- On the static site, Run for a container language answers "no code-viz server here: start one with
  code-viz serve" instead of running.

## 12. Recording agent examples

Agent examples (Python programs calling Ollama, as in CS357) are recorded once on a machine with
Ollama, committed, and replayed; CI never re-runs them.

1. Start a throwaway Ollama on its own Docker network, answering to the name `ollama`:
   ```
   docker network create cviz-ollama
   docker run -d --rm --name cviz-ollama-srv --network cviz-ollama --network-alias ollama ollama/ollama
   docker exec cviz-ollama-srv ollama pull llama3.2:1b      # and any model or embedder the examples use
   ```
2. Record: `code-viz build --record-agents --ollama-network cviz-ollama` (or `--page` one page). The
   agents runner joins only that network; agent programs reach Ollama at `http://ollama:11434`
   (override with `OLLAMA_HOST`). code-viz warns when no container on the network is named or
   aliased `ollama`.
3. Commit `viz/traces/` and remove the container, the network and the Ollama image afterwards.

The agents runner image itself is built with `--network host` (pip downloads), like every runner.

## 13. Tips

- **Lambda predefined names.** TRUE, FALSE, AND, OR, NOT, IF, ZERO to FOUR, SUCC, PLUS, MULT,
  ISZERO, PAIR, FST, SND, I, K, KI, S, C, B and OMEGA replace matching free names, so a variable
  called B, C, I, K or S becomes that combinator. The panel lists the ones a term used. To keep one
  as a variable, add a line `-- free: B` (several: `-- free: B C`) or use lowercase names. In a
  lambda block, `NAME = term` lines are definitions used by the last line.
- **Step cap.** Traces stop at 800 steps (lambda: 200 reductions) and are marked truncated. Keep
  examples small, or raise it for one block with `max_steps=`.
- **Mystery-language exercises.** The env panel shows every variable, so visualizing a block whose
  point is a hidden value spoils it. In CS374, `cs374-liascript-bindingscope-5` (the Mystery Scoping
  Language) shows `RULE`. Do not project it or share its QR code until after the reveal, or
  `code-viz unlabel` it.
- **Stable outputs.** Do not print times, dates, random numbers without a seed, or `id()` values in
  an example; each build then looks like a change. Seed randomness, or accept that the example is
  only checked for running.
- **Setup cells.** Give a page's Setup cell its own label (it is usually worth stepping through
  once), then label the cells after it with `setup=`. Keep setup cells free of slow or random work;
  it runs before every dependent cell.
- **Stable ids.** Never renumber ids that are on slides or QR codes; add new examples at new ids.
- **Inputs.** Give stdin with `input="..."`; an example that waits for input without one times out.
- **Test before class.** Open the student link on a phone before class; the first Edit and run
  downloads Pyodide (several megabytes), so ask students to open the link before the run you want them to
  try.

## 14. Trace format

One JSON file per example, `viz/traces/<id>.json` (published gzipped as `.json.gz`):

```
{
  "version": 1, "id": "...", "kind": "env|lambda|bison|automaton|c|agent|cast|plain",
  "language": "python|scheme|lambda|flexbison|dot|c|cpp|...", "source": "the code",
  "steps": [ ... ],            kind-specific, below
  "stdout": "the whole output", "error": null or "message", "truncated": false,
  "page": "_pages/...md", "line": 123, "viz": "...", "lang": "...",
  "setup": {"ids": [...], "source": "the setup code"}     only with setup= (and notebook cells)
  "figures": [{"png": "base64", "at": 123}], "figures_dropped": 2     only when the example drew
  "interp": {"page", "files": [...], "entry", "source"}       only with interp= (the interpreter that ran it)
}
```

Steps by kind:

- **env, Python:** `{line, event (line|return|exception), stack: [{id, func, line, vars: {name: value}}], heap: {ref: object}, out: chars of stdout so far, ret?, zombies?}`.
  A value is `{"p": primitive}` or `{"r": ref}`. Objects: `{t: list|tuple|set|dict, items}`,
  `{t: function, name, params, closure: {name: value}, parent}`, `{t: instance, class, attrs}`.
- **env, Scheme:** `{expr, note, env, chain: [env ids], frames: {id: {name, parent, vars}}, closures: {id: {name, params, env, body}}, out}`;
  a value is `{"p": printed}` or `{"c": closure id}`. `reference_stdout` is Guile's output; `approximate` is true when it differs from the model's.
- **lambda:** `{term, tree, redex: path or null}` in `orders.normal` and `orders.applicative`; a tree node is `{k: var|lam|app, ...}` and a path is a string of f/a/b steps. `prelude_used` maps each predefined name the term used to its definition.
- **bison:** `{action, token, stack, stack_after, state, tree}`; plus top-level `rules`, `graph` (DOT), `input`, `files`.
- **automaton:** `{read, rest, states}`; plus `automaton: {states, start, accept, edges: [[from, to, symbol]]}` and `input`.
- **c:** `{line, file, stack: [{func, line, vars: {name: {v|ptr|array|struct, type, addr}}}], out}`.
- **agent:** `events` (also `steps`): `{t, line, type: model-call|embedding|retrieval|prompt|tool-call|print, model, messages|prompt, reply, tokens_in, tokens_out, seconds, vectors, dims, uses, name, arguments, text}`; a retrieval event has `{function, query, k, metric, passages: [{rank, score, id, source, text, top}]}`; plus `recorded`. A retrieval is caught when a function in the program returns, or holds in a local, a list of (score, passage) pairs sorted by score.
- **cast:** `cast: {header, events: [[time, "o", text]]}` (asciinema v2).
- **sql:** `{line, end, sql, kind: query|change|schema|other, result?: {columns, rows, more}, changes?, tables: {name: {columns, rows, more}}, changed: [names], error?, out}`.
- **java** (kind `env`, language `java`): the Python step shape, `{line, event, stack: [{func, line, vars}], heap, out}`; a value is also `{"x": literal}` (true, false, null, 'c'); objects are `{t: array, class, items, more?}`, `{t: list, class: ArrayList, items}`, `{t: instance, class, attrs}` or `{t: <type>, repr}`. An output-only Java trace has kind `plain` and a `note`.
- **mips:** `{line, pc, ins, regs: {index: value} (changed only; 32 is hi, 33 lo), mem: [[address, size, value]] (writes), out}`; plus top-level `regs0` (34 starting values), `labels`, `data: {base, hex}`, `reference_stdout` (SPIM's) and `approximate`.
- **wave:** `steps: [{t, changed: [names]}]` (the times a signal changed, in femtoseconds), plus `signals: [{name, width, changes: [[t, value]]}]`, `end`, `top` (the testbench), `std`; `analyzed_only` when there was no testbench.

## 15. Where things run and safety

Containers run where Docker is: locally (a laptop with Docker, or GitHub Actions), or on another
machine over SSH with `--host user@machine` (or `CODE_VIZ_HOST`), using `sudo -n docker` there.
Every example runs in a throwaway container from its runner image: no network (the agents runner
reaches only the Ollama network), one CPU, 1 GB of memory, 256 processes, a time limit per example
and per batch, and the container is removed afterwards. Runner images are removed at the end of
each command unless `--keep-images`. Runner images are built with `--network host` because
downloads timed out on a default bridge network.

On Bill's machines the containers run on minipc (`--host bill@10.0.0.26`, or `CODE_VIZ_HOST`),
never on minipc2; staging folders move to `~/scratch/` when done.

**What needs containers and what runs in the browser.** Containers are needed only to *build*:
`build`, `run`, `label --try` and `serve`'s Run button. The published `viz/` is a static site: the
viewer, every trace, the step controls, the QR dialog and student mode run entirely in the reader's
browser with no server, from the course's GitHub Pages site, and keep working when no container
host exists. Re-running an *edited* example in the browser (student mode's Edit and run) works for
Python, Scheme, lambda calculus and automata, whose tracers run in Pyodide (loaded on first use);
for C, bison, shell, agents and the plain languages (Haskell, Prolog, OCaml, Mini) the browser
replays the recorded run, and editing them needs `code-viz serve` with a container host.

Environment variables:

| variable | meaning |
|---|---|
| `CODE_VIZ_HOST` | user@host to run containers on over SSH (same as `--host`), e.g. `bill@10.0.0.26` |
| `OLLAMA_HOST` | where agent examples reach Ollama inside the agents runner (default `http://ollama:11434`) |

## 16. CI

CI builds `viz/` and commits it, so nobody has to run `build` by hand after a deck edit.

**Files.** The steps live in one shared workflow, `.github/workflows/code-viz.yml` in
Ursinus-Boilerplate-Code. Each course repo carries a short caller, `.github/workflows/code-viz.yml`
("code-viz"), copied from `course/viz/workflow.yml`, which runs the shared workflow at
`Ursinus-Boilerplate-Code@main`. Changing the shared file changes every course at once.

**When it runs.** On a push to `gh-pages` that changes `_pages/**.md`, `files/**` or
`viz/manifest.json`; by hand (Actions, code-viz, Run workflow, or `gh workflow run code-viz.yml`);
and after the course's `update-submodules.yml` ("Reset and Sync Submodules") moved the `code`
submodule. That workflow's last step starts code-viz itself, because a commit pushed with the
workflow token starts no other workflow; it only does so when the repo has `code-viz.yml` and the
`code` pointer actually changed.

**What it does** (on the branch that started it):

1. Stops at once, changing nothing, when the repo has no code-viz labels (`<!-- run: ... -->` in
   `_pages/`) and no `viz/index.json`, `viz/manifest.json` or `viz/notebooks.json`. A course that has not started using
   code-viz therefore gets no `viz/` folder and no commits; `code-viz build` itself also writes
   nothing in that case.
2. Clones Ursinus-Boilerplate-Code into the runner's temporary folder, outside the repo, at the
   commit the repo's `code` submodule points at (Boilerplate main when there is no submodule); it
   fails when that commit is not in Ursinus-Boilerplate-Code.
3. Runs `code-viz build --check` with the runner's own Docker (runner images built and removed as
   usual). Recorded agent examples are not re-run; their committed recordings are kept. When an
   example stopped running it fails and commits nothing; a changed output is listed in the log
   (expected outputs are only rewritten by `build --update-expected`, run by hand).
4. Refuses to commit, and fails, when anything outside `viz/` changed, so pages, syllabi, decks,
   `files/` and the other submodules are never touched by CI.
5. When `viz/` changed, commits it as `github-actions[bot]` ("code-viz: rebuild viz/ [skip ci]"),
   fetches and rebases onto the branch (three tries, backing out a failed rebase each time, for
   pushes that land meanwhile), pushes, and starts
   "Deploy GitHub Pages" (`build-pages.yml`) by hand, since the bot's push starts no workflow.

Because traces are written deterministically and unchanged traces are not rewritten, a run with no
real change commits nothing. What CI does not do: label blocks, add links (`code-viz links`), record
agent examples (needs Ollama: record on minipc, section 12), or update expected outputs.

**Adding it to a course repo.** Copy `course/viz/workflow.yml` to `.github/workflows/code-viz.yml`,
and add the last step of `update-submodules.yml` (the "Rebuild code-viz pages when the code
submodule moved" step, with `id: autocommit` on the commit step and `actions: write` in its
permissions). Both are safe in a repo with no examples. The added step, as it is in every course:

```yaml
      - name: Rebuild code-viz pages when the code submodule moved
        if: steps.autocommit.outputs.changes_detected == 'true' && hashFiles('.github/workflows/code-viz.yml') != ''
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          if git diff --quiet HEAD~1 HEAD -- code; then
            echo "code did not move; code-viz not needed"
          else
            gh workflow run code-viz.yml --ref "${GITHUB_REF_NAME}" -R "${GITHUB_REPOSITORY}" \
              || echo "WARNING: could not start code-viz; run it by hand (Actions > code-viz > Run workflow)."
          fi
```

## 17. Troubleshooting

| symptom | cause and fix |
|---|---|
| "No trace for <id>" in the viewer | the id is not built or was renamed: `code-viz build --page ...`, commit `viz/traces/` |
| Edit and run does nothing for a while | Pyodide is downloading on first use (several megabytes); wait, or open the page earlier |
| "no code-viz server here" on Run | a container language on the static site; use `code-viz serve`, or step through the recorded run |
| QR button shows no code | the qrcode-generator script did not load (offline before first load); reload online, or use `code-viz qr` images |
| `docker build` times out | the runner downloads need the network; code-viz builds with `--network host`; check the host's internet |
| agent example errors "connection refused" | no Ollama answering to `ollama` on `--ollama-network`; see section 12 |
| `build --check` fails after a deck edit | an example stopped running: fix the block, or `--update-expected` if the change is intended |
| CI fails with "code-viz changed files outside viz/" | a code-viz bug wrote outside `viz/`; nothing was committed. The log lists the files; fix code-viz, then re-run the workflow |
| CI committed `viz/` but the site did not change | "Deploy GitHub Pages" did not start (the log warns); run it by hand (Actions, Deploy GitHub Pages, Run workflow) |
| a deck example has no Visualize link | it was labeled without `--links`: `code-viz links`, then commit the page |
| a drawing example shows no figure | the program never called `plt.show()` and closed its figure, or the ezgraphics window was never drawn on; or the 8-figure / 600 KB cap was reached (`figures_dropped`) |
| an ezgraphics or turtle example fails with AttributeError | it calls something the headless stand-in does not support (section 7, Figures): add it to `tracers/pystubs/`, or leave the block unlabeled |
| a notebook cell fails in `label --notebooks --try` | an earlier cell needs data or a service the container does not have (Google Drive files, a GPU, the network); it stays unlabeled |
| `label` rewrote every line of a page | it cannot now: pages keep their line ending and are only written when something was added; if an old copy did, `git checkout` the page |
| every build changes an output | the example prints a time or random value (section 13) |
| a lambda variable B or K acts like a combinator | predefined names; add `-- free: B` or use lowercase |
| `label --try` refuses a cell that uses an earlier cell's names | label the earlier cell first, then run `label` again (it adds `setup=`), or write `setup=<id>` by hand |
| an example says "setup: NameError ..." | the setup chain is incomplete: add the missing cell's id to `setup=` |
| the `--snippet` image is a local path | `--out` is not served by the site; use the default `viz/qr/` or a folder in the repo |
| `code-viz qr` refuses an id | not a labeled example or in `viz/index.json`; check `code-viz catalog`, or `--force` |
| SSH to `--host` asks for a password | key login and passwordless `sudo -n docker` are needed on that host |

## 18. Known problems and limits

- Step traces stop at 800 steps (lambda: 200) and are marked truncated.
- Model output varies, so agent outputs are never compared; outputs with timestamps always look
  changed.
- Of CS374's 8 Mini blocks, 7 run through the project guide's Python interpreter (`interp=page`);
  Exercise 7.2 (`make_counter`) prints nothing, so it stays unlabeled. Haskell and OCaml run whole (no
  steps) and none qualified yet; `cs374-tutorial-c-for-flex-bison-1` gives no gdb steps.
- Large bison state graphs lay out slowly on phones.
- The Python tracer keeps every object and frame it has drawn alive until the run ends (so their
  numbers stay stable), so an example about `__del__` or weak references behaves differently under
  the tracer.
- Scheme frames are a model of the evaluator, not Guile itself; "approximate" marks a difference.
- Live mode is one machine's Docker; it does not scale to a whole class running at once.
- The CI path filter misses submodule-only changes (section 16).
- The viewer needs a current browser (DecompressionStream for the gzipped traces).
- Not labeled on purpose (2026-11-14): CS170's `sounds` examples (they play audio), CS474's AutoGen
  examples (pieces of an assignment's instructions, configured for OpenAI `gpt-4` with the student's
  own key; recording them with Ollama would change the code students write), CS377's `pymongo` and
  `cassandra` examples (they connect to database servers the container does not have), and
  TensorFlow (too large for the runner).
- Java: only the example's own classes are stepped, java.util collections other than ArrayList show
  their type and size, threads other than main are not stepped, and programs that read `System.in`
  run without input. Most CS173 blocks are lab starter code with `TODO` bodies that do not compile.
- MIPS: floating-point (coprocessor 1) instructions and exceptions are not simulated; addresses in the
  text segment follow MARS, not SPIM.
- VHDL: most CS274 VHDL blocks are lab fragments (a port list, a `generate` loop) with no testbench,
  so they are not examples; signals are recorded at the testbench's top level only.
- SQL: SQLite's dialect only.

## 19. Output files

```
viz/index.html, viz/viewer.js, viz/viewer.css    the viewer (static; no server needed)
viz/tracers/                                     the in-browser tracers (Pyodide)
viz/traces/<id>.json.gz                          one trace per example (section 14)
viz/expected/<id>.out                            the expected output, checked by build --check
viz/qr/<id>.svg, viz/qr/<id>.png                 QR codes of student links (code-viz qr)
viz/figures.js                                    shows figures (section 7, Figures)
viz/index.json, viz/catalog.json, viz/manifest.json, viz/notebooks.json
```

## 20. Testing code-viz itself

Test in throwaway containers, never on a teaching machine's own Python. `screenshot.py` opens a
built viewer in headless Chromium (Playwright) and saves PNGs or checks that pages render; `--phone`
uses a 390 x 844 touch viewport and `--student` opens the student link:

```
docker run --rm -v $PWD:/w -w /w mcr.microsoft.com/playwright/python:v1.48.0-jammy \
  sh -c "pip install -q playwright==1.48.0 && python3 code/course/viz/screenshot.py viz shots --phone --student cs374-liascript-scope-chains-9"
```

Remove the Playwright image and any containers and networks afterwards.

## 21. Modes and URL arguments

The viewer shows an example in up to three modes. A tab for each mode sits in the header, in the
teacher view and in student mode, and only the modes the example has data for appear:

| mode | answers | data |
|---|---|---|
| Run | what does this code do when it runs? | the trace, `viz/traces/<id>.json.gz` (everything in sections 7 to 14) |
| Explain | how do we read and build up this code? | a tour, `viz/tours/<id>.json` (section 22) |
| Simulate | what happens when we run these commands? | a recorded session, `viz/sessions/<id>.json.gz` (section 23) |

You can switch tabs at any time, whatever mode the link opened in. Each mode keeps its own place, so
going back to a tab returns to where you were. A tour's `run` step knows its trace step, so moving
from Explain to Run lands on the same moment of the program.

URL arguments. The old ones mean exactly what they always did, so every link and QR code already
handed out keeps working:

| argument | meaning |
|---|---|
| `#<id>` | the example to open |
| `?student=1` | student mode (section 9) |
| `?step=N` | Run mode: open at trace step N |
| `?mode=run`, `explain` or `simulate` | the mode to open in (new) |
| `&t=N` | Explain mode: open at tour step N, from 0 (new) |
| `&s=N` | Simulate mode: open at session step N, from 0 (new) |
| `&tour=<name>` | Explain mode: a named tour, when an example has more than one (new) |

With no `mode`, the viewer opens in Run when there is a trace, else Explain, else Simulate. When the
link asks for a mode the example has no data for, the viewer opens the best mode it has and says so
in one line above the code; it never shows an error page. The QR button encodes the current mode and
step, so students land on what is on the screen.

Presenter keys, in every mode: Space or the right arrow for the next step, the left arrow for the
previous one, Home for the first, B to blank the screen (any key brings it back), and 1, 2 or 3 to
switch to Run, Explain or Simulate.

`viz/index.json` lists each example's `modes` (for example `["run", "explain"]`) and, when an example
has named tours, `tours`. An entry with no `modes` is Run only. A repo with no `codeviz/` folder and
no `viz=session` blocks gets no `modes` at all, so its `viz/` stays exactly as it was.

## 22. Explain mode and the tour format

A tour is a guided walkthrough of one example: show the lines in reading order, point at the line
that matters, ask the class to predict, then show the program's state at that moment. Tours are
written by hand (or drafted, below) and live outside `viz/`, because CI owns `viz/`:

- `codeviz/tours/<id>.json` is the default tour of example `<id>`;
- `codeviz/tours/<id>--<name>.json` is another tour of the same example (URL `&tour=<name>`).

`code-viz build` checks every tour and publishes the good ones to `viz/tours/`. A tour with a problem
is listed in the build's output and not published, so a broken tour never reaches students.

The format (version 1) is defined in `schemas/tour.schema.json`. Field names follow VS Code's
CodeTour where the two overlap (`title`, `description`, `steps[].title`, `steps[].description`,
`steps[].line`), so a tour reads naturally to anyone who knows CodeTour:

```
{"version": 1, "example": "cs374-liascript-scope-chains-1", "title": "The paper machine, executed",
 "description": "How a lookup walks the chain of frames.", "reviewed": false,
 "steps": [
  {"kind": "reveal", "lines": "1-4", "description": "Start with the frame: a dictionary and a parent."},
  {"kind": "focus", "lines": "9-10", "description": "lookup walks the chain upward."},
  {"kind": "predict", "question": "Which x does the inner lookup find?", "answer": "The innermost one."},
  {"kind": "run", "trace_step": 41, "lines": "9", "description": "Here is the walk, one frame at a time."},
  {"kind": "stage", "stage": "cs374-liascript-scope-chains-2", "description": "Now add assignment."}
 ]}
```

| kind | what it does | needs |
|---|---|---|
| `reveal` | shows these lines, added to the lines already shown; the rest stay hidden | `lines` |
| `focus` | highlights these lines and dims the rest | `lines` |
| `predict` | asks the question; the answer appears with Reveal answer or on the next step | `question` (and `answer`) |
| `run` | shows the program's state at a trace step, the same view as Run mode | `trace_step` |
| `stage` | switches the code to another labeled block (building code up), animating only the lines that changed | `stage` (a block id) |

`lines` are 1-based line numbers of the example's code, as ranges (`"1-4,9"`); `line: N` (CodeTour's
form) means the same as `lines: "N"`. In a source file, `note` is accepted for `description`. Every
step must say something: a `description`, a `question` or a `title`. There are no timings in a tour.

A build-up tour moves through stages: each stage is its own labeled block on the page, usually
chained with `setup=` so each one runs. From a `stage` step on, line numbers refer to that stage's
code, and `run` steps use that stage's trace.

`reviewed` is false until Bill has read the tour; the viewer marks an unreviewed tour with a small
"draft" badge, and `source` records who drafted it.

Commands:

```
code-viz tour check [ids] [-v]       check every tour (schema, lines inside the code, trace steps, stage ids)
code-viz tour draft <ids> | --all    write a drafting prompt per example (default codeviz/drafts/)
```

`tour draft` writes, for each example, a prompt with the code (numbered), the deck's own text before
and after it, the trace's first visit to each line, the format above, and Bill's writing rules in
short form. code-viz calls no model itself: a person or a helper gives the prompt to a model, saves
the reply as `codeviz/tours/<id>.json`, and runs `tour check`. `codeviz/drafts/` is never published.

## 23. Simulate mode, sessions and recording

A session is a terminal session that was run for real and recorded: shell commands and Docker
commands, each with its output, its exit status, and what Docker looked like afterwards. The viewer
replays it step by step, so a class can watch containers start, see which folder a container can
reach, and try the next command themselves, without Docker on their own machines.

Nothing is simulated by guessing. A session's output is always a recording of the real commands, and
a command that was not recorded gets a hint, never made-up output.

Where a session comes from:

- a scenario file, `codeviz/sessions/<id>.json` (or `.yaml`), for a session that is not on a page;
- a shell block on a page labeled `viz=session`: its commands are the scenario, one per line (a
  leading `$ ` is dropped, comment lines are skipped, a line ending in `\` joins the next). Label
  fields `images=a,b`, `network=` and `timeout=` fill in the rest.

A scenario (format version 1, `schemas/session.schema.json`):

```
{"version": 1, "id": "cs357-isolation-1", "title": "A container that sees one folder",
 "scenario": {"commands": ["mkdir -p shared && echo hi > shared/note.txt",
                           "docker run --rm -v \"$PWD/shared:/data:ro\" alpine:3.20 ls /data"],
              "images": ["alpine:3.20"], "network": "isolated", "watch": ["shared"]},
 "branches": [{"name": "no-mount", "after": 1, "description": "Forget -v: the container sees nothing.",
               "commands": ["docker run --rm alpine:3.20 ls /data"]}]}
```

- `commands` run in order in one shell, so `cd` and variables carry over;
- `images` are pulled first and must name a tag (never `latest`);
- `network` is `none` (no network at all), `isolated` (the sandbox's own Docker networks only, the
  default) or `internet` (needed when a command downloads something);
- `files` are written into the work folder first, and `watch` folders have their file listing
  snapshotted after each command;
- `branches` are "what if" variants: run the first `after` main-line steps, then these commands, and
  record them too, so the class can see what goes wrong.

`code-viz record <id>` runs the scenario on the recording host (minipc, with `--host`) inside a
throwaway Docker-in-Docker sandbox: a pinned `docker:dind` container with its own Docker daemon, so
nothing the session does touches the host's Docker. After each command it saves the output, the exit
status, the time it took, and a snapshot of the sandbox's containers, images, networks, ports,
volumes and watched folders. It then masks what changes from run to run (container and image ids,
`sha256:` digests, timestamps, Docker's random container names, temporary paths) to stable labels
such as `<container-1>`, adds any `masking` rules from the scenario, and writes
`viz/sessions/<id>.json.gz`. The recording is committed, like agent recordings; CI never records.

`code-viz session check` reports a scenario that has not been recorded, and a recording whose
scenario changed since (it is stale; record it again). `code-viz record --check <id>` records again
and lists what changed, so a new Docker version that changes a message shows up as a difference to
look at, not a stale slide.

The Simulate view: the terminal replay on the left, and on the right a `docker ps` panel and a
diagram of containers, the networks that join them, published ports and mounted folders, updated at
every step. Below the terminal, students can type the next command: if it is the command that was
recorded (spacing aside), the recording plays; if it is not, they get a hint toward the expected
command. Recorded branches are listed as buttons beside the step controls.
