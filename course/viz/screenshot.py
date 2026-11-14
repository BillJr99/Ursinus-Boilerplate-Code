"""code-viz screenshots and render check, run inside a Playwright container.

Serves a built viz/ folder, opens each requested example at a given step in headless Chromium
(1400 x 900, light theme) and saves a PNG; with --check it opens a sample of examples and reports
any that fail to render (a JavaScript error, an empty panel).

Usage (inside mcr.microsoft.com/playwright/python):
  python3 screenshot.py SITE_DIR OUT_DIR id:step:name [id:step:name ...]
  python3 screenshot.py SITE_DIR OUT_DIR --check id [id ...]
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
    items = [a for a in argv[3:] if a != "--check"]
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1400, "height": 900}, color_scheme="light")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        for it in items:
            vid, step, name = (it.split(":") + ["0", ""])[:3] if not check else (it, "3", "")
            errors.clear()
            page.goto(f"{base}?step={int(step)}#{vid}")
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
