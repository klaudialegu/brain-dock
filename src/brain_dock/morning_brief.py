"""The morning brief's script (ADR 0014): short spoken sentences in a fixed order.

Greeting, weather, today's workout, to-dos, job counts, sign-off. Each section is
optional: a source that's off or failed just isn't mentioned. The script is what
ElevenLabs gets, so it holds no event descriptions, feed URLs or coordinates. The only
free text is the greeting name and the titles of tasks you marked "ok to read aloud"
(ADR 0015). It's capped so weekday use fits the free plan.
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from pathlib import Path

from brain_dock import weather as weather_source
from brain_dock.brief import module_lines
from brain_dock.ics import Workout, todays_workout
from brain_dock.outbound import FetchError, fetch, keychain_secret
from brain_dock.weather import Weather, sentence

MAX_SCRIPT_CHARS = 420  # 23 weekdays x 420 = 9,660 credits, under the free plan's 10,000
MAX_JOB_LINES = 2
SIGN_OFF = "That's your morning. Have a lovely day!"
REST = "rest"  # a workout value meaning "the feed says nothing today"
RUNNA_SERVICE = "brain-dock-runna-ics"  # keychain service holding the feed's secret URL


@dataclass
class Sources:
    """What the morning brief knows this morning. None means the section is left out."""

    greeting_name: str = ""
    weather: Weather | None = None
    temperature_unit: str = "fahrenheit"
    workout: Workout | str | None = None  # a Workout, REST, or None (no feed)
    todo_lines: list[str] = field(default_factory=list)  # a count, then marked titles
    job_lines: list[str] = field(default_factory=list)


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def greeting(today: date, name: str = "") -> str:
    who = f"Good morning, {name}," if name else "Good morning,"
    return f"{who} it's {today:%A, %B} {ordinal(today.day)}."


def workout_sentence(workout: Workout | str, detail: bool = True) -> str:
    if workout == REST:
        return "No run on the plan today... it's a rest day."
    if not detail:
        return "There's a run on the plan today."
    parts = [workout.name]
    if workout.distance:
        parts.append(workout.distance)
    if workout.minutes:
        parts.append(f"about {workout.minutes} minutes")
    return f"On the training plan today: {', '.join(parts)}."


def jobs_sentence(lines: list[str]) -> str:
    return "On the job front... " + " ".join(lines)


def build_script(today: date, sources: Sources, limit: int = MAX_SCRIPT_CHARS) -> str:
    """The script, shortened until it fits: to-do titles go first (the count stays), then
    job lines (from the end), then the weather tip, then the workout detail. The greeting
    and sign-off always stay."""
    jobs = sources.job_lines[:MAX_JOB_LINES]
    todos = sources.todo_lines
    with_tip, detail = True, True

    def render() -> str:
        parts = [greeting(today, sources.greeting_name)]
        if sources.weather:
            parts.append(sentence(sources.weather, sources.temperature_unit, with_tip))
        if sources.workout is not None:
            parts.append(workout_sentence(sources.workout, detail))
        if todos:
            parts.append(" ".join(todos))
        if jobs:
            parts.append(jobs_sentence(jobs))
        parts.append(SIGN_OFF)
        return " ".join(parts)

    script = render()
    if len(script) > limit and len(todos) > 1:
        todos = todos[:1]
        script = render()
    while len(script) > limit and jobs:
        jobs = jobs[:-1]
        script = render()
    if len(script) > limit and sources.weather:
        with_tip = False
        script = render()
    if len(script) > limit and sources.workout is not None:
        detail = False
        script = render()
    return script


def say_note(message: str) -> None:
    print(message, file=sys.stderr)


def gather(
    now: datetime,
    *,
    greeting_name: str = "",
    coordinates: tuple[float, float] | None = None,
    unit: str = "fahrenheit",
    network: bool = True,
    cache_dir: Path,
    secret: Callable[[str], str | None] = keychain_secret,
    fetch_fn: Callable[..., bytes] = fetch,
    lines: Callable[[date], dict[str, list[str]]] = module_lines,
    local: tzinfo | None = None,
    note: Callable[[str], None] = say_note,
) -> Sources:
    """Everything the script needs. A failed or missing source becomes a one-line note
    (never a URL or a body) and its section is left out. network=False reads local data
    only."""
    sources = Sources(greeting_name=greeting_name, temperature_unit=unit)
    try:
        by_module = lines(now.date())
        sources.todo_lines = by_module.get("todo", [])
        sources.job_lines = [
            line for name, ls in by_module.items() if name != "todo" for line in ls
        ]
    except RuntimeError as e:
        note(f"Job counts left out: {e}")
    if not network:
        return sources

    feed_url = secret(RUNNA_SERVICE)  # starts a process: before any guarded fetch
    if coordinates:
        try:
            sources.weather = weather_source.today(
                *coordinates, now=now, cache_dir=cache_dir, fetch_fn=fetch_fn
            )
        except FetchError as e:
            note(f"Weather left out: {e}")
        except (KeyError, IndexError, TypeError, ValueError):
            note("Weather left out: the weather service sent an answer this can't read")
    else:
        note("Weather left out: set weather_latitude and weather_longitude under [voice]")
    if feed_url:
        try:
            feed = fetch_fn(feed_url, "Runna feed").decode("utf-8", "replace")
            zone = local or datetime.now().astimezone().tzinfo
            sources.workout = todays_workout(feed, now.date(), zone) or REST
        except FetchError as e:
            note(f"Workout left out: {e}")
    else:
        note(f"Workout left out: no Runna feed address in the keychain ({RUNNA_SERVICE})")
    return sources
