from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from services.auth_service import render_account_sidebar, require_user
from services.fuel_price_service import EXPECTED_CITIES, get_latest_prices
from services.forecast_tracking_service import read_forecasts, record_daily_forecasts
from services.ui import apply_fuel_theme


st.set_page_config(page_title="Tomorrow's Prediction", layout="wide", initial_sidebar_state="expanded")
apply_fuel_theme()
require_user()
render_account_sidebar("tomorrow_prediction")
st.title("Tomorrow's Price Estimate")
st.caption("Transparent persistence baseline using the latest available observation.")

base_dir = Path(__file__).resolve().parent.parent
data_path = base_dir / "Data" / "fuel_prices_model_ready.csv"
cache_path = base_dir / "Data" / "cache" / "latest_fuel_prices.json"
tracking_path = base_dir / "Data" / "daily_forecasts.csv"

if not data_path.exists():
    st.error("Historical price data is missing from Data/fuel_prices_model_ready.csv.")
    st.stop()

history = pd.read_csv(data_path)
required = {"date", "city", "petrol_price_inr_per_litre", "diesel_price_inr_per_litre"}
missing = required.difference(history.columns)
if missing:
    st.error(f"Historical data is missing required columns: {', '.join(sorted(missing))}")
    st.stop()
history["date"] = pd.to_datetime(history["date"], errors="coerce")
for column in ("petrol_price_inr_per_litre", "diesel_price_inr_per_litre"):
    history[column] = pd.to_numeric(history[column], errors="coerce")
history = history.dropna(subset=["date", "city"])

refresh = st.button("Refresh latest provider prices")
result = get_latest_prices(cache_path, force_refresh=refresh)
if refresh and result["status"] == "live" and result["records"]:
    observation_timestamp = (
        result["records"][0].get("observation_at")
        or result.get("provider_updated_at")
        or result.get("retrieved_at")
    )
    observation_day = pd.to_datetime(observation_timestamp, utc=True).tz_convert("Asia/Kolkata").date().isoformat()
    record_daily_forecasts(tracking_path, result["records"], observation_day, result["retrieved_at"])
provider_by_city = {row["city"]: row for row in result["records"]}
city = st.selectbox("City", EXPECTED_CITIES)
fuel = st.radio("Fuel", ["Petrol", "Diesel"], horizontal=True)
price_key = "petrol_price_inr_per_litre" if fuel == "Petrol" else "diesel_price_inr_per_litre"

if result["status"] == "live":
    st.success("Latest provider data available")
elif result["status"] == "stale":
    st.warning("Provider data is stale or refresh failed; using the last validated observation.")
    st.caption(result["error"])
else:
    st.warning("Provider unavailable; using historical fallback data.")
    if result["error"]:
        st.caption(result["error"])

row = provider_by_city.get(city)
if row:
    price = float(row[price_key])
    observation = row.get("observation_at")
    date_label = observation or result.get("provider_updated_at") or result.get("retrieved_at")
    input_source = "latest provider observation"
else:
    city_history = history[history["city"].astype(str).str.casefold() == city.casefold()]
    city_history = city_history.dropna(subset=[price_key]).sort_values("date")
    if city_history.empty:
        st.error(f"No {fuel.lower()} price is available for {city}.")
        st.stop()
    latest = city_history.iloc[-1]
    price = float(latest[price_key])
    date_label = latest["date"].isoformat()
    input_source = "historical CSV fallback"

st.metric(f"{fuel} persistence estimate for {city}", f"INR {price:.2f}/litre")
st.write(f"Input: **{input_source}** · observation/update date: **{date_label}**")
st.info(
    "The baseline predicts that tomorrow's price equals the latest available price. "
    "It does not predict whether a revision will occur or its size. It is not a live-trained ML model."
)

st.divider()
st.header("Daily accuracy check")
st.caption(
    "This historical backtest asks: if the estimate for each date had simply carried forward "
    "the previous day's recorded price, how close would it have been?"
)

historical = history[history["city"].astype(str).str.casefold() == city.casefold()].copy()
historical = historical.dropna(subset=[price_key]).sort_values("date")
historical["predicted"] = historical[price_key].shift(1)
historical["previous_date"] = historical["date"].shift(1)
historical["gap_days"] = (historical["date"] - historical["previous_date"]).dt.days
backtest = historical[historical["gap_days"] == 1].copy()
backtest["actual"] = backtest[price_key]
backtest["error"] = backtest["actual"] - backtest["predicted"]
backtest["absolute_error"] = backtest["error"].abs()
backtest["absolute_pct_error"] = backtest["absolute_error"] / backtest["predicted"].abs().replace(0, pd.NA) * 100

if backtest.empty:
    st.info("There are no consecutive daily records for this city to evaluate.")
else:
    mae = float(backtest["absolute_error"].mean())
    rmse = float((backtest["error"].pow(2).mean()) ** 0.5)
    exact_rate = float((backtest["absolute_error"] <= 0.01).mean() * 100)
    accuracy_cols = st.columns(4)
    accuracy_cols[0].metric("Daily comparisons", f"{len(backtest):,}")
    accuracy_cols[1].metric("Mean absolute error", f"₹{mae:.2f}/L")
    accuracy_cols[2].metric("RMSE", f"₹{rmse:.2f}/L")
    accuracy_cols[3].metric("Matched within ₹0.01", f"{exact_rate:.1f}%")

    history_fig = go.Figure()
    history_fig.add_trace(go.Scatter(x=backtest["date"], y=backtest["actual"], name="Recorded actual", mode="lines"))
    history_fig.add_trace(go.Scatter(x=backtest["date"], y=backtest["predicted"], name="Previous-day estimate", mode="lines"))
    history_fig.update_layout(title=f"Historical daily estimate vs actual · {city} {fuel}", xaxis_title="Date", yaxis_title="INR per litre", hovermode="x unified")
    st.plotly_chart(history_fig, width="stretch")

    error_fig = go.Figure(go.Scatter(
        x=backtest["date"], y=backtest["error"], mode="lines",
        name="Actual − estimate", line=dict(color="#e86f68"),
    ))
    error_fig.add_hline(y=0, line_dash="dash")
    error_fig.update_layout(title="Daily forecast error (actual minus estimate)", xaxis_title="Date", yaxis_title="INR per litre", hovermode="x unified")
    st.plotly_chart(error_fig, width="stretch")
    st.caption("This is a retrospective backtest reconstructed from consecutive historical records. It is not a record of forecasts actually issued on those past dates.")

st.subheader("API-verified daily forecasts")
st.caption("The scheduled collector saves a persistence estimate for the next observation date. When a fresh API observation for that date arrives, the tracker stores actual price and error.")
tracked = read_forecasts(tracking_path)
tracked = tracked[(tracked["city"].astype(str).str.casefold() == city.casefold()) & (tracked["fuel"].astype(str).str.casefold() == fuel.casefold())].copy()
tracked["forecast_date"] = pd.to_datetime(tracked["forecast_date"], errors="coerce")
for column in ("predicted_price", "actual_price", "absolute_error", "pct_error"):
    tracked[column] = pd.to_numeric(tracked[column], errors="coerce")

# If today's live response is available before the scheduled collector runs,
# show its comparison in this view immediately. The collector persists it.
local_today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
if result["status"] == "live" and row and not tracked.empty:
    timestamp = row.get("observation_at") or result.get("provider_updated_at")
    if timestamp:
        observation_day = pd.to_datetime(timestamp, utc=True).tz_convert("Asia/Kolkata").date()
        pending = tracked["forecast_date"].dt.date.eq(observation_day) & tracked["actual_price"].isna()
        tracked.loc[pending, "actual_price"] = float(row[price_key])
        tracked.loc[pending, "absolute_error"] = (tracked.loc[pending, "actual_price"] - tracked.loc[pending, "predicted_price"]).abs()
        tracked.loc[pending, "pct_error"] = tracked.loc[pending, "absolute_error"] / tracked.loc[pending, "predicted_price"].abs().replace(0, pd.NA) * 100

if tracked.empty:
    st.info("No daily forecasts have been recorded yet. They will appear after the scheduled collector successfully runs with a fresh API response.")
else:
    evaluated = tracked.dropna(subset=["forecast_date", "predicted_price"]).sort_values("forecast_date")
    scored = evaluated.dropna(subset=["actual_price"])
    if not scored.empty:
        tracked_cols = st.columns(3)
        tracked_cols[0].metric("API-verified days", f"{len(scored):,}")
        tracked_cols[1].metric("Tracked MAE", f"₹{scored['absolute_error'].mean():.2f}/L")
        tracked_cols[2].metric("Latest tracked error", f"₹{scored.iloc[-1]['absolute_error']:.2f}/L")
        tracked_fig = go.Figure()
        tracked_fig.add_trace(go.Scatter(x=scored["forecast_date"], y=scored["actual_price"], name="API actual", mode="lines+markers"))
        tracked_fig.add_trace(go.Scatter(x=evaluated["forecast_date"], y=evaluated["predicted_price"], name="Daily estimate", mode="lines+markers"))
        tracked_fig.update_layout(title=f"API-verified estimates · {city} {fuel}", xaxis_title="Target date", yaxis_title="INR per litre", hovermode="x unified")
        st.plotly_chart(tracked_fig, width="stretch")
        error_tracked_fig = go.Figure(go.Bar(x=scored["forecast_date"], y=scored["absolute_error"], name="Absolute error"))
        error_tracked_fig.update_layout(title="Absolute error by target date", xaxis_title="Target date", yaxis_title="INR per litre")
        st.plotly_chart(error_tracked_fig, width="stretch")
    else:
        st.info("Forecasts are saved, but no matching actual API observations have been recorded yet.")

    display = evaluated.sort_values("forecast_date", ascending=False).head(30).copy()
    display["forecast_date"] = display["forecast_date"].dt.strftime("%Y-%m-%d")
    display = display.rename(columns={
        "forecast_date": "Target date", "generated_at": "Estimate created",
        "predicted_price": "Estimate (₹/L)", "actual_price": "API actual (₹/L)",
        "absolute_error": "Absolute error (₹/L)", "pct_error": "Error (%)",
    })
    st.dataframe(display[["Target date", "Estimate created", "Estimate (₹/L)", "API actual (₹/L)", "Absolute error (₹/L)", "Error (%)"]], width="stretch", hide_index=True)

with st.expander("Why this baseline?"):
    st.write(
        "The saved chronological evaluation reports show lower overall MAE for the "
        "persistence baseline than for the tested Random Forest for both fuels. "
        "New models should be compared on the same chronological holdout before promotion."
    )
