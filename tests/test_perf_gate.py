import unittest
from perf_gate import validate


class PerformanceGateTests(unittest.TestCase):
    def test_passes_when_metrics_are_below_limits(self):
        report = {"schema": 1, "dataset_rows": 3000, "database_open_ms": 1.0,
                  "measurements": [{"name": "point_lookup", "p95": 2.0}]}
        self.assertEqual(validate(report, {"database_open_ms": 3.0, "point_lookup": 4.0}), [])

    def test_fails_when_latency_exceeds_budget(self):
        report = {"schema": 1, "dataset_rows": 3000, "database_open_ms": 30.0,
                  "measurements": []}
        self.assertTrue(validate(report, {"database_open_ms": 20.0}))

    def test_fails_if_metric_is_missing_or_fixture_too_small(self):
        with self.assertRaises(ValueError):
            validate({"schema": 1, "dataset_rows": 20, "measurements": []}, {})
        report = {"schema": 1, "dataset_rows": 3000, "database_open_ms": 1.0, "measurements": []}
        self.assertTrue(validate(report, {"text_search": 200}))


if __name__ == "__main__":
    unittest.main()
