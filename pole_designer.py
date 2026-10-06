# -*- coding: utf-8 -*-
"""
High Voltage Distribution Line Automatic Design & Placement System
22 kV / 33 kV  |  Overhead Conductor SAC 50 sq.mm.

This module is the command line / matplotlib front end only. Every
standards calculation lives in ``line_engine`` so the CLI, the Flask web
application (``app.py``) and the test suite all share one implementation.

Usage
-----
    python pole_designer.py --help          ดูตัวเลือกทั้งหมด
    python pole_designer.py                 interactive pick + plot
    python pole_designer.py --demo          use the built in 200 m sample
    python pole_designer.py --demo --save out.png --csv out.csv
    python pole_designer.py --points "0,0;120,0;120,45;200,45" --agg --save a.png
"""

from __future__ import annotations

import argparse
import math

import matplotlib
import matplotlib.pyplot as plt

import line_engine as engine
from line_engine import MAX_SLACK_SPAN, ROW_OFFSET, TANGENT_TOL, design, poles_to_csv

ROAD_WIDTH = engine.ROAD_WIDTH
ROAD_CLEARANCE = engine.ROAD_CLEARANCE
ANCHOR_LEN = engine.ANCHOR_LEN

# Re-exported so existing callers (``test_standards.py``) keep working.
Polyline = engine.Polyline
TYPE_NAME = engine.TYPE_NAME
BRACKET = engine.BRACKET
COLOR = engine.COLOR
MARKER = {
    "start": "s",
    "end": "H",
    "break_open": "s",
    "break_close": "H",
    "ba": "D",
    "curve": "o",
    "tangent": "o",
}
MAX_TANGENT_SPAN = engine.MAX_TANGENT_SPAN
MIN_SPACING = engine.MIN_SPACING
MIN_CORE = engine.MIN_CORE
USE_BREAK_POLES = engine.USE_BREAK_POLES

# matplotlib marker glyph for each pole code
PLOT_MARKER = {
    "start": "s",
    "end": "H",
    "break_open": "s",
    "break_close": "H",
    "ba": "D",
    "curve": "o",
    "tangent": "o",
}
PLOT_COLOR = {
    "start": "red",
    "end": "red",
    "break_open": "red",
    "break_close": "red",
    "ba": "darkorange",
    "curve": "darkorange",
    "tangent": "blue",
}


def max_span_for_angle(angle_deg: float) -> float:
    return engine.max_span_for_angle(angle_deg)


def span_rule_name(angle_deg: float) -> str:
    return engine.span_rule_for_angle(angle_deg)["label"]


def legacy_design(centerline, offset: float = ROW_OFFSET):
    """Backwards compatible tuple form used by the original test script.

    Returns ``(Polyline, poles, (validation_rows, ok))`` where each
    validation row is a ``(label, value, status)`` tuple.
    """
    result = design(centerline, offset)
    rows = [(row["label"], row["value"], row["status"]) for row in result.validation]
    return result.centerline, result.poles, (rows, result.ok)


def design_result(
    centerline,
    offset: float = ROW_OFFSET,
    use_break_poles: bool = True,
    road_width: float = ROAD_WIDTH,
    road_clearance: float = ROAD_CLEARANCE,
):
    """Full result object (poles, validation, warnings, summary)."""
    return design(
        centerline,
        offset,
        use_break_poles,
        road_width=road_width,
        road_clearance=road_clearance,
    )


def pick_polyline_interactive():
    """AutoCAD style PLINE picking on a matplotlib axes."""
    fig, ax = plt.subplots()
    ax.set_title("คลิกซ้ายเพื่อปักจุดแนวถนน (PLINE)  |  คลิกขวา = เสร็จสิ้น  |  ปุ่ม q = เสร็จสิ้น")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    clicks: list[tuple[float, float]] = []
    state = {"stop": False}

    def on_click(event):
        if event.inaxes is ax and event.button == 1:
            clicks.append((float(event.xdata), float(event.ydata)))
        elif event.button == 3:
            state["stop"] = True

    def on_key(event):
        if event.key in ("q", "escape", "enter"):
            state["stop"] = True

    fig.canvas.mpl_connect("button_press_event", on_click)
    fig.canvas.mpl_connect("key_press_event", on_key)
    fig.canvas.draw()
    while not state["stop"]:
        plt.ginput(1, timeout=0.5)
        fig.canvas.draw_idle()
    plt.close(fig)
    return clicks


def fallback_centerline():
    return engine.sample_centerline()


def setup_fonts():
    from matplotlib import font_manager

    avail = {f.name for f in font_manager.fontManager.ttflist}
    for name in (
        "Leelawadee UI",
        "Tahoma",
        "Browallia New",
        "Cordia New",
        "Angsana New",
        "Noto Sans Thai",
        "Garuda",
    ):
        if name in avail:
            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    return None


def _offset_polyline(pl, offset, side):
    """Return the offset polyline at +/- offset metres (world coords)."""
    # sample every vertex station plus intermediate stations every ~2 m so the
    # offset line follows corners without missing them
    stations = [float(s) for s in pl.cum]
    for i in range(len(pl.seg_len)):
        seg = pl.seg_len[i]
        n = max(1, int(math.ceil(seg / 2.0)))
        for j in range(1, n):
            stations.append(float(pl.cum[i] + seg * j / n))
    stations = sorted(set(stations))
    pts = []
    for s in stations:
        x, y, _ = pl.offset_point(s, side * offset)
        pts.append((x, y))
    return pts


def draw(result: engine.DesignResult, road_width: float | None = None):
    pl = result.centerline
    poles = result.poles
    xs, ys = pl.pts[:, 0], pl.pts[:, 1]
    px = [p["x"] for p in poles]
    py = [p["y"] for p in poles]

    width = result.road_width if road_width is None else road_width

    fig, ax = plt.subplots(figsize=(16, 9))
    if width > 0:
        ax.plot(
            xs, ys, color="0.55", lw=width, solid_capstyle="butt", zorder=1,
        )
    ax.plot(xs, ys, color="gold", ls="--", lw=1.4, label="Centerline (ถนน)", zorder=2)

    # R.O.W. offset lines: where the pole line may legally sit
    for side in (1, -1):
        row = _offset_polyline(pl, result.offset, side)
        ax.plot(
            [p[0] for p in row], [p[1] for p in row],
            color="green", ls=":", lw=1.0, zorder=2,
        )
    ax.plot(px, py, color="0.25", ls=":", lw=1.4, label="แนว R.O.W. / แนวใต้สายไฟ", zorder=2)
    ax.plot(px, py, color="#0D47A1", lw=2.5, label="สายเคเบิลอากาศ SAC 50 sq.mm. (22/33 kV)", zorder=3)

    for i, p in enumerate(poles):
        ax.plot(
            p["x"],
            p["y"],
            PLOT_MARKER[p["code"]],
            color=PLOT_COLOR[p["code"]],
            ms=9,
            mec="black",
            mew=0.8,
            zorder=5,
        )
        ax.annotate(
            f"#{p['id']} {p['code'].upper()}\n{p['bracket']}",
            (p["x"], p["y"]),
            textcoords="offset points",
            xytext=(0, 12 if i % 2 == 0 else -34),
            ha="center",
            fontsize=7.5,
            color=PLOT_COLOR[p["code"]],
            weight="bold",
        )

    # guy line + anchor block at the engine-computed anchor coordinates
    for p in poles:
        if not p["gy"]:
            continue
        if p.get("gy_anchor_x") is not None and p.get("gy_anchor_y") is not None:
            gx, gy = p["gy_anchor_x"], p["gy_anchor_y"]
        else:
            gx = p["x"] + ANCHOR_LEN * math.cos(math.radians(p["gy_angle"]))
            gy = p["y"] + ANCHOR_LEN * math.sin(math.radians(p["gy_angle"]))
        ax.annotate(
            "",
            xy=(gx, gy),
            xytext=(p["x"], p["y"]),
            arrowprops=dict(arrowstyle="->", color="#d32f2f", lw=1.1),
            zorder=6,
        )
        ax.plot(gx, gy, marker="X", color="#d32f2f", ms=6, mec="black", mew=0.6, zorder=6)

    for span in engine.spans_of(poles):
        ax.annotate(
            f"{span['length']:.1f} m",
            (span["mid_x"], span["mid_y"]),
            textcoords="offset points",
            xytext=(0, -14),
            ha="center",
            fontsize=7,
            color="#0D47A1",
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75),
        )

    summary = engine.summary_of(result)
    lines = [
        "22/33 kV  -  OVERHEAD LINE POLE PLACEMENT SUMMARY",
        "-" * 46,
        f"ความยาวแนวถนน (Centerline)   : {summary['length_m']:8.2f} m",
        f"ระยะ Offset แนว R.O.W.          : {result.offset:8.2f} m",
        f"เขตทางกว้าง / เว้นว่างขั้นต่ำ      : {result.road_width:8.1f} / "
        f"{result.road_clearance:.1f} m",
        f"ริมทางห่างเสา (จริง)             : {summary['min_edge_clearance_m']:8.2f} m",
        f"จำนวนเสาทั้งหมด                : {summary['pole_count']:8d} ต้น",
        f"ระยะช่วงเสาสูงสุดที่ใช้จริง       : {summary['max_span_used_m']:8.2f} m",
        f"เกณฑ์สูงสุดตามมาตรฐาน            : 40 / 35 / 25 / 20 m",
        f"ประเภทเสา                        : {summary['count_label']}",
        f"เสาพร้อมสายยึดโยง GY-21 + สมอบก  : {summary['guy_pole_count']:8d} ต้น",
        f"เสาบนช่วงทางโค้ง (SA/MA/BA)      : {summary['curve_pole_count']:8d} ต้น",
        "-" * 46,
        "การตรวจสอบมาตรฐาน",
    ]
    lines += [
        f"  {row['label']:<34} {row['value']:<26} {row['status']}"
        for row in result.validation
    ]
    if result.warnings:
        lines.append("-" * 46)
        lines.append("ข้อควรทราบ")
        lines += [f"  - {w}" for w in result.warnings]
    card = "\n".join(lines)
    ax.text(
        0.012,
        0.015,
        card,
        transform=ax.transAxes,
        fontsize=8.2,
        va="bottom",
        ha="left",
        bbox=dict(boxstyle="round,pad=0.5", fc="#FFFDF5", ec="#333333"),
        zorder=10,
    )
    ax.set_aspect("equal")
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title("22/33 kV Automatic Pole Placement System - SAC 50 sq.mm.")
    plt.tight_layout()
    return fig


def export_csv(poles, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        fh.write(poles_to_csv(poles))
    print(f"[export] เขียนไฟล์ {path} จำนวน {len(poles)} แถว")


def report(result: engine.DesignResult):
    poles = result.poles
    print("=" * 64)
    print("22/33 kV POLE PLACEMENT - DESIGN REPORT")
    print("=" * 64)
    print(
        f"เขตทางกว้าง {result.road_width:.1f} m | เว้นว่างขั้นต่ำ "
        f"{result.road_clearance:.1f} m | ริมทางห่างเสา "
        f"{result.offset - result.road_width / 2.0:.2f} m"
    )
    if abs(result.requested_offset - result.offset) > 1e-9:
        print(
            f"Offset ที่ขอ {result.requested_offset:.2f} m ถูกถอยออกเป็น "
            f"{result.offset:.2f} m (กันเสาล้ำเขตทาง)"
        )
    for p in poles:
        raw = p.get("span_to_next")
        sp = "-" if raw is None else f"{raw:.2f}"
        gy = "GY-21+anchor" if p["gy"] else "-"
        print(
            f"#{p['id']:>3} {p['code']:<12} {p['bracket']:<10} "
            f"ang={p['angle']:>5.1f}  st={p['station']:>7.2f}  "
            f"xy=({p['x']:>8.2f},{p['y']:>8.2f})  span={sp:>6}  {gy}"
        )
    print("-" * 64)
    for row in result.validation:
        print(f"  {row['label']:<34} {row['value']:<26} {row['status']}")
    if result.warnings:
        print("-" * 64)
        for w in result.warnings:
            print(f"  ! {w}")
    print("-" * 64)
    print("ผลรวมตรวจสอบ:", "PASS" if result.ok else "FAIL")
    print("=" * 64)


def _parse_points(text: str):
    """Parse --points "x,y;x,y;..." into a list of (x, y) tuples."""
    pts = []
    for chunk in text.replace("\n", ";").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [v.strip() for v in chunk.split(",")]
        if len(parts) != 2:
            raise ValueError(f"จุด '{chunk}' ต้องเป็นรูปแบบ x,y")
        pts.append((float(parts[0]), float(parts[1])))
    if len(pts) < 2:
        raise ValueError("ต้องระบุ --points อย่างน้อย 2 จุด")
    return pts


def build_parser():
    p = argparse.ArgumentParser(
        prog="pole_designer.py",
        description="ระบบวางเสาไฟฟ้า 22/33 kV (อัตโนมัติ) - สร้างแบบผังเสา "
        "ตามหลักศึกษา SAC 50 sq.mm. พร้อมตรวจสอบ 7 เกณฑ์",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "ตัวอย่าง:\n"
            "  python pole_designer.py --demo\n"
            "  python pole_designer.py --demo --agg --save out.png --csv out.csv\n"
            "  python pole_designer.py --points \"0,0;120,0;120,45;200,45\" --agg --save a.png\n"
            "  python pole_designer.py            # เปิดหน้าต่างคลิกเพื่อวาดเส้นทาง\n"
        ),
    )
    p.add_argument("--demo", action="store_true",
                   help="ใช้เส้นทางตัวอย่าง 200 m (100m -> เลี้ยว 90 องศา 50m -> 50m)")
    p.add_argument("--points", metavar="X,Y;X,Y;...",
                   help="ระบุ centerline เอง เช่น \"0,0;120,0;120,45;200,45\"")
    p.add_argument("--offset", type=float, default=ROW_OFFSET, metavar="M",
                   help=f"ระยะถอยจาก centerline เข้าหา R.O.W. (ค่าเริ่มต้น {ROW_OFFSET})")
    p.add_argument("--road-width", type=float, default=ROAD_WIDTH, metavar="M",
                   help=f"ความกว้างเขตทาง (ค่าเริ่มต้น {ROAD_WIDTH}) "
                   f"เสาจะไม่ถูกวางให้ใกล้ขอบทางเกิน {ROAD_CLEARANCE:.1f} m")
    p.add_argument("--no-break", action="store_true",
                   help="ไม่ใช้ break pole ที่มุม (BA/Slack จะหายไป)")
    p.add_argument("--csv", metavar="PATH", help="export ตารางเสาเป็น CSV")
    p.add_argument("--save", metavar="PATH", help="บันทึกผังเป็นภาพ PNG")
    p.add_argument("--agg", action="store_true",
                   help="ไม่เปิดหน้าต่างกราฟ (สำหรับงาน batch/บันทึกอัตโนมัติ)")
    p.add_argument("--no-fallback", action="store_true",
                   help="ถ้าโหมด interactive ใช้ไม่ได้ ให้ error แทนการใช้เส้นตัวอย่าง")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.offset <= 0:
        raise SystemExit(f"error: --offset ต้องมากกว่า 0 (ได้ {args.offset})")
    if args.road_width < 0:
        raise SystemExit(f"error: --road-width ต้องไม่ติดลบ (ได้ {args.road_width})")

    if args.agg or args.save:
        matplotlib.use("Agg")
    else:
        try:
            matplotlib.use("TkAgg")
        except Exception as exc:
            print(f"[warn] ใช้ TkAgg ไม่ได้ ({exc}) -> ใช้ {matplotlib.get_backend()}")
    print(f"[font] ฟอนต์ไทย: {setup_fonts()}")

    centerline = []
    if args.points:
        try:
            centerline = _parse_points(args.points)
            print(f"[info] ใช้ centerline จาก --points จำนวน {len(centerline)} จุด")
        except ValueError as exc:
            raise SystemExit(f"error: --points ไม่ถูกต้อง ({exc})")
    elif not args.demo:
        try:
            centerline = pick_polyline_interactive()
        except Exception as exc:
            if args.no_fallback:
                raise SystemExit(f"error: โหมด interactive ใช้ไม่ได้ ({exc})")
            print(f"[warn] โหมด interactive ใช้ไม่ได้ ({exc}) -> ใช้เส้นตัวอย่าง 200 m")
    if len(centerline) < 2:
        centerline = fallback_centerline()
        print("[info] ใช้เส้นทางตัวอย่าง 200 m (100m -> เลี้ยว 90 องศา 50m -> 50m)")

    result = design_result(
        centerline,
        offset=args.offset,
        use_break_poles=not args.no_break,
        road_width=args.road_width,
    )
    report(result)

    if args.csv:
        export_csv(result.poles, args.csv)

    if args.agg and not args.save:
        print("[info] --agg ไม่มี --save จึงไม่ได้บันทึกภาพ")
    fig = draw(result, road_width=result.road_width)
    if args.save:
        fig.savefig(args.save, dpi=140, bbox_inches="tight")
        print(f"[export] เขียนภาพ {args.save}")
    if not args.agg:
        plt.show()
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
