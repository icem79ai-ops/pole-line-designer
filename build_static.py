# -*- coding: utf-8 -*-
"""
build_static.py - Build a fully-static copy of the pole designer into docs/
so it can be served from GitHub Pages with no Python/Flask backend. The engine
line_engine.py runs in-browser via Pyodide (see web/static/js/pyodide-bridge.js).

Steps:
  1. Render index.html through the Flask test client to get defined defaults.
  2. Rewrite /static/ URLs to relative static/ (works under a Pages sub-path).
  3. Inject a __STATIC_HOST__ flag + the Pyodide bridge script before app.js.
  4. Copy web/static -> docs/static and line_engine.py -> docs/line_engine.py.
  5. Write docs/.nojekyll (Tells GitHub Pages not to run Jekyll).

Run:  python -X utf8 build_static.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB_STATIC = os.path.join(ROOT, "web", "static")
DOCS = os.path.join(ROOT, "docs")
DOCS_STATIC = os.path.join(DOCS, "static")
ENGINE_SRC = os.path.join(ROOT, "line_engine.py")
OUT_HTML = os.path.join(DOCS, "index.html")
OUT_ENGINE = os.path.join(DOCS, "line_engine.py")

INJECT = (
    '<script>window.__STATIC_HOST__ = true;</script>\n'
    '<script src="static/js/pyodide-bridge.js"></script>\n'
)


def render_index() -> str:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import app as web

    client = web.app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200, f"render status {resp.status_code}"
    html = resp.get_data(as_text=True)

    if "{{" in html:
        raise SystemExit("FAIL: unrendered Jinja expression left in HTML")

    html = html.replace('href="/static/', 'href="static/')
    html = html.replace('src="/static/', 'src="static/')
    if re.search(r'["\']/static/', html):
        raise SystemExit("FAIL: absolute /static/ URL left in HTML")

    app_tag = '<script src="static/js/app.js"></script>'
    idx = html.find(app_tag)
    if idx == -1:
        raise SystemExit("FAIL: app.js script tag not found for injection")
    html = html[:idx] + INJECT + html[idx:]

    bridge_pos = html.find('static/js/pyodide-bridge.js')
    app_pos = html.find(app_tag)
    if not (0 < bridge_pos < app_pos):
        raise SystemExit("FAIL: injected bridge script must come before app.js")

    return html


def copy_static() -> None:
    shutil.rmtree(DOCS, ignore_errors=True)
    os.makedirs(DOCS)
    shutil.copytree(WEB_STATIC, DOCS_STATIC)


def self_check() -> None:
    errors: list[str] = []

    def req(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    html = open(OUT_HTML, encoding="utf-8").read()
    req("{{" not in html, "unrendered Jinja leftover")
    req('"/static/' not in html and "'/static/" not in html, "absolute /static/ URL remains")
    req("window.__STATIC_HOST__ = true;" in html, "__STATIC_HOST__ flag missing")
    req("pyodide-bridge.js" in html, "bridge script missing")
    b = html.find("pyodide-bridge.js")
    a = html.find("static/js/app.js")
    req(0 < b < a, "bridge must load before app.js")
    req("window.APP_DEFAULTS" in html, "APP_DEFAULTS block missing")
    req("ระบบออกแบบและวางตำแหน่งเสา" in html, "Thai title missing")
    req("ยังไม่ได้ออกแบบ" in html, "idle status pill missing")

    for ref in re.findall(r'(?:href|src)="(static/[^"]+)"', html):
        req(os.path.isfile(os.path.join(DOCS, ref)), f"referenced asset missing: {ref}")

    for path in (OUT_HTML, OUT_ENGINE, os.path.join(DOCS, ".nojekyll"),
                 os.path.join(DOCS_STATIC, "js", "pyodide-bridge.js"),
                 os.path.join(DOCS_STATIC, "js", "app.js"),
                 os.path.join(DOCS_STATIC, "css", "style.css")):
        req(os.path.isfile(path), f"expected file missing: {path}")

    req(open(OUT_ENGINE, encoding="utf-8").read() == open(ENGINE_SRC, encoding="utf-8").read(),
        "engine copy differs from source")

    for js in ("pyodide-bridge.js", "app.js"):
        r = subprocess.run(["node", "--check", os.path.join(DOCS_STATIC, "js", js)],
                           capture_output=True, text=True)
        req(r.returncode == 0, f"node --check {js}: {r.stderr.strip()}")

    if errors:
        raise SystemExit("FAIL:\n- " + "\n- ".join(errors))


def main() -> None:
    copy_static()
    html = render_index()
    with open(OUT_HTML, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    shutil.copy2(ENGINE_SRC, OUT_ENGINE)
    open(os.path.join(DOCS, ".nojekyll"), "w", encoding="utf-8").close()
    self_check()
    print("OK: static build written to docs/")


if __name__ == "__main__":
    main()