"""Market data and cautious, monthly event-conditioned fuel price scenarios.

The model uses Brent crude, USD/INR and Indian city retail prices. It is a
scenario tool: future crude and FX changes are user assumptions, not known
future values. Chronological validation determines how much to trust the
learned response versus the persistence baseline.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


FRED_SERIES = {
    "brent_usd_per_barrel": "DCOILBRENTEU",
    "usd_inr": "DEXINUS",
}
FEATURES = ["brent_pct", "brent_pct_3m", "fx_pct", "fx_pct_3m", "price_pct", "freeze"]
MARKET_SOURCES = (
    "https://fred.stlouisfed.org/series/DCOILBRENTEU",
    "https://fred.stlouisfed.org/series/DEXINUS",
)


def _fred_series(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    request = Request(url, headers={"User-Agent": "FuelPriceScenarioExplorer/1.0"})
    with urlopen(request, timeout=15) as response:
        frame = pd.read_csv(BytesIO(response.read()))
    if len(frame.columns) < 2:
        raise ValueError(f"Unexpected response while downloading FRED series {series_id}.")
    frame = frame.iloc[:, :2]
    frame.columns = ["date", series_id]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame[series_id] = pd.to_numeric(frame[series_id], errors="coerce")
    frame = frame.dropna().set_index("date").sort_index()
    return frame[series_id]


def load_market_data(path: str | Path) -> tuple[pd.DataFrame, str | None]:
    """Refresh daily public FRED inputs and return monthly averages.

    If refresh is unavailable, a previously downloaded local snapshot is used.
    """
    path = Path(path)
    error = None
    try:
        brent = _fred_series(FRED_SERIES["brent_usd_per_barrel"])
        fx = _fred_series(FRED_SERIES["usd_inr"])
        daily = pd.concat(
            [brent.rename("brent_usd_per_barrel"), fx.rename("usd_inr")], axis=1
        ).sort_index().ffill(limit=5).dropna()
        monthly = daily.resample("MS").mean().dropna()
        monthly.index.name = "date"
        monthly = monthly.reset_index()
        monthly.to_csv(path, index=False)
        return monthly, None
    except Exception as exc:  # network/provider errors should not break the whole dashboard
        error = f"Could not refresh crude oil and exchange-rate history: {exc}"

    if path.exists():
        try:
            cached = pd.read_csv(path, parse_dates=["date"])
            required = {"date", *FRED_SERIES.keys()}
            if required.issubset(cached.columns) and not cached.empty:
                return cached.dropna(subset=list(required)), error
        except (OSError, ValueError, pd.errors.ParserError):
            pass
    raise RuntimeError(error or "No market history is available.")


def _monthly_prices(history: pd.DataFrame, price_column: str) -> pd.DataFrame:
    data = history.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data[price_column] = pd.to_numeric(data[price_column], errors="coerce")
    data = data.dropna(subset=["date", "city", price_column]).sort_values(["city", "date"])
    data["month"] = data["date"].dt.to_period("M").dt.to_timestamp()
    rows = []
    for (city, month), group in data.groupby(["city", "month"], sort=True):
        row = {"city": city, "month": month, "price": float(group.iloc[-1][price_column])}
        if "is_long_freeze" in group:
            row["freeze"] = pd.to_numeric(group["is_long_freeze"], errors="coerce").iloc[-1]
        else:
            row["freeze"] = np.nan
        rows.append(row)
    monthly = pd.DataFrame(rows).sort_values(["city", "month"])
    monthly["price_pct"] = monthly.groupby("city")["price"].pct_change() * 100
    monthly["freeze"] = monthly["freeze"].fillna((monthly["price_pct"].abs() < 1e-9).astype(float))
    return monthly


def _training_panel(history: pd.DataFrame, market: pd.DataFrame, price_column: str) -> tuple[pd.DataFrame, list[str]]:
    prices = _monthly_prices(history, price_column)
    macro = market.copy()
    macro["date"] = pd.to_datetime(macro["date"], errors="coerce")
    macro = macro.dropna(subset=["date", "brent_usd_per_barrel", "usd_inr"]).sort_values("date")
    macro["month"] = macro["date"].dt.to_period("M").dt.to_timestamp()
    macro = macro.drop_duplicates("month", keep="last").sort_values("month")
    macro["brent_pct"] = macro["brent_usd_per_barrel"].pct_change() * 100
    macro["brent_pct_3m"] = macro["brent_usd_per_barrel"].pct_change(3) * 100
    macro["fx_pct"] = macro["usd_inr"].pct_change() * 100
    macro["fx_pct_3m"] = macro["usd_inr"].pct_change(3) * 100
    panel = prices.merge(macro[["month", *FEATURES[:4]]], on="month", how="inner")
    panel = panel.sort_values(["city", "month"])
    panel["target"] = panel.groupby("city")["price_pct"].shift(-1)
    panel["target_month"] = panel.groupby("city")["month"].shift(-1)
    # The target is the next month's price movement. Do not train on incomplete
    # rows or on a month whose next retail observation is missing.
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(subset=[*FEATURES, "target", "target_month"])
    cities = sorted(panel["city"].astype(str).unique())
    return panel, cities


def _design(panel: pd.DataFrame, cities: list[str]) -> pd.DataFrame:
    result = panel[FEATURES].astype(float).copy()
    for city in cities[1:]:
        result[f"city_{city}"] = (panel["city"].astype(str) == city).astype(float)
    return result


def _pass_through_estimates(panel: pd.DataFrame, macro: pd.DataFrame) -> dict[str, float]:
    """Estimate historical retail response to an INR-denominated crude shock.

    The slope is a descriptive no-intercept fit of next-month retail price
    changes on monthly Brent-in-INR cost changes. It is not a causal guarantee.
    """
    targets = panel.groupby("month", as_index=False)["target"].mean()
    market = macro[["month", "brent_usd_per_barrel", "usd_inr"]].copy().sort_values("month")
    market["crude_cost_pct"] = (market["brent_usd_per_barrel"] * market["usd_inr"]).pct_change() * 100
    joined = targets.merge(market[["month", "crude_cost_pct"]], on="month").dropna()

    def slope(sample: pd.DataFrame) -> float:
        if len(sample) < 12:
            return 0.0
        shock = sample["crude_cost_pct"].to_numpy(dtype=float)
        response = sample["target"].to_numpy(dtype=float)
        denominator = float(np.dot(shock, shock))
        return float(np.clip(np.dot(shock, response) / denominator if denominator else 0.0, 0.0, 0.25))

    historical = slope(joined[joined["month"] < pd.Timestamp("2023-01-01")])
    full = slope(joined)
    recent = slope(joined[joined["month"] >= pd.Timestamp("2023-01-01")])
    return {
        "historical_oil_shock_periods": historical,
        "full_history": full,
        "recent_muted_period": recent,
    }


def fit_response_model(history: pd.DataFrame, market: pd.DataFrame, price_column: str) -> dict:
    """Fit a regularized response model and measure it on the latest 18 months."""
    panel, cities = _training_panel(history, market, price_column)
    if len(panel) < 48:
        raise ValueError("At least 48 aligned city-month observations are needed for this scenario model.")
    last_target_month = panel["target_month"].max()
    validation_cutoff = last_target_month - pd.DateOffset(months=18)
    train = panel[panel["target_month"] < validation_cutoff]
    valid = panel[panel["target_month"] >= validation_cutoff]
    if len(train) < 24 or valid.empty:
        raise ValueError("Not enough history for a chronological validation split.")

    model = make_pipeline(StandardScaler(), Ridge(alpha=8.0))
    x_train, x_valid = _design(train, cities), _design(valid, cities)
    model.fit(x_train, train["target"].to_numpy())
    valid_prediction = np.clip(model.predict(x_valid), -12.0, 12.0)
    valid_actual = valid["target"].to_numpy()
    model_mae = float(np.mean(np.abs(valid_actual - valid_prediction)))
    baseline_mae = float(np.mean(np.abs(valid_actual)))
    # Shrink the event response toward the no-change baseline when chronological
    # validation says that the model has been less accurate than persistence.
    trust = float(np.clip(1.0 - model_mae / max(baseline_mae, 1e-6), 0.0, 0.75))
    residuals = valid_actual - valid_prediction
    latest = panel.sort_values("month").groupby("city", as_index=False).tail(1).set_index("city")

    # Fit on the full historical sample only after reserving the validation period.
    final_model = make_pipeline(StandardScaler(), Ridge(alpha=8.0))
    final_model.fit(_design(panel, cities), panel["target"].to_numpy())
    macro = market.copy()
    macro["date"] = pd.to_datetime(macro["date"], errors="coerce")
    macro = macro.dropna(subset=["date", "brent_usd_per_barrel", "usd_inr"]).sort_values("date")
    macro["month"] = macro["date"].dt.to_period("M").dt.to_timestamp()
    macro = macro.drop_duplicates("month", keep="last").sort_values("month")
    return {
        "model": final_model,
        "cities": cities,
        "panel": panel,
        "latest": latest,
        "macro": macro,
        "residuals": residuals,
        "trust": trust,
        "validation_mae_pct": model_mae,
        "baseline_mae_pct": baseline_mae,
        "validation_months": 18,
        "feature_columns": list(x_train.columns),
        "pass_through": _pass_through_estimates(panel, macro),
    }


def forecast_scenario(
    fitted: dict,
    city: str,
    current_price: float,
    horizon_months: int,
    crude_shock_pct: float,
    fx_shock_pct: float,
    shock_duration_months: int,
    response_regime: str = "historical_oil_shock_periods",
    *,
    n_sims: int = 2500,
    seed: int = 17,
) -> pd.DataFrame:
    """Compare flat baseline to a scenario with assumed crude/FX changes."""
    if city not in fitted["latest"].index:
        raise ValueError(f"No aligned history is available for {city}.")
    if horizon_months < 1 or shock_duration_months < 1:
        raise ValueError("Forecast horizon and shock duration must be at least one month.")
    if response_regime not in fitted["pass_through"]:
        raise ValueError("Unknown historical pass-through regime.")

    latest_row = fitted["latest"].loc[city]
    macro = fitted["macro"]
    last_macro = macro.iloc[-1]
    previous_price_pct = float(latest_row.get("price_pct", 0.0)) if pd.notna(latest_row.get("price_pct")) else 0.0
    freeze = float(latest_row.get("freeze", 0.0)) if pd.notna(latest_row.get("freeze")) else 0.0
    current_month = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).to_period("M").to_timestamp()
    forecast_anchor = max(pd.Timestamp(last_macro["month"]), current_month)
    months = pd.date_range(forecast_anchor + pd.offsets.MonthBegin(1), periods=horizon_months, freq="MS")
    crude_per_month = (1.0 + crude_shock_pct / 100.0) ** (1.0 / shock_duration_months) - 1.0
    fx_per_month = (1.0 + fx_shock_pct / 100.0) ** (1.0 / shock_duration_months) - 1.0
    pass_through = fitted["pass_through"][response_regime]
    rng = np.random.default_rng(seed)
    residuals = fitted["residuals"]
    if not len(residuals):
        residuals = np.array([0.0])
    paths = np.full((n_sims, horizon_months + 1), float(current_price))
    scenario_rows = []

    # For each future month, the current month's macro movement predicts the
    # following retail month, matching the one-month lag in the training data.
    for step, month in enumerate(months, start=1):
        crude_change = crude_per_month * 100 if step <= shock_duration_months else 0.0
        fx_change = fx_per_month * 100 if step <= shock_duration_months else 0.0
        feature = {
            # The learned baseline sees no additional shock. A separate historical
            # pass-through term below makes the chosen event assumption visible.
            "brent_pct": 0.0,
            "brent_pct_3m": 0.0,
            "fx_pct": 0.0,
            "fx_pct_3m": 0.0,
            "price_pct": previous_price_pct,
            "freeze": freeze,
        }
        input_frame = pd.DataFrame([feature])
        for other_city in fitted["cities"][1:]:
            input_frame[f"city_{other_city}"] = float(city == other_city)
        input_frame = input_frame.reindex(columns=fitted["feature_columns"], fill_value=0.0)
        baseline_response = float(np.clip(fitted["model"].predict(input_frame)[0], -12.0, 12.0))
        baseline_response *= fitted["trust"]
        crude_cost_change = ((1 + crude_change / 100) * (1 + fx_change / 100) - 1) * 100
        event_response = pass_through * crude_cost_change
        response = float(np.clip(baseline_response + event_response, -12.0, 12.0))
        month_residuals = rng.choice(residuals, size=n_sims, replace=True)
        centered_residuals = month_residuals - float(np.median(residuals))
        monthly_returns = np.clip(response + centered_residuals, -12.0, 12.0)
        paths[:, step] = paths[:, step - 1] * (1 + monthly_returns / 100.0)
        previous_price_pct = response
        scenario_rows.append({
            "date": month,
            "baseline": float(current_price),
            "median": float(np.median(paths[:, step])),
            "low": float(np.percentile(paths[:, step], 10)),
            "high": float(np.percentile(paths[:, step], 90)),
            "assumed_crude_change_pct": crude_change,
            "assumed_usd_inr_change_pct": fx_change,
        })
    return pd.DataFrame(scenario_rows)
