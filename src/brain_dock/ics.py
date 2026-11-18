"""Today's workout from the Runna iCalendar feed, for the morning brief (ADR 0014).

A small reader for single events: folded lines, all-day dates, UTC times, TZID times and
floating times. Repeating rules (RRULE) aren't expanded; Runna lists each workout as its
own event. Meetings need repeating events, so they wait for the schedule slice and a real
calendar library. Only today's events are read, in memory; the feed is never stored.

Only the workout's name (cleaned and trimmed), its minutes and its distance reach the
script. Minutes and distance come from the event's own times or the end of its title
(titles like "Easy Run 30m", "Easy Run 5km"), never from the description: its numbers
are steps ("5 min warm up"), not the workout.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from brain_dock.core.masking import scrub

NAME_LIMIT = 40
UNSAFE = re.compile(r"[^A-Za-z0-9 .,:'&/+()\[\]-]+")
# At the end of a title only. Minutes have 1-2 digits, so "800m" stays meters in the name.
DURATION_END = re.compile(
    r"[\s,-]*\b(?:(\d{1,2})\s?h\s?)?(\d{1,2})\s?(?:m|min|mins|minutes)\.?$", re.I
)
HOURS_END = re.compile(r"[\s,-]*\b(\d{1,2})\s?(?:h|hr|hrs|hours?)\.?$", re.I)
DISTANCE_END = re.compile(r"[\s,-]*\b(\d{1,2}(?:\.\d{1,2})?)\s?(km|k|mi|miles?)\.?$", re.I)


@dataclass(frozen=True)
class Event:
    summary: str
    description: str
    start: datetime | date
    end: datetime | date | None


@dataclass(frozen=True)
class Workout:
    name: str
    minutes: int | None = None
    distance: str | None = None  # spoken form, like "5 kilometers"


def unfold(text: str) -> list[str]:
    """iCalendar wraps long lines with a leading space or tab on the next line."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def unescape(value: str) -> str:
    return (
        value.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";")
    ).replace("\\\\", "\\")


def parse_time(value: str, params: dict[str, str], local: tzinfo) -> datetime | date:
    value = value.strip()
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return datetime.strptime(value, "%Y%m%d").date()
    if value.endswith("Z"):
        moment = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=ZoneInfo("UTC"))
        return moment.astimezone(local)
    try:
        zone: tzinfo = ZoneInfo(params["TZID"]) if "TZID" in params else local
    except (ZoneInfoNotFoundError, ValueError):
        zone = local  # an unknown zone name: read it as local time
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=zone).astimezone(local)


def parse_events(text: str, local: tzinfo) -> list[Event]:
    events, current = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            if "DTSTART" in current and current.get("STATUS", "").upper() != "CANCELLED":
                events.append(
                    Event(
                        summary=unescape(current.get("SUMMARY", "")),
                        description=unescape(current.get("DESCRIPTION", "")),
                        start=current["DTSTART"],
                        end=current.get("DTEND"),
                    )
                )
            current = None
        elif current is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *raw_params = head.split(";")
            params = dict(p.split("=", 1) for p in raw_params if "=" in p)
            name = name.upper()
            try:
                if name in ("DTSTART", "DTEND"):
                    current[name] = parse_time(value, params, local)
                elif name in ("SUMMARY", "DESCRIPTION", "STATUS"):
                    current[name] = value
            except ValueError:
                pass  # an unreadable time: the event is skipped (no DTSTART)
    return events


def on_day(event: Event, day: date) -> bool:
    if isinstance(event.start, datetime):
        return event.start.date() == day
    end = event.end if isinstance(event.end, date) and not isinstance(event.end, datetime) else None
    return event.start <= day < (end or event.start + timedelta(days=1))


def clean_name(summary: str) -> str:
    name = " ".join(UNSAFE.sub(" ", summary).split())
    if len(name) <= NAME_LIMIT:
        return name
    head = name[: NAME_LIMIT + 1]
    cut = head.rsplit(" ", 1)[0] if " " in head else ""
    return cut.rstrip(" .,:-/&+(") or name[:NAME_LIMIT]


def spoken_distance(number: str, unit: str) -> str:
    unit = unit.lower()
    word = "kilometers" if unit in ("km", "k") else "miles"
    if number in ("1", "1.0"):
        word = word.rstrip("s")
    return f"{number} {word}"


def split_title(title: str) -> tuple[str, int | None, str | None]:
    """'Easy Run 30m' -> ('Easy Run', 30, None); 'Easy Run 5km' -> ('Easy Run', None,
    '5 kilometers'). Both may be there, in either order."""
    minutes = distance = None
    for _ in range(2):
        if minutes is None and (found := DURATION_END.search(title)):
            minutes = int(found.group(1) or 0) * 60 + int(found.group(2))
            title = title[: found.start()]
        elif minutes is None and (found := HOURS_END.search(title)):
            minutes = int(found.group(1)) * 60
            title = title[: found.start()]
        elif distance is None and (found := DISTANCE_END.search(title)):
            distance = spoken_distance(*found.groups())
            title = title[: found.start()]
    return title.strip(" ,-"), minutes or None, distance


def workout_of(event: Event) -> Workout:
    # Masked before cleaning: cleaning removes the "@" or "=" the masking looks for.
    title = " ".join(UNSAFE.sub(" ", scrub(event.summary)).split())
    name, title_minutes, distance = split_title(title)
    minutes = None
    if isinstance(event.start, datetime) and isinstance(event.end, datetime):
        span = int((event.end - event.start).total_seconds() // 60)
        minutes = span if 5 <= span <= 300 else None
    return Workout(
        name=clean_name(name) or "Today's run",
        minutes=minutes or title_minutes,
        distance=distance,
    )


def todays_workout(feed: str, day: date, local: tzinfo) -> Workout | None:
    """The first workout today, or None for a rest day."""
    events = sorted(
        (e for e in parse_events(feed, local) if on_day(e, day)),
        key=lambda e: (isinstance(e.start, datetime), str(e.start)),
    )
    return workout_of(events[0]) if events else None
