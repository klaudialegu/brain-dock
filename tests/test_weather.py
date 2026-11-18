"""Today's weather for the morning show (ADR 0014): rounded coordinates out, numbers back."""

import http.client
import inspect
import json
import os
import stat
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from brain_dock import outbound, weather
from brain_dock.core.agents.guard import guarded_run
from brain_dock.show import build_script, gather
from brain_dock.weather import Weather

from .show_fixtures import COORDS, FORECAST, NOW, WEATHER_LINE, FakeGuard, FakeNet


def test_weather_request_sends_only_rounded_coordinates_and_units(tmp_path):
    url = weather.request_url(*COORDS)
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}

    assert (parts.scheme, parts.hostname, parts.path) == (
        "https",
        "api.open-meteo.com",
        "/v1/forecast",
    )
    assert query == {
        "latitude": "12.3",
        "longitude": "-45.7",
        "current": "temperature_2m,precipitation",
        "hourly": "precipitation_probability",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
        "forecast_days": "1",
    }
    net = FakeNet()
    gather(NOW, coordinates=COORDS, cache_dir=tmp_path, **net.options())
    [(sent, source)] = [f for f in net.fetched if "open-meteo" in f[0]]
    assert sent == url and source == "weather service"
    assert "12.3456" not in sent and "45.6789" not in sent


def test_weather_sentence_has_now_high_low_and_rain_chance():
    w = weather.parse(FORECAST)

    assert w == Weather(now=46.2, high=52.4, low=40.6, rain=70, rain_morning=70, rain_later=30)
    assert weather.sentence(w) == WEATHER_LINE
    assert weather.sentence(w, "celsius") == (
        "Right now it's 8 degrees, heading for 11, with a low of 5. "
        "There's a 70 percent chance of rain, so grab a hood before noon."
    )
    for rain, said in [
        (88, "an 88"),
        (80, "an 80"),
        (70, "a 70"),
        (21, "a 21"),
    ]:
        wet = Weather(now=50, high=55, low=45, rain=rain, rain_morning=0, rain_later=0)
        assert f"There's {said} percent chance of rain" in weather.sentence(wet)
    dry = Weather(now=70, high=75, low=60, rain=10, rain_morning=5, rain_later=10)
    assert weather.sentence(dry, with_tip=False) == (
        "Right now it's 70 degrees, heading for 75, with a low of 60. It should stay dry."
    )


def test_weather_tips_follow_the_rules():
    def w(high=60, morning=0, later=0):
        return Weather(
            now=high,
            high=high,
            low=high - 10,
            rain=max(morning, later),
            rain_morning=morning,
            rain_later=later,
        )

    assert weather.tip(w(morning=50, later=90)) == "grab a hood before noon"  # first match
    assert weather.tip(w(later=60)) == "keep a hood handy for the afternoon"
    assert weather.tip(w(high=40)) == "bundle up"
    assert weather.tip(w(high=85)) == "bring water"
    assert weather.tip(w(high=60, morning=49)) == "a nice one for a walk"
    # Celsius changes only the spoken numbers: 60°F (16°C) is still a walk, not "bundle up"
    assert weather.sentence(w(high=60), "celsius").endswith("so a nice one for a walk.")
    assert weather.sentence(w(high=30), "celsius").endswith("so bundle up.")


def test_weather_is_cached_for_the_morning(tmp_path):
    calls = []

    def fetch_fn(url, source):
        calls.append(url)
        return json.dumps(FORECAST).encode()

    old_umask = os.umask(0o022)
    try:
        first = weather.today(*COORDS, now=NOW, cache_dir=tmp_path, fetch_fn=fetch_fn)
        again = weather.today(
            *COORDS, now=NOW.replace(hour=11, minute=59), cache_dir=tmp_path, fetch_fn=fetch_fn
        )
        weather.today(*COORDS, now=NOW.replace(hour=13), cache_dir=tmp_path, fetch_fn=fetch_fn)
        weather.today(*COORDS, now=NOW + timedelta(days=1), cache_dir=tmp_path, fetch_fn=fetch_fn)
    finally:
        os.umask(old_umask)

    assert first == again
    assert len(calls) == 3  # 7:30 fetched, 11:59 from the cache, 13:00 and tomorrow fetched
    [kept] = list(tmp_path.glob("weather-*.json"))
    assert kept.name == "weather-2026-11-19-am.json"  # only the current forecast is kept
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert "12.3" not in kept.read_text()  # numbers about the weather only


def test_weather_failure_skips_the_section_without_details(tmp_path):
    down = FakeNet(fail=("weather", outbound.FetchError("Couldn't reach the weather service")))
    odd = FakeNet(forecast={"current": {}})
    cut_off = FakeNet()  # a truncated answer: an http.client error, not an OSError

    def truncated(url, headers):
        raise http.client.IncompleteRead(b"{", 500)

    cut_off.fetch = lambda url, source, **k: outbound.fetch(
        url, source, get=truncated, guard=FakeGuard()
    )

    for net, why in [
        (down, "Couldn't reach the weather service"),
        (odd, "an answer this can't read"),
        (cut_off, "Couldn't reach the weather service"),
    ]:
        sources = gather(NOW, coordinates=COORDS, cache_dir=tmp_path / why[:5], **net.options())
        assert sources.weather is None
        assert any(n.startswith("Weather left out:") and why in n for n in net.notes)
        assert all("open-meteo" not in n and "12.3" not in n for n in net.notes)
        assert "degrees" not in build_script(NOW.date(), sources)


def test_weather_fetch_runs_under_the_guard_with_only_open_meteo():
    guard, seen = FakeGuard(), []

    def get(url, headers):
        assert guard.inside, "fetched outside the network guard"
        seen.append(url)
        return b"{}"

    outbound.fetch(weather.request_url(*COORDS), weather.SOURCE, get=get, guard=guard)

    assert guard.allow == [("api.open-meteo.com", 443)]
    assert seen == [weather.request_url(*COORDS)]
    # and the real code uses the real guard: no default may quietly skip it
    assert inspect.signature(outbound.fetch).parameters["guard"].default is guarded_run
    assert inspect.signature(weather.today).parameters["fetch_fn"].default is outbound.fetch
    assert inspect.signature(gather).parameters["fetch_fn"].default is outbound.fetch
