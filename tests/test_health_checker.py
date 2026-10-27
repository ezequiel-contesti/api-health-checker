"""Tests for api-health-checker. Spin up the bundled demo server locally and
exercise the check, classification, retry and report logic. No network access
beyond 127.0.0.1."""

import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import health_checker
from demo_server import Handler


def make_endpoint(base, path, **overrides):
    cfg = {"name": path.strip("/"), "url": base + path}
    cfg.update(overrides)
    return cfg


class HealthCheckerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_up_when_status_matches(self):
        res = health_checker.check_endpoint(make_endpoint(self.base, "/ok"), {})
        self.assertEqual(res["status"], "UP")
        self.assertEqual(res["got"], 200)
        self.assertEqual(res["attempts"], 1)
        self.assertIsNotNone(res["latency_ms"])

    def test_degraded_when_slow(self):
        res = health_checker.check_endpoint(
            make_endpoint(self.base, "/slow", warn_latency_ms=50), {}
        )
        self.assertEqual(res["status"], "DEGRADED")
        self.assertEqual(res["got"], 200)
        self.assertGreater(res["latency_ms"], 50)

    def test_down_on_unexpected_status(self):
        res = health_checker.check_endpoint(
            make_endpoint(self.base, "/error", retries=2), {}
        )
        self.assertEqual(res["status"], "DOWN")
        self.assertEqual(res["got"], 500)
        self.assertEqual(res["attempts"], 3)  # 1 initial + 2 retries

    def test_down_on_404(self):
        res = health_checker.check_endpoint(make_endpoint(self.base, "/nope"), {})
        self.assertEqual(res["status"], "DOWN")
        self.assertEqual(res["got"], 404)

    def test_down_on_connection_refused(self):
        dead = make_endpoint("http://127.0.0.1:1", "/ok", retries=1, timeout=2)
        res = health_checker.check_endpoint(dead, {})
        self.assertEqual(res["status"], "DOWN")
        self.assertIsNone(res["got"])
        self.assertTrue(res["error"])
        self.assertEqual(res["attempts"], 2)

    def test_custom_expected_status(self):
        res = health_checker.check_endpoint(
            make_endpoint(self.base, "/error", expected_status=[500]), {}
        )
        self.assertEqual(res["status"], "UP")

    def test_defaults_are_merged(self):
        # /slow always takes ~1.2s, so a merged 1ms threshold is deterministic
        # here — unlike /ok, whose sub-millisecond localhost latency is
        # sometimes rounded below 1ms and made this test flaky.
        res = health_checker.check_endpoint(
            make_endpoint(self.base, "/slow"),
            {"warn_latency_ms": 1, "timeout": 5, "retries": 0, "expected_status": [200]},
        )
        self.assertEqual(res["warn_latency_ms"], 1)  # default 1000ms overridden
        self.assertEqual(res["status"], "DEGRADED")

    def test_report_summary_and_findings(self):
        results = [
            health_checker.check_endpoint(make_endpoint(self.base, "/ok"), {}),
            health_checker.check_endpoint(
                make_endpoint(self.base, "/slow", warn_latency_ms=50), {}
            ),
            health_checker.check_endpoint(make_endpoint(self.base, "/error"), {}),
        ]
        report = health_checker.build_report(results)
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["summary"], {"UP": 1, "DEGRADED": 1, "DOWN": 1})
        self.assertEqual(len(report["findings"]), 2)
        parsed = json.loads(health_checker.format_json(report))
        self.assertEqual(parsed["summary"]["DOWN"], 1)

    def test_exit_code(self):
        up = {"status": "UP"}
        self.assertEqual(health_checker.overall_exit_code([up, {"status": "DEGRADED"}]), 0)
        self.assertEqual(health_checker.overall_exit_code([up, {"status": "DOWN"}]), 1)

    def test_text_format_lists_findings(self):
        results = [
            health_checker.check_endpoint(make_endpoint(self.base, "/error"), {}),
        ]
        text = health_checker.format_text(health_checker.build_report(results))
        self.assertIn("DOWN", text)
        self.assertIn("Summary:", text)
        self.assertIn("Findings:", text)


if __name__ == "__main__":
    unittest.main()
