from pathlib import Path

import pandas as pd
import streamlit as st

from services.auth_service import render_account_sidebar, require_user
from services.fuel_price_service import EXPECTED_CITIES, get_latest_prices
from services.ui import apply_fuel_theme


st.set_page_config(page_title="Data Sources and Methodology", layout="wide", initial_sidebar_state="expanded")
apply_fuel_theme()
require_user()
render_account_sidebar("data_sources")
st.title("Data Sources and Methodology")
st.caption("Source type and freshness are shown explicitly so provider data is not confused with historical records.")

base_dir = Path(__file__).resolve().parent.parent
data_path = base_dir / "Data" / "fuel_prices_model_ready.csv"
cache_path = base_dir / "Data" / "cache" / "latest_fuel_prices.json"
result = get_latest_prices(cache_path)

st.subheader("Current price source")
st.write("**Provider:** API Mitra, a third-party service (not an official government source).")
st.write("**Documented endpoint:** `GET https://api.apimitra.in/fuel/latest`.")
st.write("**Documented scope:** petrol and diesel prices for popular Indian cities, including city-level lookups; provider documentation says it crawls five times daily.")
st.write("**Refresh behavior:** the app caches a successful response for 15 minutes and also offers a manual refresh button on the overview and prediction page.")
st.write("**Source limitations:** the provider documentation does not establish an official government feed, independently verified accuracy, or reuse/licensing terms. The app therefore labels it third-party. Confirm the provider's terms before public/commercial deployment.")

if result["status"] == "live":
    st.success("Provider data is currently available in the app cache.")
elif result["status"] == "stale":
    st.warning("Provider data is stale or the latest refresh failed; the app is retaining the last validated response.")
    st.caption(result["error"])
else:
    st.warning("No successful provider response is cached; historical fallback is in use.")
    if result["error"]:
        st.caption(result["error"])
st.write(f"**Provider cache retrieval time:** {result.get('retrieved_at') or 'Not available'}")
st.write(f"**Provider update timestamp:** {result.get('provider_updated_at') or 'Not supplied'}")
st.write(f"**Cities returned:** {', '.join(row['city'] for row in result['records']) or 'None'}")

st.subheader("Official references")
st.markdown("- [PPAC metro-city daily retail price report](https://ppac.gov.in/uploads/page-images/1749790489_PP_9_a_DailyPriceMSHSD_Metro_13.06.2025.pdf)")
st.markdown("- [Indian Oil petrol and diesel price information](https://www.iocl.com/petrol-diesel-price)")
st.write("PPAC publishes official metro price reports. Indian Oil says daily changes take effect at 6 a.m. and provides indicative prices by SMS. This app does not scrape those sites or claim an official automated feed.")

st.subheader("Historical data and prediction")
if data_path.exists():
    data = pd.read_csv(data_path, usecols=lambda col: col in {"date", "city"})
    dates = pd.to_datetime(data["date"], errors="coerce").dropna()
    cities = sorted(data["city"].dropna().astype(str).unique())
    st.write(f"**Historical file:** `Data/fuel_prices_model_ready.csv` · {len(data):,} rows · {dates.min().date()} to {dates.max().date()} · {', '.join(cities)}.")
else:
    st.warning("Historical CSV is missing.")
st.write("**Forecast target:** next-day price estimate. **Baseline:** carry the latest available price forward. The saved evaluation favors this baseline over the tested Random Forest on overall MAE; overall error does not show revision timing skill.")
st.write("Historical patterns cannot guarantee future fuel-price decisions. The original CSV and model evaluation artifacts are left unchanged.")
