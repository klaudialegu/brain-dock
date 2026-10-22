from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from brain_dock.models import Application, RoleTrack, Stage


@dataclass(frozen=True)
class ApplicationRow:
    """What the list page shows: plain values, so templates never query the database."""

    id: int
    company: str
    role_title: str
    role_track: RoleTrack
    applied_on: date
    current_stage: Stage
    follow_up_on: date | None
    link: str | None  # only ever an http(s) URL, see safe_link()


def safe_link(url: str | None) -> str | None:
    """Return the URL if it's a plain http(s) link with a host, otherwise None.

    Keeps "javascript:", "data:" and similar URLs out of href attributes, even if
    they reach the database some other way than the importer.
    """
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        return url
    return None


def list_applications(session: Session) -> list[ApplicationRow]:
    """All applications, newest applied first; same day, most recently added first."""
    applications = session.exec(
        select(Application)
        .options(selectinload(Application.company))
        .order_by(Application.applied_on.desc(), Application.id.desc())
    ).all()
    return [
        ApplicationRow(
            id=a.id,
            company=a.company.name,
            role_title=a.role_title,
            role_track=a.role_track,
            applied_on=a.applied_on,
            current_stage=a.current_stage,
            follow_up_on=a.follow_up_on,
            link=safe_link(a.link),
        )
        for a in applications
    ]


@dataclass(frozen=True)
class EventRow:
    stage: Stage
    happened_on: date
    note: str | None


@dataclass(frozen=True)
class ApplicationDetail:
    """What the edit page shows: form values as strings, and the stage history."""

    id: int
    values: dict[str, str]
    current_stage: Stage
    events: list[EventRow]


def application_detail(session: Session, application_id: int) -> ApplicationDetail | None:
    application = session.get(Application, application_id)
    if application is None:
        return None
    values = {
        "company": application.company.name,
        "role_title": application.role_title,
        "role_track": application.role_track.value,
        "applied_on": application.applied_on.isoformat(),
        "link": application.link or "",
        "notes": application.notes or "",
        "follow_up_on": application.follow_up_on.isoformat() if application.follow_up_on else "",
    }
    events = [
        EventRow(stage=e.stage, happened_on=e.happened_on, note=e.note)
        for e in sorted(application.events, key=lambda e: (e.happened_on, e.id))
    ]
    return ApplicationDetail(
        id=application.id,
        values=values,
        current_stage=application.current_stage,
        events=events,
    )
