"""What the to-do forms post. Errors name the field, never what was typed."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from brain_dock.modules.todo.models import MINUTES_MAX, TITLE_MAX

FIELD_LABELS = {
    "title": "Title",
    "bucket": "When",
    "due_on": "Due date",
    "estimate_minutes": "Estimate",
    "ok_to_read_aloud": "Ok to read aloud",
    "minutes": "Minutes",
}


class _Form(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def blank_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class TaskForm(_Form):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    bucket: Literal["today", "can_wait"] = "today"
    due_on: date | None = None
    estimate_minutes: int | None = Field(default=None, ge=1, le=MINUTES_MAX)
    # A checkbox: present ("on") when ticked, missing when not. Missing means off.
    ok_to_read_aloud: bool = False

    @field_validator("ok_to_read_aloud", mode="before")
    @classmethod
    def checkbox(cls, value):
        return value == "on"

    @field_validator("bucket", mode="before")
    @classmethod
    def default_bucket(cls, value):
        return "today" if value is None else value


class StepForm(_Form):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    minutes: int | None = Field(default=None, ge=1, le=MINUTES_MAX)


def form_errors(error: ValidationError) -> dict[str, str]:
    """One message per field: its label and Pydantic's reason, never the input."""
    errors: dict[str, str] = {}
    for err in error.errors():
        field = err["loc"][0] if err["loc"] else None
        if field in FIELD_LABELS and err["type"] != "extra_forbidden":
            reason = err["msg"].removeprefix("Value error, ")
            errors.setdefault(str(field), f"{FIELD_LABELS[field]}: {reason}")
        else:
            errors.setdefault("form", "The form contained something unexpected. Please try again.")
    return errors
