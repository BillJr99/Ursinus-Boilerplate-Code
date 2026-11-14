/* code-viz Simulate mode (mode-simulate.js): replay a recorded terminal session step by step.

   Full manual: the header of code-viz (`code-viz readme`, or README.md), section 23 Simulate mode,
   sessions and recording; section 21 for the tabs and URL arguments.

   WHAT IT SHOWS
   A session (viz/sessions/<id>.json.gz) was run for real and recorded by `code-viz record`: each
   command with its output, exit status, time, and what Docker looked like afterwards. Nothing here is
   guessed: every output on screen is a recording.
     left    the terminal: every command so far with its output, the current one marked; below it,
             a prompt where students type the next command. The recorded command (spacing aside)
             plays its recording; anything else gets a hint toward the expected command, never
             invented output.
     right   a docker ps table, a diagram of containers grouped by network, with published ports
             and mounted folders, and the watched folders' file listings, all as they were after
             the current step.
   Recorded "what if" branches appear as buttons beside the step controls; choosing one replays the
   main line up to the branch point, then the branch's own recorded steps.

   URL: ?mode=simulate&s=N#<id> opens at step N (from 0); &branch=<name> opens on a branch.
*/
(function () {
  "use strict";
  const S = { sess: null, id: null, step: 0, branch: "" };
  const V = () => window.CVIZ_VIEWER;
  const el = (id) => document.getElementById(id);
  const norm = (c) => String(c || "").trim().replace(/\s+/g, " ");

  function steps() {
    const s = S.sess;
    if (!S.branch) return s.steps || [];
    const b = (s.branches || []).find((x) => x.name === S.branch);
    return b ? (s.steps || []).slice(0, b.after).concat(b.steps || []) : (s.steps || []);
  }

  function terminal(list) {
    const esc = V().esc;
    let h = "";
    list.forEach((st, i) => {
      if (i > S.step) return;
      h += `<div class="tline${i === S.step ? " now" : ""}"><span class="prompt">$</span> ${esc(st.cmd)}</div>`;
      if (st.output) h += `<div class="tout${i === S.step ? " now" : ""}">${esc(st.output.replace(/\n$/, ""))}</div>`;
      if (st.exit) h += `<div class="texit">exit ${st.exit}</div>`;
    });
    return h || '<div class="note">Press the right arrow (or type the first command below) to start.</div>';
  }

  // The diagram: one box per network, the containers attached to it inside, ports and mounts as tags.
  function diagram(state) {
    const esc = V().esc;
    const cs = state.containers || [];
    if (!cs.length) return '<p class="note">No containers yet.</p>';
    const nets = {};
    for (const c of cs) for (const n of (c.networks && c.networks.length ? c.networks : ["(no network)"])) (nets[n] = nets[n] || []).push(c);
    let h = '<div class="netdiag">';
    for (const [n, list] of Object.entries(nets)) {
      h += `<div class="net"><div class="netname">network ${esc(n)}</div>`;
      for (const c of list) {
        h += `<div class="ctr ${/^up|running/i.test(c.status || "") ? "up" : "down"}"><b>${esc(c.name)}</b><span class="img">${esc(c.image || "")}</span>`;
        for (const p of c.ports || []) h += `<span class="tag port" title="published port">${esc(p)}</span>`;
        for (const m of c.mounts || []) h += `<span class="tag mount" title="mounted folder">${esc(m)}</span>`;
        h += "</div>";
      }
      h += "</div>";
    }
    return h + "</div>";
  }

  function panel(st) {
    const esc = V().esc;
    const state = (st && st.state) || {};
    let h = "";
    if (st && st.note) h += `<p class="tournote">${esc(st.note)}</p>`;
    const cs = state.containers || [];
    h += '<div class="panel-sub">docker ps -a</div>';
    h += cs.length ? '<table class="dps"><tr><th>name</th><th>image</th><th>status</th><th>ports</th></tr>' +
      cs.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.image || "")}</td><td>${esc(c.status || "")}</td><td>${esc((c.ports || []).join(", "))}</td></tr>`).join("") + "</table>"
      : '<p class="note">No containers.</p>';
    h += '<div class="panel-sub">Containers, networks, ports and mounts</div>' + diagram(state);
    if (state.images && state.images.length) h += `<div class="panel-sub">Images</div><p class="mono">${state.images.map(esc).join("<br>")}</p>`;
    if (state.volumes && state.volumes.length) h += `<div class="panel-sub">Volumes</div><p class="mono">${state.volumes.map(esc).join("<br>")}</p>`;
    for (const [dir, files] of Object.entries(state.files || {})) {
      h += `<div class="panel-sub">Files in ${esc(dir)}</div><pre class="mono">${files.length ? files.map(esc).join("\n") : "(empty)"}</pre>`;
    }
    return h;
  }

  function render() {
    const list = steps(), n = list.length;
    S.step = Math.max(0, Math.min(S.step, Math.max(0, n - 1)));
    const st = list[S.step];
    el("slider").max = Math.max(0, n - 1); el("slider").value = S.step;
    el("stepinfo").textContent = n ? `step ${S.step + 1} of ${n}` : "no steps recorded";
    el("code").innerHTML = terminal(list);
    const now = el("code").querySelector(".now:last-of-type") || el("code").lastElementChild;
    if (now) now.scrollIntoView({ block: "nearest" });
    el("output").textContent = st ? `took ${st.duration != null ? st.duration + " s" : "?"}, exit ${st.exit}` : "";
    el("paneltitle").textContent = "After this step";
    el("panel").innerHTML = panel(st);
    const nxt = list[S.step + 1];
    const box = el("simcmd");
    if (box) { box.disabled = !nxt; box.placeholder = nxt ? "Type the next command and press Enter" : "That was the last command"; }
  }

  function tryCommand() {
    const box = el("simcmd"), hint = el("simhint"), list = steps(), nxt = list[S.step + 1];
    if (!box || !nxt) return;
    const typed = norm(box.value);
    if (!typed) return;
    if (typed === norm(nxt.cmd)) {
      box.value = ""; hint.textContent = ""; S.step++; render();
    } else {
      const want = norm(nxt.cmd).split(" ");
      const got = typed.split(" ");
      let k = 0; while (k < want.length && k < got.length && want[k] === got[k]) k++;
      const head = want.slice(0, Math.max(1, Math.min(k + 1, 3))).join(" ");
      hint.textContent = `That is not the command that was recorded here. Hint: it starts with "${head}".`;
    }
  }

  function chrome(on) {
    // Edit, Reset and Play belong to Run mode; the prompt and branch buttons belong to this mode.
    for (const id of ["edit", "reset", "play"]) { const b = el(id); if (b) b.style.display = on ? "none" : ""; }
    el("setupbox").hidden = true;
    const f = el("figures"); if (f) f.hidden = true;
    const sim = el("simbar"); if (sim) sim.hidden = !on;
    document.querySelectorAll(".panel-title").forEach((p) => { if (p.textContent === "Code" || p.textContent === "Terminal") p.textContent = on ? "Terminal" : "Code"; });
  }

  function branches() {
    const x = el("extra"); x.innerHTML = "";
    const bs = S.sess.branches || [];
    if (!bs.length) return;
    const mk = (name, label, title) => {
      const b = document.createElement("button");
      b.textContent = label; b.title = title || ""; b.className = S.branch === name ? "on" : "";
      b.onclick = () => { S.branch = name; S.step = 0; branches(); render(); };
      x.appendChild(b);
    };
    mk("", "main", "The session as recorded");
    for (const b of bs) mk(b.name, "what if: " + (b.title || b.name), b.description || "");
  }

  window.CVIZ_MODES.register("simulate", {
    async show(ctx) {
      if (S.id !== ctx.id || !S.sess) {
        S.sess = await ctx.fetchJson("sessions/" + encodeURIComponent(ctx.id) + ".json.gz");
        S.id = ctx.id; S.step = 0;
        const b = ctx.params.get("branch") || "";
        S.branch = (S.sess.branches || []).some((x) => x.name === b) ? b : "";
      }
      if (ctx.pos !== undefined) S.step = ctx.pos;
      el("list").hidden = true; el("example").hidden = false;
      el("title").textContent = `${S.sess.title || ctx.id}  ·  simulate`;
      if (ctx.meta.page_url) { el("pagelink").href = ctx.meta.page_url; el("pagelink").textContent = "Open the page this session is on"; }
      else el("pagelink").textContent = "";
      el("editor").hidden = true; el("code").hidden = false;
      chrome(true);
      branches();
      const box = el("simcmd");
      if (box) { box.value = ""; box.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); tryCommand(); } }; }
      const hint = el("simhint"); if (hint) hint.textContent = "";
      render();
    },
    go(to) {
      if (!S.sess) return;
      S.step = typeof to === "string" ? S.step + Number(to) : to;
      const hint = el("simhint"); if (hint) hint.textContent = "";
      render();
    },
    pos() { return S.step; },
    url() { const u = { s: S.step }; if (S.branch) u.branch = S.branch; return u; },
    hide() { chrome(false); el("extra").innerHTML = ""; },
  });
})();
