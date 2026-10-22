"""Persistence forecast log used to compare daily estimates with API prices."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pandas as pd


TRACKING_FIELDS = [
    "forecast_date",
    "generated_at",
    "city",
    "fuel",
    "predicted_price",
    "actual_price",
    "actual_observed_at",
    "absolute_error",
    "pct_error",
]


def read_forecasts(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=TRACKING_FIELDS)
    try:
        frame = pd.read_csv(
            path,
            dtype={"forecast_date": str, "generated_at": str, "city": str, "fuel": str, "actual_observed_at": str},
        )
    except (OSError, pd.errors.ParserError, UnicodeDecodeError):
        return pd.DataFrame(columns=TRACKING_FIELDS)
    for column in TRACKING_FIELDS:
        if column not in frame:
            frame[column] = pd.NA
    return frame[TRACKING_FIELDS]


def _write_forecasts(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temp_path = Path(handle.name)
        frame[TRACKING_FIELDS].to_csv(handle, index=False, quoting=csv.QUOTE_MINIMAL)
    temp_path.replace(path)


def _upsert(frame: pd.DataFrame, record: dict) -> pd.DataFrame:
    match = (
        frame["forecast_date"].astype(str).eq(str(record["forecast_date"]))
        & frame["city"].astype(str).eq(str(record["city"]))
        & frame["fuel"].astype(str).eq(str(record["fuel"]))
    )
    frame = frame.loc[~match].copy()
    return pd.concat([frame, pd.DataFrame([record], columns=TRACKING_FIELDS)], ignore_index=True)


def record_daily_forecasts(
    path: str | Path,
    records: list[dict],
    forecast_date: str,
    generated_at: str,
) -> None:
    """Reconcile today's pending forecasts, then save tomorrow's persistence estimates.

    Each input row must contain a city's current petrol and diesel API values.
    Repeating the collector for the same day updates keyed rows instead of
    creating duplicates.
    """
    path = Path(path)
    frame = read_forecasts(path)
    target_date = pd.Timestamp(forecast_date).date().isoformat()

    for row in records:
        city = str(row["city"])
        observed_at = row.get("observation_at") or row.get("retrieved_at") or generated_at
        for fuel, price_column in (
            ("Petrol", "petrol_price_inr_per_litre"),
            ("Diesel", "diesel_price_inr_per_litre"),
        ):
            actual = float(row[price_column])
            matching = (
                frame["forecast_date"].astype(str).eq(target_date)
                & frame["city"].astype(str).eq(city)
                & frame["fuel"].astype(str).eq(fuel)
                & frame["actual_price"].isna()
            )
            for index in frame.index[matching]:
                predicted = float(frame.at[index, "predicted_price"])
                frame.at[index, "actual_price"] = actual
                frame.at[index, "actual_observed_at"] = observed_at
                frame.at[index, "absolute_error"] = abs(actual - predicted)
                frame.at[index, "pct_error"] = (
                    abs(actual - predicted) / abs(predicted) * 100 if predicted else pd.NA
                )

            next_date = (pd.Timestamp(target_date) + pd.Timedelta(days=1)).date().isoformat()
            frame = _upsert(frame, {
                "forecast_date": next_date,
                "generated_at": generated_at,
                "city": city,
                "fuel": fuel,
                "predicted_price": actual,
                "actual_price": pd.NA,
                "actual_observed_at": pd.NA,
                "absolute_error": pd.NA,
                "pct_error": pd.NA,
            })

    frame = frame.sort_values(["forecast_date", "city", "fuel"], kind="stable")
    _write_forecasts(path, frame)