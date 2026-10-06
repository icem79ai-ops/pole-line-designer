# -*- coding: utf-8 -*-
"""ทดสอบมาตรฐาน 22/33 kV ด้วยกรณีต่าง ๆ : ตรง / มุมเล็ก / มุมกลาง / มุมใหญ่ / เส้นสั้น / ซิกแซ็ก

Regression harness kept from the desktop version. It drives the shared
engine in ``line_engine`` (the same code the web app uses) and prints a
readable table; ``tests/test_engine.py`` carries the assertions.
"""

import math

import line_engine as engine


def deflect(turn_deg, l1=200.0, l2=80.0, l3=200.0):
    """เส้นตรง -> เบี่ยงเบน turn_deg ครั้งเดียว -> เส้นตรง"""
    t = math.radians(turn_deg)
    p1 = (l1, 0.0)
    p2 = (l1 + l2 * math.cos(t), l2 * math.sin(t))
    p3 = (p2[0] + l3 * math.cos(t), p2[1] + l3 * math.sin(t))
    return [(0.0, 0.0), p1, p2, p3]


CASES = [
    ("เส้นตรง 150 m (ไม่มีมุม)", [(0.0, 0.0), (150.0, 0.0)]),
    ("เส้นตรง 40 m พอดี", [(0.0, 0.0), (40.0, 0.0)]),
    ("มุมเล็ก 5 deg (SA, max 35 m)", deflect(5)),
    ("มุมกลาง 20 deg (MA, max 25 m)", deflect(20)),
    ("มุมใหญ่ 45 deg (LA, max 20 m)", deflect(45)),
    ("มุม 60 deg (ขอบเขต SA/BA)", deflect(60)),
    ("มุม 61 deg (BA)", deflect(61)),
    ("มุม 90 deg (BA)", deflect(90, 100, 50, 50)),
    ("เส้นสั้นมาก 8 m", [(0.0, 0.0), (8.0, 0.0)]),
    ("หักศอกสามครั้ง", [(0.0, 0.0), (60.0, 0.0), (60.0, 45.0), (110.0, 45.0), (110.0, 90.0), (150.0, 90.0)]),
    ("มุมเล็ก 2 deg (ขอบเขต TG/SA)", deflect(2)),
]


def main() -> int:
    print("=" * 78)
    failures = 0
    for name, cl in CASES:
        result = engine.design(cl)
        maxs = max((p.get("span_to_next") or 0.0 for p in result.poles), default=0.0)
        types: dict[str, int] = {}
        for p in result.poles:
            types[p["code"]] = types.get(p["code"], 0) + 1
        print(
            f"{name:38} L={result.centerline.total:7.2f}m  "
            f"เสา={len(result.poles):3d}  maxspan={maxs:6.2f}m  "
            f"{'PASS' if result.ok else 'FAIL'}"
        )
        print(f"{'':38} {types}")
        if not result.ok:
            failures += 1
            for row in result.validation:
                if row["status"] == "FAIL":
                    print(f"{'':40} !! {row['label']} = {row['value']}")
        for w in result.warnings:
            print(f"{'':40} .. {w}")
    print("=" * 78)

    cl = [(0.0, 0.0), (0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]
    result = engine.design(cl)
    print(
        "จุดซ้ำต้องถูกลบ:",
        len(result.poles),
        "เสา,",
        "PASS" if result.ok else "FAIL",
    )
    if not result.ok:
        failures += 1
    print("=" * 78)
    print("ผลรวม:", "PASS ทุกกรณี" if failures == 0 else f"FAIL {failures} กรณี")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
