"""Multi-week price forecast: persistence baseline plus a historical-revision uncertainty band.

Indian pump prices are administered, not market-quoted day to day, so the saved
evaluation shows that nothing beats "tomorrow = today" on average error. This
module therefore keeps the median path flat and answers a different question:
"if revisions keep happening at the rate and size seen recently, how far could
the price drift over the next N days?"

Method (per fuel):
1. Take daily percentage changes over a look-back window, pooled across cities
   (a single city has only a handful of revisions, too few to estimate from).
2. p = share of city-days with a non-zero change; sizes = the non-zero changes.
3. Simulate many futures: each day a revision happens with probability p and
   its size is drawn from the observed sizes.
4. Report the median and a percentile band across simulations.

This describes historical behaviour. It is not a prediction of any government
or oil-company decision, and the band reflects the look-back window chosen.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class RevisionProfile:
    probability_per_day: float
    pct_changes: np.ndarray
    n_events: int
    n_city_days: int


def revision_profile(history: pd.DataFrame, price_column: str, lookback_days: int) -> RevisionProfile:
    """Estimate how often and by how much prices were revised, pooled over cities."""
    data = history.dropna(subset=["date", "city", price_column]).sort_values(["city", "date"])
    cutoff = data["date"].max() - pd.Timedelta(days=lookback_days)
    data = data.assign(pct=data.groupby("city")[price_column].pct_change())
    window = data[(data["date"] > cutoff) & data["pct"].notna()]
    events = window.loc[window["pct"].abs() > 1e-9, "pct"].to_numpy()
    n_days = len(window)
    probability = len(events) / n_days if n_days else 0.0
    return RevisionProfile(probability, events, len(events), n_days)


def simulate_city(
    start_price: float,
    horizon_days: int,
    profile: RevisionProfile,
    *,
    band: float = 0.8,
    n_sims: int = 5000,
    seed: int = 42,
) -> tuple[pd.DataFrame, float]:
    """Return (day, median, low, high) for days 1..horizon and P(at least one revision)."""
    days = np.arange(1, horizon_days + 1)
    if profile.n_events == 0:
        flat = np.full(horizon_days, start_price)
        return pd.DataFrame({"day": days, "median": flat, "low": flat, "high": flat}), 0.0

    rng = np.random.default_rng(seed)
    occurs = rng.random((n_sims, horizon_days)) < profile.probability_per_day
    sizes = rng.choice(profile.pct_changes, size=(n_sims, horizon_days))
    paths = start_price * np.cumprod(1.0 + occurs * sizes, axis=1)

    tail = (1.0 - band) / 2.0 * 100
    low, median, high = np.percentile(paths, [tail, 50, 100 - tail], axis=0)
    prob_any = float(occurs.any(axis=1).mean())
    frame = pd.DataFrame({"day": days, "median": median, "low": low, "high": high})
    return frame, prob_any


def build_forecast(
    history: pd.DataFrame,
    start_prices: dict[str, float],
    start_date: pd.Timestamp,
    cities: list[str],
    price_column: str,
    horizon_days: int,
    lookback_days: int,
    band: float = 0.8,
) -> tuple[pd.DataFrame, dict[str, float], RevisionProfile]:
    """Forecast every requested city. Returns (long frame, P(revision) by city, profile)."""
    profile = revision_profile(history, price_column, lookback_days)
    frames: list[pd.DataFrame] = []
    prob_any: dict[str, float] = {}
    for offset, city in enumerate(cities):
        if city not in start_prices:
            continue
        # Different seed per city so cities are not forced to move together.
        frame, probability = simulate_city(
            start_prices[city], horizon_days, profile, band=band, seed=42 + offset
        )
        frame["date"] = pd.Timestamp(start_date) + pd.to_timedelta(frame["day"], unit="D")
        frame["city"] = city
        frames.append(frame.drop(columns="day"))
        prob_any[city] = probability
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["median", "low", "high", "date", "city"]
    )
    return result, prob_any, profile