"""code-viz agent recorder.

Runs a CS357-style agent example (Python that calls an Ollama or OpenAI-compatible endpoint) and
records a timeline: every model call (endpoint, model, the prompt or messages, the reply, token
counts, time), every tool call the program makes through those calls, and the program's own
printed lines (judge scores and so on), each with a timestamp and the program line that produced
it. Retrieval is recorded as its own event: when a function in the program returns (or holds in a
local) a ranked list of (score, passage) pairs, the recorder keeps the query (the function's first
string argument), every passage with its score and source file, and which ones were returned (top
k). Output or a prompt that contains retrieved passages is marked as the assembled prompt. Model runs vary,
so a recording is made once and replayed by the viewer; it is never re-run in CI.

It works by patching the HTTP layer (urllib, requests, httpx) inside the program's process, so
the example code is unchanged.

Usage:  python3 agentrec.py PROGRAM.py > trace.json
Environment: OLLAMA_HOST (default http://ollama:11434) is honoured by the examples themselves.
"""
import io
import json
import os
import runpy
import sys
import time

T0 = time.time()
EVENTS = []
OUT = io.StringIO()
PROG = None        # absolute path of the program, to find its own lines on the stack
PASSAGES = {}      # retrieved passage text -> id, to spot the prompt assembled from them


def now():
    return round(time.time() - T0, 3)


def prog_line(frame=None):
    """The line in the program (not a library) that is running now."""
    f = frame or sys._getframe(1)
    while f is not None:
        if PROG and os.path.abspath(f.f_code.co_filename) == PROG:
            return f.f_lineno
        f = f.f_back
    return None


def add(ev, frame=None):
    ev.setdefault("line", prog_line(frame or sys._getframe(1)))
    EVENTS.append(ev)


# ---------- retrieval ----------
SRC_RE = None


def _score_pos(x):
    if isinstance(x, (tuple, list)) and len(x) >= 2:
        for i in (0, -1):
            v = x[i]
            if isinstance(v, float) or (isinstance(v, int) and not isinstance(v, bool)):
                return i
    if isinstance(x, dict):
        for k in ("score", "similarity", "distance"):
            if isinstance(x.get(k), (int, float)):
                return k
    return None


def ranked(v):
    """A list of (score, passage) pairs sorted best first, or None."""
    try:
        if not isinstance(v, (list, tuple)) or len(v) < 2 or len(v) > 5000:
            return None
        pos = _score_pos(v[0])
        if pos is None or any(_score_pos(x) != pos for x in v):
            return None
        scores = [float(x[pos]) for x in v]
        if scores != sorted(scores, reverse=True) and scores != sorted(scores):
            return None
        out = []
        for x in v:
            rest = {k: x[k] for k in x if k != pos} if isinstance(x, dict) else ([y for j, y in enumerate(x) if j != (pos % len(x))])
            out.append((float(x[pos]), rest))
        return out
    except Exception:
        return None


def passage(item):
    """(id, source file, text) from whatever the program keeps per passage."""
    import re as _re
    strs = []

    def walk(o, key=None):
        if isinstance(o, str):
            strs.append((key, o))
        elif isinstance(o, dict):
            for k, val in o.items():
                walk(val, k)
        elif isinstance(o, (list, tuple)) and len(o) <= 8:
            for val in o:
                walk(val)
    walk(item)
    text = max((s for _, s in strs), key=len, default="")
    src = next((s for k, s in strs if k in ("source", "file", "doc", "path")), None) or \
        next((s for _, s in strs if s != text and _re.fullmatch(r"[\w./ -]+\.\w{1,5}", s)), None)
    pid = next((s for _, s in strs if s not in (text, src) and len(s) < 60), None)
    return pid, src, text


def profiler(frame, event, arg):
    if event != "return" or not PROG or os.path.abspath(frame.f_code.co_filename) != PROG:
        return
    try:
        code = frame.f_code
        if code.co_name.startswith("<"):
            return
        ret = ranked(arg)
        full = None
        for name, val in frame.f_locals.items():
            r = ranked(val) if isinstance(val, (list, tuple)) else None
            if r and (full is None or len(r) > len(full)):
                full = r
        if not ret and not full:
            return
        if not full or (ret and len(ret) > len(full)):
            full = ret
        k = len(ret) if ret else frame.f_locals.get("k") or frame.f_locals.get("top_k") or len(full)
        args = [frame.f_locals.get(n) for n in code.co_varnames[:code.co_argcount]]
        query = next((a for a in args if isinstance(a, str)), None)
        rows = []
        for rank, (score, item) in enumerate(full):
            pid, src, text = passage(item)
            rows.append({"rank": rank + 1, "score": round(score, 4), "id": pid, "source": src,
                         "text": text[:600], "top": rank < k})
            if rank < k and len(text) >= 12:
                PASSAGES[text[:200]] = pid or src or f"#{rank + 1}"
        metric = "cosine" if "cosine" in frame.f_globals and callable(frame.f_globals["cosine"]) else "score"
        add({"t": now(), "type": "retrieval", "function": code.co_name, "query": query, "k": k,
             "metric": metric, "passages": rows}, frame)
    except Exception:
        pass


def uses(text):
    return [pid for snippet, pid in PASSAGES.items() if snippet and snippet in text]


def summarize_request(url, body):
    try:
        data = json.loads(body) if body else {}
    except (ValueError, TypeError):
        data = {}
    ev = {"t": now(), "type": "model-call", "url": url, "model": data.get("model")}
    if "messages" in data:
        ev["messages"] = [{"role": m.get("role"), "content": str(m.get("content"))[:4000]} for m in data["messages"]]
    if "prompt" in data:
        ev["prompt"] = str(data["prompt"])[:4000]
    if "tools" in data:
        ev["tools"] = [t.get("function", {}).get("name") for t in data.get("tools", [])]
    if "input" in data:
        ev["input"] = str(data["input"])[:2000]
    return ev


def summarize_response(ev, raw):
    ev["seconds"] = round(now() - ev["t"], 3)
    text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    replies = []
    for line in text.splitlines() or [text]:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        msg = d.get("message") or {}
        if msg.get("content"):
            replies.append(msg["content"])
        if d.get("response"):
            replies.append(d["response"])
        for tc in msg.get("tool_calls") or []:
            add({"t": now(), "type": "tool-call", "name": tc.get("function", {}).get("name"),
                 "arguments": tc.get("function", {}).get("arguments")}, sys._getframe(1))
        for ch in d.get("choices") or []:
            c = (ch.get("message") or {}).get("content")
            if c:
                replies.append(c)
        if "eval_count" in d:
            ev["tokens_out"] = d.get("eval_count")
            ev["tokens_in"] = d.get("prompt_eval_count")
        if "usage" in d:
            ev["tokens_in"] = d["usage"].get("prompt_tokens")
            ev["tokens_out"] = d["usage"].get("completion_tokens")
        if "embedding" in d or "embeddings" in d:
            ev["type"] = "embedding"
            vecs = d.get("embeddings") or [d.get("embedding")]
            if vecs and isinstance(vecs[0], list):
                ev["vectors"], ev["dims"] = len(vecs), len(vecs[0])
    ev["reply"] = "".join(replies)[:4000]
    asked = " ".join(m["content"] for m in ev.get("messages", [])) + ev.get("prompt", "")
    if uses(asked):
        ev["uses"] = uses(asked)
    add(ev, sys._getframe(1))


import os
import re

OLLAMA = os.environ.get("OLLAMA_HOST", "http://ollama:11434").rstrip("/")


def redirect(url):
    """Examples call Ollama on localhost; in the recorder it runs in its own container."""
    return re.sub(r"^https?://(localhost|127\.0\.0\.1)(:11434)?", OLLAMA, str(url))


def patch():
    import urllib.request
    orig = urllib.request.urlopen

    def urlopen(req, *a, **k):
        if isinstance(req, str):
            req = urllib.request.Request(redirect(req))
        elif hasattr(req, "full_url"):
            req.full_url = redirect(req.full_url)
        url = req.full_url if hasattr(req, "full_url") else str(req)
        body = req.data if hasattr(req, "data") else None
        ev = summarize_request(url, body)
        resp = orig(req, *a, **k)
        raw = resp.read()
        summarize_response(ev, raw)
        fake = io.BytesIO(raw)
        fake.status, fake.headers, fake.getcode = resp.status, resp.headers, (lambda: resp.status)
        fake.__enter__ = lambda *x: fake
        fake.__exit__ = lambda *x: False
        return fake
    urllib.request.urlopen = urlopen
    try:
        import requests
        orig_send = requests.Session.send

        def send(self, req, **k):
            req.url = redirect(req.url)
            ev = summarize_request(req.url, req.body)
            r = orig_send(self, req, **k)
            summarize_response(ev, r.content)
            return r
        requests.Session.send = send
    except ImportError:
        pass
    try:
        import httpx
        orig_hsend = httpx.Client.send

        def hsend(self, req, **k):
            req.url = httpx.URL(redirect(req.url))
            ev = summarize_request(str(req.url), req.content)
            r = orig_hsend(self, req, **k)
            r.read()
            summarize_response(ev, r.content)
            return r
        httpx.Client.send = hsend
    except ImportError:
        pass


class Tee(io.TextIOBase):
    """One event per print call, so a prompt printed in one go stays one event."""
    def write(self, s):
        OUT.write(s)
        if s.strip():
            ev = {"t": now(), "type": "print", "text": s.rstrip("\n")[:4000]}
            u = uses(s)
            if u:
                ev["type"], ev["uses"] = "prompt", u
            add(ev, sys._getframe(1))
        return len(s)


def main(path):
    global PROG
    PROG = os.path.abspath(path)
    patch()
    src = open(path, encoding="utf-8").read()
    old = sys.stdout
    sys.stdout = Tee()
    error = None
    import shlex
    sys.argv = [path] + shlex.split(os.environ.get("CVIZ_ARGS", ""))  # the label's args=, else none
    sys.setprofile(profiler)
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit:
        pass
    except BaseException as e:
        error = f"{type(e).__name__}: {e}"
    finally:
        sys.setprofile(None)
        sys.stdout = old
    EVENTS.sort(key=lambda e: e["t"])
    json.dump({"version": 1, "kind": "agent", "language": "python", "source": src, "events": EVENTS,
               "steps": EVENTS, "stdout": OUT.getvalue(), "error": error, "truncated": False,
               "recorded": time.strftime("%Y-%m-%d %H:%M")}, sys.stdout)


if __name__ == "__main__":
    main(sys.argv[1])
