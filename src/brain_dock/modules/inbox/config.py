"""My rule thresholds, from the gitignored config.toml ([inbox]). Personal values: they never
reach the database, the audit log, the flight recorder, logs or any API, and error messages
name the key, never the value. A missing or broken config fails closed: no run starts, and
config.example.toml is never used in its place."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from brain_dock.core.db import REPO_ROOT
from brain_dock.modules.inbox.parser import LEVELS
from brain_dock.modules.inbox.roles import normalize_text

DEFAULT_PATH = REPO_ROOT / "config.toml"
CURRENCIES = frozenset(
    {"USD", "EUR", "GBP", "CAD", "AUD", "CHF", "PLN", "SEK", "NOK", "DKK", "JPY"}
)
KEYS = ("locations", "seniority", "salary_floor", "currency")


class ConfigError(RuntimeError):
    """The inbox can't run: config.toml is missing or its [inbox] section isn't valid."""


@dataclass(frozen=True, repr=False)  # no repr: the values must not end up in a log line
class InboxConfig:
    locations: frozenset[str]  # normalized; "remote" means remote roles are fine
    seniority: frozenset[str]
    salary_floor: int  # yearly, in `currency`
    currency: str

    def __repr__(self) -> str:
        return "InboxConfig(<hidden>)"


def _strings(section: dict, key: str) -> list[str]:
    value = section[key]
    if not isinstance(value, list) or not value:
        raise ConfigError(f"inbox.{key} must be a non-empty list")
    if not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"inbox.{key} must hold only non-empty text")
    return value


def load_config(path: Path = DEFAULT_PATH) -> InboxConfig:
    if not path.is_file():
        raise ConfigError(
            f"{path.name} not found: copy config.example.toml to config.toml and fill in [inbox]"
        )
    try:
        raw = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        raise ConfigError(f"{path.name} isn't valid TOML") from None  # no excerpt of it
    section = raw.get("inbox")
    if not isinstance(section, dict):
        raise ConfigError(f"{path.name} has no [inbox] section")
    for key in KEYS:
        if key not in section:
            raise ConfigError(f"inbox.{key} is missing")

    locations = _strings(section, "locations")
    seniority = [normalize_text(s) for s in _strings(section, "seniority")]
    if not set(seniority) <= set(LEVELS):
        raise ConfigError(f"inbox.seniority has an unknown level (known: {', '.join(LEVELS)})")
    floor = section["salary_floor"]
    if isinstance(floor, bool) or not isinstance(floor, int) or floor <= 0:
        raise ConfigError("inbox.salary_floor must be a positive whole number")
    currency = section["currency"]
    if currency not in CURRENCIES:
        raise ConfigError("inbox.currency must be a known 3-letter code, like USD")

    return InboxConfig(
        locations=frozenset(normalize_text(v) for v in locations),
        seniority=frozenset(seniority),
        salary_floor=floor,
        currency=currency,
    )
