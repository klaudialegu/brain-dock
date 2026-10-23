"""Validation rules for application data, shared by everything that accepts it."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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


class ApplicationFields(BaseModel):
    """One application's own fields, with the rules every input path shares."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company: str = Field(min_length=1)
    role_title: str = Field(min_length=1)
    role_track: RoleTrack
    applied_on: date
    link: str | None = None
    notes: str | None = None
    follow_up_on: date | None = None

    @field_validator("link")
    @classmethod
    def http_link_only(cls, link: str | None) -> str | None:
        if link is not None and safe_link(link) is None:
            raise ValueError("must be an http:// or https:// URL")
        return link


class ApplicationIn(ApplicationFields):
    """An application in an import file or backup: its fields plus its stage events."""

    events: list[EventIn] = []

    @model_validator(mode="after")
    def events_not_before_applied(self) -> "ApplicationIn":
        for i, event in enumerate(self.events, start=1):
            if event.happened_on < self.applied_on:
                raise ValueError(f"events[{i}] happened_on is before applied_on")
        return self


class ApplicationsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applications: list[ApplicationIn]


class ApplicationForm(ApplicationFields):
    """What the add-application form posts. HTML sends "" for empty optional fields."""

    @field_validator("link", "notes", "follow_up_on", mode="before")
    @classmethod
    def blank_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class StageForm(EventIn):
    """What the record-stage form posts: same rules as an imported event."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("note", mode="before")
    @classmethod
    def blank_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


# Labels for form error messages, matching the form's own labels.
FIELD_LABELS = {
    "company": "Company",
    "role_title": "Role",
    "role_track": "Track",
    "applied_on": "Applied on",
    "link": "Job link",
    "notes": "Notes",
    "follow_up_on": "Follow-up",
    "stage": "Stage",
    "happened_on": "Date",
    "note": "Note",
}


def form_errors(error: ValidationError) -> dict[str, str]:
    """Map each form field to one message: its label and Pydantic's reason, never the input.
    Problems that aren't about a known field (like an unexpected extra field) go under "form",
    without naming the field, since the name came from the request."""
    errors: dict[str, str] = {}
    for err in error.errors():
        field = err["loc"][0] if err["loc"] else None
        if field in FIELD_LABELS and err["type"] != "extra_forbidden":
            reason = err["msg"].removeprefix("Value error, ")
            errors.setdefault(field, f"{FIELD_LABELS[field]}: {reason}")
        else:
            errors.setdefault("form", "The form contained something unexpected. Please try again.")
    return errors


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
