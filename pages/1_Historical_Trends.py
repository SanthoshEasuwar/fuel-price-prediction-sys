
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from services.auth_service import render_account_sidebar, require_user
from services.ui import apply_fuel_theme

# --------------------------------------------------
# 1. PAGE CONFIGURATION
# --------------------------------------------------
st.set_page_config(
    page_title="Historical Fuel Trends",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_fuel_theme()
require_user()
render_account_sidebar("historical_trends")

st.title("📈 Historical Fuel Price Trends")
st.write(
    "Explore historical petrol and diesel prices across Indian cities."
)

# --------------------------------------------------
# 2. LOAD DATA
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "Data" / "fuel_prices_model_ready.csv"


@st.cache_data
def load_data(file_path):
    data = pd.read_csv(file_path)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")

    data["petrol_price_inr_per_litre"] = pd.to_numeric(
        data["petrol_price_inr_per_litre"], errors="coerce"
    )
    data["diesel_price_inr_per_litre"] = pd.to_numeric(
        data["diesel_price_inr_per_litre"], errors="coerce"
    )

    return data.dropna(subset=["date", "city"])


if not DATA_PATH.exists():
    st.error(f"Dataset not found: {DATA_PATH}")
    st.stop()

df = load_data(str(DATA_PATH))

# --------------------------------------------------
# 3. FILTERS
# --------------------------------------------------
st.subheader("Trend Filters")

cities = sorted(df["city"].dropna().unique().tolist())

filter_cols = st.columns(2)
selected_cities = filter_cols[0].multiselect(
    "Select cities",
    options=cities,
    default=[city for city in ["Chennai", "Delhi"] if city in cities],
)

fuel_options = filter_cols[1].multiselect(
    "Select fuels",
    options=["Petrol", "Diesel"],
    default=["Petrol", "Diesel"],
)

if not selected_cities or not fuel_options:
    st.info("Select at least one city and one fuel type.")
    st.stop()

filtered_df = df[df["city"].isin(selected_cities)].copy()

# --------------------------------------------------
# 4. DATE RANGE
# --------------------------------------------------
min_date = filtered_df["date"].min().date()
max_date = filtered_df["date"].max().date()

date_range = st.date_input(
    "Select date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

filtered_df = filtered_df[
    (filtered_df["date"].dt.date >= start_date)
    & (filtered_df["date"].dt.date <= end_date)
]

if filtered_df.empty:
    st.warning("No data is available for this date range.")
    st.stop()

# --------------------------------------------------
# 5. PREPARE CHART DATA
# --------------------------------------------------
price_columns = {
    "Petrol": "petrol_price_inr_per_litre",
    "Diesel": "diesel_price_inr_per_litre",
}

chart_frames = []

for fuel in fuel_options:
    column = price_columns[fuel]

    part = filtered_df[["date", "city", column]].copy()
    part = part.rename(columns={column: "Price"})
    part["Fuel Type"] = fuel

    chart_frames.append(part)

chart_df = pd.concat(chart_frames, ignore_index=True)
chart_df = chart_df.dropna(subset=["Price"])

# --------------------------------------------------
# 6. INTERACTIVE PRICE CHART
# --------------------------------------------------
st.subheader("Price Comparison")

fig = px.line(
    chart_df,
    x="date",
    y="Price",
    color="city",
    line_dash="Fuel Type",
    title="Fuel Prices by City and Fuel Type",
    labels={
        "date": "Date",
        "Price": "Price (₹ per litre)",
        "city": "City",
        "Fuel Type": "Fuel",
    },
)

fig.update_layout(
    hovermode="x unified",
    legend_title_text="City",
)

st.plotly_chart(fig, width="stretch")

# --------------------------------------------------
# 7. PRICE STATISTICS
# --------------------------------------------------
st.subheader("Price Statistics")

summary = (
    chart_df.groupby(["city", "Fuel Type"])["Price"]
    .agg(
        Average_Price="mean",
        Minimum_Price="min",
        Maximum_Price="max",
        Recorded_Days="count",
    )
    .reset_index()
)

summary = summary.rename(
    columns={
        "city": "City",
        "Fuel Type": "Fuel",
        "Average_Price": "Average (₹/L)",
        "Minimum_Price": "Minimum (₹/L)",
        "Maximum_Price": "Maximum (₹/L)",
        "Recorded_Days": "Records",
    }
)

for column in ["Average (₹/L)", "Minimum (₹/L)", "Maximum (₹/L)"]:
    summary[column] = summary[column].round(2)

st.dataframe(summary, width="stretch", hide_index=True)

# --------------------------------------------------
# 8. DOWNLOAD FILTERED DATA
# --------------------------------------------------
st.subheader("Download Historical Data")

csv_data = chart_df.to_csv(index=False).encode("utf-8")

st.download_button(
    label="Download chart data as CSV",
    data=csv_data,
    file_name="fuel_price_historical_trends.csv",
    mime="text/csv",
)

st.caption(
    "Statistics describe recorded prices in the selected period. "
    "They do not represent live prices or future predictions."
)
