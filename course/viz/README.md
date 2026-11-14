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
18 Known problems and limits, 19 Output files, 20 Testing code-viz itself.

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
  runners/        one Dockerfile per toolchain: python, scheme, c, flexbison, mini, haskell,
                  prolog, ocaml, agents, shell, qr
  tracers/        step tracers that run inside the containers: driver.py (dispatch), pytrace.py,
                  schemetrace.py, lambdatrace.py, cstep_gdb.py, bisontrace.py, automaton.py,
                  agentrec.py, shellcast.py, cviz-repl.scm. pytrace, schemetrace, lambdatrace and
                  automaton are pure Python, so the viewer also runs them in the browser (Pyodide).
  viewer/         the static viewer: index.html, viewer.js, viewer.css
  screenshot.py   headless-browser screenshots and render checks of a built viewer
  workflow.yml    the GitHub Actions template for course repos ("code-viz check")
  README.md       generated from this header by `code-viz readme --write`
```

The pipeline, left to right:

1. **Catalog.** `code-viz catalog` scans `_pages/**/*.md` for fenced blocks at column 0. A block is
   an example when a label comment sits on the line above its fence (section 4). Files that are not
   blocks (bison grammars, `.dot` automata) come from `viz/manifest.json`.
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
| `lang=` | `python`, `scheme`, `lambda`, `c`, `cpp`, `haskell`, `prolog`, `ocaml`, `mini`, `shell` (default: the fence's language) |
| `input="..."` | text given to the program on stdin, to a bison parser, or to an automaton |
| `args="..."` | command line arguments (Python and agent examples) |
| `timeout=N` | seconds for this example (default 20; agents 300) |
| `max_steps=N` | step cap for this example (default 800) |
| `setup=ID[,ID]` | Python only: run these earlier blocks' code first, untraced and silent (below) |
| `record` | agent examples: replay the committed recording; never re-run in CI |

**Ids.** `label` makes ids as `<course>-<page>-<n>`: the course from the repo name (`cs374`), the
page's file name lowercased with other characters turned into hyphens (`liascript-scope-chains`),
and the next free number on that page (`cs374-liascript-scope-chains-3`). Ids written by hand can be
anything unique (older CS357 ones look like `cs357-tut-llmjudges-3`). Keep an id once students have its link or QR code; renumbering breaks them. Manifest entries
use the ids written in `viz/manifest.json`.

**Links.** `label --links` writes the "Visualize this example" line, marked `<!-- code-viz link -->`
so `unlabel` can find it. It goes after any LiaScript run macro (`@LIA.eval(...)`, `@Pyodide.eval`)
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
`--page`, so a one-page look never shrinks it.

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
| plain | Haskell, Prolog, OCaml, Mini | the program and its output (no step trace) |

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
  "setup": {"ids": [...], "source": "the setup code"}     only with setup=
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

Environment variables:

| variable | meaning |
|---|---|
| `CODE_VIZ_HOST` | user@host to run containers on over SSH (same as `--host`), e.g. `bill@10.0.0.26` |
| `OLLAMA_HOST` | where agent examples reach Ollama inside the agents runner (default `http://ollama:11434`) |

## 16. CI

`workflow.yml` is the template; course repos carry it as `.github/workflows/code-viz.yml`
("code-viz check"). On a push to `gh-pages` that touches `_pages/Activities`, `_pages/Tutorials` or
`viz/manifest.json`, or by hand, it checks out the repo with submodules and runs
`code-viz build --check` on the GitHub runner's local Docker. Agent examples are skipped there. The
path filter means moving only the `code` submodule does not trigger it: run it by hand
(Actions, code-viz check, Run workflow, or `gh workflow run code-viz.yml`). The committed `viz/` is
published by the course's normal Pages build.

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
- The 8 CS374 Mini-language blocks have no interpreter in the repo; Haskell and OCaml run whole (no
  steps) and none qualified yet; `cs374-tutorial-c-for-flex-bison-1` gives no gdb steps.
- Large bison state graphs lay out slowly on phones.
- The Python tracer keeps every object and frame it has drawn alive until the run ends (so their
  numbers stay stable), so an example about `__del__` or weak references behaves differently under
  the tracer.
- Scheme frames are a model of the evaluator, not Guile itself; "approximate" marks a difference.
- Live mode is one machine's Docker; it does not scale to a whole class running at once.
- The CI path filter misses submodule-only changes (section 16).
- The viewer needs a current browser (DecompressionStream for the gzipped traces).

## 19. Output files

```
viz/index.html, viz/viewer.js, viz/viewer.css    the viewer (static; no server needed)
viz/tracers/                                     the in-browser tracers (Pyodide)
viz/traces/<id>.json.gz                          one trace per example (section 14)
viz/expected/<id>.out                            the expected output, checked by build --check
viz/qr/<id>.svg, viz/qr/<id>.png                 QR codes of student links (code-viz qr)
viz/index.json, viz/catalog.json, viz/manifest.json
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
