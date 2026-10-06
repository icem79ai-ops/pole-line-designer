# -*- coding: utf-8 -*-
"""smoke_live.py - live HTTP smoke test against a running app.py instance.

    python app.py --no-browser --port 5123
    python smoke_live.py --port 5123
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def post(base: str, path: str, payload=None, raw: bytes | None = None):
    data = raw if raw is not None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as err:
        return err.code, err.read(), dict(err.headers)


def get(base: str, path: str):
    try:
        with urllib.request.urlopen(base + path, timeout=15) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5123)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        mark = "OK  " if condition else "FAIL"
        print(f"[{mark}] {label} {detail}")
        if not condition:
            failures.append(label)

    print("--- GET endpoints ---")
    for path in ("/", "/api/health", "/api/standards", "/api/sample",
                 "/static/css/style.css", "/static/js/app.js"):
        status, body = get(base, path)
        check(f"GET {path}", status == 200 and len(body) > 100, f"status={status} bytes={len(body)}")

    status, body = get(base, "/")
    check("index has no unrendered jinja", b"{{" not in body)
    check("index embeds APP_DEFAULTS", b"APP_DEFAULTS" in body)
    check("index is utf-8 thai", "ออกแบบ".encode("utf-8") in body)

    status, body = get(base, "/api/health")
    health = json.loads(body)
    check("health payload", health.get("status") == "ok" and health.get("engine") == "line_engine")

    status, body = get(base, "/api/standards")
    std = json.loads(body)
    check("standards span table", len(std["span_table"]) == 5, f"rows={len(std['span_table'])}")
    check("standards tangent span", std["tangent_max_span_m"] == 40.0)

    print("--- design: straight run ---")
    straight = {"points": [[0, 0], [150, 0]], "offset": 5.0, "use_break_poles": True,
                "road_width": 0.0}
    status, body, headers = post(base, "/api/design", straight)
    data = json.loads(body)
    check("design 200", status == 200, f"status={status}")
    check("design ok", data["ok"] is True)
    check("design 7 checks all PASS",
          len(data["validation"]) == 7
          and all(r["status"] == "PASS" for r in data["validation"]))
    check("design two end dead ends",
          data["poles"][0]["bracket"] == "(-O" and data["poles"][-1]["bracket"] == "O-)")
    check("design offset honoured", all(abs(p["y"] - 5.0) < 1e-6 for p in data["poles"]))
    check("design max span <= 40", data["summary"]["max_span_used_m"] <= 40.0 + 1e-6,
          f"maxspan={data['summary']['max_span_used_m']}")

    print("--- design: road clearance raises offset ---")
    on_road = {"points": [[0, 0], [150, 0]], "offset": 5.0, "use_break_poles": True,
               "road_width": 16.0}
    status, body, _ = post(base, "/api/design", on_road)
    data = json.loads(body)
    check("road design ok", data["ok"] is True)
    check("offset raised above road edge",
          all(abs(p["y"] - 10.0) < 1e-6 for p in data["poles"]),
          f"offset_m={data['offset_m']}")
    check("requested offset preserved", data["requested_offset_m"] == 5.0)
    check("road fields in payload",
          data["road_width_m"] == 16.0
          and data["min_edge_clearance_m"] == 2.0
          and data["road_clearance_m"] == 2.0)
    check("road raise warning present",
          any("ระบบจึงถอยแนวเสา" in w for w in data["warnings"]))
    road_row = [r for r in data["validation"] if r["key"] == "no_pole_on_road"]
    check("road check PASS with real clearance",
          road_row and road_row[0]["status"] == "PASS" and "ริมทาง 2.00 m" in road_row[0]["value"],
          f"value={road_row[0]['value'] if road_row else 'missing'}")

    print("--- design: route with two corners ---")
    corner = {"points": [[0, 0], [200, 0], [254.8, 47.0], [400, 47.0]],
              "offset": 5.0, "use_break_poles": True, "road_width": 0.0}
    status, body, _ = post(base, "/api/design", corner)
    data = json.loads(body)
    check("corner design ok", data["ok"] is True)
    check("corner design has angle poles",
          any(p["code"] in ("curve", "ba") for p in data["poles"]),
          f"counts={data['summary']['count_label']}")
    check("corner design has break poles",
          {"break_open", "break_close"} & {p["code"] for p in data["poles"]})
    check("corner slack spans <= 20",
          all(p["span_to_next"] <= 20.0 + 1e-6
              for p in data["poles"]
              if p["code"] in ("curve", "ba") and p["span_to_next"]))
    check("corner payload keys",
          {"id", "x", "y", "station", "code", "gy", "gy_angle", "bracket",
           "angle", "span_to_next", "marker", "color"} <= set(data["poles"][0]))
    guyed = [p for p in data["poles"] if p["gy"]]
    check("guy anchors present in payload",
          bool(guyed)
          and all(p["gy_anchor_x"] is not None and p["gy_anchor_y"] is not None
                  for p in guyed),
          f"guyed={len(guyed)}")
    check("spans cover every gap", len(data["spans"]) == len(data["poles"]) - 1)
    corner_pole_count = len(data["poles"])

    print("--- design: gentle bend keeps single angle pole ---")
    gentle = {"points": [[0, 0], [200, 0], [300, 28.1], [500, 63.2]],
              "offset": 12.0, "use_break_poles": True}
    status, body, _ = post(base, "/api/design", gentle)
    data = json.loads(body)
    codes = {p["code"] for p in data["poles"]}
    check("gentle design ok", data["ok"] is True)
    check("gentle bend has no break poles",
          not ({"break_open", "break_close"} & codes), f"codes={data['summary']['count_label']}")
    check("gentle bend still has an angle pole", "curve" in codes)

    print("--- design: option toggle ---")
    off = dict(corner, use_break_poles=False)
    status, body, _ = post(base, "/api/design", off)
    no_break = json.loads(body)
    check("break toggle changes result",
          not ({"break_open", "break_close"} & {p["code"] for p in no_break["poles"]}),
          f"counts={no_break['summary']['count_label']}")
    wide = dict(corner, offset=7.5)
    status, body, _ = post(base, "/api/design", wide)
    check("offset option honoured", json.loads(body)["offset_m"] == 7.5)
    raised = {"points": [[0, 0], [150, 0]], "offset": 7.5, "road_width": 16.0}
    status, body, _ = post(base, "/api/design", raised)
    check("offset below road floor gets raised",
          json.loads(body)["offset_m"] == 10.0)

    print("--- CSV export ---")
    status, body, headers = post(base, "/api/export/csv", corner)
    text = body.decode("utf-8")
    lines = text.splitlines()
    check("csv 200", status == 200, f"status={status}")
    check("csv content type", "text/csv" in headers.get("Content-Type", ""))
    check("csv disposition", "poles.csv" in headers.get("Content-Disposition", ""))
    check("csv header", lines[0] == "id,x,y,station,code,type,gy,gy_angle,bracket,angle,span_from_prev,span_to_next")
    check("csv row count", len(lines) - 1 == corner_pole_count, f"rows={len(lines) - 1}")
    check("csv thai type text intact", "เสาดับสายต้นทาง" in text)
    check("csv status header", headers.get("X-Design-Status") == "PASS")

    print("--- input validation (must be 400 with a message) ---")
    bad_cases = [
        ("one point", {"points": [[0, 0]]}, None),
        ("empty points", {"points": []}, None),
        ("missing key", {"offset": 5.0}, None),
        ("flat list", {"points": [0, 0, 1, 1]}, None),
        ("string coords", {"points": [["a", "b"], [1, 2]]}, None),
        ("wrong pair", {"points": [[1, 2, 3], [4, 5, 6]]}, None),
        ("negative offset", {"points": [[0, 0], [1, 1]], "offset": -3}, None),
        ("huge offset", {"points": [[0, 0], [1, 1]], "offset": 999}, None),
        ("text offset", {"points": [[0, 0], [1, 1]], "offset": "x"}, None),
        ("body not json", None, b"not-json"),
        ("body empty", None, b""),
        ("body json array", None, b"[1,2,3]"),
        ("body json null", None, b"null"),
        ("duplicate points", {"points": [[0, 0], [0, 0]]}, None),
    ]
    for label, payload, raw in bad_cases:
        status, body, _ = post(base, "/api/design", payload, raw)
        try:
            message = json.loads(body).get("error", "")
        except json.JSONDecodeError:
            message = ""
        check(f"400 {label}", status == 400 and bool(message), f"status={status} msg={message[:60]}")

    status, body, _ = post(base, "/api/export/csv", {"points": [[0, 0]]})
    check("400 csv bad input", status == 400, f"status={status}")

    status, _ = get(base, "/api/nope")
    check("404 unknown api", status == 404, f"status={status}")

    print("=" * 70)
    if failures:
        print(f"SMOKE FAIL: {len(failures)} รายการ -> {failures}")
        return 1
    print("SMOKE PASS: ทุกรายการผ่าน")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
