"""Fetch, validate, and cache the latest published city fuel prices.

API Mitra is a third-party provider. The UI must keep the source and
freshness visible and fall back to dated project history on any failure.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


PROVIDER_NAME = "API Mitra (third-party)"
DEFAULT_BASE_URL = "https://api.apimitra.in"
CITY_ALIASES = {
    "chennai": "Chennai",
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "mumbai": "Mumbai",
    "kolkata": "Kolkata",
}
EXPECTED_CITIES = ("Chennai", "Delhi", "Mumbai", "Kolkata")
FUEL_FIELDS = ("petrol", "diesel")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _price(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("price")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # Broad guard against malformed units or obvious bad values, not a price correction.
    return number if 10 <= number <= 300 else None


def _extract_records(payload: Any, retrieved_at: datetime) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("status") not in ("ok", None):
        raise ValueError("Provider response did not report a successful status.")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Provider response is missing its data list.")

    provider_updated = _parse_timestamp(payload.get("updated_at") or payload.get("fetched_at"))
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_city = str(item.get("location", "")).strip().casefold()
        city = CITY_ALIASES.get(raw_city)
        if city is None:
            continue
        if city in seen:
            raise ValueError(f"Provider returned duplicate observations for {city}.")
        seen.add(city)
        prices = {fuel: _price(item.get(fuel)) for fuel in FUEL_FIELDS}
        if any(price is None for price in prices.values()):
            # A partially malformed city row is excluded, never silently repaired.
            continue
        item_updated = _parse_timestamp(item.get("updated_at")) or provider_updated
        records.append({
            "city": city,
            "petrol_price_inr_per_litre": prices["petrol"],
            "diesel_price_inr_per_litre": prices["diesel"],
            "observation_at": item_updated.isoformat() if item_updated else None,
            "retrieved_at": retrieved_at.isoformat(),
            "provider": PROVIDER_NAME,
            "source_url": f"{os.getenv('FUEL_PRICE_API_BASE_URL', DEFAULT_BASE_URL).rstrip('/')}/fuel/latest",
        })

    if not records:
        raise ValueError("Provider returned no valid prices for the supported cities.")
    return records


def _read_cache(cache_path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(cache_path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and isinstance(value.get("records"), list) else None
    except (OSError, json.JSONDecodeError):
        return None


def _source_freshness(value: dict[str, Any], now: datetime) -> tuple[str, str | None]:
    """Do not call data live when its own provider timestamp is absent or old."""
    provider_time = _parse_timestamp(value.get("provider_updated_at"))
    if provider_time is None:
        return "stale", "Provider did not supply a usable update timestamp."
    age_hours = (now - provider_time).total_seconds() / 3600
    if age_hours < -1:
        return "stale", "Provider update timestamp is unexpectedly in the future."
    if age_hours > 36:
        return "stale", f"Provider data is {age_hours:.0f} hours old."
    return "live", None


def _write_cache(cache_path: Path, value: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement prevents a failed process from leaving a partial cache.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_path.parent, delete=False) as temp:
        json.dump(value, temp, ensure_ascii=False, indent=2)
        temp_path = Path(temp.name)
    temp_path.replace(cache_path)


def get_latest_prices(
    cache_path: str | Path,
    *,
    force_refresh: bool = False,
    cache_minutes: int = 720,
    timeout_seconds: int = 8,
) -> dict[str, Any]:
    """Return validated provider data, or the last successful cached response."""
    path = Path(cache_path)
    cached = _read_cache(path)
    now = _utc_now()
    cached_at = _parse_timestamp(cached.get("retrieved_at")) if cached else None
    if (
        not force_refresh
        and cached
        and cached_at
        and (now - cached_at).total_seconds() < cache_minutes * 60
    ):
        freshness, freshness_note = _source_freshness(cached, now)
        return {**cached, "status": freshness, "error": freshness_note, "from_cache": True}

    base_url = os.getenv("FUEL_PRICE_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    url = f"{base_url}/fuel/latest"
    try:
        headers = {"Accept": "application/json", "User-Agent": "FuelPricePredictionSystem/1.0"}
        api_key = os.getenv("FUEL_PRICE_API_KEY", "").strip()
        if api_key:
            headers["x-api-key"] = api_key
        elif "FUEL_PRICE_API_KEY" not in os.environ:
            raise ValueError("FUEL_PRICE_API_KEY is not set; API Mitra requires an API key.")
        request = Request(url, headers=headers)
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise ValueError(f"Provider returned HTTP {response.status}.")
            payload = json.loads(response.read().decode("utf-8"))
        records = _extract_records(payload, now)
        result = {
            "provider": PROVIDER_NAME,
            "source_url": url,
            "retrieved_at": now.isoformat(),
            "provider_updated_at": payload.get("updated_at") or payload.get("fetched_at"),
            "records": records,
        }
        _write_cache(path, result)
        freshness, freshness_note = _source_freshness(result, now)
        return {**result, "status": freshness, "error": freshness_note, "from_cache": False}
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        error = f"Could not refresh the provider data: {exc}"
        if cached:
            return {**cached, "status": "stale", "error": error, "from_cache": True}
        return {
            "provider": PROVIDER_NAME,
            "source_url": url,
            "retrieved_at": None,
            "provider_updated_at": None,
            "records": [],
            "status": "unavailable",
            "error": error,
            "from_cache": False,
        }