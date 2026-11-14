"""code-viz shell recorder.

Runs a shell example one command at a time in bash and records an asciinema v2 cast (the prompt,
each command as typed, and its output with timing), so the viewer can replay it.

Usage:  python3 shellcast.py SCRIPT.sh > trace.json

PIPELINE  driver.py in the shell runner for viz=cast examples.

TRACE FIELDS WRITTEN
  kind "cast", language "shell", source, stdout, error, truncated, cast: {version 2 header,
  events: [[seconds, "o", text]]}; the viewer replays events step by step.

EXAMPLE  python3 shellcast.py setup.sh > t.json

LIMITS AND KNOWN PROBLEMS
  - Runs with no network, so commands that download (pip, curl, apt) fail in the recording;
    such examples are better left unlabeled or shown as plain text.
"""
import json
import subprocess
import sys
import time


def commands(src):
    out, buf = [], ""
    for line in src.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        s = line[2:] if line.startswith("$ ") else line
        buf = buf + "\n" + s if buf else s
        if not s.rstrip().endswith("\\"):
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def main(path):
    src = open(path, encoding="utf-8").read()
    t0, events, all_out, error = time.time(), [], [], None
    for cmd in commands(src):
        events.append([round(time.time() - t0, 3), "o", "$ "])
        for ch in cmd:
            events.append([round(time.time() - t0, 3), "o", ch])
        events.append([round(time.time() - t0, 3), "o", "\r\n"])
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=20)
        text = (r.stdout + r.stderr).replace("\n", "\r\n")
        all_out.append(r.stdout + r.stderr)
        if text:
            events.append([round(time.time() - t0, 3), "o", text])
        if r.returncode != 0:
            error = f"exit {r.returncode}: {cmd}"
            break
    json.dump({"version": 1, "kind": "cast", "language": "shell", "source": src,
               "cast": {"header": {"version": 2, "width": 100, "height": 30}, "events": events},
               "steps": [{"t": e[0]} for e in events[::20]], "stdout": "".join(all_out), "error": error,
               "truncated": False}, sys.stdout)


if __name__ == "__main__":
    main(sys.argv[1])
