# code-viz

Run a course site's code examples in throwaway containers and step through what they do in a
static viewer. The full command reference, with examples for every subcommand, is in the header of
[`code-viz`](code-viz) (`code-viz --help` prints it).

```
course/viz/
  code-viz        the command: catalog, label, run, build, serve
  runners/        one Dockerfile per toolchain: python, scheme, c, flexbison, mini, haskell, prolog, ocaml, agents, shell
  tracers/        step tracers that run inside the containers (pure Python where possible, so the
                  viewer can also run Python, Scheme and lambda examples in the browser with Pyodide)
  viewer/         the static viewer (index.html, viewer.js, viewer.css)
  workflow.yml    a GitHub Actions template for course repos
```

## Labels

A code block is an example when a hidden comment sits on the line above its fence:

    <!-- run: id=cs374-liascript-scopechains-3 viz=env -->
    ```python
    ...
    ```
    [Visualize this example](https://billjr99.github.io/Ursinus-CS374-Fall2026/viz/#cs374-liascript-scopechains-3) <!-- code-viz link -->

`code-viz label --try --links` writes both lines. The link goes after any LiaScript run macro
(`@LIA.eval(...)`, `@Pyodide.eval`) that follows the fence, so the deck's own Run button keeps
working. Bison grammars and automata, which are files rather than blocks, are listed in
`viz/manifest.json` (generated from `files/`, editable).

## Kinds of visualization

| viz | languages | what the panel shows |
|---|---|---|
| env | Python | frames with their variables, objects on the heap (lists, dicts, instances), functions with the variables their closures capture, arrows from names to objects and from closures to the frame that defined them; frames kept alive by a closure stay on screen after they return |
| env | Scheme | environments (frames) with parent links, closures with an arrow to their defining environment, the expression being evaluated; output checked against Guile |
| lambda | lambda calculus | the term tree with the next redex highlighted, the reduction sequence, normal and applicative order side by side; standard Church encodings (TRUE, AND, SUCC, PAIR, S, K, ...) are available by name |
| bison | flex + bison | the LR state stack, lookahead and action at each step (shift, reduce by rule N, accept), the parse tree as it grows, and bison's state graph with the current state highlighted |
| automaton | DOT (files/dotty) | the automaton with its current state set highlighted as it reads an input string (DFA, NFA, ε-NFA); the input can be edited in the page |
| c | C, C++ | stack frames with locals and arguments, arrays as cells, structs, pointers drawn as arrows to the variable they point at (gdb steps the program) |
| agent | Python calling Ollama | a timeline of model calls (model, prompt or messages, reply, tokens, seconds), embeddings, tool calls and printed output; recorded once on a machine with Ollama and replayed |
| cast | shell | a terminal replay of each command and its output |
| plain | Haskell, Prolog, OCaml, Mini | the program and its output (no step trace) |

## Trace format (version 1)

One JSON file per example, `viz/traces/<id>.json`:

```
{
  "version": 1, "id": "...", "kind": "env|lambda|bison|automaton|c|agent|cast|plain",
  "language": "python|scheme|lambda|flexbison|dot|c|cpp|...", "source": "the code",
  "steps": [ ... ],            kind-specific, below
  "stdout": "the whole output", "error": null or "message", "truncated": false,
  "page": "_pages/...md", "line": 123, "viz": "...", "lang": "..."
}
```

Steps by kind:

- **env, Python:** `{line, event (line|return|exception), stack: [{id, func, line, vars: {name: value}}], heap: {ref: object}, out: chars of stdout so far, ret?, zombies?}`.
  A value is `{"p": primitive}` or `{"r": ref}`. Objects: `{t: list|tuple|set|dict, items}`,
  `{t: function, name, params, closure: {name: value}, parent}`, `{t: instance, class, attrs}`.
- **env, Scheme:** `{expr, note, env, chain: [env ids], frames: {id: {name, parent, vars}}, closures: {id: {name, params, env, body}}, out}`;
  a value is `{"p": printed}` or `{"c": closure id}`. `reference_stdout` is Guile's output; `approximate` is true when it differs from the model's.
- **lambda:** `{term, tree, redex: path or null}` in `orders.normal` and `orders.applicative`; a tree node is `{k: var|lam|app, ...}` and a path is a string of f/a/b steps.
- **bison:** `{action, token, stack, stack_after, state, tree}`; plus top-level `rules`, `graph` (DOT), `input`, `files`.
- **automaton:** `{read, rest, states}`; plus `automaton: {states, start, accept, edges: [[from, to, symbol]]}` and `input`.
- **c:** `{line, file, stack: [{func, line, vars: {name: {v|ptr|array|struct, type, addr}}}], out}`.
- **agent:** `events` (also `steps`): `{t, type: model-call|embedding|tool-call|print, model, messages|prompt, reply, tokens_in, tokens_out, seconds, name, arguments, text}`; plus `recorded`.
- **cast:** `cast: {header, events: [[time, "o", text]]}` (asciinema v2).

`viz/expected/<id>.out` holds each example's expected output; `code-viz build --check` fails when
an output changes, so a deck edit that breaks an example is caught.

## Safety

Every example runs in a throwaway container from its runner image: no network (the agents runner
reaches only the Ollama container on its own Docker network), one CPU, 1 GB of memory, 256
processes, a time limit per example and per batch, and the container is removed afterwards. On
Bill's machines the containers run on minipc (`--host bill@10.0.0.26`, or `CODE_VIZ_HOST`), never
on minipc2, with `sudo -n docker`; staging folders move to `~/scratch/code-viz/` when done.
