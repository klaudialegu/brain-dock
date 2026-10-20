import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Order is the display order. The first city is the reference for showing a day.
DEFAULT_CITIES = [
    ("Seattle", "America/Los_Angeles"),
    ("Chicago", "America/Chicago"),
    ("New York", "America/New_York"),
    ("Warsaw", "Europe/Warsaw"),
]


@dataclass(frozen=True)
class Clock:
    city: str
    tz: str
    time: str  # 24-hour "HH:MM"
    day: str | None  # short weekday like "Tue", only when the date differs from the reference


def load_cities(path: Path) -> list[tuple[str, str]]:
    """Read [[clocks]] entries from a TOML file, or return the defaults if it doesn't exist."""
    if not path.exists():
        return DEFAULT_CITIES

    with path.open("rb") as f:
        entries = tomllib.load(f).get("clocks", [])
    if not entries:
        raise ValueError(f"{path.name} has no [[clocks]] entries")

    cities = []
    for entry in entries:
        if "city" not in entry or "tz" not in entry:
            raise ValueError(f"{path.name}: each [[clocks]] entry needs a city and a tz")
        city, tz = entry["city"], entry["tz"]
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"{path.name}: unknown time zone {tz!r} for {city}") from None
        cities.append((city, tz))
    return cities


def world_clocks(
    now: datetime | None = None, cities: list[tuple[str, str]] = DEFAULT_CITIES
) -> list[Clock]:
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must include a time zone")

    reference_date = now.astimezone(ZoneInfo(cities[0][1])).date()
    clocks = []
    for city, tz in cities:
        local = now.astimezone(ZoneInfo(tz))
        day = local.strftime("%a") if local.date() != reference_date else None
        clocks.append(Clock(city=city, tz=tz, time=local.strftime("%H:%M"), day=day))
    return clocks
