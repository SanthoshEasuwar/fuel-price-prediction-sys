"""Daily collector: fetch latest prices from the provider and append them to history.

Usage (from the project root):
    python -m scripts.collector

Reuses the validation in services/fuel_price_service.py. Exits non-zero when the
provider is unreachable or its data is stale, so a scheduled run shows up red
instead of silently saving bad or old data.
"""

from __future__ import annotations

import csv
import sys
import tempfile
from datetime import timezone, timedelta
from pathlib import Path

from services.fuel_price_service import get_latest_prices
from services.forecast_tracking_service import record_daily_forecasts

IST = timezone(timedelta(hours=5, minutes=30))
LIVE_CSV = Path("Data") / "live_prices.csv"
FORECAST_CSV = Path("Data") / "daily_forecasts.csv"
FIELDS = [
    "date",
    "city",
    "petrol_price_inr_per_litre",
    "diesel_price_inr_per_litre",
    "retrieved_at",
    "provider_updated_at",
]


def _read_rows(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {(row["date"], row["city"]): row for row in csv.DictReader(handle)}


def _write_rows(path: Path, rows: dict[tuple[str, str], dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for key in sorted(rows):
            writer.writerow(rows[key])


def collect(csv_path: Path = LIVE_CSV) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        result = get_latest_prices(Path(tmp) / "cache.json", force_refresh=True)

    if result["status"] == "unavailable":
        print(f"FAILED: provider unavailable. {result['error']}")
        return 1
    if result["status"] == "stale" or result.get("from_cache"):
        print(f"SKIPPED: data not fresh. {result['error']}")
        return 2

    retrieved = result["retrieved_at"]
    # Calendar date in India, since prices change at 6 a.m. IST.
    from datetime import datetime
    day = datetime.fromisoformat(retrieved).astimezone(IST).date().isoformat()

    rows = _read_rows(csv_path)
    for record in result["records"]:
        # Same (date, city) overwrites, so a re-run never creates duplicates.
        rows[(day, record["city"])] = {
            "date": day,
            "city": record["city"],
            "petrol_price_inr_per_litre": f"{record['petrol_price_inr_per_litre']:.2f}",
            "diesel_price_inr_per_litre": f"{record['diesel_price_inr_per_litre']:.2f}",
            "retrieved_at": retrieved,
            "provider_updated_at": result.get("provider_updated_at") or "",
        }
    _write_rows(csv_path, rows)
    # Score forecasts against the provider's observation date, not the local
    # retrieval date. This avoids treating an old-but-recent response as today's actual.
    source_timestamp = (
        result["records"][0].get("observation_at")
        or result.get("provider_updated_at")
        or retrieved
    )
    observed_day = datetime.fromisoformat(source_timestamp.replace("Z", "+00:00")).astimezone(IST).date().isoformat()
    print(f"OK: saved {len(result['records'])} cities for {day} to {csv_path}")
    try:
        record_daily_forecasts(FORECAST_CSV, result["records"], observed_day, retrieved)
        print(f"OK: reconciled available forecasts and saved estimates through {FORECAST_CSV}")
    except Exception as exc:  # forecast tracking must never block saving prices
        print(f"WARNING: forecast tracking failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(collect())