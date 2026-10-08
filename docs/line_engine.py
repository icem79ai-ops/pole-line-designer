# -*- coding: utf-8 -*-
"""
line_engine.py - 22/33 kV Overhead Line Automatic Pole Placement Engine

Pure calculation module (no GUI, no web framework) so that the same
standards logic is used by:
    - the Flask web application (app.py)
    - the matplotlib CLI report (pole_designer.py)
    - the automated test suite (tests/)

Standards implemented (22/33 kV, conductor SAC 50 sq.mm.):
    1. Every pole is offset 5.0 m from the road centerline (R.O.W. line),
       never on the carriageway or shoulder.
    2. Maximum span table for SAC 50 sq.mm.:
           theta <= 2 deg      -> 40 m   (Tangent structure, TG)
           2 < theta <= 15 deg -> 35 m   (Small angle, SA)
           15 < theta <= 30 deg-> 25 m   (Medium angle, MA)
           30 < theta <= 60 deg-> 20 m   (Large angle, LA)
           theta > 60 deg      -> 20 m   (Slack span via Buck Arm, BA)
    3. Tangent structures (TG) are forbidden on curved runs (PC - PT);
       only SA / MA / LA / BA structures may be placed there.
    4. Mechanical tension balance, bracket logic:
           (-O   open bracket  : DDE receiving tension from the straight side
           ---O---  balanced  : tangent pole, no guy wire, no anchor
           O-)   close bracket : DDE receiving tension from the straight side
           Slack-BA           : slack span carried by a Buck Arm
    5. Slack spans on curved runs must not exceed 20 m, measured as the
       real chord distance between the Buck/Angle structure and the
       adjacent bracket pole (not the chainage distance).
    6. Guy wires (GY-21) and anchors are installed only on dead-end poles
       and are directed parallel to and back along the R.O.W. line.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ----------------------------------------------------------------- constants
ROW_OFFSET = 5.0
TANGENT_TOL = 2.0
MAX_SLACK_SPAN = 20.0
MIN_SPACING = 10.0
MIN_CORE = 3.0
MAX_TANGENT_SPAN = 40.0
USE_BREAK_POLES = True

# Road corridor rule. A pole must never stand on the carriageway: the offset it
# uses is never allowed below half the road width plus this clearance, which is
# the distance kept between the pole centre line and the edge of the road.
ROAD_WIDTH = 16.0
ROAD_CLEARANCE = 2.0

# Deflection below this angle is carried by a single angle pole; a pair of
# break poles around it would add hardware without adding strength.
ANGLE_BREAK_MIN = 30.0

# Distance from a guy pole to its anchor block, in metres.
ANCHOR_LEN = 10.0

SPAN_TABLE = (
    {"max_angle": 2.0, "label": "Tangent (TG)", "code": "TG", "max_span": 40.0},
    {"max_angle": 15.0, "label": "Small Angle (SA)", "code": "SA", "max_span": 35.0},
    {"max_angle": 30.0, "label": "Medium Angle (MA)", "code": "MA", "max_span": 25.0},
    {"max_angle": 60.0, "label": "Large Angle (LA)", "code": "LA", "max_span": 20.0},
    {"max_angle": 180.0, "label": "Slack Span / Buck Arm (BA)", "code": "BA", "max_span": 20.0},
)

TYPE_NAME = {
    "start": "เสาดับสายต้นทาง DDE (Start Deadend)",
    "end": "เสาดับสายปลายทาง DDE (End Deadend)",
    "tangent": "เสาทางตรง Tangent (TG)",
    "curve": "เสาทางโค้ง Angle (SA/MA/LA)",
    "break_open": "เสาเบรกเปิดวงเล็บ DDE (Break Open)",
    "break_close": "เสาเบรกปิดวงเล็บ DDE (Break Close)",
    "ba": "เสาหักศอก Buck Arm (BA)",
}

BRACKET = {
    "start": "(-O",
    "end": "O-)",
    "break_open": "(-O",
    "break_close": "O-)",
    "ba": "Slack-BA",
    "curve": "---O---",
    "tangent": "---O---",
}

MARKER = {
    "start": "square",
    "end": "hexagon",
    "break_open": "square",
    "break_close": "hexagon",
    "ba": "diamond",
    "curve": "circle",
    "tangent": "circle",
}

COLOR = {
    "start": "#d32f2f",
    "end": "#d32f2f",
    "break_open": "#d32f2f",
    "break_close": "#d32f2f",
    "ba": "#ef6c00",
    "curve": "#ef6c00",
    "tangent": "#1565c0",
}

ANGLE_CODES = ("curve", "ba")
DDE_CODES = ("start", "end", "break_open", "break_close")

CSV_COLUMNS = [
    "id",
    "x",
    "y",
    "station",
    "code",
    "type",
    "gy",
    "gy_angle",
    "bracket",
    "angle",
    "span_from_prev",
    "span_to_next",
]


# ----------------------------------------------------------------- utilities
def max_span_for_angle(angle_deg: float) -> float:
    """Maximum span in metres allowed for SAC 50 sq.mm. at a given angle."""
    a = abs(float(angle_deg))
    for row in SPAN_TABLE:
        if a <= row["max_angle"]:
            return row["max_span"]
    return SPAN_TABLE[-1]["max_span"]


def span_rule_for_angle(angle_deg: float) -> dict:
    """Return the span-table row that governs a given deflection angle."""
    a = abs(float(angle_deg))
    for row in SPAN_TABLE:
        if a <= row["max_angle"]:
            return row
    return SPAN_TABLE[-1]


def deflection_angle(deg_in: float, deg_out: float) -> float:
    """Absolute deflection angle between two direction angles, in [0, 180]."""
    delta = abs(math.radians(deg_out) - math.radians(deg_in))
    delta = abs(math.degrees(delta))
    if delta > 180.0:
        delta = 360.0 - delta
    return float(delta)


# ----------------------------------------------------------------- geometry
class Polyline:
    """Road centerline defined by a list of vertices, with station based
    position, heading and 2D normal offset queries."""

    def __init__(self, points):
        pts = np.asarray(points, dtype=float)
        if pts.ndim != 2 or pts.shape[0] < 2 or pts.shape[1] != 2:
            raise ValueError("centerline ต้องเป็นรูปแบบ [[x, y], ...] อย่างน้อย 2 จุด")
        if not np.all(np.isfinite(pts)):
            raise ValueError("พิกัด centerline ต้องเป็นตัวเลขจำนวนจริงทั้งหมด")

        clean: list[np.ndarray] = [pts[0]]
        for p in pts[1:]:
            if float(np.hypot(float(p[0] - clean[-1][0]), float(p[1] - clean[-1][1]))) > 1e-9:
                clean.append(p)
        if len(clean) < 2:
            raise ValueError("centerline ต้องมีระยะห่างระหว่างจุดมากกว่า 0")

        self.pts = np.array(clean, dtype=float)
        self.seg_len = [
            float(
                np.hypot(
                    float(self.pts[i + 1][0] - self.pts[i][0]),
                    float(self.pts[i + 1][1] - self.pts[i][1]),
                )
            )
            for i in range(len(self.pts) - 1)
        ]
        self.cum = np.concatenate([[0.0], np.cumsum(self.seg_len)]).astype(float)
        self.total = float(self.cum[-1])

    @property
    def vertices(self) -> list[tuple[float, float]]:
        return [(float(p[0]), float(p[1])) for p in self.pts]

    def segment_index(self, s: float) -> int:
        s = float(np.clip(s, 0.0, self.total))
        i = int(np.searchsorted(self.cum, s, side="right")) - 1
        return int(np.clip(i, 0, len(self.seg_len) - 1))

    def heading_at(self, s: float) -> float:
        i = self.segment_index(s)
        d = self.pts[i + 1] - self.pts[i]
        return math.degrees(math.atan2(float(d[1]), float(d[0])))

    def corner_heading(self, s: float) -> float:
        """Bisector heading used for offsetting a pole that sits on a corner."""
        i = int(np.searchsorted(self.cum, s, side="left"))
        if 0 < i < len(self.seg_len):
            h1 = self.heading_at(float(self.cum[i - 1]) + 1e-9)
            h2 = self.heading_at(float(self.cum[i]) + 1e-9)
            x = math.cos(math.radians(h1)) + math.cos(math.radians(h2))
            y = math.sin(math.radians(h1)) + math.sin(math.radians(h2))
            if abs(x) > 1e-9 or abs(y) > 1e-9:
                return math.degrees(math.atan2(y, x))
        return self.heading_at(s)

    def position(self, s: float, at_corner: bool = False) -> tuple[float, float, float]:
        s = float(np.clip(s, 0.0, self.total))
        i = self.segment_index(s)
        length = max(self.seg_len[i], 1e-12)
        t = (s - float(self.cum[i])) / length
        p = self.pts[i] + t * (self.pts[i + 1] - self.pts[i])
        heading = self.corner_heading(s) if at_corner else self.heading_at(s)
        return float(p[0]), float(p[1]), float(heading)

    def offset_point(
        self, s: float, offset: float, at_corner: bool = False
    ) -> tuple[float, float, float]:
        """Offset a station sideways from the centerline using the 2D normal
        vector n = [-v_y, v_x] of the local tangent."""
        x, y, heading = self.position(s, at_corner)
        a = math.radians(heading)
        return (
            float(x - offset * math.sin(a)),
            float(y + offset * math.cos(a)),
            float(heading),
        )

    def station_at_chord(
        self,
        corner_xy: tuple[float, float],
        s_corner: float,
        backward: bool,
        dist: float,
        offset: float,
    ) -> float:
        """Station whose real chord distance from a corner pole equals `dist`.

        The 20 m slack reserve must be measured as a chord, not as a chainage
        distance: on a sharp corner the pole standing on the angle bisector is
        offset sideways from the centerline, so equal station differences do not
        produce equal spans. Solved by bisection, which is monotone.
        """
        tx, ty = float(corner_xy[0]), float(corner_xy[1])

        def chord(t: float) -> float:
            s = s_corner - t if backward else s_corner + t
            if s < -1e-9 or s > self.total + 1e-9:
                return float("inf")
            x, y, _ = self.offset_point(
                float(min(max(s, 0.0), self.total)), offset, at_corner=False
            )
            return float(math.hypot(x - tx, y - ty))

        if chord(0.0) >= dist:
            return float(s_corner)
        hi = min(80.0, self.total)
        if chord(hi) < dist:
            return float(s_corner - hi if backward else s_corner + hi)
        lo = 0.0
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if chord(mid) < dist:
                lo = mid
            else:
                hi = mid
        t = (lo + hi) / 2.0
        return float(s_corner - t if backward else s_corner + t)

    def corners(self) -> list[dict]:
        """All polyline corners with their deflection angles in degrees."""
        out: list[dict] = []
        for i in range(1, len(self.pts) - 1):
            d1 = self.pts[i] - self.pts[i - 1]
            d2 = self.pts[i + 1] - self.pts[i]
            th1 = math.degrees(math.atan2(float(d1[1]), float(d1[0])))
            th2 = math.degrees(math.atan2(float(d2[1]), float(d2[0])))
            out.append(
                {
                    "index": i,
                    "station": float(self.cum[i]),
                    "angle": deflection_angle(th1, th2),
                    "x": float(self.pts[i][0]),
                    "y": float(self.pts[i][1]),
                }
            )
        return out


# ------------------------------------------------------------ request parsing
def parse_request(payload) -> dict:
    """Validate one design request (JSON body) and return the engine arguments.

    Shared by the Flask routes and the in-browser Pyodide bridge so both
    reject the same bad input with the same Thai message. Raises ValueError
    on any invalid input; the web layer turns that into HTTP 400.
    """
    if not isinstance(payload, dict):
        raise ValueError("body ต้องเป็น JSON object")

    points = payload.get("points")
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("ต้องส่ง points เป็นรายการพิกัด [[x, y], ...] อย่างน้อย 2 จุด")

    cleaned: list[list[float]] = []
    for index, point in enumerate(points):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"points[{index}] ต้องเป็น [x, y]")
        try:
            x = float(point[0])
            y = float(point[1])
        except (TypeError, ValueError):
            raise ValueError(f"points[{index}] ต้องเป็นตัวเลข")
        cleaned.append([x, y])

    offset_raw = payload.get("offset", ROW_OFFSET)
    try:
        offset = float(offset_raw)
    except (TypeError, ValueError):
        raise ValueError("offset ต้องเป็นตัวเลข (เมตร)")
    if not 0.0 < offset <= 50.0:
        raise ValueError("offset ต้องอยู่ระหว่าง 0 (ไม่รวม) ถึง 50 เมตร")

    road_width_raw = payload.get("road_width", ROAD_WIDTH)
    try:
        road_width = float(road_width_raw)
    except (TypeError, ValueError):
        raise ValueError("road_width ต้องเป็นตัวเลข (เมตร)")
    if not 0.0 <= road_width <= 50.0:
        raise ValueError("road_width ต้องอยู่ระหว่าง 0 ถึง 50 เมตร")

    use_break = bool(payload.get("use_break_poles", USE_BREAK_POLES))
    return {
        "points": cleaned,
        "offset": offset,
        "use_break_poles": use_break,
        "road_width": road_width,
        "road_clearance": float(payload.get("road_clearance", ROAD_CLEARANCE)),
    }


# ----------------------------------------------------------------- design
@dataclass
class DesignResult:
    centerline: Polyline
    poles: list[dict]
    validation: list[dict]
    warnings: list[str] = field(default_factory=list)
    ok: bool = True
    offset: float = ROW_OFFSET
    use_break_poles: bool = USE_BREAK_POLES
    road_width: float = ROAD_WIDTH
    road_clearance: float = ROAD_CLEARANCE
    requested_offset: float = ROW_OFFSET


def design(
    centerline,
    offset: float = ROW_OFFSET,
    use_break_poles: bool = USE_BREAK_POLES,
    road_width: float = ROAD_WIDTH,
    road_clearance: float = ROAD_CLEARANCE,
) -> DesignResult:
    """Place all poles along the centerline according to utility practice.

    Returns a DesignResult holding the polyline, the pole list, the standards
    check table and any warnings raised while designing.

    ``offset`` is what the caller asks for. If it would put a pole closer to the
    road than ``road_clearance`` allows, it is raised to
    ``road_width / 2 + road_clearance`` and a warning says so, because a pole on
    the carriageway is never a valid answer.
    """
    offset = float(offset)
    if offset <= 0.0:
        raise ValueError("ระยะ Offset แนว R.O.W. ต้องมากกว่า 0 เมตร")
    road_width = float(road_width)
    if road_width < 0.0:
        raise ValueError("ความกว้างถนนต้องไม่ติดลบ")
    road_clearance = float(road_clearance)
    if road_clearance < 0.0:
        raise ValueError("ระยะเว้นว่างเสา-ถนนต้องไม่ติดลบ")

    requested_offset = offset
    min_offset = road_width / 2.0 + road_clearance
    if offset < min_offset - 1e-9:
        offset = min_offset

    pl = Polyline(centerline)
    corners = [c for c in pl.corners() if c["angle"] > TANGENT_TOL]
    warnings: list[str] = []
    if requested_offset < min_offset - 1e-9:
        warnings.append(
            f"ระยะ Offset ที่ขอ ({requested_offset:.2f} m) ทำให้เสาอยู่ใกล้ขอบถนน "
            f"เกินกว่าเกณฑ์เว้นว่าง {road_clearance:.1f} m (เขตทางกว้าง {road_width:.1f} m) "
            f"ระบบจึงถอยแนวเสาออกเป็น {offset:.2f} m โดยอัตโนมัติ"
        )

    # 1. fixed anchor poles: both dead ends + every structure on a corner.
    #    break poles are only worth adding around a real bend, so each corner
    #    records whether it qualifies for them.
    anchors: list[dict] = [
        {"s": 0.0, "role": "start", "angle": 0.0, "break_ok": False}
    ]
    for c in corners:
        angle = float(c["angle"])
        anchors.append(
            {
                "s": float(c["station"]),
                "role": "ba" if angle > 60.0 else "curve",
                "angle": angle,
                "break_ok": angle >= ANGLE_BREAK_MIN,
            }
        )
    if anchors[-1]["role"] in ANGLE_CODES and pl.total - anchors[-1]["s"] < MIN_SPACING:
        anchors[-1] = {
            "s": pl.total,
            "role": "end",
            "angle": 0.0,
            "break_ok": False,
        }
        warnings.append(
            "จุดหักมุมอยู่ใกล้ปลายสายมาก (น้อยกว่า "
            f"{MIN_SPACING:.0f} m) จึงยุบรวมเป็นเสาดับสายปลายทาง (End Deadend) แทนเสาหักมุม"
        )
    else:
        anchors.append({"s": pl.total, "role": "end", "angle": 0.0, "break_ok": False})
    anchors = [
        a
        for i, a in enumerate(anchors)
        if i == 0 or a["role"] == "end" or a["s"] > anchors[i - 1]["s"] + 1e-6
    ]

    def make_pole(role: str, angle: float, s: float) -> dict:
        is_corner = role in ANGLE_CODES
        x, y, heading = pl.offset_point(s, offset, at_corner=is_corner)
        # a BA pole carries the same unbalanced side pull as an angle pole, so it
        # is guyed as well.
        gy = role in ("start", "end", "curve", "ba", "break_open", "break_close")
        return {
            "x": float(x),
            "y": float(y),
            "station": float(s),
            "code": role,
            "angle": float(angle),
            "gy": bool(gy),
            "gy_angle": float((heading + 180.0) % 360.0) if gy else 0.0,
            "gy_anchor_x": None,
            "gy_anchor_y": None,
            "bracket": BRACKET[role],
            "type": TYPE_NAME[role],
            "heading": float(heading),
            "span_from_prev": None,
            "span_to_next": None,
        }

    poles = [make_pole(a["role"], a["angle"], a["s"]) for a in anchors]
    fills: list[tuple[float, str]] = []

    # 2. fill the working spans between consecutive anchors
    for k in range(len(poles) - 1):
        a, b = poles[k], poles[k + 1]
        sa, sb = a["station"], b["station"]

        if a["code"] in ANGLE_CODES:
            r_a = min(
                pl.total,
                pl.station_at_chord((a["x"], a["y"]), sa, False, MAX_SLACK_SPAN, offset),
            )
        else:
            r_a = sa
        if b["code"] in ANGLE_CODES:
            r_b = max(
                0.0,
                pl.station_at_chord((b["x"], b["y"]), sb, True, MAX_SLACK_SPAN, offset),
            )
        else:
            r_b = sb

        if r_b - r_a >= MIN_CORE:
            n = max(1, int(math.ceil((r_b - r_a) / MAX_TANGENT_SPAN - 1e-9)))
            for j in range(n + 1):
                role = "tangent"
                if use_break_poles and j == 0:
                    # only a break pair around a real bend: on a gentle corner
                    # the angle pole itself already carries the side pull.
                    if (
                        anchors[k]["break_ok"]
                        and r_a > sa + 1e-6
                        and (r_a - sa) >= MIN_SPACING
                    ):
                        role = "break_open"
                elif use_break_poles and j == n:
                    if (
                        anchors[k + 1]["break_ok"]
                        and r_b < sb - 1e-6
                        and (sb - r_b) >= MIN_SPACING
                    ):
                        role = "break_close"
                fills.append((float(r_a + (r_b - r_a) * j / n), role))
        else:
            warnings.append(
                f"ช่วงระหว่างเสาบนช่วงโค้ง (chainage {sa:.1f} m ถึง {sb:.1f} m) สั้นเกินไป "
                f"จึงยังคงช่วงหลักไว้ที่ {MAX_TANGENT_SPAN:.0f} m "
                "(ผลตรวจสอบจะรายงานว่าไม่ผ่านเกณฑ์ Slack Span)"
            )
            n = max(1, int(math.ceil((sb - sa) / MAX_TANGENT_SPAN - 1e-9)))
            for j in range(n + 1):
                fills.append((float(sa + (sb - sa) * j / n), "tangent"))

    first_s, last_s = poles[0]["station"], poles[-1]["station"]
    for s, role in fills:
        if first_s + 1e-6 < s < last_s - 1e-6:
            poles.append(make_pole(role, 0.0, s))
    poles.sort(key=lambda d: d["station"])

    for idx, p in enumerate(poles, start=1):
        p["id"] = int(idx)
        p["marker"] = MARKER[p["code"]]
        p["color"] = COLOR[p["code"]]

    # 3. every guy has to oppose the wire pull that actually acts on it, which
    #    is what makes an end pole point away from the line instead of back
    #    into it and an angle pole point at the outside of the bend.
    _set_guy_angles(poles)

    validation, ok = validate(pl, poles, offset, road_width, road_clearance)
    warnings += _collect_warnings(pl, poles, offset)
    for p in poles:
        p.pop("heading", None)
    return DesignResult(
        centerline=pl,
        poles=poles,
        validation=validation,
        warnings=warnings,
        ok=ok,
        offset=offset,
        use_break_poles=bool(use_break_poles),
        road_width=road_width,
        road_clearance=road_clearance,
        requested_offset=requested_offset,
    )


def _guy_direction_for(poles: list[dict], index: int):
    """Direction (degrees, world frame) in which the guy of poles[index] runs.

    The anchor has to oppose the resultant of the wire tensions acting on the
    pole, so it is the direction opposite to ``unit(pole->prev) +
    unit(pole->next)``. At a dead end only one of the two terms exists, which
    makes the anchor point straight away from the line; on an angle pole the two
    terms bisect the bend from the outside.

    Returns None when the pole is the only one (nothing to pull against).
    """
    p = poles[index]
    if len(poles) < 2:
        return None
    vx = vy = 0.0
    if index > 0:
        q = poles[index - 1]
        length = math.hypot(q["x"] - p["x"], q["y"] - p["y"])
        if length > 1e-9:
            vx += (q["x"] - p["x"]) / length
            vy += (q["y"] - p["y"]) / length
    if index < len(poles) - 1:
        q = poles[index + 1]
        length = math.hypot(q["x"] - p["x"], q["y"] - p["y"])
        if length > 1e-9:
            vx += (q["x"] - p["x"]) / length
            vy += (q["y"] - p["y"]) / length
    resultant = math.hypot(vx, vy)
    if resultant < 1e-9:
        # the two tensions cancel exactly (the line doubles back): there is no
        # net pull to oppose, so fall back to facing away from the next pole.
        q = poles[min(index + 1, len(poles) - 1)]
        return (math.degrees(math.atan2(p["y"] - q["y"], p["x"] - q["x"])) + 360.0) % 360.0
    return (math.degrees(math.atan2(-vy, -vx)) + 360.0) % 360.0


def _set_guy_angles(poles: list[dict]) -> None:
    """Write the true guy direction and anchor block onto every guy pole."""
    for index, pole in enumerate(poles):
        if not pole["gy"]:
            pole["gy_angle"] = 0.0
            pole["gy_anchor_x"] = None
            pole["gy_anchor_y"] = None
            continue
        direction = _guy_direction_for(poles, index)
        if direction is None:
            pole["gy_angle"] = 0.0
            pole["gy_anchor_x"] = None
            pole["gy_anchor_y"] = None
            continue
        radians = math.radians(direction)
        pole["gy_angle"] = float(direction)
        pole["gy_anchor_x"] = float(pole["x"] + math.cos(radians) * ANCHOR_LEN)
        pole["gy_anchor_y"] = float(pole["y"] + math.sin(radians) * ANCHOR_LEN)


def _collect_warnings(pl: Polyline, poles: list[dict], offset: float) -> list[str]:
    out: list[str] = []
    for i in range(len(poles) - 1):
        a, b = poles[i], poles[i + 1]
        span = float(math.hypot(b["x"] - a["x"], b["y"] - a["y"]))
        if a["code"] in ANGLE_CODES and span > MAX_SLACK_SPAN + 1e-6:
            out.append(
                f"ช่วง Slack ของเสาหักมุม #{a['id']} ({a['code'].upper()}) ยาว {span:.2f} m "
                f"เกิน {MAX_SLACK_SPAN:.0f} m ตามเกณฑ์ SAC 50"
            )
        if a["code"] in ANGLE_CODES and b["code"] in ANGLE_CODES:
            out.append(
                f"เสาหักมุม #{a['id']} และ #{b['id']} อยู่ใกล้กันเกินไป "
                "ควรพิจารณารวมจุดหักหรือเลื่อนแนวเส้นทาง"
            )
    if len(poles) < 2:
        out.append("จำนวนเสาน้อยกว่า 2 ต้น กรุณาตรวจสอบความยาวแนวเส้นทาง")
    return out


# ----------------------------------------------------------------- validation
def validate(
    pl: Polyline,
    poles: list[dict],
    offset: float,
    road_width: float = ROAD_WIDTH,
    road_clearance: float = ROAD_CLEARANCE,
) -> tuple[list[dict], bool]:
    """Check the designed pole list against the design rules.

    Returns the check table plus an overall pass flag. Nothing is assumed to
    pass: every check is recomputed from the final coordinates.
    """
    ok_span = True
    ok_slack = True
    ok_curve = True
    ok_bracket = True
    ok_gy = True
    ok_offset = True
    max_span_used = 0.0
    curve_stations = [p["station"] for p in poles if p["code"] in ANGLE_CODES]

    for i in range(len(poles) - 1):
        a, b = poles[i], poles[i + 1]
        span = float(math.hypot(b["x"] - a["x"], b["y"] - a["y"]))
        a["span_to_next"] = round(span, 3)
        b["span_from_prev"] = round(span, 3)
        max_span_used = max(max_span_used, span)

        allow = min(max_span_for_angle(a["angle"]), max_span_for_angle(b["angle"]))
        if span > allow + 1e-6:
            ok_span = False
        for pole in (a, b):
            if pole["code"] in ANGLE_CODES and span > MAX_SLACK_SPAN + 1e-6:
                ok_slack = False

        if a["code"] == "tangent" and b["code"] == "tangent":
            for s0 in curve_stations:
                if a["station"] < s0 < b["station"]:
                    ok_curve = False

    for index, p in enumerate(poles):
        if BRACKET[p["code"]] != p["bracket"]:
            ok_bracket = False
        if p["code"] == "tangent" and (p["gy"] or p["bracket"] != "---O---"):
            ok_bracket = False
        if p["code"] == "tangent" and abs(p["angle"]) > TANGENT_TOL:
            ok_curve = False
        need_gy = p["code"] in (
            "start",
            "end",
            "curve",
            "ba",
            "break_open",
            "break_close",
        )
        if bool(p["gy"]) != need_gy:
            ok_gy = False
        if p["gy"]:
            # Recompute the guy direction from the real pole geometry instead of
            # trusting the stored angle: an anchor has to oppose the resultant
            # wire pull, which validate() must be able to verify on any pole
            # list, including one that came back from JSON or a CSV round trip.
            expect = _guy_direction_for(poles, index)
            if expect is None:
                ok_gy = False
            elif abs(((p["gy_angle"] - expect + 180.0) % 360.0) - 180.0) > 1e-6:
                ok_gy = False
        x0, y0, _ = pl.offset_point(
            p["station"], 0.0, at_corner=p["code"] in ANGLE_CODES
        )
        if abs(float(math.hypot(p["x"] - x0, p["y"] - y0)) - offset) > 1e-6:
            ok_offset = False

    if poles:
        if poles[0]["bracket"] != "(-O" or poles[-1]["bracket"] != "O-)":
            ok_bracket = False

    # real road clearance: distance from the pole centre line to the edge of the
    # road has to be at least road_clearance everywhere.
    min_edge_clearance = float(offset) - float(road_width) / 2.0
    ok_road = min_edge_clearance >= float(road_clearance) - 1e-6

    table = [
        {
            "key": "max_span",
            "label": "Max Span SAC 50 (40/35/25/20 m)",
            "value": f"{max_span_used:.2f} m",
            "status": "PASS" if ok_span else "FAIL",
        },
        {
            "key": "slack_span",
            "label": "Slack Span บนช่วงโค้ง <= 20 m",
            "value": "ตรวจทุกช่อง BA/SA/MA/LA",
            "status": "PASS" if ok_slack else "FAIL",
        },
        {
            "key": "no_tangent_on_curve",
            "label": "ห้ามเสา TG บนช่วง PC-PT",
            "value": "ไม่พบ TG บนโค้ง",
            "status": "PASS" if ok_curve else "FAIL",
        },
        {
            "key": "bracket_logic",
            "label": "Bracket Logic (-O ... O-)",
            "value": "สมดุลแรงดึง",
            "status": "PASS" if ok_bracket else "FAIL",
        },
        {
            "key": "guy_anchor",
            "label": "สายยึดโยง + สมอบก GY-21",
            "value": "ขนานใต้แนว R.O.W.",
            "status": "PASS" if ok_gy else "FAIL",
        },
        {
            "key": "row_offset",
            "label": "ระยะ Offset จาก Centerline",
            "value": f"{offset:.2f} m",
            "status": "PASS" if ok_offset else "FAIL",
        },
        {
            "key": "no_pole_on_road",
            "label": "ห้ามปักเสาบนผิวจราจร",
            "value": f"ริมทาง {min_edge_clearance:.2f} m (ต้อง ≥ {road_clearance:.1f} m)",
            "status": "PASS" if ok_road else "FAIL",
        },
    ]
    ok = (
        ok_span
        and ok_slack
        and ok_curve
        and ok_bracket
        and ok_gy
        and ok_offset
        and ok_road
    )
    return table, bool(ok)


# ----------------------------------------------------------------- reporting
def spans_of(poles: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i in range(len(poles) - 1):
        a, b = poles[i], poles[i + 1]
        length = float(math.hypot(b["x"] - a["x"], b["y"] - a["y"]))
        out.append(
            {
                "from_id": a["id"],
                "to_id": b["id"],
                "length": round(length, 3),
                "mid_x": (a["x"] + b["x"]) / 2.0,
                "mid_y": (a["y"] + b["y"]) / 2.0,
            }
        )
    return out


def summary_of(result: DesignResult) -> dict:
    poles = result.poles
    counts: dict[str, int] = {}
    for p in poles:
        counts[p["code"]] = counts.get(p["code"], 0) + 1
    max_span = max((p["span_to_next"] or 0.0 for p in poles), default=0.0)
    return {
        "length_m": round(result.centerline.total, 3),
        "pole_count": len(poles),
        "offset_m": result.offset,
        "requested_offset_m": result.requested_offset,
        "road_width_m": result.road_width,
        "road_clearance_m": result.road_clearance,
        "min_edge_clearance_m": round(
            result.offset - result.road_width / 2.0, 3
        ),
        "max_span_used_m": round(max_span, 3),
        "tangent_max_span_m": MAX_TANGENT_SPAN,
        "guy_pole_count": sum(1 for p in poles if p["gy"]),
        "curve_pole_count": sum(1 for p in poles if p["code"] in ANGLE_CODES),
        "break_pole_count": sum(
            1 for p in poles if p["code"] in ("break_open", "break_close")
        ),
        "counts": counts,
        "count_label": "  ".join(
            f"{code.upper()}={counts[code]}" for code in sorted(counts)
        ),
    }


def to_payload(result: DesignResult) -> dict:
    """JSON serialisable representation used by the web application."""
    return {
        "ok": result.ok,
        "offset_m": result.offset,
        "requested_offset_m": result.requested_offset,
        "road_width_m": result.road_width,
        "road_clearance_m": result.road_clearance,
        "min_edge_clearance_m": round(result.offset - result.road_width / 2.0, 3),
        "use_break_poles": result.use_break_poles,
        "centerline": [[p[0], p[1]] for p in result.centerline.vertices],
        "poles": [
            {
                "id": p["id"],
                "x": round(p["x"], 4),
                "y": round(p["y"], 4),
                "station": round(p["station"], 4),
                "code": p["code"],
                "type": p["type"],
                "gy": p["gy"],
                "gy_angle": round(p["gy_angle"], 3),
                "gy_anchor_x": None
                if p.get("gy_anchor_x") is None
                else round(p["gy_anchor_x"], 4),
                "gy_anchor_y": None
                if p.get("gy_anchor_y") is None
                else round(p["gy_anchor_y"], 4),
                "bracket": p["bracket"],
                "angle": round(p["angle"], 3),
                "span_from_prev": p["span_from_prev"],
                "span_to_next": p["span_to_next"],
                "marker": p["marker"],
                "color": p["color"],
            }
            for p in result.poles
        ],
        "spans": spans_of(result.poles),
        "validation": result.validation,
        "warnings": result.warnings,
        "summary": summary_of(result),
    }


def poles_to_csv(poles: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for p in poles:
        writer.writerow(p)
    return buffer.getvalue()


def sample_centerline() -> list[tuple[float, float]]:
    """Fallback road polyline: 100 m straight -> 90 deg corner 50 m -> 50 m."""
    return [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (150.0, 50.0)]


def standards_reference() -> dict:
    return {
        "span_table": [
            {
                "condition": (
                    f"มุมเบี่ยงเบน <= {int(row['max_angle'])} องศา"
                    if row["code"] != "BA"
                    else "มุมเบี่ยงเบน > 60 องศา (Slack Span)"
                ),
                "code": row["code"],
                "label": row["label"],
                "max_span_m": row["max_span"],
            }
            for row in SPAN_TABLE
        ],
        "row_offset_m": ROW_OFFSET,
        "slack_span_max_m": MAX_SLACK_SPAN,
        "tangent_tolerance_deg": TANGENT_TOL,
        "road_width_m": ROAD_WIDTH,
        "road_clearance_m": ROAD_CLEARANCE,
        "min_offset_for_road_m": ROAD_WIDTH / 2.0 + ROAD_CLEARANCE,
        "angle_break_min_deg": ANGLE_BREAK_MIN,
        "anchor_len_m": ANCHOR_LEN,
        "rules": [
            "เสาต้องอยู่นอกเขตทาง: ห่างจากเส้นกึ่งกลางถนนอย่างน้อย "
            "ครึ่งหนึ่งของความกว้างทาง + "
            f"{ROAD_CLEARANCE:.1f} m เว้นว่าง (ถ้า Offset ที่ขอสั้นกว่า ระบบถอยออกให้เอง)",
            f"ระยะ Offset เริ่มต้นของระบบคือ {ROW_OFFSET:.1f} m และต้องไม่น้อยกว่า "
            f"ครึ่งหนึ่งของความกว้างทาง",
            "ระยะช่วงเสาสูงสุดของสายเคเบิลอากาศ SAC 50 ตร.มม. เป็น 40 / 35 / 25 / 20 m",
            "ห้ามใช้เสาทางตรง (TG) บนช่วงแนวโค้ง (PC - PT)",
            "เสาทุกต้นบนช่วงโค้งต้องเป็นเสาทางโค้ง (SA/MA/LA) หรือเสาหักศอก (BA)",
            "Slack Span บนช่วงโค้งต้องไม่เกิน "
            f"{MAX_SLACK_SPAN:.0f} m (วัดเป็นระยะสายจริง)",
            f"เสาเบรก (Break) คู่หน้าหลังมุมใช้เฉพาะมุมเบี่ยงเบน ≥ "
            f"{ANGLE_BREAK_MIN:.0f} องศา และต้องมีระยะตั้งเสาแทรกอย่างน้อย "
            f"{MIN_SPACING:.0f} m โค้งอ่อนไม่ต้องใช้",
            "สมอบกและสายยึดโยงต้องชี้ทวนแรงดึงจริงของสาย "
            "(เสาดับสายปลายทางชี้ออกไปทางปลายสาย ไม่ใช่ย้อนกลับเข้าไปในสาย)",
            "สายยึดโยงของเสาหักมุมชี้ที่มุมภายนอกของแนวโค้ง "
            f"ระยะห่างจากเสาถึงสมอบก {ANCHOR_LEN:.0f} m",
            "เสาทางตรงที่อยู่ระหว่างแรงดึงสมดุล (---O---) ไม่ต้องมีสายยึดโยง",
        ],
    }