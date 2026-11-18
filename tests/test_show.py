"""The morning show's script (ADR 0014): order, spoken style, the cap, and what stays out."""

from datetime import date

from brain_dock.ics import Workout
from brain_dock.show import REST, SIGN_OFF, Sources, build_script, gather, greeting, ordinal
from brain_dock.voice import prepare_text
from brain_dock.weather import parse

from .show_fixtures import COORDS, FEED_URL, FORECAST, NOW, WEATHER_LINE, FakeNet

TODAY = NOW.date()  # Wednesday, November 18
JOBS = ["2 follow-ups are overdue.", "1 offer is open.", "3 inbox roles are waiting."]


def test_greeting_uses_the_configured_name_or_none():
    assert greeting(TODAY, "Avery") == "Good morning, Avery, it's Wednesday, November 18th."
    assert greeting(TODAY) == "Good morning, it's Wednesday, November 18th."
    assert build_script(TODAY, Sources(greeting_name="Avery")).startswith("Good morning, Avery,")


def test_greeting_says_the_day_and_an_ordinal_date():
    expected = {
        1: "1st",
        2: "2nd",
        3: "3rd",
        4: "4th",
        11: "11th",
        12: "12th",
        13: "13th",
        21: "21st",
        22: "22nd",
        23: "23rd",
        30: "30th",
        31: "31st",
    }
    assert {n: ordinal(n) for n in expected} == expected
    assert greeting(date(2026, 12, 1)) == "Good morning, it's Tuesday, December 1st."


def test_sections_come_in_order_and_read_like_speech():
    sources = Sources(
        greeting_name="Avery",
        weather=parse(FORECAST),
        workout=Workout("Easy Run", 40, "5 kilometers"),
        job_lines=JOBS,
    )

    assert build_script(TODAY, sources) == (
        "Good morning, Avery, it's Wednesday, November 18th. "
        f"{WEATHER_LINE} "
        "On the training plan today: Easy Run, 5 kilometers, about 40 minutes. "
        "On the job front... 2 follow-ups are overdue. 1 offer is open. "
        f"{SIGN_OFF}"
    )  # at most 2 job lines; no "Weather:" labels or lists read like a spreadsheet
    rest = build_script(TODAY, Sources(workout=REST))
    assert "No run on the plan today... it's a rest day." in rest


def test_missing_sources_are_skipped_quietly(tmp_path):
    assert build_script(TODAY, Sources()) == (
        f"Good morning, it's Wednesday, November 18th. {SIGN_OFF}"
    )
    net = FakeNet(feed_url=None)
    sources = gather(NOW, cache_dir=tmp_path, **net.options(lines=[]))  # no coordinates either

    assert build_script(TODAY, sources) == build_script(TODAY, Sources())
    assert net.fetched == []
    assert len(net.notes) == 2 and all("left out" in n for n in net.notes)  # stderr, not script

    def no_database(day):
        raise RuntimeError("No database yet. Run: uv run python -m brain_dock.db")

    offline = gather(
        NOW, cache_dir=tmp_path, network=False, **{**FakeNet().options(), "lines": no_database}
    )
    assert offline.job_lines == [] and offline.weather is None and offline.workout is None


def test_script_is_capped_by_dropping_the_least_needed_parts():
    full = Sources(
        greeting_name="Avery",
        weather=parse(FORECAST),
        workout=Workout("Tempo Run - 6 x 800m 5K pace w/ 90s", 55, "8 kilometers"),
        job_lines=JOBS,
    )
    script = build_script(TODAY, full)
    assert len(script) == 377  # the longest workout name still fits, with both job lines
    assert "1 offer is open." in script and "3 inbox roles" not in script  # 2 lines at most

    steps = [
        (360, ["1 offer"], ["2 follow-ups", "hood", "Tempo Run"]),  # job lines go from the end
        (340, ["follow-ups", "offer"], ["hood", "Tempo Run"]),
        (300, ["follow-ups", "hood"], ["Tempo Run"]),  # then the weather tip
        (280, ["follow-ups", "hood", "Tempo Run"], ["There's a run on the plan today."]),
    ]
    for limit, gone, kept in steps:
        short = build_script(TODAY, full, limit=limit)
        assert len(short) <= limit, (limit, len(short))
        assert all(word not in short for word in gone), (limit, short)
        assert all(word in short for word in kept), (limit, short)
        assert short.startswith("Good morning, Avery,") and short.endswith(SIGN_OFF)


def test_script_never_has_event_details_feed_urls_or_coordinates(tmp_path):
    net = FakeNet()
    sources = gather(
        NOW, greeting_name="Avery", coordinates=COORDS, cache_dir=tmp_path, **net.options()
    )

    script = prepare_text(build_script(TODAY, sources))

    assert "Easy Run" in script and "degrees" in script  # the sources were read
    for leak in [
        "note-qwfp",
        "knee",
        "Example Street",
        "easy pace",
        "Long Run",
        "feeds.example.test",
        "feed-secret-qwfp",
        FEED_URL,
        "12.3",
        "45.6",
        "45.7",
    ]:
        assert leak not in script, leak
