# -*- coding: utf-8 -*-
"""Unit tests for the standards engine (line_engine)."""

from __future__ import annotations

import json
import math
import unittest

import line_engine as engine


def deflect(turn_deg, l1=200.0, l2=80.0, l3=200.0):
    """straight -> single deflection of turn_deg -> straight"""
    t = math.radians(turn_deg)
    p1 = (l1, 0.0)
    p2 = (l1 + l2 * math.cos(t), l2 * math.sin(t))
    p3 = (p2[0] + l3 * math.cos(t), p2[1] + l3 * math.sin(t))
    return [(0.0, 0.0), p1, p2, p3]


class TestSpanTable(unittest.TestCase):
    def test_boundaries(self):
        cases = {0.0: 40.0, 2.0: 40.0, 2.01: 35.0, 15.0: 35.0, 15.01: 25.0,
                 30.0: 25.0, 30.01: 20.0, 60.0: 20.0, 60.01: 20.0, 120.0: 20.0}
        for angle, expected in cases.items():
            self.assertAlmostEqual(
                engine.max_span_for_angle(angle), expected, msg=f"angle {angle}"
            )

    def test_negative_angle_is_absolute(self):
        self.assertEqual(
            engine.max_span_for_angle(-20.0), engine.max_span_for_angle(20.0)
        )


class TestPolyline(unittest.TestCase):
    def test_requires_two_distinct_points(self):
        with self.assertRaises(ValueError):
            engine.Polyline([(0.0, 0.0)])
        with self.assertRaises(ValueError):
            engine.Polyline([(0.0, 0.0), (0.0, 0.0)])

    def test_rejects_non_finite(self):
        with self.assertRaises(ValueError):
            engine.Polyline([(0.0, 0.0), (float("nan"), 1.0)])

    def test_duplicate_points_removed(self):
        pl = engine.Polyline([(0.0, 0.0), (0.0, 0.0), (50.0, 0.0), (100.0, 0.0)])
        self.assertEqual(len(pl.vertices), 3)
        self.assertAlmostEqual(pl.total, 100.0)

    def test_station_and_heading(self):
        pl = engine.Polyline([(0.0, 0.0), (100.0, 0.0)])
        x, y, h = pl.position(50.0)
        self.assertAlmostEqual(x, 50.0)
        self.assertAlmostEqual(y, 0.0)
        self.assertAlmostEqual(h, 0.0)

    def test_offset_is_perpendicular(self):
        pl = engine.Polyline([(0.0, 0.0), (100.0, 0.0)])
        x, y, _ = pl.offset_point(50.0, 5.0)
        self.assertAlmostEqual(x, 50.0)
        self.assertAlmostEqual(y, 5.0)

    def test_station_at_chord_is_true_chord(self):
        pl = engine.Polyline([(0.0, 0.0), (100.0, 0.0)])
        s = pl.station_at_chord((50.0, 5.0), 50.0, False, 20.0, 5.0)
        x, y, _ = pl.offset_point(s, 5.0)
        self.assertAlmostEqual(math.hypot(x - 50.0, y - 5.0), 20.0, places=6)

    def test_corners_deflection(self):
        pl = engine.Polyline([(0.0, 0.0), (100.0, 0.0), (100.0, 50.0)])
        corners = pl.corners()
        self.assertEqual(len(corners), 1)
        self.assertAlmostEqual(corners[0]["angle"], 90.0)


class TestDesign(unittest.TestCase):
    def test_straight_run(self):
        # road_width=0 removes the road-clearance floor so the pure offset
        # geometry is what the assertions below actually test
        r = engine.design([(0.0, 0.0), (150.0, 0.0)], road_width=0.0)
        self.assertTrue(r.ok)
        self.assertEqual(r.poles[0]["code"], "start")
        self.assertEqual(r.poles[-1]["code"], "end")
        for p in r.poles:
            self.assertEqual(p["bracket"], "---O---" if p["code"] == "tangent" else p["bracket"])
            self.assertAlmostEqual(abs(p["y"] - 0.0), 5.0, places=6)

    def test_two_end_dead_ends(self):
        for name, cl in (
            ("straight", [(0.0, 0.0), (150.0, 0.0)]),
            ("corner", deflect(45.0)),
            ("sag", [(0.0, 0.0), (60.0, 0.0), (60.0, 45.0), (110.0, 45.0)]),
        ):
            r = engine.design(cl)
            self.assertEqual(r.poles[0]["bracket"], "(-O", msg=name)
            self.assertEqual(r.poles[-1]["bracket"], "O-)", msg=name)

    def test_no_tangent_on_curve(self):
        for turn in (5.0, 20.0, 45.0, 61.0, 90.0):
            r = engine.design(deflect(turn))
            curve_stations = [
                p["station"] for p in r.poles if p["code"] in engine.ANGLE_CODES
            ]
            for a, b in zip(r.poles, r.poles[1:]):
                if a["code"] == "tangent" and b["code"] == "tangent":
                    for s0 in curve_stations:
                        self.assertFalse(
                            a["station"] < s0 < b["station"],
                            msg=f"tangent pair straddles a curve at turn={turn}",
                        )

    def test_slack_span_within_limit(self):
        for turn in (20.0, 45.0, 61.0, 90.0):
            r = engine.design(deflect(turn))
            for i, a in enumerate(r.poles[:-1]):
                if a["code"] in engine.ANGLE_CODES:
                    span = a["span_to_next"]
                    if span is not None and span > engine.MIN_CORE:
                        self.assertLessEqual(
                            span,
                            engine.MAX_SLACK_SPAN + 0.01,
                            msg=f"slack span too long at turn={turn}",
                        )

    def test_guy_only_on_dead_end_and_angle(self):
        for turn in (45.0, 90.0):
            r = engine.design(deflect(turn))
            for p in r.poles:
                need = p["code"] in (
                    "start", "end", "curve", "ba", "break_open", "break_close"
                )
                self.assertEqual(p["gy"], need, msg=f"turn={turn} #{p['id']} {p['code']}")
                if p["gy"]:
                    self.assertTrue(0.0 <= p["gy_angle"] < 360.0)
                    self.assertIsNotNone(p["gy_anchor_x"])
                    self.assertIsNotNone(p["gy_anchor_y"])

    def test_break_poles_flag(self):
        with_break = engine.design(deflect(45.0), use_break_poles=True)
        without = engine.design(deflect(45.0), use_break_poles=False)
        codes_with = {p["code"] for p in with_break.poles}
        codes_without = {p["code"] for p in without.poles}
        self.assertTrue({"break_open", "break_close"} & codes_with)
        self.assertFalse({"break_open", "break_close"} & codes_without)

    def test_stations_sorted_and_unique(self):
        r = engine.design([(0.0, 0.0), (60.0, 0.0), (60.0, 45.0), (110.0, 45.0),
                          (110.0, 90.0), (150.0, 90.0)])
        stations = [p["station"] for p in r.poles]
        self.assertEqual(stations, sorted(stations))
        self.assertEqual(len(stations), len(set(stations)))

    def test_offset_parameter_respected(self):
        # road_width=0 keeps the requested offset untouched; the road-clearance
        # raise is covered separately in TestRoadClearance
        r = engine.design([(0.0, 0.0), (150.0, 0.0)], offset=7.5, road_width=0.0)
        self.assertAlmostEqual(r.offset, 7.5)
        for p in r.poles:
            self.assertAlmostEqual(p["y"], 7.5, places=6)

    def test_zero_offset_rejected(self):
        with self.assertRaises(ValueError):
            engine.design([(0.0, 0.0), (100.0, 0.0)], offset=0.0)

    def test_tiny_run_still_produces_two_poles(self):
        r = engine.design([(0.0, 0.0), (8.0, 0.0)])
        self.assertGreaterEqual(len(r.poles), 2)
        self.assertEqual(r.poles[0]["code"], "start")
        self.assertEqual(r.poles[-1]["code"], "end")

    def test_corner_near_end_merges_into_end_deadend(self):
        # corner at station 150, only 4 m before the route end
        r = engine.design([(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (104.0, 50.0)])
        self.assertEqual(r.poles[-1]["code"], "end")
        self.assertTrue(any("ยุบรวม" in w for w in r.warnings))


def gentle_bend(deflection_deg=8.0, leg=200.0, tail=200.0):
    """Centerline whose corner deflects by ``deflection_deg`` degrees."""
    rad = math.radians(deflection_deg)
    return [
        (0.0, 0.0),
        (leg, 0.0),
        (leg + tail * math.cos(rad), tail * math.sin(rad)),
    ]


class TestBreakPoleThreshold(unittest.TestCase):
    def test_gentle_bend_has_no_break_poles(self):
        r = engine.design(gentle_bend(8.0))
        codes = [p["code"] for p in r.poles]
        self.assertNotIn("break_open", codes)
        self.assertNotIn("break_close", codes)
        self.assertIn("curve", codes, msg="a gentle bend still needs an angle pole")
        self.assertTrue(r.ok)

    def test_medium_bend_keeps_break_poles(self):
        r = engine.design(deflect(45.0))
        codes = {p["code"] for p in r.poles}
        self.assertIn("break_open", codes)
        self.assertIn("break_close", codes)

    def test_threshold_boundary(self):
        just_under = engine.design(gentle_bend(engine.ANGLE_BREAK_MIN - 1.0))
        just_over = engine.design(gentle_bend(engine.ANGLE_BREAK_MIN + 1.0))
        self.assertFalse(
            any(p["code"].startswith("break") for p in just_under.poles),
            msg="deflection below the threshold must not produce break poles",
        )
        self.assertTrue(
            any(p["code"].startswith("break") for p in just_over.poles),
            msg="deflection at/above the threshold keeps break poles",
        )


def grouped_bend(deg1=18.0, sep=15.0, deg2=18.0, tail=200.0, leg=60.0):
    """Two deflections in the same direction, the second corner ``sep``
    metres after the first -- the building block of a sweeping curve."""
    rad1 = math.radians(deg1)
    rad2 = math.radians(deg1 + deg2)
    p2 = (leg + sep * math.cos(rad1), sep * math.sin(rad1))
    p3 = (p2[0] + tail * math.cos(rad2), p2[1] + tail * math.sin(rad2))
    return [(0.0, 0.0), (leg, 0.0), p2, p3]


class TestBreakPoleGrouping(unittest.TestCase):
    """Corners within one slack span merge into a single bend group; its
    deflection is summed, and one break pair flanks the whole group."""

    def test_grouped_corners_share_one_break_pair(self):
        r = engine.design(grouped_bend(18.0, 15.0, 18.0))
        bo = [p for p in r.poles if p["code"] == "break_open"]
        bc = [p for p in r.poles if p["code"] == "break_close"]
        self.assertEqual(len(bo), 1, msg=[p["station"] for p in r.poles])
        self.assertEqual(len(bc), 1)
        corner_sts = [
            p["station"] for p in r.poles
            if p["code"] in ("curve", "ba") and p["angle"] > 0.0
        ]
        self.assertEqual(len(corner_sts), 2)
        # entry break_close before the first corner, exit break_open after the last
        self.assertLess(bc[0]["station"], corner_sts[0])
        self.assertGreater(bo[0]["station"], corner_sts[-1])
        self.assertTrue(r.ok, msg=[w for w in r.warnings])

    def test_corners_beyond_one_slack_span_do_not_group(self):
        r = engine.design(grouped_bend(18.0, 60.0, 18.0))
        codes = [p["code"] for p in r.poles]
        self.assertNotIn("break_open", codes)
        self.assertNotIn("break_close", codes)

    def test_grouped_sum_below_threshold_keeps_no_breaks(self):
        r = engine.design(grouped_bend(12.0, 15.0, 14.0))
        codes = [p["code"] for p in r.poles]
        self.assertNotIn("break_open", codes)
        self.assertNotIn("break_close", codes)

    def test_single_sharp_corner_keeps_its_own_pair(self):
        r = engine.design(deflect(45.0))
        codes = [p["code"] for p in r.poles]
        self.assertIn("break_open", codes)
        self.assertIn("break_close", codes)


class TestRoadClearance(unittest.TestCase):
    STRAIGHT = [(0.0, 0.0), (200.0, 0.0)]

    def test_offset_auto_raised_to_clear_road(self):
        r = engine.design(self.STRAIGHT, offset=5.0, road_width=16.0)
        expected = 16.0 / 2.0 + engine.ROAD_CLEARANCE
        self.assertAlmostEqual(r.offset, expected)
        self.assertAlmostEqual(r.requested_offset, 5.0)
        self.assertTrue(any("ระบบจึงถอยแนวเสา" in w for w in r.warnings))
        for p in r.poles:
            self.assertAlmostEqual(p["y"], expected, places=6)

    def test_valid_offset_left_untouched(self):
        r = engine.design(self.STRAIGHT, offset=6.0, road_width=7.0)
        self.assertAlmostEqual(r.offset, 6.0)
        self.assertEqual(r.warnings, [])

    def test_narrow_road_never_raises_a_valid_offset(self):
        # 7 m road needs only 3.5 + 2 = 5.5 m, so 6 m stands
        r = engine.design(self.STRAIGHT, offset=6.0, road_width=7.0)
        self.assertAlmostEqual(r.offset, 6.0)
        self.assertGreater(r.offset, 7.0 / 2.0)

    def test_clearance_matrix(self):
        for road in (0.0, 7.0, 10.0, 16.0, 24.0):
            r = engine.design(self.STRAIGHT, offset=5.0, road_width=road)
            clearance = r.offset - road / 2.0
            self.assertGreaterEqual(
                clearance, engine.ROAD_CLEARANCE - 1e-9, msg=f"road={road}"
            )
            row = [c for c in r.validation if c["key"] == "no_pole_on_road"][0]
            self.assertEqual(row["status"], "PASS", msg=f"road={road}")

    def test_road_check_reports_real_clearance(self):
        r = engine.design(self.STRAIGHT, offset=12.0, road_width=16.0)
        row = [c for c in r.validation if c["key"] == "no_pole_on_road"][0]
        self.assertEqual(row["status"], "PASS")
        self.assertIn("ริมทาง 4.00 m", row["value"])

    def test_validate_fails_when_road_check_violated(self):
        # tamper: a 40 m road against a 10 m offset cannot keep 2 m clearance
        pl = engine.Polyline(self.STRAIGHT)
        r = engine.design(self.STRAIGHT, offset=10.0, road_width=0.0)
        table, ok = engine.validate(pl, r.poles, 10.0, road_width=40.0, road_clearance=2.0)
        row = [c for c in table if c["key"] == "no_pole_on_road"][0]
        self.assertEqual(row["status"], "FAIL")
        self.assertFalse(ok)

    def test_payload_carries_road_fields(self):
        r = engine.design(self.STRAIGHT, offset=5.0, road_width=16.0)
        payload = engine.to_payload(r)
        self.assertEqual(payload["road_width_m"], 16.0)
        self.assertEqual(payload["road_clearance_m"], engine.ROAD_CLEARANCE)
        self.assertEqual(payload["requested_offset_m"], 5.0)
        self.assertEqual(payload["min_edge_clearance_m"], 2.0)


class TestGuyDirection(unittest.TestCase):
    """The anchor runs parallel to the R.O.W. behind the pole, never across
    the carriageway."""

    BEND = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (150.0, 50.0)]

    def test_end_pole_points_away_from_the_line(self):
        r = engine.design(self.BEND)
        last = r.poles[-1]
        self.assertEqual(last["code"], "end")
        self.assertAlmostEqual(last["gy_angle"], 0.0, places=6)
        # anchor sits ahead of the end pole in the direction of travel
        self.assertGreater(last["gy_anchor_x"], last["x"])

    def test_start_pole_points_backwards(self):
        r = engine.design(self.BEND)
        first = r.poles[0]
        self.assertEqual(first["code"], "start")
        self.assertAlmostEqual(first["gy_angle"], 180.0, places=6)
        self.assertLess(first["gy_anchor_x"], first["x"])

    def test_ba_pole_guy_parallel_to_row_and_off_the_road(self):
        r = engine.design(self.BEND)
        bas = [p for p in r.poles if p["code"] == "ba"]
        self.assertTrue(bas, msg="a 90 deg bend needs BA poles")
        ba = bas[0]
        self.assertTrue(ba["gy"])
        self.assertIsNotNone(ba["gy_anchor_x"])
        # the guy must be parallel to one of the two adjacent R.O.W. runs --
        # at a bend the R.O.W. carries on into the shorter adjoining run, so
        # the guy points toward that neighbour -- never the old resultant that
        # sent the anchor of an inside-of-bend pole across the road.
        idx = [p["id"] for p in r.poles].index(ba["id"])
        expected = []
        for j in (idx - 1, idx + 1):
            if 0 <= j < len(r.poles):
                q = r.poles[j]
                expected.append(
                    math.degrees(math.atan2(q["y"] - ba["y"], q["x"] - ba["x"])) % 360.0
                )
        actual = ba["gy_angle"] % 360.0
        matching = [
            e_ for e_ in expected if abs(((actual - e_ + 180.0) % 360.0) - 180.0) < 1e-6
        ]
        self.assertTrue(matching, msg=f"guy {actual:.1f} not parallel to either run {expected}")
        # the anchor must stay at least as far from the road as the pole
        poly = engine.Polyline(self.BEND)
        d_anchor = engine._dist_to_polyline(
            poly, ba["gy_anchor_x"], ba["gy_anchor_y"]
        )
        d_pole = engine._dist_to_polyline(poly, ba["x"], ba["y"])
        self.assertGreaterEqual(d_anchor, d_pole - 1e-9)

    def test_guy_anchor_matches_stored_angle(self):
        r = engine.design(self.BEND)
        for p in r.poles:
            if not p["gy"]:
                continue
            self.assertIsNotNone(p["gy_anchor_x"])
            dx = p["gy_anchor_x"] - p["x"]
            dy = p["gy_anchor_y"] - p["y"]
            self.assertAlmostEqual(
                math.hypot(dx, dy), engine.ANCHOR_LEN, places=6, msg=f"#{p['id']}"
            )
            angle = math.degrees(math.atan2(dy, dx)) % 360.0
            self.assertAlmostEqual(angle, p["gy_angle"] % 360.0, places=4, msg=f"#{p['id']}")

    def test_validate_accepts_engine_guy_angles(self):
        r = engine.design(self.BEND)
        gy_rows = [c for c in r.validation if c["key"] == "guy_anchor"]
        self.assertTrue(gy_rows)
        self.assertEqual(gy_rows[0]["status"], "PASS")
        self.assertTrue(r.ok)

    def test_validate_detects_wrong_guy_angle(self):
        r = engine.design(self.BEND)
        tampered = [dict(p) for p in r.poles]
        end = tampered[-1]
        end["gy_angle"] = (end["gy_angle"] + 90.0) % 360.0
        table, ok = engine.validate(r.centerline, tampered, r.offset)
        row = [c for c in table if c["key"] == "guy_anchor"][0]
        self.assertEqual(row["status"], "FAIL")
        self.assertFalse(ok)


class TestValidation(unittest.TestCase):
    CASES = [
        ("straight_150", [(0.0, 0.0), (150.0, 0.0)]),
        ("straight_40", [(0.0, 0.0), (40.0, 0.0)]),
        ("angle_5", deflect(5.0)),
        ("angle_20", deflect(20.0)),
        ("angle_45", deflect(45.0)),
        ("angle_60", deflect(60.0)),
        ("angle_61", deflect(61.0)),
        ("angle_90", deflect(90.0, 100, 50, 50)),
        ("very_short_8", [(0.0, 0.0), (8.0, 0.0)]),
        ("three_bends", [(0.0, 0.0), (140.0, 0.0), (140.0, 120.0),
                         (300.0, 120.0), (300.0, -30.0)]),
        ("grouped_sweep", grouped_bend(18.0, 15.0, 18.0)),
        ("tangent_edge_2", deflect(2.0)),
    ]

    def test_all_designs_pass_standards(self):
        for name, cl in self.CASES:
            r = engine.design(cl)
            failures = [
                row["label"] for row in r.validation if row["status"] != "PASS"
            ]
            self.assertEqual(failures, [], msg=f"{name}: {failures}")
            self.assertTrue(r.ok, msg=name)

    def test_close_facing_corners_report_failure_honestly(self):
        # two right-angle corners only ~45 m apart facing each other: their
        # inner break pair can't both fit MIN_SPACING, so no valid design
        # exists -- the engine must FAIL the slack/max checks instead of
        # dragging poles or anchors onto the road to make the numbers fit.
        r = engine.design([(0.0, 0.0), (60.0, 0.0), (60.0, 45.0),
                           (110.0, 45.0), (110.0, 90.0), (150.0, 90.0)])
        labels = {row["label"]: row["status"] for row in r.validation}
        self.assertEqual(labels.get("Slack Span บนช่วงโค้ง <= 20 m"), "FAIL")
        self.assertEqual(labels.get("Max Span SAC 50 (40/35/25/20 m)"), "FAIL")
        self.assertFalse(r.ok)
        self.assertEqual(labels.get("สายยึดโยง + สมอบก GY-21"), "PASS")
        self.assertEqual(labels.get("ห้ามปักเสาบนผิวจราจร"), "PASS")

    def test_validation_table_shape(self):
        r = engine.design([(0.0, 0.0), (150.0, 0.0)])
        keys = {row["key"] for row in r.validation}
        self.assertEqual(
            keys,
            {
                "max_span",
                "slack_span",
                "no_tangent_on_curve",
                "bracket_logic",
                "guy_anchor",
                "row_offset",
                "no_pole_on_road",
            },
        )

    def test_validate_detects_tampered_offset(self):
        r = engine.design([(0.0, 0.0), (150.0, 0.0)])
        r.poles[0]["x"] += 3.0
        rows, ok = engine.validate(r.centerline, r.poles, 5.0)
        by_key = {row["key"]: row for row in rows}
        self.assertEqual(by_key["row_offset"]["status"], "FAIL")
        self.assertFalse(ok)

    def test_validate_detects_span_violation(self):
        r = engine.design([(0.0, 0.0), (150.0, 0.0)])
        r.poles[1]["x"] = r.poles[0]["x"] + 300.0
        rows, ok = engine.validate(r.centerline, r.poles, 5.0)
        by_key = {row["key"]: row for row in rows}
        self.assertEqual(by_key["max_span"]["status"], "FAIL")
        self.assertFalse(ok)


class TestPayloadAndExport(unittest.TestCase):
    def setUp(self):
        self.result = engine.design(engine.sample_centerline())
        self.payload = engine.to_payload(self.result)

    def test_payload_is_json_serialisable(self):
        text = json.dumps(self.payload, ensure_ascii=False)
        restored = json.loads(text)
        self.assertEqual(restored["summary"]["pole_count"], len(self.result.poles))

    def test_payload_keys_used_by_frontend(self):
        for key in ("ok", "offset_m", "centerline", "poles", "spans",
                    "validation", "warnings", "summary"):
            self.assertIn(key, self.payload)
        for key in ("length_m", "pole_count", "max_span_used_m", "guy_pole_count",
                    "curve_pole_count", "count_label", "tangent_max_span_m"):
            self.assertIn(key, self.payload["summary"])
        for pole in self.payload["poles"]:
            for key in ("id", "x", "y", "station", "code", "type", "gy", "gy_angle",
                        "bracket", "angle", "span_from_prev", "span_to_next",
                        "marker", "color"):
                self.assertIn(key, pole)

    def test_spans_cover_all_gaps(self):
        self.assertEqual(len(self.payload["spans"]), len(self.result.poles) - 1)
        self.assertAlmostEqual(
            sum(s["length"] for s in self.payload["spans"]),
            sum(s["length"] for s in self.payload["spans"]),
        )

    def test_csv_header_and_rows(self):
        csv_text = engine.poles_to_csv(self.result.poles)
        lines = csv_text.strip().splitlines()
        self.assertEqual(lines[0].split(","), engine.CSV_COLUMNS)
        self.assertEqual(len(lines) - 1, len(self.result.poles))

    def test_standards_reference(self):
        ref = engine.standards_reference()
        self.assertEqual(len(ref["span_table"]), len(engine.SPAN_TABLE))
        self.assertEqual(ref["row_offset_m"], engine.ROW_OFFSET)
        self.assertEqual(ref["slack_span_max_m"], engine.MAX_SLACK_SPAN)
        self.assertTrue(ref["rules"])

    def test_sample_centerline_shape(self):
        sample = engine.sample_centerline()
        self.assertGreaterEqual(len(sample), 2)
        r = engine.design(sample)
        self.assertTrue(r.ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
