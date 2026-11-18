"""Today's workout from the Runna iCalendar feed (ADR 0014): today only, and the feed URL is
a secret."""

import inspect
import io
import logging
import urllib.error
from datetime import datetime

import pytest

from brain_dock import ics, outbound, voice
from brain_dock.core.agents.guard import guarded_run
from brain_dock.ics import Workout
from brain_dock.morning_brief import REST, RUNNA_SERVICE, build_script, gather

from .brief_fixtures import FEED_URL, LOCAL, NOW, RUNNA_FEED, FakeGuard, FakeNet, event, feed

TODAY = NOW.date()


def test_parses_only_todays_events():
    text = feed(
        event("Timed, New York", "DTSTART;TZID=America/New_York:20261118T090000"),
        event("Timed, UTC", "DTSTART:20261118T150000Z", "DTEND:20261118T153000Z"),
        event("All day", "DTSTART;VALUE=DATE:20261118", "DTEND;VALUE=DATE:20261119"),
        event("Two days", "DTSTART;VALUE=DATE:20261117", "DTEND;VALUE=DATE:20261119"),
        event("Yesterday", "DTSTART;VALUE=DATE:20261117"),
        event("Tomorrow", "DTSTART;TZID=America/Chicago:20261119T070000"),
        event("Late UTC is tomorrow here", "DTSTART:20261119T020000Z"),  # 8 pm the 18th
        event("Cancelled", "DTSTART;VALUE=DATE:20261118", extra="STATUS:CANCELLED"),
        event("Unknown zone", "DTSTART;TZID=Not/AZone:20261118T060000"),
        event("Bad time", "DTSTART:2026-11-18"),
    ).replace("SUMMARY:Timed, New York", "SUMMARY:Timed\\, New\r\n  York")  # a folded line

    events = ics.parse_events(text, LOCAL)
    today = [e.summary for e in events if ics.on_day(e, TODAY)]

    assert today == [
        "Timed, New York",
        "Timed, UTC",
        "All day",
        "Two days",
        "Late UTC is tomorrow here",
        "Unknown zone",
    ]
    new_york = events[0].start
    assert new_york == datetime(2026, 11, 18, 8, 0, tzinfo=LOCAL)  # 9 am Eastern, 8 here
    assert "Cancelled" not in [e.summary for e in events]
    assert "Bad time" not in [e.summary for e in events]


def test_workout_name_duration_and_distance():
    # Timed: the minutes come from its own times; the description's "5 km" is never read.
    assert ics.todays_workout(RUNNA_FEED, TODAY, LOCAL) == Workout("Easy Run", 40, None)

    def one(title, description="DESCRIPTION:5 min warm up\\, then 2 km easy\\, 10 min walk"):
        text = feed(event(title, "DTSTART;VALUE=DATE:20261118", extra=description))
        return ics.todays_workout(text, TODAY, LOCAL)

    assert one("Easy Run 30m") == Workout("Easy Run", 30, None)  # a duration at the end
    assert one("Easy Run 5km") == Workout("Easy Run", None, "5 kilometers")
    assert one("Long Run 1h 30m") == Workout("Long Run", 90, None)
    assert one("Long Run 2h") == Workout("Long Run", 120, None)
    assert one("Easy Run 5 km 30 min") == Workout("Easy Run", 30, "5 kilometers")
    assert one("Recovery 3.1 mi") == Workout("Recovery", None, "3.1 miles")
    assert one("Shakeout 1 mi") == Workout("Shakeout", None, "1 mile")
    assert one("Intervals 6 x 800m") == Workout("Intervals 6 x 800m", None, None)  # meters
    assert one("Tempo Run") == Workout("Tempo Run", None, None)  # description ignored
    assert one("28m") == Workout("Today's run", 28, None)


def test_long_workout_titles_are_trimmed(tmp_path):
    title = ("Tempo Run - 6 x 800m @ 5K pace w/ 90s recovery jog between reps 🏃‍♀️ " * 5)[:300]
    long_feed = feed(event(title, "DTSTART;VALUE=DATE:20261118"))

    workout = ics.todays_workout(long_feed, TODAY, LOCAL)

    assert len(workout.name) <= ics.NAME_LIMIT
    assert workout.name == "Tempo Run - 6 x 800m 5K pace w/ 90s"
    assert "🏃" not in workout.name and "@" not in workout.name
    word = "'".join(["abcdefghij"] * 6)  # one 65-character word, not key-shaped
    assert ics.clean_name(word) == word[:40]  # cut at 40, not 41
    net = FakeNet(runna=long_feed)
    script = build_script(TODAY, gather(NOW, cache_dir=tmp_path, **net.options()))
    assert workout.name in script


def test_rest_day_when_no_workout_today(tmp_path):
    net = FakeNet(runna=feed(event("Long Run", "DTSTART;VALUE=DATE:20261122")))

    sources = gather(NOW, cache_dir=tmp_path, **net.options())

    assert sources.workout == REST
    assert "No run on the plan today... it's a rest day." in build_script(TODAY, sources)


def test_feed_url_comes_from_the_keychain_and_never_shows(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    net = FakeNet()
    gather(NOW, cache_dir=tmp_path, **net.options())
    assert net.secrets == [RUNNA_SERVICE] == ["brain-dock-runna-ics"]
    assert (
        "webcal://feeds.example.test/calendar/abc123.ics?token=feed-secret-qwfp",
        "Runna feed",
    ) in net.fetched

    def failing_get(url, headers):
        raise urllib.error.HTTPError(url, 403, f"denied {url}", {}, io.BytesIO(url.encode()))

    def real_fetch(url, source, **kwargs):
        return outbound.fetch(url, source, get=failing_get, guard=FakeGuard())

    broken = FakeNet()
    options = {**broken.options(), "fetch_fn": real_fetch}
    sources = gather(NOW, cache_dir=tmp_path, **options)
    assert sources.workout is None
    assert broken.notes[-1] == "Workout left out: Runna feed: the service answered HTTP 403"
    with pytest.raises(outbound.FetchError) as raised:
        real_fetch(FEED_URL, "Runna feed")
    assert raised.value.__cause__ is None and raised.value.__context__ is None

    missing = FakeNet(feed_url=None)
    gather(NOW, cache_dir=tmp_path, **missing.options())
    assert missing.notes[-1] == (
        "Workout left out: no Runna feed address in the keychain (brain-dock-runna-ics)"
    )
    voice_on = tmp_path / "config.toml"
    voice_on.write_text('[voice]\nenabled = true\nvoice_id = "TestVoice123"\n')
    dry = FakeNet()
    voice.main(
        ["--dry-run"], config_path=voice_on, gather_options=dry.options(), cache_dir=tmp_path
    )
    assert dry.fetched and dry.secrets  # voice on: the feed really was read
    out = capsys.readouterr()
    seen = [out.out, out.err, caplog.text, str(raised.value), *broken.notes, *missing.notes]
    for text in seen:
        assert "feeds.example.test" not in text and "feed-secret-qwfp" not in text


def test_feed_fetch_runs_under_the_guard_with_only_its_host():
    guard, seen = FakeGuard(), []

    def get(url, headers):
        assert guard.inside, "fetched outside the network guard"
        seen.append(url)
        return b"BEGIN:VCALENDAR"

    outbound.fetch(FEED_URL, "Runna feed", get=get, guard=guard)

    assert guard.allow == [("feeds.example.test", 443)]
    assert inspect.signature(outbound.fetch).parameters["guard"].default is guarded_run
    assert inspect.signature(gather).parameters["fetch_fn"].default is outbound.fetch
    assert seen == ["https://feeds.example.test/calendar/abc123.ics?token=feed-secret-qwfp"]


def test_webcal_urls_are_fetched_over_https_only():
    assert outbound.https_url("webcal://a.example.test/x.ics", "Runna feed") == (
        "https://a.example.test/x.ics"
    )
    assert outbound.https_url(" HTTPS://a.example.test/x.ics#frag ", "f") == (
        "https://a.example.test/x.ics"
    )
    for bad in [
        "http://a.example.test/x.ics",
        "ftp://a.example.test/x",
        "webcal:///nohost",
        "a.example.test/x.ics",
        "file:///etc/passwd",
    ]:
        with pytest.raises(outbound.FetchError) as raised:
            outbound.https_url(bad, "Runna feed")
        assert str(raised.value) == "Runna feed: the address must be an https:// or webcal:// link"
        assert "example" not in str(raised.value)
