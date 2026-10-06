# -*- coding: utf-8 -*-
"""HTTP level tests for the Flask application (app.py)."""

from __future__ import annotations

import json
import unittest

import app as web


class WebTestCase(unittest.TestCase):
    def setUp(self):
        web.app.config.update(TESTING=True)
        self.client = web.app.test_client()

    def post_json(self, url, payload):
        return self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )

    def sample_payload(self, **overrides):
        payload = {
            "points": web.engine.sample_centerline(),
            "offset": 5.0,
            "use_break_poles": True,
        }
        payload.update(overrides)
        return payload


class TestHealthAndStatic(WebTestCase):
    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["engine"])

    def test_index_renders(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("22/33", body)
        self.assertIn("APP_DEFAULTS", body)
        self.assertNotIn("{{", body)

    def test_static_assets(self):
        for path in ("/static/css/style.css", "/static/js/app.js"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, msg=path)
            self.assertGreater(len(r.get_data()), 500, msg=path)


class TestStandardsAndSample(WebTestCase):
    def test_standards(self):
        r = self.client.get("/api/standards")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(len(data["span_table"]), 5)
        self.assertEqual(data["row_offset_m"], 5.0)
        self.assertEqual(data["tangent_max_span_m"], 40.0)

    def test_sample(self):
        r = self.client.get("/api/sample")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertGreaterEqual(len(data["points"]), 2)


class TestDesignEndpoint(WebTestCase):
    def test_design_ok(self):
        r = self.post_json("/api/design", self.sample_payload())
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["ok"])
        self.assertGreaterEqual(data["summary"]["pole_count"], 2)
        self.assertEqual(len(data["validation"]), 7)
        self.assertTrue(all(row["status"] == "PASS" for row in data["validation"]))

    def test_design_angle_case(self):
        r = self.post_json(
            "/api/design",
            self.sample_payload(points=[[0, 0], [200, 0], [254.8, 47.0], [400, 47.0]]),
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(any(p["code"] in ("curve", "ba") for p in data["poles"]))

    def test_design_offset_option(self):
        # road_width=0 disables the road-clearance floor so the raw offset
        # parameter is what the assertion measures
        r = self.post_json(
            "/api/design", self.sample_payload(offset=7.0, road_width=0.0)
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertAlmostEqual(data["offset_m"], 7.0)
        self.assertAlmostEqual(data["requested_offset_m"], 7.0)

    def test_design_road_width_raises_offset(self):
        r = self.post_json("/api/design", self.sample_payload(offset=5.0))
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        # default road (16 m) + 2 m clearance -> 10 m minimum offset
        self.assertAlmostEqual(data["offset_m"], 10.0)
        self.assertAlmostEqual(data["requested_offset_m"], 5.0)
        self.assertEqual(data["road_width_m"], 16.0)
        self.assertAlmostEqual(data["min_edge_clearance_m"], 2.0)
        self.assertTrue(any("ระบบจึงถอยแนวเสา" in w for w in data["warnings"]))

    def test_design_road_width_explicit(self):
        r = self.post_json(
            "/api/design",
            self.sample_payload(offset=5.0, road_width=7.0),
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertAlmostEqual(data["offset_m"], 5.5)

    def test_rejects_bad_road_width(self):
        r = self.post_json("/api/design", self.sample_payload(road_width=-2))
        self.assertEqual(r.status_code, 400)
        r = self.post_json("/api/design", self.sample_payload(road_width="wide"))
        self.assertEqual(r.status_code, 400)

    def test_payload_carries_guy_anchor(self):
        r = self.post_json("/api/design", self.sample_payload())
        data = r.get_json()
        guyed = [p for p in data["poles"] if p["gy"]]
        self.assertTrue(guyed)
        for p in guyed:
            self.assertIsNotNone(p["gy_anchor_x"])
            self.assertIsNotNone(p["gy_anchor_y"])

    def test_break_poles_toggle_changes_result(self):
        with_bp = self.post_json(
            "/api/design", self.sample_payload(use_break_poles=True)
        ).get_json()
        without_bp = self.post_json(
            "/api/design", self.sample_payload(use_break_poles=False)
        ).get_json()
        codes_with = {p["code"] for p in with_bp["poles"]}
        codes_without = {p["code"] for p in without_bp["poles"]}
        self.assertTrue({"break_open", "break_close"} & codes_with)
        self.assertFalse({"break_open", "break_close"} & codes_without)

    def test_rejects_single_point(self):
        r = self.post_json("/api/design", {"points": [[0, 0]]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.get_json())

    def test_rejects_bad_offset(self):
        r = self.post_json("/api/design", self.sample_payload(offset=-1))
        self.assertEqual(r.status_code, 400)

    def test_rejects_non_numeric_points(self):
        r = self.post_json("/api/design", {"points": [["a", "b"], [1, 2]]})
        self.assertEqual(r.status_code, 400)

    def test_rejects_missing_points_key(self):
        r = self.post_json("/api/design", {"offset": 5.0})
        self.assertEqual(r.status_code, 400)

    def test_rejects_non_json_body(self):
        r = self.client.post("/api/design", data="not json", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_rejects_empty_body(self):
        r = self.client.post("/api/design", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_rejects_points_wrong_shape(self):
        r = self.post_json("/api/design", {"points": [0, 0, 10, 10]})
        self.assertEqual(r.status_code, 400)


class TestCsvEndpoint(WebTestCase):
    def test_csv_export(self):
        r = self.post_json("/api/export/csv", self.sample_payload())
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])
        body = r.get_data(as_text=True)
        self.assertTrue(body.strip())
        self.assertIn("id,x,y,station,code", body.replace("﻿", ""))

    def test_csv_export_validates_input(self):
        r = self.post_json("/api/export/csv", {"points": [[0, 0]]})
        self.assertEqual(r.status_code, 400)


class TestUnknownRoute(WebTestCase):
    def test_404_json(self):
        r = self.client.get("/api/does-not-exist")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
