"""code-viz session recorder (tracers/sessrec.py), run inside the "session" runner by `code-viz record`.

Full manual: the header of code-viz (`code-viz readme`, or README.md), section 23 Simulate mode,
sessions and recording.

Usage (inside the recorder container):  python3 sessrec.py SCENARIO.json OUT.json [--shell CONTAINER]

Runs the scenario's commands in order, one bash per command, under a pseudo-terminal of 100 columns
by 30 rows with HOME set to the work folder, so `docker run -it ...` and other programs that want a
terminal work with nobody typing: their input is at end of file. The shell's working folder and
exported variables carry over from one command to the next (saved in /tmp/cviz after each command),
so `cd` and `export` behave as in one terminal. Commands run in bash. With --shell, each command runs
inside that container (a scenario `shell` image, started by code-viz record in the sandbox) through
`docker exec -it`, in bash when the image has it, else in the image's sh.

After each command it saves the output as the terminal showed it, as timestamped chunks (`cast`:
[[seconds since the command started, text], ...], like asciinema's cast v2), so the viewer can replay
it at the pace it ran; the exit status; the time it took; and a snapshot of the sandbox: containers (name, image, status,
published ports, networks, mounts), images, networks, volumes, and the file listing of each watched
folder. DOCKER_HOST points at the sandbox, so every docker command here talks to the sandbox's own
daemon. Masking and the plain-text `output` are done afterwards by code-viz on the recording host.
Writes OUT.json: {"steps": [...], "docker": "<server version>"}.
"""
import json
import os
import pty
import select
import shlex
import signal
import struct
import subprocess
import sys
import termios
import fcntl
import time

COLS, ROWS = 100, 30
INTERNAL = {"cviz-shell"}          # the --shell container itself is not part of the session


def docker(*args):
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else ""


def snapshot(work, watch, shell_image):
    state = {"containers": [], "images": [], "networks": [], "volumes": [], "files": {}}
    ids = [x for x in docker("ps", "-aq").split() if x]
    info = json.loads(docker("inspect", *ids) or "[]") if ids else []
    nets = {}
    for c in info:
        name = c.get("Name", "").lstrip("/")
        if name in INTERNAL:
            continue
        ports = []
        for cport, binds in sorted(((c.get("NetworkSettings") or {}).get("Ports") or {}).items()):
            for b in binds or []:
                ports.append(f"{b.get('HostPort')}->{cport}")
        cn = sorted(((c.get("NetworkSettings") or {}).get("Networks") or {}).keys())
        for n in cn:
            nets.setdefault(n, []).append(name)
        mounts = []
        for m in c.get("Mounts") or []:
            src = m.get("Source") if m.get("Type") == "bind" else (m.get("Name") or "volume")
            mounts.append(f"{src}:{m.get('Destination')}" + ("" if m.get("RW", True) else ":ro"))
        st = c.get("State") or {}
        status = st.get("Status", "")
        if status == "exited":
            status = f"exited ({st.get('ExitCode')})"
        state["containers"].append({"name": name, "image": (c.get("Config") or {}).get("Image", ""), "status": status,
                                    "ports": ports, "networks": cn, "mounts": sorted(mounts)})
    state["containers"].sort(key=lambda x: x["name"])
    imgs = docker("images", "--format", "{{.Repository}}:{{.Tag}}").split()
    state["images"] = sorted(i for i in imgs if i and not i.startswith(shell_image or "\0") and i != "<none>:<none>")
    for line in docker("network", "ls", "--format", "{{.Name}} {{.Driver}}").splitlines():
        n, _, drv = line.partition(" ")
        if n in ("host", "none") or (n == "bridge" and n not in nets):
            continue
        state["networks"].append({"name": n, "driver": drv, "containers": sorted(nets.get(n, []))})
    state["volumes"] = sorted(v for v in docker("volume", "ls", "--format", "{{.Name}}").split() if v)
    for w in watch:
        base = os.path.join(work, w)
        entries = []
        if os.path.isdir(base):
            for dp, dn, fn in os.walk(base):
                dn.sort()
                rel = os.path.relpath(dp, base)
                for d in dn:
                    entries.append(os.path.normpath(os.path.join(rel, d)) + "/")
                for f in sorted(fn):
                    entries.append(os.path.normpath(os.path.join(rel, f)))
        state["files"][w] = sorted(entries)
    return state


def run(cmd, work, timeout, shell):
    """Run one command under a pseudo-terminal; returns (chunks [[seconds, text]], exit status, seconds)."""
    prelude = ("mkdir -p /tmp/cviz; cd \"$(cat /tmp/cviz/cwd 2>/dev/null || echo \"$HOME\")\"; "
               "[ -f /tmp/cviz/env ] && . /tmp/cviz/env; ")
    # A newline, not "; ", so a command ending in "&" or in a "# comment" cannot swallow the tail.
    tail = "\n__rc=$?; pwd > /tmp/cviz/cwd; export -p > /tmp/cviz/env; exit $__rc"
    script = prelude + cmd + tail
    if shell:
        # Tutorials assume bash (echo -e, [[ ]], arrays), so use it when the image has it; images without
        # bash (alpine and other minimal ones) fall back to their sh.
        inner = "stty cols %d rows %d 2>/dev/null; %s" % (COLS, ROWS, script)
        argv = ["docker", "exec", "-it", "-e", f"HOME={work}", "-e", f"COLUMNS={COLS}", "-e", f"LINES={ROWS}",
                "-e", "TERM=xterm", shell, "sh", "-c",
                'if command -v bash >/dev/null 2>&1; then exec bash -c "$1"; else exec sh -c "$1"; fi', "cviz", inner]
    else:
        argv = ["bash", "-c", script]
    env = dict(os.environ, HOME=work, TERM="xterm", COLUMNS=str(COLS), LINES=str(ROWS))
    t0 = time.time()
    pid, fd = pty.fork()
    if pid == 0:
        fcntl.ioctl(sys.stdout.fileno(), termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        os.chdir(work)
        os.execvpe(argv[0], argv, env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    try:
        os.write(fd, b"\x04")          # end of file on the terminal: nobody is typing
    except OSError:
        pass
    out = bytearray()
    chunks = []                       # [[seconds since start, bytes]]
    rc = None
    cut = [False]

    def keep(chunk):
        """Keep output up to 400000 bytes, then one notice; later output is read (so the program never
        blocks on a full terminal) but dropped."""
        if cut[0]:
            return
        room = 400000 - len(out)
        if len(chunk) > room:
            chunk, cut[0] = chunk[:room], True
        out.extend(chunk)
        chunks.append([round(time.time() - t0, 3), chunk])
        if cut[0]:
            chunks.append([round(time.time() - t0, 3), b"\r\n[code-viz: output cut at 400000 bytes]\r\n"])
    while True:
        left = timeout - (time.time() - t0)
        if left <= 0:
            os.kill(pid, signal.SIGKILL)
            chunks.append([round(time.time() - t0, 3), f"\r\n[code-viz: stopped after {timeout} s]\r\n".encode()])
            os.waitpid(pid, 0)
            rc = 124
            break
        r, _, _ = select.select([fd], [], [], min(left, 0.5))
        if r:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b""
            if chunk:
                keep(chunk)
                continue
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            try:
                while True:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    keep(chunk)
            except OSError:
                pass
            rc = os.waitstatus_to_exitcode(status)
            break
    os.close(fd)
    # Decode the chunks together, so a character split across two reads stays whole.
    dec, cast = __import__("codecs").getincrementaldecoder("utf-8")(errors="replace"), []
    for t, b in chunks:
        s = dec.decode(b)
        if s:
            cast.append([t, s])
    tail = dec.decode(b"", final=True)
    if tail:
        cast.append([round(time.time() - t0, 3), tail])
    return cast, rc, round(time.time() - t0, 1)


def main():
    scn = json.load(open(sys.argv[1]))
    outp = sys.argv[2]
    shell = sys.argv[sys.argv.index("--shell") + 1] if "--shell" in sys.argv else None
    shell_image = sys.argv[sys.argv.index("--shell-image") + 1] if "--shell-image" in sys.argv else None
    work = scn.get("workdir", "/work")
    os.makedirs(work, exist_ok=True)
    if shell:
        subprocess.run(["docker", "exec", shell, "sh", "-c", f"mkdir -p /tmp/cviz && echo {shlex.quote(work)} > /tmp/cviz/cwd"])
    else:
        os.makedirs("/tmp/cviz", exist_ok=True)
        open("/tmp/cviz/cwd", "w").write(work + "\n")
    steps = []
    for cmd in scn["commands"]:
        cast, rc, secs = run(cmd, work, scn.get("timeout", 120), shell)
        steps.append({"cmd": cmd, "cast": cast, "exit": rc, "duration": secs,
                      "state": snapshot(work, scn.get("watch", []), shell_image)})
    ver = docker("version", "--format", "{{.Server.Version}}").strip()
    json.dump({"steps": steps, "docker": ver, "term": {"cols": COLS, "rows": ROWS}}, open(outp, "w"))


if __name__ == "__main__":
    main()
