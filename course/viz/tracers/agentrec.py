"""code-viz agent recorder.

Runs a CS357-style agent example (Python that calls an Ollama or OpenAI-compatible endpoint) and
records a timeline: every model call (endpoint, model, the prompt or messages, the reply, token
counts, time), every tool call the program makes through those calls, and the program's own
printed lines (retrieved chunks, judge scores and so on), each with a timestamp. Model runs vary,
so a recording is made once and replayed by the viewer; it is never re-run in CI.

It works by patching the HTTP layer (urllib, requests, httpx) inside the program's process, so
the example code is unchanged.

Usage:  python3 agentrec.py PROGRAM.py > trace.json
Environment: OLLAMA_HOST (default http://ollama:11434) is honoured by the examples themselves.
"""
import io
import json
import runpy
import sys
import time

T0 = time.time()
EVENTS = []
OUT = io.StringIO()


def now():
    return round(time.time() - T0, 3)


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
            EVENTS.append({"t": now(), "type": "tool-call", "name": tc.get("function", {}).get("name"),
                           "arguments": tc.get("function", {}).get("arguments")})
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
    ev["reply"] = "".join(replies)[:4000]
    EVENTS.append(ev)


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
    def write(self, s):
        OUT.write(s)
        for line in s.splitlines():
            if line.strip():
                EVENTS.append({"t": now(), "type": "print", "text": line[:500]})
        return len(s)


def main(path):
    patch()
    src = open(path, encoding="utf-8").read()
    old = sys.stdout
    sys.stdout = Tee()
    error = None
    import shlex
    sys.argv = [path] + shlex.split(os.environ.get("CVIZ_ARGS", ""))  # the label's args=, else none
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit:
        pass
    except BaseException as e:
        error = f"{type(e).__name__}: {e}"
    finally:
        sys.stdout = old
    EVENTS.sort(key=lambda e: e["t"])
    json.dump({"version": 1, "kind": "agent", "language": "python", "source": src, "events": EVENTS,
               "steps": EVENTS, "stdout": OUT.getvalue(), "error": error, "truncated": False,
               "recorded": time.strftime("%Y-%m-%d %H:%M")}, sys.stdout)


if __name__ == "__main__":
    main(sys.argv[1])
