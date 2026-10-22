
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from services.auth_service import current_user, render_account_sidebar, render_login_signup
from services.fuel_price_service import EXPECTED_CITIES, get_latest_prices
from services.ui import apply_fuel_theme

# --------------------------------------------------
# 1. PAGE CONFIGURATION
# --------------------------------------------------
st.set_page_config(
    page_title="Fuel Price Prediction System",
    page_icon="⛽",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_fuel_theme()
if current_user() is None:
    render_login_signup()
    st.stop()
render_account_sidebar("overview")

# --------------------------------------------------
# 2. PROJECT PATHS
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "Data" / "fuel_prices_model_ready.csv"

# --------------------------------------------------
# 3. LOAD DATA
# --------------------------------------------------
@st.cache_data
def load_data(file_path):
    data = pd.read_csv(file_path)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=["date", "city"])

    price_columns = [
        "petrol_price_inr_per_litre",
        "diesel_price_inr_per_litre",
    ]

    for column in price_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    return data.sort_values(["date", "city"]).reset_index(drop=True)


# --------------------------------------------------
# 4. LOAD AND VALIDATE DATA
# --------------------------------------------------
st.title("⛽ Fuel Price Prediction System")
st.caption(
    "Historical fuel prices and a transparent next-day baseline estimate"
)
st.page_link(
    "pages/7_Event_Impact_Forecast.py",
    label="Explore an event impact scenario",
    icon="🌍",
    help="Compare a crude oil and USD/INR shock scenario with the persistence baseline.",
)

if not DATA_PATH.exists():
    st.error(f"Dataset not found: {DATA_PATH}")
    st.info(
        "Place fuel_prices_model_ready.csv inside the Data folder."
    )
    st.stop()

df = load_data(str(DATA_PATH))

required_columns = [
    "date",
    "city",
    "petrol_price_inr_per_litre",
    "diesel_price_inr_per_litre",
]

missing_columns = [
    column for column in required_columns
    if column not in df.columns
]

if missing_columns:
    st.error(f"Missing required columns: {missing_columns}")
    st.stop()

if df.empty:
    st.error("The dataset contains no usable records.")
    st.stop()

force_refresh = st.button("Refresh latest published prices")
live_result = get_latest_prices(
    BASE_DIR / "Data" / "cache" / "latest_fuel_prices.json",
    force_refresh=force_refresh,
)
live_by_city = {row["city"]: row for row in live_result["records"]}

st.subheader("Latest Published Prices")
if live_result["status"] == "live":
    st.success("Latest provider data available")
elif live_result["status"] == "stale":
    st.warning("Provider data is stale or refresh failed; showing the last validated provider data")
    st.caption(live_result["error"])
else:
    st.warning("Provider unavailable; showing dated historical data")
    if live_result["error"]:
        st.caption(live_result["error"])

if live_result.get("retrieved_at"):
    retrieved = pd.to_datetime(live_result["retrieved_at"], utc=True).tz_convert("Asia/Kolkata")
    st.caption(
        f"Source: {live_result.get('provider')}. Retrieved "
        f"{retrieved.strftime('%d %b %Y, %I:%M %p IST')}. "
        f"Provider update: {live_result.get('provider_updated_at') or 'not supplied'}."
    )

live_columns = st.columns(4)
for index, city in enumerate(EXPECTED_CITIES):
    with live_columns[index]:
        row = live_by_city.get(city)
        history = df[df["city"] == city].sort_values("date")
        st.markdown(f"**{city}**")
        if row:
            st.metric("Petrol (INR/L)", f"{row['petrol_price_inr_per_litre']:.2f}")
            st.metric("Diesel (INR/L)", f"{row['diesel_price_inr_per_litre']:.2f}")
            st.caption("API Mitra · provider data")
        elif not history.empty:
            latest = history.iloc[-1]
            st.metric("Petrol (INR/L)", f"{latest['petrol_price_inr_per_litre']:.2f}")
            st.metric("Diesel (INR/L)", f"{latest['diesel_price_inr_per_litre']:.2f}")
            st.caption(f"Historical fallback · {latest['date'].strftime('%d %b %Y')}")
        else:
            st.info("No data available")

# --------------------------------------------------
# 5. SIDEBAR FILTERS
# --------------------------------------------------
st.subheader("Dashboard Filters")

cities = sorted(df["city"].dropna().unique().tolist())

filter_cols = st.columns(2)
selected_city = filter_cols[0].selectbox(
    "Select city",
    cities,
    index=cities.index("Chennai") if "Chennai" in cities else 0,
)

fuel_type = filter_cols[1].radio(
    "Select fuel",
    ["Petrol", "Diesel"],
)

price_column = (
    "petrol_price_inr_per_litre"
    if fuel_type == "Petrol"
    else "diesel_price_inr_per_litre"
)

# --------------------------------------------------
# 6. LATEST RECORDED PRICES
# --------------------------------------------------
st.subheader("Historical Dataset Snapshot")

latest_date = df["date"].max()
latest_data = df[df["date"] == latest_date]

st.caption(
    f"Latest date available across the dataset: "
    f"{latest_date.strftime('%d %B %Y')}. "
    "This section shows the historical CSV snapshot; use the provider section above for latest published prices."
)

city_columns = st.columns(4)

for index, city in enumerate(
    ["Chennai", "Delhi", "Mumbai", "Kolkata"]
):
    with city_columns[index]:
        city_data = latest_data[latest_data["city"] == city]

        if city_data.empty:
            st.metric(city, "Unavailable")
        else:
            row = city_data.iloc[-1]

            petrol = row["petrol_price_inr_per_litre"]
            diesel = row["diesel_price_inr_per_litre"]

            st.markdown(f"**{city}**")
            st.metric(
                "Petrol",
                f"₹{petrol:.2f}/L" if pd.notna(petrol) else "N/A",
            )
            st.metric(
                "Diesel",
                f"₹{diesel:.2f}/L" if pd.notna(diesel) else "N/A",
            )

# --------------------------------------------------
# 7. SELECTED CITY PRICE
# --------------------------------------------------
st.divider()
st.subheader(f"{selected_city}: {fuel_type} Price")

city_df = df[df["city"] == selected_city].copy()
city_df = city_df.dropna(subset=[price_column])
city_df = city_df.sort_values("date")

if city_df.empty:
    st.warning("No price records are available for this selection.")
    st.stop()

latest_city_row = city_df.iloc[-1]
latest_price = float(latest_city_row[price_column])
city_latest_date = latest_city_row["date"]
live_city_row = live_by_city.get(selected_city)
if live_city_row:
    live_price_key = "petrol_price_inr_per_litre" if fuel_type == "Petrol" else "diesel_price_inr_per_litre"
    latest_price = float(live_city_row[live_price_key])
    if live_city_row.get("observation_at"):
        city_latest_date = pd.to_datetime(live_city_row["observation_at"], utc=True).tz_convert("Asia/Kolkata").tz_localize(None)

# --------------------------------------------------
# 8. NEXT-DAY BASELINE ESTIMATE
# --------------------------------------------------
st.subheader("Tomorrow's Baseline Estimate")

st.metric(
    label=f"{fuel_type} estimate for {selected_city}",
    value=f"₹{latest_price:.2f}/litre",
)

st.caption(
    f"Input price date/update: {city_latest_date.strftime('%d %B %Y')}. "
    "The persistence baseline carries the latest available price forward. "
    "It is not a guaranteed forecast and does not predict the timing "
    "or magnitude of a future price revision."
)
st.caption(
    "Input: latest provider price. This is a persistence baseline, not a live-trained ML forecast."
    if live_city_row
    else "Input: dated historical fallback because a successful provider refresh is not available."
)

# --------------------------------------------------
# 9. HISTORICAL PRICE CHART
# --------------------------------------------------
st.divider()
st.subheader("Historical Price Trend")

min_date = city_df["date"].min().date()
max_date = city_df["date"].max().date()

date_range = st.date_input(
    "Choose date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

filtered_df = city_df[
    (city_df["date"].dt.date >= start_date)
    & (city_df["date"].dt.date <= end_date)
]

if filtered_df.empty:
    st.warning("No records found for this date range.")
else:
    chart = px.line(
        filtered_df,
        x="date",
        y=price_column,
        title=f"{selected_city} {fuel_type} Price Over Time",
        labels={
            "date": "Date",
            price_column: "Price (₹ per litre)",
        },
    )

    chart.update_layout(
        hovermode="x unified",
        xaxis_title="Date",
        yaxis_title="Price (₹ per litre)",
    )

    st.plotly_chart(chart, width="stretch")

# --------------------------------------------------
# 10. DATASET INFORMATION
# --------------------------------------------------
with st.expander("About the dataset"):
    st.write(f"**Total records:** {len(df):,}")
    st.write(f"**Cities:** {', '.join(cities)}")
    st.write(f"**First date:** {df['date'].min().date()}")
    st.write(f"**Last date:** {df['date'].max().date()}")
    st.write(
        "**Historical source:** The project's prepared CSV. Latest published prices are requested from a third-party provider when available; fallback observations retain their original dates."
    )
