# Fuel Price Prediction System

A Streamlit dashboard for Indian petrol and diesel prices. It combines a prepared historical dataset, latest published prices from API Mitra, historical analyses, forecast scenarios, and account sign-in.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Python dependencies are listed in `requirements.txt` (versions are not pinned). The historical dataset must be available at `Data/fuel_prices_model_ready.csv`.

To enable API Mitra prices, set `FUEL_PRICE_API_KEY` in the environment where Streamlit runs. The app sends it in the `x-api-key` request header. Optionally set `FUEL_PRICE_API_BASE_URL` if using a compatible API endpoint. Do not put API keys in source files or commit them to Git. In GitHub Actions, configure the repository secret `FUEL_PRICE_API_KEY` for the scheduled collector.

## Pages

- **Overview** — latest published prices, historical snapshot, city/fuel selection, persistence estimate, and historical chart.
- **Account** — sign up, log in, and log out.
- **Historical Trends** — filter, compare, chart, and export history.
- **Price Change Analysis** — inspect revisions, their distribution, and larger changes.
- **Model Evaluation** — view saved model evaluation and persistence comparison reports.
- **Tomorrow Prediction** — latest-price persistence estimate.
- **Daily accuracy check** — reconstructs historical one-day persistence estimates and compares them with recorded prices; also charts API-verified daily forecasts as they accumulate.
- **Data Sources** — data coverage, sources, and methodology.
- **Price Forecast** — simulate possible price paths from historical revision rates and sizes.
- **Event Impact Forecast** — explore a monthly scenario based on assumed Brent crude and USD/INR changes.

## Data files and storage

### Historical and market data

- `Data/fuel_prices_model_ready.csv` — prepared historical price dataset used for analysis and historical fallbacks. The current workspace dataset covers June 16, 2017 through October 16, 2026 for Chennai, Delhi, Kolkata, and Mumbai.
- `Data/live_prices.csv` — daily records written by `scripts/collector.py`. The GitHub Actions workflow commits updates to this file. The dashboard's live price display currently calls the provider and uses its separate cache; historical fallback comes from `fuel_prices_model_ready.csv`.
- `Data/daily_forecasts.csv` — daily persistence estimates written by the collector, keyed by target date, city, and fuel. A later fresh API observation is matched to the forecast date and adds the actual price and absolute/percentage error. The GitHub Actions workflow commits updates to this tracking file.
- `Data/cache/latest_fuel_prices.json` — validated API Mitra response cache. Successful responses are reused for up to 15 minutes. Provider data without a usable update timestamp or older than 36 hours is marked stale. This cache is excluded from Git.
- `Data/market_inputs.csv` — monthly Brent crude and USD/INR data downloaded from FRED for Event Impact Forecast. The page refreshes this file and uses the saved snapshot if a later refresh fails. This file is excluded from Git.

### Accounts and evaluation reports

- `Data/users.sqlite3` — local SQLite database for accounts. Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes, not plain text. The database is excluded from Git.
- `models/final_evaluation_report_v1.csv`, `models/model_comparison_v3.csv`, and `models/persistence_by_year_v1.csv` — saved evaluation inputs displayed by Model Evaluation. The dashboard does not overwrite or retrain these reports.

Other local secrets/configuration such as `.env` and `.streamlit/secrets.toml`, Python caches, and user database sidecar files are ignored by Git.

## Data collection and sources

### Latest published fuel prices

The application requests `GET https://api.apimitra.in/fuel/latest` from API Mitra, a third-party provider, and validates supported city names and price values. A successful response is cached in `Data/cache/latest_fuel_prices.json`. The refresh button requests an immediate update. If the API cannot be reached, the app labels cached data stale or falls back to a dated row in the prepared historical dataset.

The live dashboard API cache and `Data/live_prices.csv` are separate: the latter is maintained by the collector workflow and is not currently the dashboard's live-price source.

API Mitra's public documentation describes its fuel data for Indian cities. Provider sourcing, accuracy, availability, and reuse terms should be verified with the provider before public or commercial use. The code can be configured with `FUEL_PRICE_API_BASE_URL` if a compatible API endpoint changes.

### Scheduled collector

`.github/workflows/collect.yml` runs `python -m scripts.collector` daily (07:00 IST) and supports manual runs. The collector requests fresh API data, rejects stale/unavailable responses, and appends or updates date/city rows in `Data/live_prices.csv`. It also reconciles pending forecasts with matching provider observations, then saves a persistence estimate for the next observation date in `Data/daily_forecasts.csv`. A successful workflow commits both changed CSVs to the repository. It requires the GitHub Actions secret `FUEL_PRICE_API_KEY`.

### Event market inputs

Event Impact Forecast downloads Brent crude prices (EIA series distributed through FRED) and USD/INR exchange rates (Federal Reserve H.10 series distributed through FRED), then aggregates the daily records into monthly inputs.

References:

- [API Mitra fuel API documentation](https://docs.apimitra.in/fuel/overview/)
- [EIA Brent crude price series on FRED](https://fred.stlouisfed.org/series/DCOILBRENTEU)
- [Federal Reserve USD/INR series on FRED](https://fred.stlouisfed.org/series/DEXINUS)
- [PPAC metro-city daily retail price report](https://ppac.gov.in/uploads/page-images/1749790489_PP_9_a_DailyPriceMSHSD_Metro_13.06.2025.pdf)
- [Indian Oil petrol and diesel price information](https://www.iocl.com/petrol-diesel-price)

## Forecast methods

### Tomorrow's estimate

The tomorrow estimate is a persistence baseline: the next estimate equals the latest available price. It is not a live-trained ML forecast and does not predict whether or when a price revision will happen. The saved evaluation reports show the historical performance of the tested models and persistence baseline.

The Tomorrow Prediction page also shows a retrospective one-day backtest using consecutive dates in the historical CSV, with estimate-vs-actual and error charts. These reconstructed historical estimates were not saved at the time they would have been issued. Separately, `Data/daily_forecasts.csv` records estimates made by the scheduled collector and scores them when a matching provider observation is received. Pressing **Refresh latest provider prices** on that page also records/reconciles the live observation immediately. API-verified metrics therefore accumulate from successful daily collector runs or manual refreshes onward.

### Price Forecast

The multi-day forecast estimates how often revisions occurred and how large they were in a selected historical window, pooling city observations when needed. It simulates possible future paths from those observed revisions and displays a median and uncertainty band. It describes historical revision behavior; it cannot predict a future official decision.

### Event Impact Forecast

The event page asks for a scenario label, city, fuel, horizon, assumed Brent change, assumed USD/INR change, event duration, and a historical price-response regime. The label itself is not a model input.

The page fits a regularized monthly response model using historical city prices and market inputs, then evaluates it using the latest 18 months held out chronologically. It also calculates a separate descriptive historical pass-through estimate: next-month retail price changes regressed on changes in Brent priced in INR. The available regimes are historical oil-shock periods (2017–2022), full-history average, and recent pricing period (2023 onward). The explicit scenario shock uses the selected pass-through estimate even when validation gives the learned model zero weight; validation trust affects the learned baseline component. The page shows the assumed cost shock, selected response, scenario median, and an 80% range sampled from holdout errors.

This is a conditional scenario estimate, not a precise forecast of a war, disaster, or government response. Historical association is not a causal guarantee. Retail prices may be delayed or moderated by taxes, oil-company pricing, or government policy. Local refinery, transport, or supply disruptions may not be captured by Brent and USD/INR alone.

## Accounts and deployment notes

Accounts are local to this project instance. Login state lasts for the current Streamlit browser session. There is no email verification, password reset, login rate limiting, administrator approval, or shared multi-instance database. Accounts gate access to the pages; they do not provide per-user privacy for project data. This is intended for a single-instance college project/demo. Use HTTPS in deployment and consider a managed identity provider before exposing a production service.

## Project structure

```text
app.py                         Main dashboard
pages/                         Streamlit pages
services/                      Authentication, data, forecast, and shared UI logic
scripts/collector.py           Provider collector for Data/live_prices.csv
models/                         Saved evaluation reports
Data/                            Historical, live, cache, market, and account data
.github/workflows/collect.yml  Scheduled GitHub Actions collector
.streamlit/config.toml          Streamlit theme
requirements.txt                Python dependencies
tests/                           Project tests
```

## Limitations

- Provider availability and correctness depend on API Mitra; live data is not an official government feed verified by this project.
- The prepared historical dataset is not a substitute for a fresh provider observation. Historical backtest results are reconstructed from the records and are not a log of forecasts actually made in the past.
- There is no background collector in the Streamlit app itself. The separate GitHub Actions workflow collects to `Data/live_prices.csv`; the dashboard also refreshes provider prices when pages are used.
- Event results depend on user-supplied crude and currency assumptions and cannot foresee taxes, policy decisions, price freezes, or local disruptions.
- FRED refresh requires network access. A previously saved `Data/market_inputs.csv` snapshot is used if refresh fails.
