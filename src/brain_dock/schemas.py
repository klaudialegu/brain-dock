"""Validation rules for application data, shared by everything that accepts it."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brain_dock.models import RoleTrack, Stage
from brain_dock.queries import safe_link


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Stage
    happened_on: date
    note: str | None = None

    @field_validator("stage")
    @classmethod
    def not_applied(cls, stage: Stage) -> Stage:
        if stage == Stage.applied:
            raise ValueError('"applied" comes from applied_on; don\'t list it as an event')
        return stage


class ApplicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company: str = Field(min_length=1)
    role_title: str = Field(min_length=1)
    role_track: RoleTrack
    applied_on: date
    link: str | None = None
    notes: str | None = None
    follow_up_on: date | None = None
    events: list[EventIn] = []

    @field_validator("link")
    @classmethod
    def http_link_only(cls, link: str | None) -> str | None:
        if link is not None and safe_link(link) is None:
            raise ValueError("must be an http:// or https:// URL")
        return link

    @model_validator(mode="after")
    def events_not_before_applied(self) -> "ApplicationIn":
        for i, event in enumerate(self.events, start=1):
            if event.happened_on < self.applied_on:
                raise ValueError(f"events[{i}] happened_on is before applied_on")
        return self


class ApplicationsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applications: list[ApplicationIn]


def describe_error(error: dict) -> str:
    # Uses only the location and Pydantic's message, never error["input"],
    # so personal values from the file can't end up in the terminal.
    loc = list(error["loc"])
    parts = []
    if loc[:1] == ["applications"] and len(loc) > 1 and isinstance(loc[1], int):
        parts.append(f"entry {loc[1] + 1}")
        loc = loc[2:]
    field = ""
    for item in loc:
        field += f"[{item + 1}]" if isinstance(item, int) else f"{'.' if field else ''}{item}"
    if field:
        parts.append(field)
    reason = error["msg"].removeprefix("Value error, ")
    return f"{', '.join(parts) or 'file'}: {reason}"


def company_key(name: str) -> str:
    return name.strip().casefold()
