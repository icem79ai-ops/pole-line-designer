# -*- coding: utf-8 -*-
"""
check_static.py - End-to-end test of the static (Pyodide) build.

Proves the docs/ build boots Pyodide in a real browser, loads line_engine.py,
and serves /api/* identically to the Flask backend:

  1. Build docs/ (unless a --url is given).
  2. Serve docs/ on a random localhost port (unless --url).
  3. Open headless Chromium and:
       - wait for the standards table to render (proves Pyodide boot)
       - click the 200 m sample, assert poles/status/stats/checks
       - POST /api/design via the page and diff against the local engine
       - error path: offset=-1 -> 400 with Thai message in the error box
       - CSV export: diff bridge CSV against the local engine
       - sample again, then reload -> localStorage persistence re-renders design
  4. Fail on any uncaught page error.

Usage:
    python -X utf8 check_static.py                # local build + test
    python -X utf8 check_static.py --url <URL>    # test an already-published URL
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading

import line_engine as engine

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, "docs")
ANY_FAILED = False


def fail(msg: str) -> None:
    global ANY_FAILED
    ANY_FAILED = True
    print("  FAIL: " + msg)


def ok(msg: str) -> None:
    print("  ok: " + msg)


def diff_json(actual, expected, path="root", tol=1e-6) -> list[str]:
    """Recursively compare JSON with a float tolerance; return problem strings."""
    problems: list[str] = []
    if isinstance(expected, dict):
        for k in actual:
            if k not in expected:
                problems.append(f"{path}.{k}: key only in actual")
        for k, ev in expected.items():
            if k not in actual:
                problems.append(f"{path}.{k}: missing in actual")
                continue
            problems += diff_json(actual[k], ev, f"{path}.{k}", tol)
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            problems.append(f"{path}: length {len(actual)} != {len(expected)}")
        else:
            for i, (a, e) in enumerate(zip(actual, expected)):
                problems += diff_json(a, e, f"{path}[{i}]", tol)
    elif isinstance(expected, (int, float)):
        if isinstance(actual, (int, float)) and abs(float(actual) - float(expected)) <= tol:
            pass
        else:
            problems.append(f"{path}: {actual} != {expected}")
    else:
        if actual != expected:
            problems.append(f"{path}: {actual!r} != {expected!r}")
    return problems


def collect_page_errors(page) -> list[str]:
    problems: list[str] = []

    def _on_pageerror(info):
        problems.append("pageerror: " + str(info))

    def _on_console(msg):
        if msg.type == "error":
            text = msg.text
            if text and ("favicon" in text or "Failed to load resource" in text):
                return
            problems.append("console.error: " + text)

    page.on("pageerror", _on_pageerror)
    page.on("console", _on_console)
    return problems


def serve_docs() -> subprocess.Popen:
    """Serve docs/ on 127.0.0.1:0; return a started subprocess (prints the port)."""
    code = (
        "import http.server, os, sys;"
        "os.chdir(sys.argv[1]);"
        "h=http.server.SimpleHTTPRequestHandler;"
        "s=http.server.ThreadingHTTPServer(('127.0.0.1', 0), h);"
        "print('PORT:' + str(s.server_address[1]), flush=True);"
        "s.serve_forever()"
    )
    return subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", code, DOCS],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def read_port(proc: subprocess.Popen, timeout: int) -> int:
    import time
    deadline = time.time() + timeout
    line = ""
    while time.time() < deadline:
        line = proc.stdout.readline().strip()
        if line.startswith("PORT:"):
            return int(line.split(":", 1)[1])
        if "Traceback" in line or "Error" in line:
            raise RuntimeError("server failed: " + line)
    raise TimeoutError("server did not start")


def run_checks(page, base_url: str) -> None:
    errors = collect_page_errors(page)

    print("== boot ==")
    page.goto(base_url + "/", wait_until="load", timeout=90_000)
    try:
        page.wait_for_selector("#std-table tbody tr:not(.empty)", timeout=240_000)
        n_std = page.locator("#std-table tbody tr").count()
        if n_std == 5:
            ok(f"standards table rendered {n_std} rows (Pyodide boot ok)")
        else:
            fail(f"standards table expected 5 rows, got {n_std}")
    except Exception as e:
        fail("pyodide did not boot / standards fetch failed: " + str(e))
        print("  page error state: " + str(errors))
        return

    print("== sample design ==")
    page.click("#btn-sample")
    try:
        page.wait_for_selector("#pole-tbody tr", timeout=60_000)
        status = page.text_content("#status-pill").strip()
        count = page.locator("#pole-tbody tr").count()
        expected_poles = engine.to_payload(engine.design(engine.sample_centerline()))["poles"]
        if status == "ผ่านทุกเกณฑ์" and count == len(expected_poles):
            ok(f"sample: status '{status}', {count} poles (engine parity count)")
        else:
            fail(f"sample: status '{status}', poles {count} != {len(expected_poles)}")
    except Exception as e:
        fail("sample design failed or UI did not render: " + str(e))

    poles_txt = page.text_content("#stat-poles") or "-"
    if poles_txt != "-":
        ok("stat tile populated: จำนวนเสา = " + poles_txt)
    else:
        fail("stat tiles not populated")

    print("== /api/design parity (bridge vs local engine) ==")
    sample = engine.sample_centerline()
    expected = engine.to_payload(
        engine.design(sample, offset=5.0, use_break_poles=True, road_width=16.0)
    )
    body = json.dumps({
        "points": sample,
        "offset": 5.0,
        "use_break_poles": True,
        "road_width": 16.0,
    }, ensure_ascii=False)
    try:
        actual = page.evaluate(
            """async (body) => {
                const r = await fetch("/api/design", {method:"POST",
                  headers:{"Content-Type":"application/json"}, body: body});
                return await r.json();
            }""", body)
        problems = diff_json(actual, expected)
        if problems:
            fail("/api/design parity: " + "; ".join(problems[:5]))
        else:
            ok("/api/design matches local engine output exactly")
    except Exception as e:
        fail("/api/design parity threw: " + str(e))

    print("== /api/export/csv parity ==")
    try:
        csv_bridge = page.evaluate(
            """async (body) => {
                const r = await fetch("/api/export/csv", {method:"POST",
                  headers:{"Content-Type":"application/json"}, body: body});
                return await r.text();
            }""", body)
        csv_local = engine.poles_to_csv(
            engine.design(sample, offset=5.0, use_break_poles=True, road_width=16.0).poles
        )
        if csv_bridge.strip() == csv_local.strip():
            ok("/api/export/csv matches local engine")
        else:
            fail("CSV differs from local engine")
            print("   local: " + csv_local.splitlines()[0])
            print("   bridge:" + csv_bridge.splitlines()[0])
    except Exception as e:
        fail("/api/export/csv threw: " + str(e))

    print("== error path (offset=-1 -> 400 Thai msg) ==")
    try:
        page.evaluate("""() => {
            const el = document.getElementById("input-offset");
            el.value = "-1";
            el.dispatchEvent(new Event("change", {bubbles:true}));
        }""")
        page.wait_for_selector("#error-box:not([hidden])", timeout=30_000)
        err = page.text_content("#error-box").strip()
        if "offset" in err and "ต้องอยู่ระหว่าง" in err:
            ok("error box shows 400 message: " + err[:60] + "...")
        else:
            fail("error box message unexpected: " + err)
    except Exception as e:
        fail("offset=-1 did not surface a 400 error: " + str(e))

    # restore a valid offset so subsequent steps are deterministic
    page.evaluate("""() => {
        const el = document.getElementById("input-offset");
        el.value = "5";
        el.dispatchEvent(new Event("change", {bubbles:true}));
    }""")
    page.wait_for_selector("#pole-tbody tr", timeout=30_000)

    print("== reload persistence (localStorage) ==")
    page.reload(wait_until="load", timeout=90_000)
    try:
        page.wait_for_selector("#std-table tbody tr:not(.empty)", timeout=240_000)
        page.wait_for_selector("#pole-tbody tr", timeout=60_000)
        count = page.locator("#pole-tbody tr").count()
        if count == len(expected_poles):
            ok(f"after reload {count} poles restored from localStorage")
        else:
            fail(f"after reload poles {count} != {len(expected_poles)}")
    except Exception as e:
        fail("reload persistence failed: " + str(e))

    print("== uncaught page errors ==")
    if errors:
        fail("page errors: " + "; ".join(errors))
    else:
        ok("no uncaught page errors / console errors")


def main() -> int:
    ap = argparse.ArgumentParser(description="E2E test of static Pyodide build")
    ap.add_argument("--url", default=None, help="test an already-published URL")
    args = ap.parse_args()

    if args.url:
        base_url = args.url.rstrip("/")
        print("Testing published URL:", base_url)
    else:
        print("Building docs/ ...")
        r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(ROOT, "build_static.py")],
                           capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode != 0:
            print(r.stderr.strip())
            return 1
        print("Starting local server ...")
        proc = serve_docs()
        port = read_port(proc, 15)
        base_url = f"http://127.0.0.1:{port}"
        print("Serving", base_url)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = None
        for launcher in (
            lambda: p.chromium.launch(headless=True),
            lambda: p.chromium.launch(headless=True, channel="msedge"),
            lambda: p.chromium.launch(headless=True, channel="chrome"),
        ):
            try:
                browser = launcher()
                print("Using browser:", browser.browser_type.name)
                break
            except Exception:
                continue
        if browser is None:
            print("FAIL: no usable Chromium (tried default, msedge, chrome channels)")
            return 1
        try:
            ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = ctx.new_page()
            run_checks(page, base_url)
            ctx.close()
        finally:
            browser.close()

    if not args.url:
        proc.terminate()

    print("RESULT:", "FAIL" if ANY_FAILED else "PASS")
    return 1 if ANY_FAILED else 0


if __name__ == "__main__":
    sys.exit(main())