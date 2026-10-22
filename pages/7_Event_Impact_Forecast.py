from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from services.auth_service import render_account_sidebar, require_user
from services.event_forecast_service import forecast_scenario, fit_response_model, load_market_data
from services.fuel_price_service import EXPECTED_CITIES, get_latest_prices
from services.ui import apply_fuel_theme


st.set_page_config(page_title="Event Impact Forecast", page_icon="🌍", layout="wide")
apply_fuel_theme()
require_user()
render_account_sidebar("event_impact_forecast")

st.title("Event Impact Forecast")
st.caption(
    "Explore how assumed oil-market and currency shocks could affect city fuel prices. "
    "The model uses historical relationships and shows its validation performance."
)

base_dir = Path(__file__).resolve().parent.parent
history_path = base_dir / "Data" / "fuel_prices_model_ready.csv"
market_path = base_dir / "Data" / "market_inputs.csv"
cache_path = base_dir / "Data" / "cache" / "latest_fuel_prices.json"

if not history_path.exists():
    st.error("Historical fuel-price data is missing.")
    st.stop()

history = pd.read_csv(history_path)
required = {"date", "city", "petrol_price_inr_per_litre", "diesel_price_inr_per_litre"}
missing = required.difference(history.columns)
if missing:
    st.error(f"Historical data is missing required columns: {', '.join(sorted(missing))}")
    st.stop()
history["date"] = pd.to_datetime(history["date"], errors="coerce")
for col in ("petrol_price_inr_per_litre", "diesel_price_inr_per_litre"):
    history[col] = pd.to_numeric(history[col], errors="coerce")
history = history.dropna(subset=["date", "city"])

refresh_col, note_col = st.columns([1, 3], vertical_alignment="center")
@st.cache_data(ttl=86400, show_spinner=False)
def get_market_data_cached(path: str) -> tuple[pd.DataFrame, str | None]:
    return load_market_data(path)

refresh_market = refresh_col.button("Refresh crude and USD/INR data")
if refresh_market:
    get_market_data_cached.clear()

try:
    with st.spinner("Loading public crude oil and exchange-rate history…"):
        market, market_warning = get_market_data_cached(str(market_path))
except RuntimeError as exc:
    st.error(str(exc))
    st.info("Connect to the internet and refresh. The event model needs Brent crude and USD/INR history.")
    st.stop()

if market_warning:
    st.warning(f"Using the last downloaded market-data snapshot. {market_warning}")
else:
    note_col.caption(f"Market inputs loaded through {pd.to_datetime(market['date']).max():%B %Y}.")

st.subheader("Set the event assumptions")
st.info(
    "An event name alone cannot tell the model how prices will move. Set the expected crude-oil "
    "and USD/INR changes; these measurable assumptions condition the estimate."
)
assumption_cols = st.columns(4)
scenario_name = assumption_cols[0].text_input("Scenario name", "Oil supply disruption")
city = assumption_cols[1].selectbox("City", EXPECTED_CITIES)
fuel = assumption_cols[2].selectbox("Fuel", ["Petrol", "Diesel"])
horizon_months = assumption_cols[3].select_slider(
    "Forecast horizon", options=[1, 2, 3, 4, 5, 6], value=3,
    format_func=lambda n: f"{n} month" if n == 1 else f"{n} months",
)

shock_cols = st.columns(3)
crude_shock = shock_cols[0].slider("Assumed Brent change over event period (%)", -50, 100, 20, step=5)
fx_shock = shock_cols[1].slider(
    "Assumed USD/INR change (%)", -20, 20, 2, step=1,
    help="A positive value means the rupee weakens against the US dollar.",
)
shock_duration = shock_cols[2].slider("Event duration (months)", 1, 6, 3)

regime_labels = {
    "Historical oil-shock periods (2017–2022)": "historical_oil_shock_periods",
    "Full-history average": "full_history",
    "Recent pricing period (2023 onward)": "recent_muted_period",
}
response_regime_label = st.selectbox(
    "Historical price response to use",
    list(regime_labels),
    help="Choose how much Indian pump prices moved with crude-cost changes in the historical sample. This is an average association, not a guarantee.",
)
response_regime = regime_labels[response_regime_label]

price_column = "petrol_price_inr_per_litre" if fuel == "Petrol" else "diesel_price_inr_per_litre"
result = get_latest_prices(cache_path)
provider_rows = {row["city"]: row for row in result["records"]}
provider_row = provider_rows.get(city)
if provider_row:
    current_price = float(provider_row[price_column])
    price_source = "latest API Mitra observation"
    if result["status"] != "live":
        st.warning("The available provider observation is stale; the scenario starts from the last validated price.")
else:
    city_history = history[history["city"].astype(str).str.casefold() == city.casefold()]
    city_history = city_history.dropna(subset=[price_column]).sort_values("date")
    if city_history.empty:
        st.error(f"No starting {fuel.lower()} price is available for {city}.")
        st.stop()
    current_price = float(city_history.iloc[-1][price_column])
    price_source = f"historical CSV ({city_history.iloc[-1]['date']:%d %b %Y})"

try:
    fitted = fit_response_model(history, market, price_column)
    forecast = forecast_scenario(
        fitted, city, current_price, int(horizon_months), float(crude_shock),
        float(fx_shock), int(shock_duration), response_regime,
    )
except (ValueError, KeyError) as exc:
    st.error(f"Could not build the event-conditioned estimate: {exc}")
    st.stop()

end_row = forecast.iloc[-1]
baseline_end = float(end_row["baseline"])
scenario_end = float(end_row["median"])
low_end = float(end_row["low"])
high_end = float(end_row["high"])

st.subheader(f"{scenario_name or 'Event scenario'} · {city} {fuel.lower()}")
st.caption(f"Starting price: ₹{current_price:.2f}/L from {price_source}.")
metric_cols = st.columns(4)
metric_cols[0].metric("Starting price", f"₹{current_price:.2f}/L")
metric_cols[1].metric("No-shock baseline", f"₹{baseline_end:.2f}/L")
metric_cols[2].metric("Scenario median", f"₹{scenario_end:.2f}/L", delta=f"₹{scenario_end - baseline_end:+.2f}/L vs baseline")
metric_cols[3].metric("Scenario 80% range", f"₹{low_end:.2f}–₹{high_end:.2f}/L")

fig = go.Figure()
fig.add_trace(go.Scatter(x=forecast["date"], y=forecast["high"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
fig.add_trace(go.Scatter(x=forecast["date"], y=forecast["low"], mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(241,184,68,.20)", name="80% scenario range", hoverinfo="skip"))
fig.add_trace(go.Scatter(x=forecast["date"], y=forecast["median"], mode="lines+markers", name="Event scenario median", line=dict(color="#f1b844", width=3)))
fig.add_trace(go.Scatter(x=forecast["date"], y=forecast["baseline"], mode="lines+markers", name="No-shock persistence baseline", line=dict(color="#1ba6a6", width=2, dash="dash")))
fig.update_layout(title="Monthly price scenario", xaxis_title="Month", yaxis_title="INR per litre", hovermode="x unified")
st.plotly_chart(fig, width="stretch")

st.subheader("How much should you trust this estimate?")
trust_cols = st.columns(3)
trust_cols[0].metric("Chronological model MAE", f"{fitted['validation_mae_pct']:.3f}% / month")
trust_cols[1].metric("Persistence MAE", f"{fitted['baseline_mae_pct']:.3f}% / month")
trust_cols[2].metric("Model response retained", f"{fitted['trust'] * 100:.0f}%")
if fitted["trust"] == 0:
    st.warning(
        "Recent held-out data did not support the learned baseline response. The scenario still applies "
        "the selected historical crude-cost sensitivity below; actual pump prices can be held flat by policy."
    )
pass_through = fitted["pass_through"][response_regime]
combined_shock = ((1 + crude_shock / 100) * (1 + fx_shock / 100) - 1) * 100
st.info(
    f"Selected response: {pass_through * 100:.1f}% of the assumed INR crude-cost move is passed through "
    f"in the historical data. Your inputs imply a {combined_shock:+.1f}% crude-cost move and an estimated "
    f"{scenario_end - current_price:+.2f}/L change by month {horizon_months}."
)
st.caption(
    "Validation uses the latest 18 months held out in time. The explicit event effect uses the selected "
    "historical pass-through estimate, while the shaded range resamples errors from that holdout period."
)
with st.expander("Assumptions and limits"):
    st.markdown(
        """
        - This is a monthly scenario estimate, not a precise prediction of a future war, disaster, or policy decision.
        - The event is represented by the assumed Brent crude and USD/INR changes; the event label itself is not a model input.
        - Retail price revisions can be delayed or moderated by taxes and government decisions. Those future decisions are unknown.
        - A domestic refinery or transport disruption may not be represented by global crude and currency changes alone.
        - Market history: [EIA Brent crude price via FRED](https://fred.stlouisfed.org/series/DCOILBRENTEU) and [Federal Reserve USD/INR rate via FRED](https://fred.stlouisfed.org/series/DEXINUS).
        """
    )

st.download_button(
    "Download scenario results as CSV",
    data=forecast.to_csv(index=False).encode("utf-8"),
    file_name=f"event_scenario_{city.lower()}_{fuel.lower()}.csv",
    mime="text/csv",
)
