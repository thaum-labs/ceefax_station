import warnings
from dataclasses import dataclass
from typing import Any, Dict, List

import requests

from .compiler import PAGE_WIDTH


OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _normalize_location(location: str) -> str:
    loc = (location or "").strip()
    if loc.endswith(",GB"):
        loc = loc[:-3] + ",UK"
    return loc


@dataclass
class WeatherSummary:
    location: str
    temp_c: str
    feels_like_c: str
    description: str
    wind_kph: str
    wind_dir: str
    icon: str
    today_max: str = "?"
    today_min: str = "?"
    today_desc: str = ""
    tonight_min: str = "?"
    tonight_desc: str = ""
    tomorrow_desc: str = ""


def weather_summary_to_dict(summary: WeatherSummary) -> Dict[str, str]:
    return {
        field: str(getattr(summary, field))
        for field in WeatherSummary.__dataclass_fields__
    }


def weather_summary_from_dict(data: Dict[str, Any]) -> WeatherSummary:
    return WeatherSummary(
        **{
            field: str(data.get(field, ""))
            for field in WeatherSummary.__dataclass_fields__
        }
    )


def _weather_description(code: int) -> str:
    descriptions = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Freezing fog",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Heavy drizzle",
        56: "Freezing drizzle",
        57: "Heavy freezing drizzle",
        61: "Light rain",
        63: "Rain",
        65: "Heavy rain",
        66: "Freezing rain",
        67: "Heavy freezing rain",
        71: "Light snow",
        73: "Snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Light rain showers",
        81: "Rain showers",
        82: "Heavy rain showers",
        85: "Light snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Severe thunderstorm with hail",
    }
    return descriptions.get(int(code), "Unknown conditions")


def _wind_direction(degrees: float) -> str:
    points = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
    return points[round(float(degrees) / 22.5) % 16]


def _open_meteo_coordinates(location: str) -> tuple[float, float, str]:
    parts = [part.strip() for part in location.split(",", 1)]
    query = parts[0]
    params: Dict[str, str | int] = {
        "name": query,
        "count": 1,
        "language": "en",
        "format": "json",
    }
    if len(parts) > 1 and parts[1]:
        country = parts[1].upper()
        params["countryCode"] = "GB" if country in {"UK", "GB"} else country
    response = requests.get(
        OPEN_METEO_GEOCODING_URL,
        params=params,
        timeout=10,
        headers={"User-Agent": "CeefaxStation/1.0"},
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        raise ValueError(f"Open-Meteo could not locate {query!r}")
    place = results[0]
    return float(place["latitude"]), float(place["longitude"]), str(place.get("name") or query)


def fetch_open_meteo(location: str) -> WeatherSummary:
    """Fetch structured current and forecast weather from Open-Meteo."""
    latitude, longitude, resolved_name = _open_meteo_coordinates(location)
    response = requests.get(
        OPEN_METEO_FORECAST_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "temperature_2m,apparent_temperature,weather_code,"
                "wind_speed_10m,wind_direction_10m"
            ),
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "forecast_days": 2,
        },
        timeout=10,
        headers={"User-Agent": "CeefaxStation/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    daily_codes = daily.get("weather_code") or []
    maximums = daily.get("temperature_2m_max") or []
    minimums = daily.get("temperature_2m_min") or []
    required = ("temperature_2m", "apparent_temperature", "weather_code",
                "wind_speed_10m", "wind_direction_10m")
    if any(key not in current for key in required) or not daily_codes:
        raise ValueError("Open-Meteo response is missing required weather fields")

    description = _weather_description(int(current["weather_code"]))
    today_desc = _weather_description(int(daily_codes[0]))
    tomorrow_desc = _weather_description(int(daily_codes[1])) if len(daily_codes) > 1 else ""
    fmt = lambda value: f"{float(value):.0f}"  # noqa: E731
    return WeatherSummary(
        location=resolved_name,
        temp_c=fmt(current["temperature_2m"]),
        feels_like_c=fmt(current["apparent_temperature"]),
        description=description,
        wind_kph=fmt(current["wind_speed_10m"]),
        wind_dir=_wind_direction(float(current["wind_direction_10m"])),
        icon=_pick_icon(description),
        today_max=fmt(maximums[0]) if maximums else "?",
        today_min=fmt(minimums[0]) if minimums else "?",
        today_desc=today_desc,
        tonight_min=fmt(minimums[0]) if minimums else "?",
        tonight_desc=today_desc,
        tomorrow_desc=tomorrow_desc,
    )


def fetch_open_meteo_many(locations: List[str], *, max_workers: int = 6) -> Dict[str, WeatherSummary]:
    """Fetch several Open-Meteo locations concurrently; fail if any is unavailable."""
    from concurrent.futures import ThreadPoolExecutor

    normalized = list(dict.fromkeys(_normalize_location(item) for item in locations if item))
    workers = max(1, min(int(max_workers), len(normalized)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        summaries = executor.map(fetch_open_meteo, normalized)
        return dict(zip(normalized, summaries))


def _pick_icon(desc: str) -> str:
    """
    Map a free-text weather description to a simple Ceefax-style icon.
    """
    lower = desc.lower()
    if "sun" in lower or "clear" in lower:
        return "☀"
    if "rain" in lower or "shower" in lower or "drizzle" in lower:
        return "🌦"
    if "snow" in lower or "sleet" in lower:
        return "❄"
    if "storm" in lower or "thunder" in lower:
        return "⛈"
    if "fog" in lower or "mist" in lower or "haze" in lower:
        return "🌫"
    return "☁"  # default cloud


def fetch_wttr(location: str, max_retries: int = 3) -> WeatherSummary:
    """Deprecated compatibility wrapper for :func:`fetch_open_meteo`."""
    del max_retries
    warnings.warn(
        "fetch_wttr() is deprecated; use fetch_open_meteo()",
        DeprecationWarning,
        stacklevel=2,
    )
    return fetch_open_meteo(location)


def fetch_wttr_many(locations: List[str], *, max_workers: int = 6) -> Dict[str, WeatherSummary]:
    """Deprecated compatibility wrapper for :func:`fetch_open_meteo_many`."""
    warnings.warn(
        "fetch_wttr_many() is deprecated; use fetch_open_meteo_many()",
        DeprecationWarning,
        stacklevel=2,
    )
    return fetch_open_meteo_many(locations, max_workers=max_workers)


def build_ceefax_panel(summary: WeatherSummary) -> List[str]:
    """
    Render a single-location weather panel as Ceefax-style text lines.

    These lines are sized to PAGE_WIDTH so they can be dropped straight
    into a page's 'content' array.
    """

    def pad(text: str) -> str:
        return text[:PAGE_WIDTH].ljust(PAGE_WIDTH)

    lines: List[str] = []
    lines.append(pad(f"{summary.location.upper()} WEATHER"))
    lines.append(pad(""))
    lines.append(
        pad(f"   {summary.icon}    {summary.description[: PAGE_WIDTH - 8]}")
    )
    lines.append(
        pad(f"Temp {summary.temp_c}C (feels {summary.feels_like_c}C)")
    )
    lines.append(
        pad(f"Wind {summary.wind_kph} km/h from {summary.wind_dir}")
    )
    lines.append(pad(""))
    lines.append(pad("Data source: Open-Meteo"))

    return lines


def build_ceefax_panel_for(location: str) -> List[str]:
    """
    Convenience helper: fetch + render in one call.

    Example:

        from src.weather_map import build_ceefax_panel_for
        lines = build_ceefax_panel_for("Frome,UK")
        for l in lines:
            print(l)
    """
    warnings.warn(
        "build_ceefax_panel_for() is deprecated; fetch with Open-Meteo and "
        "call build_ceefax_panel()",
        DeprecationWarning,
        stacklevel=2,
    )
    summary = fetch_open_meteo(location)
    return build_ceefax_panel(summary)


