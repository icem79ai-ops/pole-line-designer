# -*- coding: utf-8 -*-
"""
app.py - Web application server for the 22/33 kV automatic pole placement
system (conductor SAC 50 sq.mm.).

Run:
    python app.py                 # http://127.0.0.1:5000
    python app.py --port 8080     # custom port
    python app.py --host 0.0.0.0  # allow LAN access
"""

from __future__ import annotations

import argparse
import webbrowser

from flask import Flask, Response, jsonify, render_template, request

import line_engine as engine

app = Flask(__name__, static_folder="web/static", template_folder="web/templates")
app.json.ensure_ascii = False


class BadRequest(Exception):
    """Raised for invalid client input; converted to HTTP 400 with a message."""


@app.errorhandler(BadRequest)
def _handle_bad_request(err: BadRequest):
    return jsonify({"error": str(err)}), 400


@app.errorhandler(ValueError)
def _handle_value_error(err: ValueError):
    return jsonify({"error": str(err)}), 400


def _parse_request(payload: dict) -> dict:
    """Validate one design request and return the engine arguments."""
    if not isinstance(payload, dict):
        raise BadRequest("body ต้องเป็น JSON object")

    points = payload.get("points")
    if not isinstance(points, list) or len(points) < 2:
        raise BadRequest("ต้องส่ง points เป็นรายการพิกัด [[x, y], ...] อย่างน้อย 2 จุด")

    cleaned: list[list[float]] = []
    for index, point in enumerate(points):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise BadRequest(f"points[{index}] ต้องเป็น [x, y]")
        try:
            x = float(point[0])
            y = float(point[1])
        except (TypeError, ValueError):
            raise BadRequest(f"points[{index}] ต้องเป็นตัวเลข")
        cleaned.append([x, y])

    offset_raw = payload.get("offset", engine.ROW_OFFSET)
    try:
        offset = float(offset_raw)
    except (TypeError, ValueError):
        raise BadRequest("offset ต้องเป็นตัวเลข (เมตร)")
    if not 0.0 < offset <= 50.0:
        raise BadRequest("offset ต้องอยู่ระหว่าง 0 (ไม่รวม) ถึง 50 เมตร")

    road_width_raw = payload.get("road_width", engine.ROAD_WIDTH)
    try:
        road_width = float(road_width_raw)
    except (TypeError, ValueError):
        raise BadRequest("road_width ต้องเป็นตัวเลข (เมตร)")
    if not 0.0 <= road_width <= 50.0:
        raise BadRequest("road_width ต้องอยู่ระหว่าง 0 ถึง 50 เมตร")

    use_break = bool(payload.get("use_break_poles", engine.USE_BREAK_POLES))
    return {
        "points": cleaned,
        "offset": offset,
        "use_break_poles": use_break,
        "road_width": road_width,
        "road_clearance": float(
            payload.get("road_clearance", engine.ROAD_CLEARANCE)
        ),
    }


@app.get("/")
def index():
    return render_template(
        "index.html",
        defaults={
            "offset": engine.ROW_OFFSET,
            "use_break_poles": engine.USE_BREAK_POLES,
            "road_width": engine.ROAD_WIDTH,
            "road_clearance": engine.ROAD_CLEARANCE,
            "angle_break_min": engine.ANGLE_BREAK_MIN,
            "sample": engine.sample_centerline(),
        },
    )


@app.post("/api/design")
def api_design():
    payload = request.get_json(silent=True)
    args = _parse_request(payload or {})
    result = engine.design(
        args["points"],
        offset=args["offset"],
        use_break_poles=args["use_break_poles"],
        road_width=args["road_width"],
        road_clearance=args["road_clearance"],
    )
    return jsonify(engine.to_payload(result))


@app.post("/api/export/csv")
def api_export_csv():
    payload = request.get_json(silent=True)
    args = _parse_request(payload or {})
    result = engine.design(
        args["points"],
        offset=args["offset"],
        use_break_poles=args["use_break_poles"],
        road_width=args["road_width"],
        road_clearance=args["road_clearance"],
    )
    csv_text = engine.poles_to_csv(result.poles)
    filename = request.args.get("filename", "poles.csv")
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Design-Status": "PASS" if result.ok else "FAIL",
        },
    )


@app.get("/api/standards")
def api_standards():
    reference = engine.standards_reference()
    reference["tangent_max_span_m"] = engine.MAX_TANGENT_SPAN
    reference["min_spacing_m"] = engine.MIN_SPACING
    return jsonify(reference)


@app.get("/api/sample")
def api_sample():
    """Return the built in 200 m sample as a ready to post design."""
    centerline = engine.sample_centerline()
    result = engine.design(centerline)
    payload = engine.to_payload(result)
    payload["source"] = "sample"
    payload["points"] = centerline
    return jsonify(payload)


@app.get("/api/health")
def api_health():
    return jsonify(
        {
            "status": "ok",
            "engine": "line_engine",
            "row_offset_m": engine.ROW_OFFSET,
            "tangent_max_span_m": engine.MAX_TANGENT_SPAN,
            "slack_span_max_m": engine.MAX_SLACK_SPAN,
            "road_width_m": engine.ROAD_WIDTH,
            "road_clearance_m": engine.ROAD_CLEARANCE,
            "angle_break_min_deg": engine.ANGLE_BREAK_MIN,
        }
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pole placement web application")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="TCP port (default 5000)")
    parser.add_argument("--no-browser", action="store_true", help="ไม่เปิดเบราว์เซอร์อัตโนมัติ")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.port}/"
    print("=" * 66)
    print("22/33 kV Automatic Pole Placement System (SAC 50 sq.mm.)")
    print(f"เปิดเว็บที่: {url}")
    print("กด Ctrl+C เพื่อหยุดเซิร์ฟเวอร์")
    print("=" * 66)
    if not args.no_browser:
        webbrowser.open(url)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()