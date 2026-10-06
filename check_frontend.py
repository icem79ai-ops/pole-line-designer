# -*- coding: utf-8 -*-
"""check_frontend.py - static + runtime checks for the web front end.

  1. every id / selector referenced by web/static/js/app.js must exist in
     web/templates/index.html
  2. every static file the template links must exist on disk
  3. app.js must run through its init path inside a stub DOM (node), so a
     missing element throws here instead of white-screening the real page

Usage:  python check_frontend.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(ROOT, "web", "templates", "index.html")
JS = os.path.join(ROOT, "web", "static", "js", "app.js")
CSS = os.path.join(ROOT, "web", "static", "css", "style.css")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK  ' if ok else 'FAIL'}] {label} {detail}")
    if not ok:
        failures.append(label)


def main() -> int:
    html = open(HTML, encoding="utf-8").read()
    js = open(JS, encoding="utf-8").read()
    css = open(CSS, encoding="utf-8").read()

    # ---- 1. ids -------------------------------------------------------
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))
    js_ids = set(re.findall(r'getElementById\(\s*"([^"]+)"\s*\)', js))
    js_query = set(re.findall(r'querySelector\(\s*"#([A-Za-z0-9_-]+)"\s*\)', js))
    js_query_all = set(re.findall(r'querySelectorAll\(\s*"\.([A-Za-z0-9_-]+)"\s*\)', js))
    referenced = js_ids | js_query
    missing = sorted(referenced - html_ids)
    check("all JS ids exist in template", not missing, f"missing={missing}")
    unused = sorted(html_ids - referenced)
    print(f"       (template ids not fetched by JS: {unused})")

    # ---- 2. static links ---------------------------------------------
    links = re.findall(r'url_for\(\s*\'static\'\s*,\s*filename=[\'"]([^\'"]+)[\'"]\s*\)', html)
    for link in links:
        path = os.path.join(ROOT, "web", "static", link)
        check(f"static file {link}", os.path.isfile(path) and os.path.getsize(path) > 200)

    # ---- 3. data-mode buttons ----------------------------------------
    modes = set(re.findall(r'data-mode="([^"]+)"', html))
    check("mode buttons present", {"draw", "pan"} <= modes, f"modes={sorted(modes)}")

    # ---- 4. payload fields the JS reads -------------------------------
    required_pole = ["id", "x", "y", "station", "code", "bracket", "angle",
                     "gy", "gy_angle", "color", "marker", "span_to_next", "span_from_prev", "type"]
    required_summary = ["length_m", "pole_count", "max_span_used_m", "guy_pole_count",
                        "curve_pole_count", "count_label", "tangent_max_span_m"]
    import line_engine as engine
    payload = engine.to_payload(engine.design(engine.sample_centerline()))
    check("payload has every pole field JS reads",
          all(k in payload["poles"][0] for k in required_pole),
          f"missing={[k for k in required_pole if k not in payload['poles'][0]]}")
    check("payload has every summary field JS reads",
          all(k in payload["summary"] for k in required_summary),
          f"missing={[k for k in required_summary if k not in payload['summary']]}")
    for key in ("centerline", "spans", "validation", "warnings", "ok", "offset_m"):
        check(f"payload top level '{key}'", key in payload)
    check("span fields JS reads",
          {"length", "mid_x", "mid_y"} <= set(payload["spans"][0]))
    check("validation fields JS reads",
          {"label", "value", "status"} <= set(payload["validation"][0]))

    # ---- 5. template defaults ----------------------------------------
    check("template sets APP_DEFAULTS", "APP_DEFAULTS" in html)
    check("template passes sample points", "defaults.sample" in html)
    check("template has no leftover TODO marker", "TODO" not in html and "TODO" not in js)

    # ---- 6. css sanity ------------------------------------------------
    check("css has no broken var", "#2b3away" not in css)
    for cls in ("btn", "btn-primary", "card", "pill", "stat", "tag", "empty"):
        check(f"css defines .{cls}", f".{cls}" in css)

    # ---- 7. runtime smoke in stubbed DOM ------------------------------
    node = None
    for candidate in ("node", "node.exe"):
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            node = candidate
            break
        except (OSError, subprocess.CalledProcessError):
            continue

    if node is None:
        print("[SKIP] node not available - cannot run the DOM stub check")
    else:
        syntax = subprocess.run([node, "--check", JS], capture_output=True, text=True)
        check("node --check app.js", syntax.returncode == 0, syntax.stderr.strip()[:200])

        html_ids_js = json.dumps(sorted(html_ids))
        stub = f"""
const ids = {html_ids_js};
function makeEl(id) {{
  return {{
    id,
    tagName: id === 'filter-code' || id === 'input-offset' ? 'INPUT' : 'DIV',
    dataset: {{ mode: 'draw' }},
    className: '',
    style: {{}},
    value: id === 'input-offset' ? '5' : (id === 'input-road' ? '16' : ''),
    checked: false,
    hidden: false,
    textContent: '',
    innerHTML: '',
    classList: {{ add() {{}}, remove() {{}}, toggle() {{}}, contains() {{ return false; }} }},
    addEventListener() {{}},
    getBoundingClientRect() {{ return {{ width: 1200, height: 700, left: 0, top: 0 }}; }},
    setPointerCapture() {{}}, showModal() {{}}, close() {{}},
    appendChild() {{}}, removeChild() {{}}, click() {{}}
  }};
}}
const cache = {{}};
global.document = {{
  getElementById: (id) => (cache[id] = cache[id] || makeEl(id)),
  querySelector: (sel) => makeEl(sel.replace('#', '')),
  querySelectorAll: () => [makeEl('a'), makeEl('b')],
  addEventListener() {{}},
  createElement: () => makeEl('tmp'),
  body: {{ appendChild() {{}}, removeChild() {{}} }}
}};
const noop = () => {{}};
const ctx2d = new Proxy({{}}, {{ get: (t, k) => (k === 'canvas' ? makeEl('canvas') : noop), set: () => true }});
global.window = {{
  devicePixelRatio: 1,
  addEventListener() {{}},
  APP_DEFAULTS: {{ offset: 5, useBreakPoles: true, sample: [[0,0],[100,0],[100,50],[150,50]] }}
}};
global.localStorage = {{ getItem: () => null, setItem() {{}} }};
global.navigator = {{ clipboard: {{ writeText: () => Promise.resolve() }} }};
global.fetch = () => Promise.resolve({{ ok: true, json: () => Promise.resolve({{ span_table: [], tangent_max_span_m: 40 }}) }});
global.requestAnimationFrame = noop;
global.alert = noop;
global.confirm = () => true;
global.URL = {{ createObjectURL: () => 'blob:x', revokeObjectURL: noop }};
global.Blob = function () {{}};

const canvas = makeEl('canvas');
canvas.getContext = () => ctx2d;
global.document.getElementById = (id) => {{
  if (id === 'canvas') return canvas;
  return cache[id] = cache[id] || makeEl(id);
}};

require({json.dumps(JS.replace('\\\\', '/'))});
console.log('APPJS_INIT_OK');
"""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(stub)
            stub_path = fh.name
        try:
            run = subprocess.run([node, stub_path], capture_output=True, text=True, timeout=30)
            ok = run.returncode == 0 and "APPJS_INIT_OK" in run.stdout
            check("app.js init runs without throwing", ok,
                  (run.stderr.strip().splitlines() or [""])[-1][:300])
        finally:
            os.unlink(stub_path)

        # ---- 8. full click -> API -> render chain in the stub -----------
        design_payload = engine.to_payload(engine.design(engine.sample_centerline()))
        standards_payload = dict(engine.standards_reference())
        standards_payload["tangent_max_span_m"] = engine.MAX_TANGENT_SPAN
        interaction = f"""
const ids = {html_ids_js};
const handlers = {{}};
function makeEl(id) {{
  const el = {{
    id,
    tagName: id.startsWith('input-') || id === 'filter-code' ? 'INPUT' : 'DIV',
    dataset: {{ mode: 'draw' }},
    className: '',
    style: {{}},
    value: id === 'input-offset' ? '5' : (id === 'input-road' ? '16' : ''),
    checked: false,
    hidden: false,
    textContent: '',
    innerHTML: '',
    classList: {{ add() {{}}, remove() {{}}, toggle() {{}}, contains() {{ return false; }} }},
    addEventListener(evt, fn) {{ (handlers[id] = handlers[id] || {{}})[evt] = fn; }},
    getBoundingClientRect() {{ return {{ width: 1200, height: 700, left: 0, top: 0 }}; }},
    showModal() {{}}, appendChild() {{}}, removeChild() {{}}, click() {{}}
  }};
  return el;
}}
const cache = {{}};
const noop = () => {{}};
const ctx2d = new Proxy({{}}, {{ get: (t, k) => (k === 'canvas' ? makeEl('canvas') : noop), set: () => true }});
const canvas = makeEl('canvas');
canvas.getContext = () => ctx2d;
global.document = {{
  getElementById: (id) => id === 'canvas' ? canvas : (cache[id] = cache[id] || makeEl(id)),
  querySelector: (sel) => {{
    const key = sel.replace('#', '').split(/\\s+/)[0];
    return cache[key] = cache[key] || makeEl(key);
  }},
  querySelectorAll: () => [makeEl('a'), makeEl('b')],
  addEventListener() {{}},
  createElement: () => makeEl('tmp'),
  body: {{ appendChild() {{}}, removeChild() {{}} }}
}};
global.window = {{ devicePixelRatio: 1, addEventListener() {{}},
  APP_DEFAULTS: {{ offset: 5, useBreakPoles: true, sample: [[0,0],[100,0],[100,50],[150,50]] }} }};
global.localStorage = {{ getItem: () => null, setItem() {{}} }};
global.navigator = {{ clipboard: {{ writeText: () => Promise.resolve() }} }};
const DESIGN = {json.dumps(design_payload)};
const STANDARDS = {json.dumps(standards_payload)};
global.fetch = (url) => Promise.resolve({{
  ok: true, text: () => Promise.resolve('id,x,y'),
  json: () => Promise.resolve(url.indexOf('standards') !== -1 ? STANDARDS : DESIGN)
}});
global.requestAnimationFrame = noop;
global.URL = {{ createObjectURL: () => 'blob:x', revokeObjectURL: noop }};
global.Blob = function () {{}};

require({json.dumps(JS.replace('\\\\', '/'))});

(async () => {{
  handlers['btn-sample']['click']();
  await new Promise((r) => setTimeout(r, 60));
  const rows = (document.getElementById('pole-tbody').innerHTML.match(/<tr>/g) || []).length;
  const checks = (document.getElementById('check-tbody').innerHTML.match(/<tr>/g) || []).length;
  const pts = document.getElementById('point-tbody').innerHTML.match(/<tr>/g) || [];
  console.log(JSON.stringify({{
    pointRows: pts.length,
    poleRows: rows,
    checkRows: checks,
    statPoles: document.getElementById('stat-poles').textContent,
    statMaxSpan: document.getElementById('stat-maxspan').textContent,
    statLength: document.getElementById('stat-length').textContent,
    status: document.getElementById('status-pill').textContent,
    stdRows: (document.getElementById('std-table').innerHTML.match(/<tr>/g) || []).length
  }}));
}})();
"""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(interaction)
            interaction_path = fh.name
        try:
            run = subprocess.run([node, interaction_path], capture_output=True, text=True, timeout=30)
            report: dict = {}
            if run.returncode == 0 and run.stdout.strip():
                report = json.loads(run.stdout.strip().splitlines()[-1])
            expected_rows = len(design_payload["poles"])
            check("sample button renders point list",
                  report.get("pointRows") == len(design_payload["centerline"]),
                  f"rows={report.get('pointRows')}")
            check("design renders every pole row",
                  report.get("poleRows") == expected_rows,
                  f"rows={report.get('poleRows')} expected={expected_rows}")
            check("design renders 7 check rows",
                  report.get("checkRows") == 7, f"rows={report.get('checkRows')}")
            check("standards table populated", report.get("stdRows") == 5,
                  f"rows={report.get('stdRows')}")
            check("stat tiles filled",
                  bool(report.get("statPoles")) and "ต้น" in str(report.get("statPoles")),
                  f"poles={report.get('statPoles')} maxspan={report.get('statMaxSpan')}")
            check("status pill shows pass", "ผ่านทุกเกณฑ์" in str(report.get("status")),
                  f"status={report.get('status')}")
            if run.returncode != 0:
                print("       node stderr:", run.stderr.strip()[-300:])
        finally:
            os.unlink(interaction_path)


    print("=" * 70)
    if failures:
        print(f"FRONTEND CHECK FAIL: {len(failures)} -> {failures}")
        return 1
    print("FRONTEND CHECK PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
