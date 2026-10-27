from datetime import date
from enum import StrEnum

from sqlmodel import Field, Relationship, Session, SQLModel, func, select


# Members are lowercase on purpose: SQLAlchemy stores an enum's member *name*,
# so lowercase names keep the database readable ("screen", not "SCREEN").
class Stage(StrEnum):
    interested = "interested"  # saved, not applied yet (applied_on is None)
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
    applied_on: date | None = None  # None: saved as interested, not applied yet
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


def company_key(name: str) -> str:
    """How company names are compared everywhere: ignoring case and surrounding spaces."""
    return name.strip().casefold()


def get_or_create_company(session: Session, name: str) -> Company:
    """Find a company by name (see company_key), or add it, trimmed."""
    key = company_key(name)
    for company in session.exec(select(Company)):
        if company_key(company.name) == key:
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


def save_interested(
    session: Session,
    company: Company,
    role_title: str,
    role_track: RoleTrack | str,
    interested_on: date,
    *,
    link: str | None = None,
    notes: str | None = None,
    follow_up_on: date | None = None,
) -> Application:
    """Save a job I'm considering, with its "interested" stage event. The caller commits.

    It isn't an application yet: applied_on stays None until mark_applied().
    """
    application = Application(
        company=company,
        role_title=role_title,
        role_track=RoleTrack(role_track),
        link=link,
        notes=notes,
        follow_up_on=follow_up_on,
    )
    session.add(application)
    record_stage(session, application, Stage.interested, interested_on)
    return application


def interested_event(application: Application) -> StageEvent | None:
    """The "interested" event save_interested() added, if the job was saved first."""
    saved = [e for e in application.events if e.stage == Stage.interested]
    return min(saved, key=lambda e: e.id) if saved else None


def mark_applied(session: Session, application: Application, applied_on: date) -> StageEvent:
    """Turn a saved job into an application. The caller commits."""
    if application.applied_on is not None:
        raise ValueError("already applied")
    saved = interested_event(application)
    if saved is not None and applied_on < saved.happened_on:
        raise DateOrderError("applied_on is before the interested date")
    application.applied_on = applied_on
    return record_stage(session, application, Stage.applied, applied_on)


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


class DateOrderError(ValueError):
    """A date would put an application's history out of order. Nothing was changed."""


class NotAppliedError(ValueError):
    """Only applications can be edited or move through stages; a saved job can't yet."""


def creation_event(application: Application) -> StageEvent | None:
    """The "applied" event create_application() added (the first one recorded)."""
    applied = [e for e in application.events if e.stage == Stage.applied]
    return min(applied, key=lambda e: e.id) if applied else None


def update_application(
    session: Session,
    application: Application,
    *,
    company_name: str,
    role_title: str,
    role_track: RoleTrack | str,
    applied_on: date,
    link: str | None,
    notes: str | None,
    follow_up_on: date | None,
) -> None:
    """Change an application's own fields. The caller commits.

    applied_on can't move past a later stage event, and the creation "applied" event moves
    with it. Renaming the company reuses an existing one (ignoring case and spaces); if the
    new name matches the current company, its spelling is updated instead.
    """
    if application.applied_on is None:
        raise NotAppliedError("not applied yet")
    creation = creation_event(application)
    saved = interested_event(application)
    later = [e.happened_on for e in application.events if e is not creation and e is not saved]
    if later and applied_on > min(later):
        raise DateOrderError("applied_on is after a recorded stage")
    if saved is not None and applied_on < saved.happened_on:
        raise DateOrderError("applied_on is before the interested date")

    old_company = application.company
    if company_key(old_company.name) == company_key(company_name):
        old_company.name = company_name.strip()  # same company: allow fixing its spelling
        new_company = old_company
    else:
        new_company = get_or_create_company(session, company_name)

    application.company = new_company
    application.role_title = role_title
    application.role_track = RoleTrack(role_track)
    application.applied_on = applied_on
    application.link = link
    application.notes = notes
    application.follow_up_on = follow_up_on
    if creation is not None:
        creation.happened_on = applied_on
    session.flush()

    # A company only exists to group applications, so one left with none is removed in the
    # same transaction. Revisit when companies get their own data (prep folders): then a
    # company may need to stay without applications. See ADR 0006.
    if new_company is not old_company:
        remaining = session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.company_id == old_company.id)
        )
        if remaining == 0:
            session.delete(old_company)
            session.flush()


def add_stage(
    session: Session,
    application: Application,
    stage: Stage | str,
    happened_on: date,
    note: str | None = None,
) -> StageEvent:
    """record_stage() for people: refuses a date before the application was sent."""
    if application.applied_on is None:
        raise NotAppliedError("not applied yet")
    if happened_on < application.applied_on:
        raise DateOrderError("happened_on is before applied_on")
    return record_stage(session, application, stage, happened_on, note)
