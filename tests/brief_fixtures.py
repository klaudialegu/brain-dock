"""Shared fakes for the morning brief tests: a forecast, a feed, and a network stand-in.
Nothing here reaches the network; the coordinates and URLs are made up."""

import json
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("America/Chicago")  # any fixed zone: tests never use the machine's own
NOW = datetime(2026, 11, 18, 7, 30)  # a Wednesday morning
COORDS = (12.3456, -45.6789)  # made up, not anyone's city
FEED_URL = "webcal://feeds.example.test/calendar/abc123.ics?token=feed-secret-qwfp"

FORECAST = {
    "current": {"time": "2026-11-18T07:30", "temperature_2m": 46.2, "precipitation": 0.0},
    "hourly": {
        "time": [f"2026-11-18T{h:02d}:00" for h in range(24)],
        "precipitation_probability": [10] * 8 + [70] * 4 + [30] * 12,
    },
    "daily": {
        "time": ["2026-11-18"],
        "temperature_2m_max": [52.4],
        "temperature_2m_min": [40.6],
        "precipitation_probability_max": [70],
    },
}
WEATHER_LINE = (
    "Right now it's 46 degrees, heading for 52, with a low of 41. "
    "There's a 70 percent chance of rain, so grab a hood before noon."
)


def feed(*events: str) -> str:
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def event(summary: str, start: str, end: str | None = None, extra: str = "") -> str:
    lines = ["BEGIN:VEVENT", f"SUMMARY:{summary}", start]
    if end:
        lines.append(end)
    if extra:
        lines.append(extra)
    return "\r\n".join([*lines, "END:VEVENT"]) + "\r\n"


RUNNA_FEED = feed(
    event(
        "Easy Run",
        "DTSTART;TZID=America/Chicago:20261118T070000",
        "DTEND;TZID=America/Chicago:20261118T074000",
        "DESCRIPTION:5 km at an easy pace. Private note-qwfp about my knee\\, keep it slow.\r\n"
        "LOCATION:12 Example Street",
    ),
    event("Long Run 16 km", "DTSTART;VALUE=DATE:20261122"),
)


class FakeNet:
    """Stands in for the keychain, the weather service and the Runna feed."""

    def __init__(self, forecast=FORECAST, runna=RUNNA_FEED, feed_url=FEED_URL, fail=None):
        self.forecast, self.runna, self.feed_url, self.fail = forecast, runna, feed_url, fail
        self.fetched: list[tuple[str, str]] = []
        self.secrets: list[str] = []
        self.notes: list[str] = []

    def secret(self, service):
        self.secrets.append(service)
        return self.feed_url

    def fetch(self, url, source, **kwargs):
        self.fetched.append((url, source))
        if self.fail and self.fail[0] in source:
            raise self.fail[1]
        if "open-meteo" in url:
            return json.dumps(self.forecast).encode()
        return self.runna.encode()

    def options(self, lines=("2 follow-ups are overdue.", "1 offer is open.")):
        return {
            "secret": self.secret,
            "fetch_fn": self.fetch,
            "lines": lambda day: {"job_search": list(lines)},
            "local": LOCAL,
            "note": self.notes.append,
        }


class FakeGuard:
    """Records what a guarded block allowed, and whether it's open."""

    def __init__(self):
        self.allow, self.inside = None, False

    @contextmanager
    def __call__(self, allow):
        self.allow, self.inside = list(allow), True
        try:
            yield
        finally:
            self.inside = False
