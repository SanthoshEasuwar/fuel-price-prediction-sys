import json
from datetime import datetime, timedelta, timezone
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from services.fuel_price_service import _extract_records, get_latest_prices


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def valid_payload():
    cities = ("Chennai", "New Delhi", "Mumbai", "Kolkata")
    return {
        "status": "ok",
        "updated_at": (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": [
            {"location": city, "petrol": {"price": 100.0}, "diesel": {"price": 90.0}}
            for city in cities
        ],
    }


class FuelPriceServiceTests(unittest.TestCase):
    def setUp(self):
        import os
        patcher = patch.dict(os.environ, {"FUEL_PRICE_API_KEY": "test-key"})
        patcher.start()
        self.cache_dir = Path("Data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / ".fuel_price_service_test.json"
        self.cache_path.unlink(missing_ok=True)

    def tearDown(self):
        self.cache_path.unlink(missing_ok=True)
        try:
            self.cache_dir.rmdir()
        except OSError:
            pass

    def test_city_normalization_and_numeric_validation(self):
        records = _extract_records(valid_payload(), _utc_now())
        self.assertEqual(
            {row["city"] for row in records},
            {"Chennai", "Delhi", "Mumbai", "Kolkata"},
        )
        self.assertTrue(all(isinstance(row["petrol_price_inr_per_litre"], float) for row in records))

    def test_duplicate_city_observation_is_rejected(self):
        payload = valid_payload()
        payload["data"].append(payload["data"][0])
        with self.assertRaisesRegex(ValueError, "duplicate observations"):
            _extract_records(payload, _utc_now())

    def test_refresh_saves_valid_data_and_failure_uses_stale_cache(self):
        with patch("services.fuel_price_service.urlopen", return_value=FakeResponse(valid_payload())):
            first = get_latest_prices(self.cache_path, force_refresh=True)
        self.assertEqual(first["status"], "live")
        self.assertEqual(len(first["records"]), 4)

        with patch("services.fuel_price_service.urlopen", side_effect=URLError("offline")):
            fallback = get_latest_prices(self.cache_path, force_refresh=True)
        self.assertEqual(fallback["status"], "stale")
        self.assertEqual(len(fallback["records"]), 4)
        self.assertIn("offline", fallback["error"])


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


if __name__ == "__main__":
    unittest.main()