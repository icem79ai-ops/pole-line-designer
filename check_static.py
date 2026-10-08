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
        - background map: paste a PNG, calibrate against a 200 px reference
          length, re-calibrate, wheel-scale, off-image click error, drag,
          opacity, apply/lock, then reload -> image is NOT persisted
  4. Fail on any uncaught page error.

Usage:
    python -X utf8 check_static.py                # local build + test
    python -X utf8 check_static.py --url <URL>    # test an already-published URL
"""

from __future__ import annotations

import argparse
import base64
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


def screen_of(d: dict, px: float, py: float) -> tuple[float, float]:
    """Map an image pixel to canvas screen coords using a __BG_DEBUG__ snapshot."""
    mpp = d["metersW"] / d["w"]
    wx = d["origin"][0] + px * mpp
    wy = d["origin"][1] - py * mpp
    v = d["view"]
    return (wx * v["scale"] + v["tx"], -wy * v["scale"] + v["ty"])


def image_screen_rect(d: dict) -> tuple[float, float, float, float]:
    """Screen (left, top, width, height) of the background image."""
    v = d["view"]
    left = d["origin"][0] * v["scale"] + v["tx"]
    top = -d["origin"][1] * v["scale"] + v["ty"]
    width = d["metersW"] * v["scale"]
    return (left, top, width, width * d["h"] / d["w"])


def pixel_at(d: dict, sx: float, sy: float) -> tuple[float, float]:
    """Map canvas screen coords back to image pixel coords."""
    v = d["view"]
    wx = (sx - v["tx"]) / v["scale"]
    wy = (v["ty"] - sy) / v["scale"]
    mpp = d["metersW"] / d["w"]
    return ((wx - d["origin"][0]) / mpp, (d["origin"][1] - wy) / mpp)


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

    print("== background map image (place / calibrate / scale / apply) ==")
    try:
        png_b64 = page.evaluate(
            """() => {
                const cv = document.createElement('canvas');
                cv.width = 400; cv.height = 300;
                const c = cv.getContext('2d');
                c.fillStyle = '#ffffff'; c.fillRect(0, 0, 400, 300);
                c.fillStyle = '#000000';
                c.beginPath(); c.arc(100, 150, 12, 0, Math.PI * 2); c.fill();
                c.beginPath(); c.arc(300, 150, 12, 0, Math.PI * 2); c.fill();
                return cv.toDataURL('image/png').split(',')[1];
            }"""
        )
        page.set_input_files("#input-bg-file", [{
            "name": "map.png",
            "mimeType": "image/png",
            "buffer": base64.b64decode(png_b64),
        }])
        page.wait_for_function(
            "() => window.__BG_DEBUG__ && window.__BG_DEBUG__().has", timeout=20_000)
        d = page.evaluate("() => window.__BG_DEBUG__()")
        if d["mode"] == "bg" and (d["w"], d["h"]) == (400, 300):
            ok(f"image placed {d['w']}x{d['h']} (max-dim path), mode -> bg")
        else:
            fail(f"image placement wrong: mode={d['mode']} size={d['w']}x{d['h']}")

        box = page.locator("#canvas").bounding_box()
        if not box:
            fail("canvas bounding box unavailable")
            raise RuntimeError("no canvas")

        def canvas_point(sx: float, sy: float) -> None:
            page.mouse.click(box["x"] + sx, box["y"] + sy)

        # --- calibrate: 200 px of image = 100 m  ->  0.5 m/px -------------
        page.fill("#input-bg-ref", "100")
        page.click("#btn-bg-measure")
        page.wait_for_function("() => window.__BG_DEBUG__().calibrating", timeout=10_000)
        d = page.evaluate("() => window.__BG_DEBUG__()")
        x1, y1 = screen_of(d, 100, 150)
        x2, y2 = screen_of(d, 300, 150)
        canvas_point(x1, y1)
        canvas_point(x2, y2)
        page.wait_for_function("() => !window.__BG_DEBUG__().calibrating", timeout=10_000)
        d = page.evaluate("() => window.__BG_DEBUG__()")
        expect_mw = 0.5 * d["w"]
        if abs(d["metersW"] - expect_mw) <= 0.02 * expect_mw:
            ok(f"calibrate 100 m / 200 px -> {d['metersW']:.2f} m wide "
               f"({d['metersW'] / d['w']:.4f} m/px)")
        else:
            fail(f"calibration wrong: metersW={d['metersW']} expected {expect_mw:.2f}")

        # --- second calibration doubles the scale --------------------------
        page.fill("#input-bg-ref", "200")
        page.click("#btn-bg-measure")
        d = page.evaluate("() => window.__BG_DEBUG__()")
        x1, y1 = screen_of(d, 100, 150)
        x2, y2 = screen_of(d, 300, 150)
        canvas_point(x1, y1)
        canvas_point(x2, y2)
        page.wait_for_function("() => !window.__BG_DEBUG__().calibrating", timeout=10_000)
        d2 = page.evaluate("() => window.__BG_DEBUG__()")
        ratio = d2["metersW"] / d["metersW"]
        if abs(ratio - 2.0) <= 0.04:
            ok(f"re-calibrate 200 m over the same span -> scale x{ratio:.3f}")
        else:
            fail(f"re-calibrate ratio {ratio:.4f} != 2")

        # --- wheel in bg mode scales the image around the cursor -----------
        cw, ch = box["width"], box["height"]
        cur_w = d2["metersW"] * d2["view"]["scale"]
        target_w = 0.35 * cw
        n = 0
        while cur_w * (1 / 1.12) ** n > target_w and n < 60:
            n += 1
        n = max(1, n)
        page.mouse.move(box["x"] + cw / 2, box["y"] + ch / 2)
        for _ in range(n):
            page.mouse.wheel(0, 100)
        d3 = page.evaluate("() => window.__BG_DEBUG__()")
        got_ratio = d3["metersW"] / d2["metersW"]
        want_ratio = (1 / 1.12) ** n
        if abs(got_ratio - want_ratio) <= 1e-6 * want_ratio:
            ok(f"wheel x{n} in bg mode -> scale ratio {got_ratio:.6f} (1/1.12)^{n}")
        else:
            fail(f"wheel ratio {got_ratio} != {want_ratio}")

        # --- click outside the image -> Thai error, right-click cancels ----
        d4 = d3
        left, top, iw, ih = image_screen_rect(d3)
        candidates = [
            (left + iw + 40, top + ih / 2),
            (left - 40, top + ih / 2),
            (left + iw / 2, top + ih + 40),
            (left + iw / 2, top - 40),
        ]
        target = None
        for cx, cy in candidates:
            if 5 < cx < cw - 5 and 5 < cy < ch - 5:
                ppx, ppy = pixel_at(d3, cx, cy)
                if not (0 <= ppx <= d3["w"] and 0 <= ppy <= d3["h"]):
                    target = (cx, cy)
                    break
        if target is None:
            fail("could not find an off-image click point inside the canvas")
        else:
            page.click("#btn-bg-measure")
            canvas_point(*target)
            err = (page.text_content("#bg-error") or "").strip()
            if page.get_attribute("#bg-error", "hidden") is None and "คลิกบนภาพ" in err:
                ok("off-image click rejected: " + err)
            else:
                fail(f"off-image click not rejected (err={err!r})")
            page.mouse.click(box["x"] + target[0], box["y"] + target[1], button="right")
            page.wait_for_function("() => !window.__BG_DEBUG__().calibrating", timeout=10_000)
            d4 = page.evaluate("() => window.__BG_DEBUG__()")
            if not d4["calibrating"] and d4["mode"] == "bg":
                ok("right-click cancels the measurement, stays in bg mode")
            else:
                fail(f"cancel failed: {d4['calibrating']} / mode={d4['mode']}")

        # --- drag the image (origin delta = screen delta / scale) ----------
        px0, py0 = box["x"] + cw / 2, box["y"] + ch / 2
        page.mouse.move(px0, py0)
        page.mouse.down()
        page.mouse.move(px0 + 60, py0 - 30, steps=6)
        page.mouse.up()
        d5 = page.evaluate("() => window.__BG_DEBUG__()")
        want_dx = 60 / d4["view"]["scale"]
        want_dy = -(-30) / d4["view"]["scale"]
        got_dx = d5["origin"][0] - d4["origin"][0]
        got_dy = d5["origin"][1] - d4["origin"][1]
        if abs(got_dx - want_dx) < 1e-6 and abs(got_dy - want_dy) < 1e-6:
            ok(f"drag moved origin by ({got_dx:.4f}, {got_dy:.4f}) m")
        else:
            fail(f"drag origin delta ({got_dx}, {got_dy}) != ({want_dx}, {want_dy})")

        # --- opacity slider ------------------------------------------------
        page.evaluate(
            """() => {
                const e = document.getElementById('input-bg-opacity');
                e.value = '0.9';
                e.dispatchEvent(new Event('input', {bubbles: true}));
            }"""
        )
        d6 = page.evaluate("() => window.__BG_DEBUG__()")
        if abs(d6["opacity"] - 0.9) < 1e-9:
            ok("opacity slider -> 0.9")
        else:
            fail(f"opacity {d6['opacity']} != 0.9")
        readout = (page.text_content("#bg-readout") or "").strip()
        if "ม./พิกเซล" in readout:
            ok("readout shows meters per pixel: " + readout)
        else:
            fail(f"readout unexpected: {readout!r}")

        # --- apply -> lock + back to draw mode -----------------------------
        page.click("#btn-bg-apply")
        d7 = page.evaluate("() => window.__BG_DEBUG__()")
        if d7["mode"] == "draw" and d7["locked"] and not d7["calibrating"]:
            ok("apply locks the image and returns to draw mode")
        else:
            fail(f"apply wrong: mode={d7['mode']} locked={d7['locked']}")

        # --- reload: image gone (not stored), poles restored ---------------
        page.reload(wait_until="load", timeout=90_000)
        page.wait_for_selector("#std-table tbody tr:not(.empty)", timeout=240_000)
        page.wait_for_selector("#pole-tbody tr", timeout=60_000)
        d8 = page.evaluate("() => window.__BG_DEBUG__()")
        count = page.locator("#pole-tbody tr").count()
        if not d8["has"] and count == len(expected_poles):
            ok("after reload: image not persisted (by design), "
               f"{count} poles restored")
        else:
            fail(f"after reload: has={d8['has']} poles={count} != {len(expected_poles)}")
    except Exception as e:
        fail("background map test threw: " + str(e))

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