from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from brain_dock.models import Application, RoleTrack, Stage


@dataclass(frozen=True)
class ApplicationRow:
    """What the list page shows: plain values, so templates never query the database."""

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
