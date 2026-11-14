/* code-viz viewer. Static: loads index.json and traces/<id>.json from the same folder.
   Address: viz/#<example id>; viz/ alone lists every example. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
  const state = { trace: null, step: 0, timer: null, order: "normal", index: null, pyodide: null };

  // ---------- routing ----------
  async function loadIndex() {
    if (state.index) return state.index;
    try { state.index = await (await fetch("index.json", { cache: "no-store" })).json(); }
    catch (e) { state.index = { examples: [] }; }
    return state.index;
  }

  async function route() {
    stop();
    const id = decodeURIComponent(location.hash.replace(/^#/, ""));
    const idx = await loadIndex();
    if (!id) return showList(idx);
    let t;
    try { t = expand(await loadTrace(id)); }
    catch (e) { $("list").hidden = false; $("example").hidden = true; $("list").innerHTML = `<p class="err">No trace for ${esc(id)}.</p>`; return; }
    const meta = (idx.examples || []).find((e) => e.id === id) || {};
    showTrace(t, meta);
  }

  async function loadTrace(id) {
    // traces are gzipped; the browser decompresses them (DecompressionStream)
    const r = await fetch("traces/" + encodeURIComponent(id) + ".json.gz", { cache: "no-store" });
    if (!r.ok) throw new Error("no trace");
    const buf = await r.arrayBuffer();
    const b = new Uint8Array(buf);
    // gzip magic number; a server that already decompressed it hands back plain JSON
    if (b[0] === 0x1f && b[1] === 0x8b) {
      const text = await new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
      return JSON.parse(text);
    }
    return JSON.parse(new TextDecoder().decode(b));
  }

  // A compact trace stores, per step, only the objects that changed and the ids still present.
  function expand(t) {
    if (!t.compact) return t;
    const keys = t.language === "python" ? ["heap"] : ["frames", "closures"];
    const cur = {};
    for (const k of keys) cur[k] = {};
    for (const s of t.steps || []) {
      for (const k of keys) {
        const next = {};
        for (const id of s[k + "_ids"] || []) next[id] = (s[k] && id in s[k]) ? s[k][id] : cur[k][id];
        s[k] = next; cur[k] = next;
      }
    }
    t.compact = 0;
    return t;
  }

  function showList(idx) {
    $("example").hidden = true; $("list").hidden = false;
    $("title").textContent = (idx.course || "").toUpperCase() + " examples";
    $("pagelink").textContent = "";
    const by = {};
    for (const e of idx.examples || []) (by[e.page] = by[e.page] || []).push(e);
    let h = `<p class="note">${(idx.examples || []).length} examples, built ${esc(idx.built || "")}. Choose one to step through it.</p>`;
    for (const page of Object.keys(by).sort()) {
      h += `<h2>${esc(page.replace(/^_pages\//, ""))}</h2>`;
      for (const e of by[page]) {
        h += `<div class="item"><span class="tag">${esc(e.viz)} · ${esc(e.lang)}</span><a href="#${esc(e.id)}">${esc(e.id)}</a>` +
             `${e.error ? ' <span class="err">(' + esc(String(e.error).slice(0, 60)) + ")</span>" : ""}</div>`;
      }
    }
    $("list").innerHTML = h;
  }

  // ---------- example ----------
  function stepsOf(t) {
    if (t.kind === "lambda") return (t.orders && t.orders[state.order]) || t.steps || [];
    if (t.kind === "agent") return t.events || t.steps || [];
    if (t.kind === "cast") return (t.cast && t.cast.events) || [];
    return t.steps || [];
  }

  function showTrace(t, meta) {
    state.trace = t; state.step = 0;
    $("list").hidden = true; $("example").hidden = false;
    $("title").textContent = `${t.id || ""}  ·  ${t.viz || t.kind} · ${t.lang || t.language || ""}`;
    if (meta.page_url) { $("pagelink").href = meta.page_url; $("pagelink").textContent = "Open the page this example is on"; }
    else $("pagelink").textContent = "";
    $("editor").hidden = true; $("code").hidden = false;
    const n = stepsOf(t).length;
    $("slider").max = Math.max(0, n - 1);
    // Start partway through the first call, so the page opens on something worth looking at.
    state.step = Number(new URLSearchParams(location.search).get("step") || 0) || 0;
    buildExtra(t);
    renderCode(t.source || "");
    render();
  }

  function buildExtra(t) {
    const x = $("extra"); x.innerHTML = "";
    if (t.kind === "lambda") {
      for (const o of ["normal", "applicative"]) {
        const b = document.createElement("button");
        b.textContent = o + " order"; b.className = state.order === o ? "on" : "";
        b.onclick = () => { state.order = o; state.step = 0; $("slider").max = Math.max(0, stepsOf(t).length - 1); buildExtra(t); render(); };
        x.appendChild(b);
      }
    }
    if (t.kind === "automaton") {
      x.innerHTML = 'input <input id="autoin" value="' + esc(t.input || "") + '"> <span id="verdict"></span>';
      $("autoin").oninput = () => { t.input = $("autoin").value; t.steps = simulate(t.automaton, t.input); state.step = 0; $("slider").max = t.steps.length - 1; render(); };
    }
    if (t.approximate) x.insertAdjacentHTML("beforeend", ' <span class="note">(diagram from code-viz\'s Scheme model; output from Guile)</span>');
    if (t.truncated) x.insertAdjacentHTML("beforeend", ' <span class="note">(trace stops early: step limit)</span>');
  }

  function renderCode(src) {
    $("code").innerHTML = src.split("\n").map((l, i) => `<span class="ln" data-n="${i + 1}">${esc(l) || " "}</span>`).join("");
  }

  function currentLine(t, s) {
    if (!s) return null;
    if (t.kind === "env" && t.language === "python") return s.line;
    if (t.kind === "c") return s.line;
    return null;
  }

  function render() {
    const t = state.trace; if (!t) return;
    const steps = stepsOf(t);
    const n = steps.length;
    state.step = Math.max(0, Math.min(state.step, Math.max(0, n - 1)));
    $("slider").value = state.step;
    $("stepinfo").textContent = n ? `step ${state.step + 1} of ${n}` : "no steps";
    const s = steps[state.step];
    document.querySelectorAll("#code .ln").forEach((el) => el.classList.remove("cur", "prev"));
    const ln = currentLine(t, s);
    if (ln) {
      const el = document.querySelector(`#code .ln[data-n="${ln}"]`);
      if (el) { el.classList.add("cur"); el.scrollIntoView({ block: "nearest" }); }
      const prev = currentLine(t, steps[state.step - 1]);
      if (prev && prev !== ln) { const p = document.querySelector(`#code .ln[data-n="${prev}"]`); if (p) p.classList.add("prev"); }
    }
    // output so far
    let out = t.stdout || "";
    if (s && typeof s.out === "number" && (t.kind === "env" || t.kind === "c")) out = (t.stdout || "").slice(0, s.out);
    $("output").innerHTML = esc(out) + (t.error && state.step === n - 1 ? `<span class="err">\n${esc(t.error)}</span>` : "");
    const P = { env: t.language === "scheme" ? schemePanel : pyPanel, lambda: lambdaPanel, bison: bisonPanel, automaton: autoPanel,
                c: cPanel, agent: agentPanel, cast: castPanel };
    (P[t.kind] || plainPanel)(t, s, steps);
  }

  // ---------- arrows ----------
  function drawArrows(container, pairs) {
    const old = container.querySelector("svg.arrows"); if (old) old.remove();
    const box = container.getBoundingClientRect();
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "arrows");
    svg.setAttribute("width", container.scrollWidth); svg.setAttribute("height", container.scrollHeight);
    svg.innerHTML = '<defs><marker id="ah" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" style="fill:var(--accent);stroke:none"/></marker></defs>';
    for (const [a, b] of pairs) {
      if (!a || !b) continue;
      const r1 = a.getBoundingClientRect(), r2 = b.getBoundingClientRect();
      const x1 = r1.left + r1.width / 2 - box.left + container.scrollLeft, y1 = r1.top + r1.height / 2 - box.top + container.scrollTop;
      const x2 = r2.left - box.left + container.scrollLeft - 2, y2 = r2.top + 12 - box.top + container.scrollTop;
      const back = r2.right < r1.left + 4;  // the target is to the left: go out the left side, in at its right side
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      if (back) {
        const sx = r1.left - box.left + container.scrollLeft, ex = r2.right - box.left + container.scrollLeft + 2;
        const c = Math.max(30, (sx - ex) / 2);
        p.setAttribute("d", `M${sx},${y1} C${sx - c},${y1} ${ex + c},${y2} ${ex},${y2}`);
      } else {
        const c = Math.max(40, (x2 - x1) / 2);
        p.setAttribute("d", `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`);
      }
      p.setAttribute("marker-end", "url(#ah)");
      svg.appendChild(p);
    }
    container.appendChild(svg);
  }

  // ---------- Python environment diagram ----------
  function pyVal(v) {
    if (!v) return "";
    if ("p" in v) return typeof v.p === "string" ? `<span>${esc(JSON.stringify(v.p))}</span>` : esc(v.p === null ? "None" : v.p === true ? "True" : v.p === false ? "False" : v.p);
    return `<span class="ref" data-to="h${v.r}"></span>`;
  }

  function heapBox(id, o) {
    if (!o) return "";
    if (["list", "tuple", "set", "frozenset"].includes(o.t)) {
      return `<div class="obj" data-id="h${id}"><h4>${o.t}</h4><div class="cells">${o.items.map((x, i) => `<div class="cell"><small>${o.t === "set" ? "" : i}</small>${pyVal(x)}</div>`).join("") || '<span class="note-line">empty</span>'}${o.more ? `<div class="cell">+${o.more}</div>` : ""}</div></div>`;
    }
    if (o.t === "dict") {
      return `<div class="obj" data-id="h${id}"><h4>dict</h4><table>${o.items.map(([k, x]) => `<tr><td>${pyVal(k)}</td><td>${pyVal(x)}</td></tr>`).join("") || '<tr><td class="note-line">empty</td></tr>'}</table></div>`;
    }
    if (o.t === "function") {
      const cl = Object.entries(o.closure || {});
      return `<div class="clos" data-id="h${id}" data-parent="${esc(o.parent || "")}"><h4>function ${esc(o.name)}(${esc(o.params.join(", "))})${o.parent ? ` <span class="badge">defined in ${esc(o.parent)}</span>` : ""}</h4>` +
        (cl.length ? `<table>${cl.map(([k, x]) => `<tr><td>captures ${esc(k)}</td><td>${pyVal(x)}</td></tr>`).join("")}</table>` : "") + `</div>`;
    }
    if (o.t === "instance") {
      return `<div class="obj" data-id="h${id}"><h4>${esc(o.class)} instance</h4><table>${Object.entries(o.attrs).map(([k, x]) => `<tr><td>${esc(k)}</td><td>${pyVal(x)}</td></tr>`).join("")}</table></div>`;
    }
    return `<div class="obj" data-id="h${id}"><h4>${esc(o.t)}</h4><div class="note-line">${esc(o.repr || o.name || "")}</div></div>`;
  }

  function pyPanel(t, s) {
    $("paneltitle").textContent = "Frames and objects";
    const panel = $("panel");
    if (!s) { panel.innerHTML = '<p class="note">No steps recorded.</p>'; return; }
    const frames = (s.zombies || []).map((z) => Object.assign({ zombie: true }, z)).concat(s.stack);
    const fh = frames.map((f, i) => `<div class="frame${f.zombie ? " zombie" : ""}${!f.zombie && i === frames.length - 1 ? " cur" : ""}" data-frame="${esc(f.func)}"><h4>${f.func === "global" ? "Global frame" : esc(f.func) + (f.zombie ? " (returned; kept alive by a closure)" : "")}</h4><table>` +
      Object.entries(f.vars).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${pyVal(v)}</td></tr>`).join("") +
      (!f.zombie && i === frames.length - 1 && s.event === "return" ? `<tr><td>return value</td><td>${pyVal(s.ret)}</td></tr>` : "") + `</table></div>`).join("");
    const hh = Object.entries(s.heap).map(([k, o]) => heapBox(k, o)).join("");
    panel.innerHTML = `<div class="env"><div><div class="colhead">Frames</div>${fh}</div><div><div class="colhead">Objects</div>${hh}</div></div>`;
    requestAnimationFrame(() => {
      const pairs = [];
      panel.querySelectorAll(".ref").forEach((r) => pairs.push([r, panel.querySelector(`[data-id="${r.dataset.to}"]`)]));
      panel.querySelectorAll(".clos[data-parent]").forEach((c) => {
        if (!c.dataset.parent) return;
        const fr = [...panel.querySelectorAll(`.frame[data-frame="${CSS.escape(c.dataset.parent)}"]`)].pop();
        if (fr) pairs.push([c.querySelector("h4"), fr]);
      });
      drawArrows(panel, pairs);
    });
  }

  // ---------- Scheme environment diagram ----------
  function scmVal(v) { return v && "c" in v ? `<span class="ref" data-to="c${v.c}"></span>` : esc(v ? v.p : ""); }

  function schemePanel(t, s) {
    $("paneltitle").textContent = "Environments and closures";
    const panel = $("panel");
    if (!s) { panel.innerHTML = '<p class="note">No steps recorded.</p>'; return; }
    const chain = new Set(s.chain);
    const ids = Object.keys(s.frames).map(Number).sort((a, b) => a - b).filter((id) => Object.keys(s.frames[id].vars).length || chain.has(id));
    const fh = ids.map((id) => { const f = s.frames[id]; return `<div class="frame${id === s.env ? " cur" : ""}${chain.has(id) ? "" : " zombie"}" data-id="e${id}"><h4>${id === 1 ? "Global environment" : "E" + id + ": " + esc(f.name)}${f.parent && f.parent !== 1 ? ` <span class="badge">parent E${f.parent}</span>` : ""}</h4><table>` +
      Object.entries(f.vars).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${scmVal(v)}</td></tr>`).join("") + `</table></div>`; }).join("");
    const used = new Set();
    for (const id of ids) for (const v of Object.values(s.frames[id].vars)) if (v && "c" in v) used.add(String(v.c));
    const ch = Object.entries(s.closures).filter(([k]) => used.has(k)).map(([k, c]) => `<div class="clos" data-id="c${k}" data-env="e${c.env}"><h4>closure ${esc(c.name)} (λ (${esc(c.params.join(" "))}))</h4><div class="note-line">${esc(c.body)}</div><div class="note-line">environment: ${c.env === 1 ? "global" : "E" + c.env}</div></div>`).join("");
    panel.innerHTML = `<div class="note-line">evaluating <b>${esc(s.expr)}</b> (${esc(s.note)})</div><div class="env"><div><div class="colhead">Environments</div>${fh}</div><div><div class="colhead">Closures</div>${ch}</div></div>`;
    requestAnimationFrame(() => {
      const pairs = [];
      panel.querySelectorAll(".ref").forEach((r) => pairs.push([r, panel.querySelector(`[data-id="${r.dataset.to}"]`)]));
      panel.querySelectorAll(".clos").forEach((c) => pairs.push([c.querySelector("h4"), panel.querySelector(`[data-id="${c.dataset.env}"]`)]));
      drawArrows(panel, pairs);
    });
  }

  // ---------- lambda terms ----------
  function lambdaPanel(t, s, steps) {
    $("paneltitle").textContent = "Term tree (" + state.order + " order)";
    const panel = $("panel");
    if (!s) { panel.innerHTML = '<p class="note">' + esc(t.error || "No steps.") + "</p>"; return; }
    const W = 46, H = 56;
    let x = 0; const nodes = [], edges = [];
    function lay(n, d) {
      let me;
      if (n.k === "var") { me = { x: x++ * W, y: d * H, label: n.n, path: n.path }; }
      else if (n.k === "lam") { const c = lay(n.b, d + 1); me = { x: c.x, y: d * H, label: "λ" + n.v, path: n.path }; edges.push([me, c]); }
      else { const a = lay(n.f, d + 1), b = lay(n.a, d + 1); me = { x: (a.x + b.x) / 2, y: d * H, label: "@", path: n.path }; edges.push([me, a], [me, b]); }
      nodes.push(me); return me;
    }
    lay(s.tree, 0);
    const red = s.redex;
    const inRedex = (p) => red !== null && red !== undefined && p.startsWith(red);
    const w = Math.max(...nodes.map((n) => n.x)) + 60, h = Math.max(...nodes.map((n) => n.y)) + 50;
    const svg = `<svg width="${w}" height="${h}" viewBox="-30 -20 ${w} ${h}">` +
      edges.map(([a, b]) => `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`).join("") +
      nodes.map((n) => `<g class="${inRedex(n.path) ? "redex" : ""}"><circle cx="${n.x}" cy="${n.y}" r="17"/><text x="${n.x}" y="${n.y + 4}" text-anchor="middle">${esc(n.label)}</text></g>`).join("") + "</svg>";
    const next = state.step < steps.length - 1 ? steps[state.step + 1].term : null;
    panel.innerHTML = `<div class="term">${esc(s.term)}</div>` +
      `<div class="note-line">${red === null ? '<span class="okc">normal form: no redex left</span>' : "highlighted: the redex reduced next" + (next ? " → " + esc(next) : "")}</div>` +
      `<div class="tree">${svg}</div>` +
      `<div class="panel-title">Reduction sequence</div><table class="steps">${steps.map((x, i) => `<tr class="${i === state.step ? "cur" : i < state.step ? "done" : ""}"><td>${i}</td><td>${esc(x.term)}</td></tr>`).join("")}</table>`;
  }

  // ---------- graphs (Graphviz in the browser) ----------
  let viz = null;
  async function renderDot(el, dot) {
    try {
      if (!viz && window.Viz) viz = new Viz();
      if (!viz) { el.innerHTML = '<pre class="note">' + esc(dot.slice(0, 2000)) + "</pre>"; return; }
      const svg = await viz.renderSVGElement(dot);
      el.innerHTML = ""; el.appendChild(svg);
    } catch (e) { viz = null; el.innerHTML = '<p class="note">graph could not be drawn: ' + esc(e.message || e) + "</p>"; }
  }

  function highlightDot(dot, names, color) {
    const add = names.map((n) => `"${n}" [style=filled fillcolor="${color}"];`).join("\n");
    const i = dot.lastIndexOf("}");
    return i < 0 ? dot : dot.slice(0, i) + "\n" + add + "\n" + dot.slice(i);
  }

  // ---------- bison ----------
  function treeSvg(forest) {
    const W = 64, H = 50; let x = 0; const nodes = [], edges = [];
    function lay(n, d) {
      let me;
      if (!n.kids || !n.kids.length) me = { x: x++ * W, y: d * H, label: n.s };
      else { const ks = n.kids.map((k) => lay(k, d + 1)); me = { x: (ks[0].x + ks[ks.length - 1].x) / 2, y: d * H, label: n.s }; ks.forEach((k) => edges.push([me, k])); }
      nodes.push(me); return me;
    }
    forest.forEach((t) => { lay(t, 0); x += 0.5; });
    if (!nodes.length) return "";
    const w = Math.max(...nodes.map((n) => n.x)) + 90, h = Math.max(...nodes.map((n) => n.y)) + 40;
    return `<svg width="${w}" height="${h}" viewBox="-40 -18 ${w} ${h}">` + edges.map(([a, b]) => `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`).join("") +
      nodes.map((n) => `<g><circle cx="${n.x}" cy="${n.y}" r="5"/><text x="${n.x}" y="${n.y - 9}" text-anchor="middle">${esc(n.label)}</text></g>`).join("") + "</svg>";
  }

  function bisonPanel(t, s, steps) {
    $("paneltitle").textContent = "LR parse of: " + (t.input || "");
    const panel = $("panel");
    if (!s) { panel.innerHTML = '<p class="err">' + esc(t.error || "No steps.") + "</p>"; return; }
    const lo = Math.max(0, state.step - 8), hi = Math.min(steps.length, state.step + 9);
    const rows = steps.slice(lo, hi).map((x, j) => { const i = lo + j; return `<tr class="${i === state.step ? "cur" : i < state.step ? "done" : ""}"><td>${i + 1}</td><td>${esc((x.stack_after || x.stack || []).join(" "))}</td><td>${esc(x.token || "")}</td><td>${esc(x.action)}</td></tr>`; }).join("");
    panel.innerHTML = `<div class="split"><div><div class="panel-title">State stack, lookahead, action</div><table class="steps"><tr><th>#</th><th>stack</th><th>lookahead</th><th>action</th></tr>${rows}</table></div>` +
      `<div class="pair"><div><div class="panel-title">Parse tree so far</div><div class="tree">${treeSvg(s.tree || [])}</div></div>` +
      `<div><div class="panel-title">Parser state ${esc(String((s.stack_after || s.stack || []).slice(-1)[0] ?? ""))} in the state graph</div><div class="graph" id="g"></div></div></div></div>`;
    const top = (s.stack_after || s.stack || []).slice(-1)[0];
    if (t.graph) renderDot($("g"), highlightDot(t.graph, top === undefined ? [] : [String(top)], "#ffd54f"));
  }

  // ---------- automata ----------
  function closure(a, set) {
    const seen = new Set(set), todo = [...set];
    while (todo.length) { const q = todo.pop(); for (const [x, y, sym] of a.edges) if (x === q && ["ε", "eps", "epsilon", "λ", "e"].includes(sym) && !seen.has(y)) { seen.add(y); todo.push(y); } }
    return seen;
  }
  function simulate(a, inp) {
    let cur = closure(a, [a.start]); const out = [{ read: null, rest: inp, states: [...cur].sort() }];
    [...inp].forEach((ch, i) => { const nx = new Set(); for (const [x, y, sym] of a.edges) if (cur.has(x) && sym === ch) nx.add(y); cur = closure(a, nx); out.push({ read: ch, rest: inp.slice(i + 1), states: [...cur].sort() }); });
    return out;
  }
  function autoPanel(t, s, steps) {
    $("paneltitle").textContent = "Automaton";
    const panel = $("panel");
    if (!s) { panel.innerHTML = '<p class="err">' + esc(t.error || "No steps.") + "</p>"; return; }
    const done = state.step === steps.length - 1;
    const acc = s.states.some((q) => (t.automaton.accept || []).includes(q));
    const v = $("verdict"); if (v) v.innerHTML = done ? (acc ? '<span class="okc">accepted</span>' : '<span class="err">rejected</span>') : "";
    const read = (t.input || "").slice(0, (t.input || "").length - s.rest.length);
    panel.innerHTML = `<div class="term">read: <b>${esc(read)}</b><span class="note">${esc(s.rest)}</span></div>` +
      `<div class="note-line">current state${s.states.length === 1 ? "" : "s"}: ${esc(s.states.join(", ") || "none (stuck)")}</div><div class="graph" id="g"></div>`;
    renderDot($("g"), highlightDot(t.source, s.states, acc && done ? "#a5d6a7" : "#ffd54f"));
  }

  // ---------- C memory ----------
  function cVal(v) {
    if (!v) return "";
    if (v.ptr) return `<span class="ref" data-to="a${v.ptr}"></span> <span class="note">${esc(v.ptr)}${v.str !== undefined ? " " + esc(JSON.stringify(v.str)) : ""}</span>`;
    if (v.array) return `<div class="cells">${v.array.map((x, i) => `<div class="cell"><small>${i}</small>${cVal(x)}</div>`).join("")}</div>`;
    if (v.struct) return `<table>${Object.entries(v.struct).map(([k, x]) => `<tr><td>.${esc(k)}</td><td>${cVal(x)}</td></tr>`).join("")}</table>`;
    return esc(v.v);
  }
  function cPanel(t, s) {
    $("paneltitle").textContent = "Stack frames and memory";
    const panel = $("panel");
    if (!s) { panel.innerHTML = '<p class="err">' + esc(t.error || "No steps.") + "</p>"; return; }
    panel.innerHTML = `<div class="env" style="grid-template-columns:minmax(0,1fr)">${s.stack.map((f, i) => `<div class="frame${i === s.stack.length - 1 ? " cur" : ""}"><h4>${esc(f.func)}  <span class="badge">line ${f.line}</span></h4><table>` +
      Object.entries(f.vars).map(([k, v]) => `<tr data-id="a${esc(v.addr || "")}"><td>${esc(k)} <span class="note">${esc(v.type || "")}</span></td><td>${cVal(v)}</td></tr>`).join("") + "</table></div>").join("")}</div>`;
    requestAnimationFrame(() => {
      const pairs = [];
      panel.querySelectorAll(".ref").forEach((r) => pairs.push([r, panel.querySelector(`tr[data-id="${CSS.escape(r.dataset.to)}"]`)]));
      drawArrows(panel, pairs);
    });
  }

  // ---------- agent timeline ----------
  function agentPanel(t, s, steps) {
    $("paneltitle").textContent = "Agent timeline" + (t.recorded ? " (recorded " + t.recorded + ")" : "");
    const panel = $("panel");
    if (!steps.length) { panel.innerHTML = '<p class="err">' + esc(t.error || "No events recorded.") + "</p>"; return; }
    panel.innerHTML = `<div class="timeline">${steps.map((e, i) => {
      const cls = "ev" + (i === state.step ? " cur" : i > state.step ? " future" : "");
      if (e.type === "print") return `<div class="${cls}"><h5>${e.t.toFixed(2)} s · program output</h5><pre>${esc(e.text)}</pre></div>`;
      if (e.type === "tool-call") return `<div class="${cls}"><h5>${e.t.toFixed(2)} s · tool call <b>${esc(e.name)}</b></h5><pre>${esc(JSON.stringify(e.arguments, null, 1))}</pre></div>`;
      const ask = e.messages ? e.messages.map((m) => m.role + ": " + m.content).join("\n\n") : e.prompt || e.input || "";
      return `<div class="${cls}"><h5>${e.t.toFixed(2)} s · ${e.type === "embedding" ? "embedding" : "model call"} <b>${esc(e.model || "")}</b>` +
        `<span class="badge">${e.seconds !== undefined ? e.seconds + " s" : ""}</span>${e.tokens_out !== undefined ? `<span class="badge">${e.tokens_in || 0} in / ${e.tokens_out} out tokens</span>` : ""}</h5>` +
        `<details${i === state.step ? " open" : ""}><summary>prompt</summary><pre>${esc(ask)}</pre></details>${e.reply ? `<pre>${esc(e.reply)}</pre>` : ""}</div>`;
    }).join("")}</div>`;
    const cur = panel.querySelector(".ev.cur"); if (cur) cur.scrollIntoView({ block: "nearest" });
  }

  // ---------- shell cast ----------
  function castPanel(t, s, steps) {
    $("paneltitle").textContent = "Terminal";
    const text = steps.slice(0, state.step + 1).map((e) => e[2]).join("").replace(/\r\n/g, "\n");
    $("panel").innerHTML = `<div class="term-screen">${esc(text)}</div>`;
  }

  function plainPanel(t) {
    $("paneltitle").textContent = "Run";
    $("panel").innerHTML = `<p class="note">This example runs as a whole (no step trace for ${esc(t.lang || t.language || "this language")}). Its output is on the left.</p>` +
      (t.error ? `<p class="err">${esc(t.error)}</p>` : "");
  }

  // ---------- playback ----------
  function stop() { if (state.timer) { clearInterval(state.timer); state.timer = null; $("play").textContent = "Play"; } }
  $("slider").oninput = () => { stop(); state.step = Number($("slider").value); render(); };
  $("first").onclick = () => { stop(); state.step = 0; render(); };
  $("prev").onclick = () => { stop(); state.step--; render(); };
  $("next").onclick = () => { stop(); state.step++; render(); };
  $("last").onclick = () => { stop(); state.step = 1e9; render(); };
  $("play").onclick = () => {
    if (state.timer) return stop();
    $("play").textContent = "Pause";
    state.timer = setInterval(() => { if (state.step >= stepsOf(state.trace).length - 1) return stop(); state.step++; render(); }, 700);
  };
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT") return;
    if (e.key === "ArrowRight") { stop(); state.step++; render(); }
    if (e.key === "ArrowLeft") { stop(); state.step--; render(); }
  });

  // ---------- edit and re-run ----------
  $("edit").onclick = () => {
    const t = state.trace; if (!t) return;
    const on = $("editor").hidden;
    $("editor").hidden = !on; $("code").hidden = on;
    if (on) $("editbox").value = t.source || "";
    $("runnote").textContent = ["python", "scheme", "lambda"].includes(t.language || t.lang) || t.kind === "lambda"
      ? "runs here in your browser" : "runs on the code-viz server (code-viz serve)";
  };
  async function pyodide() {
    if (state.pyodide) return state.pyodide;
    $("runnote").textContent = "loading Python in the browser (first time only) ...";
    await new Promise((ok, bad) => { const s = document.createElement("script"); s.src = PYODIDE + "pyodide.js"; s.onload = ok; s.onerror = bad; document.head.appendChild(s); });
    state.pyodide = await window.loadPyodide({ indexURL: PYODIDE });
    for (const f of ["pytrace.py", "schemetrace.py", "lambdatrace.py"]) {
      const src = await (await fetch("tracers/" + f)).text();
      state.pyodide.FS.writeFile(f, src);
    }
    state.pyodide.runPython("import sys; sys.path.insert(0, '.')");
    return state.pyodide;
  }
  $("rerun").onclick = async () => {
    const t = state.trace; const code = $("editbox").value;
    const lang = t.kind === "lambda" ? "lambda" : (t.language || t.lang);
    let nt = null;
    try {
      if (["python", "scheme", "lambda"].includes(lang) && t.kind !== "agent") {
        const py = await pyodide();
        $("runnote").textContent = "running ...";
        py.globals.set("cviz_src", code);
        const mod = { python: "pytrace", scheme: "schemetrace", lambda: "lambdatrace" }[lang];
        nt = JSON.parse(py.runPython(`import json, ${mod}; json.dumps(${mod}.trace_source(cviz_src))`));
      } else {
        $("runnote").textContent = "running on the server ...";
        const r = await fetch("api/run", { method: "POST", body: JSON.stringify({ code, lang, viz: t.viz || t.kind, input: t.input || "" }) });
        if (!r.ok) throw new Error("no code-viz server here: start one with code-viz serve");
        nt = await r.json();
      }
    } catch (e) { $("runnote").textContent = "could not run: " + (e.message || e); return; }
    Object.assign(nt, { id: t.id, viz: t.viz, lang: t.lang });
    $("runnote").textContent = nt.error ? "ran with an error (see output)" : "done";
    state.trace = nt; state.step = 0; $("slider").max = Math.max(0, stepsOf(nt).length - 1);
    $("editor").hidden = true; $("code").hidden = false; renderCode(nt.source || code); buildExtra(nt); render();
  };

  window.addEventListener("hashchange", route);
  window.addEventListener("resize", () => render());
  route();
})();
