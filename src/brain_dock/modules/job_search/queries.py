from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlparse

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from brain_dock.modules.job_search.models import (
    Application,
    Company,
    RoleTrack,
    Stage,
    interested_event,
)
from brain_dock.modules.job_search.stages import INTERVIEW_STAGES, REPLY_STAGES, STAGES, stage_order


@dataclass(frozen=True)
class ApplicationRow:
    """What the list page shows: plain values, so templates never query the database."""

    id: int
    company_id: int
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


# Jobs saved as interested (applied_on is None) aren't applications yet, so the list,
# the company page and the stats leave them out (the pipeline chart: see pipeline_path).
APPLIED = Application.applied_on.is_not(None)


def list_applications(session: Session) -> list[ApplicationRow]:
    """All applications, newest applied first; same day, most recently added first."""
    applications = session.exec(
        select(Application)
        .where(APPLIED)
        .options(selectinload(Application.company))
        .order_by(Application.applied_on.desc(), Application.id.desc())
    ).all()
    return [
        ApplicationRow(
            id=a.id,
            company_id=a.company_id,
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
    if application is None or application.applied_on is None:
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


@dataclass(frozen=True)
class CompanyApplication:
    id: int
    role_title: str
    applied_on: date
    current_stage: Stage
    link: str | None  # only ever an http(s) URL, see safe_link()
    events: list[EventRow]  # the stage timeline, oldest first


@dataclass(frozen=True)
class SavedJobRow:
    """A job saved as interested (ADR 0009): not an application yet."""

    id: int
    company_id: int
    company: str
    role_title: str
    saved_on: date
    link: str | None  # only ever an http(s) URL, see safe_link()


def _saved_rows(applications) -> list[SavedJobRow]:
    rows = [
        SavedJobRow(
            id=a.id,
            company_id=a.company_id,
            company=a.company.name,
            role_title=a.role_title,
            saved_on=interested_event(a).happened_on,
            link=safe_link(a.link),
        )
        for a in applications
        if a.applied_on is None and interested_event(a) is not None
    ]
    return sorted(rows, key=lambda r: (r.saved_on, r.id), reverse=True)


def list_saved_jobs(session: Session) -> list[SavedJobRow]:
    """Jobs saved as interested, newest saved first."""
    saved = session.exec(
        select(Application)
        .where(Application.applied_on.is_(None))
        .options(selectinload(Application.company), selectinload(Application.events))
    ).all()
    return _saved_rows(saved)


@dataclass(frozen=True)
class CompanyDetail:
    """What the company page shows: its applications, newest first, each with its timeline,
    and its saved jobs, which aren't applications yet."""

    id: int
    name: str
    applications: list[CompanyApplication]
    saved: list[SavedJobRow]


def company_detail(session: Session, company_id: int) -> CompanyDetail | None:
    # Eager loads: three queries in total, however many applications the company has.
    company = session.exec(
        select(Company)
        .where(Company.id == company_id)
        .options(selectinload(Company.applications).selectinload(Application.events))
    ).first()
    if company is None:
        return None
    applications = sorted(
        (a for a in company.applications if a.applied_on is not None),
        key=lambda a: (a.applied_on, a.id),
        reverse=True,
    )
    return CompanyDetail(
        id=company.id,
        name=company.name,
        applications=[
            CompanyApplication(
                id=a.id,
                role_title=a.role_title,
                applied_on=a.applied_on,
                current_stage=a.current_stage,
                link=safe_link(a.link),
                # Same day: the order they were recorded in (ids), so the timeline is stable.
                events=[
                    EventRow(stage=e.stage, happened_on=e.happened_on, note=e.note)
                    for e in sorted(a.events, key=lambda e: (e.happened_on, e.id))
                ],
            )
            for a in applications
        ],
        saved=_saved_rows(company.applications),
    )


@dataclass(frozen=True)
class PipelineLink:
    source: Stage
    target: Stage
    count: int


def pipeline_path(application: Application) -> list[Stage]:
    """The application's way through the pipeline, for the Sankey chart.

    Starts at applied, then only ever moves forward in STAGES order (a chart can't draw
    loops, so repeated or backwards steps are left out), and ends with the outcome if the
    application has closed (rejected, ghosted, withdrawn). "Interested" comes before
    applied, so it never enters a path: a job saved first joins the chart at applied, and a
    job only saved adds no links.
    """
    path = [Stage.applied]
    for event in sorted(application.events, key=lambda e: (e.happened_on, e.id)):
        stage = event.stage
        if STAGES[stage].kind != "closed" and stage_order(stage) > stage_order(path[-1]):
            path.append(stage)
    outcome = application.current_stage
    if STAGES[outcome].kind == "closed" and path[-1] != outcome:
        path.append(outcome)
    return path


def pipeline_links(session: Session) -> list[PipelineLink]:
    """How many applications moved from each stage to the next, as plain values."""
    applications = session.exec(select(Application).options(selectinload(Application.events))).all()
    counts: Counter[tuple[Stage, Stage]] = Counter()
    for application in applications:
        path = pipeline_path(application)
        counts.update(zip(path, path[1:], strict=False))
    return [
        PipelineLink(source, target, n)
        for (source, target), n in sorted(
            counts.items(), key=lambda item: (stage_order(item[0][0]), stage_order(item[0][1]))
        )
    ]


# Applications younger than this haven't had a fair chance to get a reply or an interview
# yet, so they're left out of both rates (the page says so).
RESPONSE_MIN_AGE_DAYS = 14


@dataclass(frozen=True)
class Stats:
    total: int
    response_rate: float | None  # None when no application is old enough
    responded: int
    old_enough: int
    interview_rate: float | None  # None when no application is old enough
    interviewed: int
    days_since_last_application: int | None


def stats(session: Session, today: date) -> Stats:
    """The numbers above the list. `today` is passed in, so tests can pick any day."""
    applications = session.exec(
        select(Application).where(APPLIED).options(selectinload(Application.events))
    ).all()

    def reached(application: Application, stages: frozenset) -> bool:
        return any(e.stage in stages for e in application.events)

    cutoff = today - timedelta(days=RESPONSE_MIN_AGE_DAYS)
    old_enough = [a for a in applications if a.applied_on <= cutoff]
    responded = sum(reached(a, REPLY_STAGES) for a in old_enough)
    interviewed = sum(reached(a, INTERVIEW_STAGES) for a in old_enough)
    latest = max((a.applied_on for a in applications), default=None)

    return Stats(
        total=len(applications),
        response_rate=responded / len(old_enough) if old_enough else None,
        responded=responded,
        old_enough=len(old_enough),
        interview_rate=interviewed / len(old_enough) if old_enough else None,
        interviewed=interviewed,
        days_since_last_application=max(0, (today - latest).days) if latest else None,
    )
