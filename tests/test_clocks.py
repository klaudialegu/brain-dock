from datetime import UTC, datetime
from pathlib import Path

import pytest

from brain_dock.clocks import DEFAULT_CITIES, load_cities, world_clocks


def by_city(now):
    return {clock.city: clock for clock in world_clocks(now)}


def test_cities_in_order_with_named_time_zones():
    clocks = world_clocks(datetime(2026, 10, 19, 18, 0, tzinfo=UTC))

    assert [(c.city, c.tz) for c in clocks] == [
        ("Seattle", "America/Los_Angeles"),
        ("Chicago", "America/Chicago"),
        ("New York", "America/New_York"),
        ("Warsaw", "Europe/Warsaw"),
    ]


def test_seattle_and_warsaw_are_9_hours_apart_in_summer_time():
    clocks = by_city(datetime(2026, 10, 19, 18, 0, tzinfo=UTC))

    assert clocks["Seattle"].time == "11:00"
    assert clocks["Warsaw"].time == "20:00"


def test_gap_shrinks_to_8_hours_after_europe_changes_clocks():
    # Europe leaves summer time on Oct 25, 2026; the US waits until Nov 1.
    clocks = by_city(datetime(2026, 10, 26, 18, 0, tzinfo=UTC))

    assert clocks["Seattle"].time == "11:00"
    assert clocks["Warsaw"].time == "19:00"


def test_no_day_shown_when_every_city_shares_seattles_date():
    clocks = world_clocks(datetime(2026, 10, 19, 18, 0, tzinfo=UTC))

    assert all(clock.day is None for clock in clocks)


def test_day_shown_only_for_cities_ahead_of_seattles_date():
    # 06:00 UTC on Tue Oct 20 is still Monday 23:00 in Seattle.
    clocks = by_city(datetime(2026, 10, 20, 6, 0, tzinfo=UTC))

    assert clocks["Seattle"].time == "23:00"
    assert clocks["Seattle"].day is None
    assert clocks["Chicago"].day == "Tue"
    assert clocks["New York"].day == "Tue"
    assert clocks["Warsaw"].day == "Tue"


def test_defaults_to_the_current_time():
    assert len(world_clocks()) == 4


def test_rejects_a_time_without_a_time_zone():
    with pytest.raises(ValueError):
        world_clocks(datetime(2026, 10, 19, 18, 0))


def test_uses_the_given_city_list_with_the_first_city_as_reference():
    cities = [("Tokyo", "Asia/Tokyo"), ("Seattle", "America/Los_Angeles")]
    # 06:00 UTC on Tue Oct 20 is 15:00 Tuesday in Tokyo, still Monday in Seattle.
    clocks = world_clocks(datetime(2026, 10, 20, 6, 0, tzinfo=UTC), cities)

    assert [(c.city, c.time, c.day) for c in clocks] == [
        ("Tokyo", "15:00", None),
        ("Seattle", "23:00", "Mon"),
    ]


def test_load_cities_falls_back_to_defaults_without_a_file(tmp_path):
    assert load_cities(tmp_path / "config.toml") == DEFAULT_CITIES


def test_load_cities_reads_the_file_in_order(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[[clocks]]\ncity = "Tokyo"\ntz = "Asia/Tokyo"\n\n'
        '[[clocks]]\ncity = "London"\ntz = "Europe/London"\n'
    )

    assert load_cities(path) == [("Tokyo", "Asia/Tokyo"), ("London", "Europe/London")]


def test_load_cities_rejects_an_unknown_time_zone(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[[clocks]]\ncity = "Warsaw"\ntz = "Europe/Warsw"\n')

    with pytest.raises(ValueError, match="Europe/Warsw"):
        load_cities(path)


def test_load_cities_rejects_a_file_without_clocks(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("# nothing here\n")

    with pytest.raises(ValueError, match="no \\[\\[clocks\\]\\]"):
        load_cities(path)


def test_load_cities_rejects_an_entry_missing_a_field(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[[clocks]]\ncity = "Warsaw"\n')

    with pytest.raises(ValueError, match="needs a city and a tz"):
        load_cities(path)


def test_example_config_matches_the_defaults():
    example = Path(__file__).parents[1] / "config.example.toml"

    assert load_cities(example) == DEFAULT_CITIES
