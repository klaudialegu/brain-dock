from datetime import date
from enum import StrEnum

from sqlmodel import Field, Relationship, Session, SQLModel, select


# Members are lowercase on purpose: SQLAlchemy stores an enum's member *name*,
# so lowercase names keep the database readable ("screen", not "SCREEN").
class Stage(StrEnum):
    applied = "applied"
    screen = "screen"
    interview = "interview"
    onsite = "onsite"
    offer = "offer"
    rejected = "rejected"
    ghosted = "ghosted"
    withdrawn = "withdrawn"


class RoleTrack(StrEnum):
    support = "support"
    fde = "fde"
    other = "other"


class Company(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)

    applications: list["Application"] = Relationship(back_populates="company")


class Application(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    role_title: str
    role_track: RoleTrack
    applied_on: date
    # Only record_stage() should change this; it always matches the latest StageEvent.
    current_stage: Stage = Stage.applied
    link: str | None = None
    notes: str | None = None
    follow_up_on: date | None = None

    company: Company | None = Relationship(back_populates="applications")
    events: list["StageEvent"] = Relationship(back_populates="application")


class StageEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application.id", index=True)
    stage: Stage
    happened_on: date
    note: str | None = None

    application: Application | None = Relationship(back_populates="events")


def get_or_create_company(session: Session, name: str) -> Company:
    """Find a company by name, ignoring case and surrounding spaces, or add it (trimmed)."""
    key = name.strip().casefold()
    for company in session.exec(select(Company)):
        if company.name.strip().casefold() == key:
            return company
    company = Company(name=name.strip())
    session.add(company)
    return company


def create_application(
    session: Session,
    company: Company,
    role_title: str,
    role_track: RoleTrack | str,
    applied_on: date,
    *,
    link: str | None = None,
    notes: str | None = None,
    follow_up_on: date | None = None,
) -> Application:
    """Create an application together with its "applied" stage event. The caller commits."""
    application = Application(
        company=company,
        role_title=role_title,
        role_track=RoleTrack(role_track),  # raises ValueError for an unknown track
        applied_on=applied_on,
        link=link,
        notes=notes,
        follow_up_on=follow_up_on,
    )
    session.add(application)
    record_stage(session, application, Stage.applied, applied_on)
    return application


def record_stage(
    session: Session,
    application: Application,
    stage: Stage | str,
    happened_on: date,
    note: str | None = None,
) -> StageEvent:
    """Add a stage event and set current_stage to the latest one. The caller commits.

    Latest means the latest date; on the same date, the most recently recorded event wins.
    So backfilling an older event never moves an application backwards.
    """
    event = StageEvent(
        application=application, stage=Stage(stage), happened_on=happened_on, note=note
    )
    session.add(event)
    session.flush()  # assigns ids, which give same-day events their recording order
    latest = max(application.events, key=lambda e: (e.happened_on, e.id))
    application.current_stage = latest.stage
    return event
