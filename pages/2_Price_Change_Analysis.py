
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
    page_title="Price Change Analysis",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_fuel_theme()
require_user()
render_account_sidebar("price_change_analysis")

st.title("🔎 Fuel Price Change Analysis")
st.write(
    "Analyze recorded fuel price revisions by city, date, and magnitude."
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

    for column in [
        "petrol_price_inr_per_litre",
        "diesel_price_inr_per_litre",
    ]:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    return data.dropna(subset=["date", "city"]).sort_values(
        ["city", "date"]
    )


if not DATA_PATH.exists():
    st.error(f"Dataset not found: {DATA_PATH}")
    st.stop()

df = load_data(str(DATA_PATH))

# --------------------------------------------------
# 3. CALCULATE DAY-TO-DAY PRICE CHANGES
# --------------------------------------------------
df["Petrol Change"] = (
    df.groupby("city")["petrol_price_inr_per_litre"].diff()
)

df["Diesel Change"] = (
    df.groupby("city")["diesel_price_inr_per_litre"].diff()
)

# --------------------------------------------------
# 4. FILTERS
# --------------------------------------------------
st.subheader("Analysis Filters")

cities = sorted(df["city"].dropna().unique().tolist())

filter_cols = st.columns(2)
selected_city = filter_cols[0].selectbox(
    "Select city",
    ["All cities"] + cities,
)

fuel_type = filter_cols[1].selectbox(
    "Select fuel",
    ["Petrol", "Diesel"],
)

change_column = (
    "Petrol Change" if fuel_type == "Petrol" else "Diesel Change"
)

price_column = (
    "petrol_price_inr_per_litre"
    if fuel_type == "Petrol"
    else "diesel_price_inr_per_litre"
)

# Filter by date
min_date = df["date"].min().date()
max_date = df["date"].max().date()

date_range = st.date_input(
    "Select analysis period",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

filtered = df[
    (df["date"].dt.date >= start_date)
    & (df["date"].dt.date <= end_date)
].copy()

if selected_city != "All cities":
    filtered = filtered[filtered["city"] == selected_city]

filtered = filtered.dropna(subset=[change_column])

if filtered.empty:
    st.warning("No price-change records found for these filters.")
    st.stop()

# --------------------------------------------------
# 5. SUMMARY METRICS
# --------------------------------------------------
# A price revision is any non-zero difference between
# consecutive recorded dates for the same city.
changed = filtered[filtered[change_column].abs() > 1e-9]

increased = filtered[filtered[change_column] > 1e-9]
decreased = filtered[filtered[change_column] < -1e-9]

col1, col2, col3, col4 = st.columns(4)

col1.metric("Price revisions", f"{len(changed):,}")
col2.metric("Price increases", f"{len(increased):,}")
col3.metric("Price decreases", f"{len(decreased):,}")

revision_rate = (
    len(changed) / len(filtered) * 100 if len(filtered) else 0
)

col4.metric("Revision rate", f"{revision_rate:.2f}%")

st.caption(
    "The revision rate is the share of rows in the selected period "
    "whose price differs from the previous recorded row for that city. "
    "The first row of each city is excluded because no prior price exists."
)

# --------------------------------------------------
# 6. PRICE CHANGE DISTRIBUTION
# --------------------------------------------------
st.subheader("Distribution of Price Changes")

distribution = filtered.copy()
distribution["Change Direction"] = distribution[change_column].apply(
    lambda value: (
        "Increase" if value > 1e-9
        else "Decrease" if value < -1e-9
        else "No change"
    )
)

direction_counts = (
    distribution["Change Direction"]
    .value_counts()
    .rename_axis("Direction")
    .reset_index(name="Records")
)

fig_direction = px.bar(
    direction_counts,
    x="Direction",
    y="Records",
    color="Direction",
    title=f"{fuel_type}: Increase, Decrease and No Change",
    text="Records",
)

st.plotly_chart(fig_direction, width="stretch")

# --------------------------------------------------
# 7. PRICE CHANGE MAGNITUDES
# --------------------------------------------------
st.subheader("Largest Recorded Price Revisions")

threshold = st.number_input(
    "Minimum absolute change (₹ per litre)",
    min_value=0.0,
    value=0.0,
    step=0.1,
)

large_changes = filtered[
    filtered[change_column].abs() > threshold
].copy()

large_changes["Absolute Change"] = large_changes[change_column].abs()

large_changes = large_changes.sort_values(
    "Absolute Change", ascending=False
)

display_columns = [
    "date",
    "city",
    price_column,
    change_column,
    "Absolute Change",
]

display_table = large_changes[display_columns].copy()

display_table = display_table.rename(
    columns={
        "date": "Date",
        "city": "City",
        price_column: "Recorded Price (₹/L)",
        change_column: "Change (₹/L)",
        "Absolute Change": "Absolute Change (₹/L)",
    }
)

display_table["Date"] = display_table["Date"].dt.strftime("%Y-%m-%d")

for column in [
    "Recorded Price (₹/L)",
    "Change (₹/L)",
    "Absolute Change (₹/L)",
]:
    display_table[column] = display_table[column].round(2)

st.dataframe(
    display_table.head(100),
    width="stretch",
    hide_index=True,
)

# --------------------------------------------------
# 8. PRICE CHANGE OVER TIME
# --------------------------------------------------
st.subheader("Price Revisions Over Time")

timeline = filtered.copy()
timeline["Absolute Change"] = timeline[change_column].abs()

fig_timeline = px.scatter(
    timeline,
    x="date",
    y=change_column,
    color="city",
    size="Absolute Change",
    hover_data=[price_column],
    title=f"{fuel_type}: Day-to-Day Price Changes",
    labels={
        "date": "Date",
        change_column: "Change (₹ per litre)",
        "city": "City",
    },
)

fig_timeline.add_hline(y=0, line_dash="dash")

st.plotly_chart(fig_timeline, width="stretch")

# --------------------------------------------------
# 9. DOWNLOAD RESULTS
# --------------------------------------------------
st.subheader("Export Analysis")

csv_data = filtered.to_csv(index=False).encode("utf-8")

st.download_button(
    "Download filtered analysis as CSV",
    data=csv_data,
    file_name="fuel_price_change_analysis.csv",
    mime="text/csv",
)

st.caption(
    "Changes are calculated from consecutive rows in the dataset. "
    "A recorded revision does not establish its cause."
)
