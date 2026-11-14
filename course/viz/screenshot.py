"""code-viz screenshots and render check, run inside a Playwright container.

Serves a built viz/ folder, opens each requested example at a given step in headless Chromium
(1400 x 900, light theme) and saves a PNG; with --check it opens a sample of examples and reports
any that fail to render (a JavaScript error, an empty panel).

Usage (inside mcr.microsoft.com/playwright/python):
  python3 screenshot.py SITE_DIR OUT_DIR id:step:name [id:step:name ...]
  python3 screenshot.py SITE_DIR OUT_DIR --check id [id ...]

PIPELINE
  Used by hand (and by the course helpers) to check a built site and to make screenshots for
  Bill; never part of build or CI.

OPTIONS
  id:step:name   one screenshot of example <id> at step <step>, saved as OUT_DIR/<name>
                 (name includes the extension, e.g. closure.png)
  --check        open each id, wait for the panel, and report any page that failed to render
  --phone        390 x 844 viewport instead of 1400 x 900, for student mode
  --student      open the student link (?student=1) instead of the teacher view

EXAMPLES (in a throwaway Playwright container on minipc)
  sudo -n docker run --rm -v $PWD:/w -w /w mcr.microsoft.com/playwright/python:v1.48.0-jammy \
    python3 code/course/viz/screenshot.py viz shots cs374-liascript-scope-chains-9:9:closure
  ... python3 screenshot.py viz shots --check cs374-liascript-scope-chains-9 cs357-liascript-observability-1

LIMITS
  - Needs the Playwright image (pulled once, removed afterwards); serves viz/ on a local port.
"""
import functools
import http.server
import os
import sys
import threading

from playwright.sync_api import sync_playwright


def serve(site):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=site)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8799), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "http://127.0.0.1:8799/"


def main(argv):
    site, out = argv[1], argv[2]
    os.makedirs(out, exist_ok=True)
    base = serve(site)
    check = "--check" in argv
    phone = "--phone" in argv
    student = "--student" in argv
    items = [a for a in argv[3:] if a not in ("--check", "--phone", "--student")]
    size = {"width": 390, "height": 844} if phone else {"width": 1400, "height": 900}
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport=size, color_scheme="light", is_mobile=phone, has_touch=phone,
                          device_scale_factor=2 if phone else 1)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        for it in items:
            vid, step, name = (it.split(":") + ["0", ""])[:3] if not check else (it, "3", "")
            errors.clear()
            page.goto(f"{base}?step={int(step)}{'&student=1' if student else ''}#{vid}")
            page.wait_for_timeout(2500)
            page.evaluate("() => document.fonts.ready")
            panel = page.inner_text("#panel") if page.query_selector("#panel") else ""
            if check:
                if errors or not panel.strip():
                    bad.append(f"{vid}: {'; '.join(errors) or 'empty panel'}")
                continue
            page.screenshot(path=os.path.join(out, name), full_page=False)
            print("saved", name, ("errors: " + "; ".join(errors)) if errors else "")
        b.close()
    if check:
        print(f"checked {len(items)}; problems {len(bad)}")
        for x in bad:
            print("  " + x)


if __name__ == "__main__":
    main(sys.argv)
