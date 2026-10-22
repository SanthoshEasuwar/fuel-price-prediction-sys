from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from services.auth_service import render_account_sidebar, require_user
from services.forecast_service import build_forecast
from services.fuel_price_service import EXPECTED_CITIES, get_latest_prices
from services.ui import apply_fuel_theme

st.set_page_config(page_title="Price Forecast", page_icon="🔮", layout="wide", initial_sidebar_state="expanded")
apply_fuel_theme()
require_user()
render_account_sidebar("price_forecast")

st.title("🔮 Price Forecast")
st.caption(
    "Current price carried forward, with a range showing how far prices could drift "
    "if revisions keep happening at their recent rate and size."
)

base_dir = Path(__file__).resolve().parent.parent
data_path = base_dir / "Data" / "fuel_prices_model_ready.csv"
cache_path = base_dir / "Data" / "cache" / "latest_fuel_prices.json"

if not data_path.exists():
    st.error("Historical price data is missing from Data/fuel_prices_model_ready.csv.")
    st.stop()


@st.cache_data
def load_history(path: str) -> pd.DataFrame:
    data = pd.read_csv(path)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    for column in ("petrol_price_inr_per_litre", "diesel_price_inr_per_litre"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.dropna(subset=["date", "city"]).sort_values(["city", "date"]).reset_index(drop=True)


history = load_history(str(data_path))

# ---------------- Controls ----------------
st.subheader("Forecast Settings")
control_cols = st.columns(3)
cities = control_cols[0].multiselect(
    "Cities", list(EXPECTED_CITIES), default=["Chennai", "Delhi"]
)
fuel = control_cols[1].radio("Fuel", ["Petrol", "Diesel"], horizontal=True)
horizon_label = control_cols[2].select_slider(
    "Forecast horizon",
    options=["1 week", "2 weeks", "4 weeks", "8 weeks", "12 weeks (~3 months)"],
    value="12 weeks (~3 months)",
)
horizon_days = {"1 week": 7, "2 weeks": 14, "4 weeks": 28, "8 weeks": 56, "12 weeks (~3 months)": 84}[horizon_label]
lookback_label = control_cols[0].selectbox(
    "Revision history used",
    ["Last 1 year", "Last 2 years", "Last 5 years"],
    index=1,
    help="Which past period defines how often and how much prices are revised.",
)
lookback_days = {"Last 1 year": 365, "Last 2 years": 730, "Last 5 years": 1825}[lookback_label]
band_label = control_cols[1].radio("Range shown", ["80%", "90%"], horizontal=True)
band = 0.8 if band_label == "80%" else 0.9
show_days = control_cols[2].slider("Past days shown on chart", 30, 365, 120, step=30)

if not cities:
    st.info("Select at least one city in Forecast Settings above.")
    st.stop()

price_column = "petrol_price_inr_per_litre" if fuel == "Petrol" else "diesel_price_inr_per_litre"

# ---------------- Starting prices ----------------
result = get_latest_prices(cache_path)
provider_by_city = {row["city"]: row for row in result["records"]}

start_prices: dict[str, float] = {}
start_dates: dict[str, pd.Timestamp] = {}
for city in cities:
    row = provider_by_city.get(city)
    city_history = history[history["city"] == city].dropna(subset=[price_column])
    if row:
        start_prices[city] = float(row[price_column])
        observed = row.get("observation_at") or result.get("retrieved_at")
        start_dates[city] = (
            pd.to_datetime(observed, utc=True).tz_convert("Asia/Kolkata").tz_localize(None).normalize()
        )
    elif not city_history.empty:
        start_prices[city] = float(city_history.iloc[-1][price_column])
        start_dates[city] = city_history.iloc[-1]["date"]

if not start_prices:
    st.error("No starting price is available for the selected cities.")
    st.stop()

if result["status"] == "live":
    st.success("Starting point: latest provider price")
elif result["status"] == "stale":
    st.warning("Provider data is stale; starting from the last validated provider price.")
else:
    st.warning("Provider unavailable; starting from the last historical CSV price.")

# ---------------- Forecast ----------------
forecast_start = max(start_dates.values())
forecast, prob_any, profile = build_forecast(
    history, start_prices, forecast_start, list(start_prices), price_column,
    horizon_days, lookback_days, band,
)

if profile.n_events == 0:
    st.info(
        "No price revisions occurred in the selected history window, so the forecast is a flat line. "
        "Try a longer window."
    )

# ---------------- Chart ----------------
PALETTE = ["#1ba6a6", "#f1b844", "#e86f68", "#8f9bff"]


def rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


fig = go.Figure()
past_cutoff = forecast_start - pd.Timedelta(days=show_days)
for index, city in enumerate(start_prices):
    color = PALETTE[index % len(PALETTE)]
    past = history[(history["city"] == city) & (history["date"] >= past_cutoff)].dropna(subset=[price_column])
    # Join the dashed forecast onto the last known point so the line is continuous.
    anchor = pd.DataFrame({"date": [start_dates[city]], "median": [start_prices[city]],
                           "low": [start_prices[city]], "high": [start_prices[city]]})
    future = pd.concat([anchor, forecast[forecast["city"] == city][["date", "median", "low", "high"]]],
                       ignore_index=True)

    fig.add_trace(go.Scatter(x=past["date"], y=past[price_column], name=f"{city} (recorded)",
                             mode="lines", line=dict(color=color, width=2), legendgroup=city))
    fig.add_trace(go.Scatter(x=future["date"], y=future["high"], mode="lines", line=dict(width=0),
                             showlegend=False, hoverinfo="skip", legendgroup=city))
    fig.add_trace(go.Scatter(x=future["date"], y=future["low"], mode="lines", line=dict(width=0),
                             fill="tonexty", fillcolor=rgba(color, 0.22), showlegend=False,
                             hoverinfo="skip", legendgroup=city))
    fig.add_trace(go.Scatter(x=future["date"], y=future["median"], name=f"{city} (forecast)",
                             mode="lines", line=dict(color=color, width=2, dash="dash"), legendgroup=city,
                             hovertemplate="%{x|%d %b %Y}<br>₹%{y:.2f}/L<extra>" + city + " forecast</extra>"))

fig.add_vline(x=forecast_start, line_dash="dot", line_color="#9aabba")
fig.update_layout(
    title=f"{fuel} price: recorded and {horizon_label} forecast ({band_label} range)",
    xaxis_title="Date", yaxis_title="Price (₹ per litre)", hovermode="x unified",
)
st.plotly_chart(fig, width="stretch")

# ---------------- Summary ----------------
st.subheader("Forecast Summary")
end = forecast[forecast["date"] == forecast["date"].max()].set_index("city")
summary = pd.DataFrame({
    "City": list(start_prices),
    "Current (₹/L)": [round(start_prices[c], 2) for c in start_prices],
    "Median at end (₹/L)": [round(end.loc[c, "median"], 2) for c in start_prices],
    f"Low, {band_label} range (₹/L)": [round(end.loc[c, "low"], 2) for c in start_prices],
    f"High, {band_label} range (₹/L)": [round(end.loc[c, "high"], 2) for c in start_prices],
    "Chance of any revision": [f"{prob_any[c] * 100:.0f}%" for c in start_prices],
})
st.dataframe(summary, width="stretch", hide_index=True)

st.download_button(
    "Download forecast as CSV",
    data=forecast.to_csv(index=False).encode("utf-8"),
    file_name=f"fuel_price_forecast_{fuel.lower()}_{horizon_days}d.csv",
    mime="text/csv",
)

# ---------------- Honesty notes ----------------
with st.expander("How to read this forecast"):
    st.markdown(
        f"""
        - **Dashed line:** the persistence baseline, meaning the current price carried forward.
          The saved evaluation shows this beats the tested Random Forest and two-stage models on average error.
        - **Shaded range:** from {profile.n_events} revisions across {profile.n_city_days:,} city-days in the
          history window you chose (all four cities pooled, sizes taken as percentages). Each simulated day has a
          {profile.probability_per_day * 100:.2f}% chance of a revision of a size drawn from that history.
        - **The range is lopsided when recent revisions went one way.** In the last two years the observed revisions
          were mostly increases, so the range leans upward. That is a property of the history, not a forecast that
          prices will rise. Choose the 5-year window for a more balanced range.
        - **What this cannot do:** predict whether the government or oil companies will revise prices, or when.
          Treat the range as "how far prices have tended to move", not as a prediction.
        """
    )
