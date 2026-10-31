"""The inbox's local config (decisions 5 and 6): my thresholds live only in gitignored
config.toml. Missing or broken, the run refuses before anything is received; the example
file is never used in its place; errors name the key, never the value."""

import re

import pytest
from sqlalchemy import text

from brain_dock.core.db import REPO_ROOT
from brain_dock.modules.inbox.agent import run_inbox
from brain_dock.modules.inbox.config import ConfigError, load_config

from .inbox_support import (
    FAKE_CITY,
    FAKE_CONFIG,
    FAKE_FLOOR,
    all_fixtures,
    make_runner,
    migrate_app_db,
    write_config,
)


@pytest.fixture
def inbox_db():
    migrate_app_db()


def received_count(engine):
    with engine.connect() as connection:
        emails = connection.execute(text("SELECT count(*) FROM inbox_email")).scalar()
        items = connection.execute(text("SELECT count(*) FROM core_work_item")).scalar()
        runs = connection.execute(text("SELECT count(*) FROM core_agent_run")).scalar()
    return emails, items, runs


def test_missing_config_refuses_the_run_before_anything_is_received(inbox_db, tmp_path):
    runner, engine = make_runner(tmp_path)

    with pytest.raises(ConfigError, match="config.toml not found"):
        run_inbox(runner, all_fixtures(), config_path=tmp_path / "config.toml")

    assert received_count(engine) == (0, 0, 0)


@pytest.mark.parametrize(
    "broken, key",
    [
        pytest.param("[other]\nx = 1\n", "[inbox]", id="missing_section"),
        pytest.param(
            FAKE_CONFIG.replace('currency = "USD"\n', ""), "inbox.currency", id="missing_key"
        ),
        pytest.param(
            FAKE_CONFIG.replace("150000", "-5"), "inbox.salary_floor", id="negative_floor"
        ),
        pytest.param(
            FAKE_CONFIG.replace('"USD"', '"XXX"'), "inbox.currency", id="unknown_currency"
        ),
        pytest.param(
            FAKE_CONFIG.replace('["remote", "Example City"]', "[]"),
            "inbox.locations",
            id="empty_locations",
        ),
        pytest.param(
            FAKE_CONFIG.replace('"staff"', '"wizard"'), "inbox.seniority", id="unknown_seniority"
        ),
    ],
)
def test_incomplete_or_invalid_config_refuses_the_run(inbox_db, tmp_path, broken, key):
    runner, engine = make_runner(tmp_path)
    path = write_config(tmp_path, broken)

    with pytest.raises(ConfigError, match=re.escape(key)):
        run_inbox(runner, all_fixtures(), config_path=path)

    assert received_count(engine) == (0, 0, 0)


def test_never_falls_back_to_the_example_file(tmp_path):
    example = REPO_ROOT / "config.example.toml"
    assert example.is_file()  # there is an example it could wrongly fall back to
    (tmp_path / "config.example.toml").write_text(example.read_text())

    with pytest.raises(ConfigError):
        load_config(tmp_path / "config.toml")


def test_config_errors_name_the_key_never_the_value(tmp_path):
    messages = []
    for broken in (
        FAKE_CONFIG.replace("150000", "-150000"),
        FAKE_CONFIG.replace('"USD"', f'"{FAKE_CITY}"'),
        FAKE_CONFIG.replace('"staff"', f'"{FAKE_FLOOR}"'),
        FAKE_CONFIG.replace("salary_floor = 150000", f'salary_floor = "{FAKE_CITY}"'),
        FAKE_CONFIG + f"{FAKE_CITY} = = broken\n",
    ):
        with pytest.raises(ConfigError) as caught:
            load_config(write_config(tmp_path, broken))
        messages.append(str(caught.value))
        assert caught.value.__cause__ is None  # no parser excerpt riding along

    assert len(messages) == 5
    for message in messages:
        assert FAKE_CITY not in message and FAKE_FLOOR not in message, message
    assert repr(load_config(write_config(tmp_path))) == "InboxConfig(<hidden>)"


def test_the_example_config_is_complete_and_valid():
    config = load_config(REPO_ROOT / "config.example.toml")

    assert config.locations and config.seniority and config.salary_floor > 0
