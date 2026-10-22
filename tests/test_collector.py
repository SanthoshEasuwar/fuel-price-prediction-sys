import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import collector


def fake_result(petrol=100.0):
    return {
        "status": "live", "error": None, "from_cache": False,
        "retrieved_at": "2026-10-20T02:00:00+00:00",
        "provider_updated_at": "2026-10-20T01:00:00Z",
        "records": [
            {"city": "Chennai", "petrol_price_inr_per_litre": petrol, "diesel_price_inr_per_litre": 90.0},
            {"city": "Delhi", "petrol_price_inr_per_litre": petrol - 5, "diesel_price_inr_per_litre": 88.0},
        ],
    }


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(collector, "FORECAST_CSV", Path(self._tmp.name) / "forecasts.csv")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rerun_same_day_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live.csv"
            with patch.object(collector, "get_latest_prices", return_value=fake_result()):
                self.assertEqual(collector.collect(path), 0)
            with patch.object(collector, "get_latest_prices", return_value=fake_result(101.0)):
                self.assertEqual(collector.collect(path), 0)
            with path.open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["petrol_price_inr_per_litre"], "101.00")

    def test_unavailable_and_stale_write_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live.csv"
            bad = {"status": "unavailable", "error": "down", "records": []}
            with patch.object(collector, "get_latest_prices", return_value=bad):
                self.assertEqual(collector.collect(path), 1)
            stale = {**fake_result(), "status": "stale", "error": "old"}
            with patch.object(collector, "get_latest_prices", return_value=stale):
                self.assertEqual(collector.collect(path), 2)
            self.assertFalse(path.exists())

    def test_tracking_failure_does_not_block_saving_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live.csv"
            with patch.object(collector, "get_latest_prices", return_value=fake_result()), \
                 patch.object(collector, "record_daily_forecasts", side_effect=RuntimeError("boom")):
                self.assertEqual(collector.collect(path), 0)
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()