import tempfile
import unittest
from pathlib import Path

from services.forecast_tracking_service import read_forecasts, record_daily_forecasts


def rows(petrol, diesel=99.55):
    return [{
        "city": "Chennai",
        "petrol_price_inr_per_litre": petrol,
        "diesel_price_inr_per_litre": diesel,
        "observation_at": "2026-10-21T05:00:00Z",
    }]


class ForecastTrackingTests(unittest.TestCase):
    def test_saves_tomorrow_then_scores_it_next_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "forecasts.csv"
            record_daily_forecasts(path, rows(107.77), "2026-10-21", "2026-10-21T12:00:00Z")
            # Re-running the same day must not create duplicates.
            record_daily_forecasts(path, rows(107.77), "2026-10-21", "2026-10-21T13:00:00Z")
            saved = read_forecasts(path)
            self.assertEqual(len(saved), 2)                      # petrol + diesel for 22 Oct
            self.assertTrue((saved["forecast_date"] == "2026-10-22").all())
            self.assertTrue(saved["actual_price"].isna().all())

            # Next day's real price scores yesterday's persistence guess (this used to crash).
            record_daily_forecasts(path, rows(110.00), "2026-10-22", "2026-10-22T12:00:00Z")
            saved = read_forecasts(path)
            self.assertEqual(len(saved), 4)
            petrol = saved[(saved["forecast_date"] == "2026-10-22") & (saved["fuel"] == "Petrol")].iloc[0]
            self.assertAlmostEqual(float(petrol["absolute_error"]), 2.23, places=2)
            tomorrow = saved[(saved["forecast_date"] == "2026-10-23") & (saved["fuel"] == "Petrol")].iloc[0]
            self.assertAlmostEqual(float(tomorrow["predicted_price"]), 110.00)


if __name__ == "__main__":
    unittest.main()