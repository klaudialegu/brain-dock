"""Today's weather for the morning brief (ADR 0014), from Open-Meteo: free, no key.

Only the coordinates go out, rounded to 1 decimal (about 10 km, city level), plus fixed
settings. The answer is always in Fahrenheit, so the tip rules have one scale; only the
spoken numbers are converted for Celsius. The forecast is cached for the morning (and then
per hour), so re-running the show produces the same script and hits the audio cache.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from brain_dock.outbound import fetch, private_dir, write_private

API = "https://api.open-meteo.com/v1/forecast"
SOURCE = "weather service"
RAINY = 50  # percent: worth a hood
DRY = 20  # percent: below this, "it should stay dry"


@dataclass(frozen=True)
class Weather:
    now: float  # all in Fahrenheit
    high: float
    low: float
    rain: int  # today's highest chance of rain, percent
    rain_morning: int  # highest chance before noon
    rain_later: int  # highest chance from noon on


def request_url(latitude: float, longitude: float) -> str:
    params = {
        "latitude": round(latitude, 1),
        "longitude": round(longitude, 1),
        "current": "temperature_2m,precipitation",
        "hourly": "precipitation_probability",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
        "forecast_days": 1,
    }
    return f"{API}?{urlencode(params)}"


def parse(data: dict) -> Weather:
    """Raises KeyError, IndexError, TypeError or ValueError on an unexpected answer."""
    hours = [int(t[11:13]) for t in data["hourly"]["time"]]
    chances = [p or 0 for p in data["hourly"]["precipitation_probability"]]
    return Weather(
        now=float(data["current"]["temperature_2m"]),
        high=float(data["daily"]["temperature_2m_max"][0]),
        low=float(data["daily"]["temperature_2m_min"][0]),
        rain=int(data["daily"]["precipitation_probability_max"][0] or 0),
        rain_morning=max((p for h, p in zip(hours, chances, strict=True) if h < 12), default=0),
        rain_later=max((p for h, p in zip(hours, chances, strict=True) if h >= 12), default=0),
    )


def tip(w: Weather) -> str:
    """Deterministic, first match wins; thresholds are in Fahrenheit."""
    if w.rain_morning >= RAINY:
        return "grab a hood before noon"
    if w.rain_later >= RAINY:
        return "keep a hood handy for the afternoon"
    if w.high <= 40:
        return "bundle up"
    if w.high >= 85:
        return "bring water"
    return "a nice one for a walk"


def spoken(value_f: float, unit: str) -> int:
    return round((value_f - 32) * 5 / 9) if unit == "celsius" else round(value_f)


def sentence(w: Weather, unit: str = "fahrenheit", with_tip: bool = True) -> str:
    now, high, low = (spoken(v, unit) for v in (w.now, w.high, w.low))
    text = f"Right now it's {now} degrees, heading for {high}, with a low of {low}."
    if w.rain >= DRY:
        article = "an" if str(w.rain).startswith("8") else "a"  # "an 80", "an 88"
        text += f" There's {article} {w.rain} percent chance of rain"
    else:
        text += " It should stay dry"
    return text + (f", so {tip(w)}." if with_tip else ".")


def cache_name(now: datetime) -> str:
    part = "am" if now.hour < 12 else f"{now.hour:02d}h"
    return f"weather-{now.date().isoformat()}-{part}.json"


def today(
    latitude: float,
    longitude: float,
    *,
    now: datetime,
    cache_dir: Path,
    fetch_fn: Callable[..., bytes] = fetch,
) -> Weather:
    """From the cache when this morning (or this hour) already has one; otherwise fetched."""
    cached = cache_dir / cache_name(now)
    if cached.exists():
        return Weather(**json.loads(cached.read_text()))
    weather = parse(json.loads(fetch_fn(request_url(latitude, longitude), SOURCE)))
    for old in cache_dir.glob("weather-*.json"):
        old.unlink()  # only the current forecast is kept
    write_private(private_dir(cache_dir) / cached.name, json.dumps(asdict(weather)).encode())
    return weather
