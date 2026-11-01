"""Job search pages: the list with stats and pipeline, add, edit and record a stage, and
saved jobs (save one, mark it applied)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlmodel import Session

from brain_dock.core.security import verify_csrf
from brain_dock.core.web import FormValues, SessionDep, render, render_form
from brain_dock.modules.job_search.charts import pipeline_chart_data, pipeline_summary
from brain_dock.modules.job_search.models import (
    Application,
    DateOrderError,
    add_stage,
    create_application,
    get_or_create_company,
    mark_applied,
    save_interested,
    update_application,
)
from brain_dock.modules.job_search.queries import (
    RESPONSE_MIN_AGE_DAYS,
    application_detail,
    company_detail,
    list_applications,
    list_saved_jobs,
    pipeline_links,
    safe_link,
    stats,
)
from brain_dock.modules.job_search.schemas import (
    ApplicationForm,
    MarkAppliedForm,
    SavedJobForm,
    StageForm,
    form_errors,
)
from brain_dock.modules.job_search.stages import recordable_stages, stage_css, stage_label

router = APIRouter()


@router.get("/stages.css")
def stages_css() -> Response:
    return Response(stage_css(), media_type="text/css")


def render_list(
    request: Request, session: Session, mark_errors: dict | None = None, status_code: int = 200
) -> HTMLResponse:
    links = pipeline_links(session)
    return render_form(
        request,
        "job_search/applications.html",
        {"applied_on": date.today().isoformat()},  # the mark-applied forms' default
        status_code=status_code,
        applications=list_applications(session),
        saved=list_saved_jobs(session),
        mark_errors=mark_errors or {},  # saved job id -> message
        stats=stats(session, date.today()),
        min_age=RESPONSE_MIN_AGE_DAYS,
        pipeline=pipeline_chart_data(links),
        pipeline_summary=pipeline_summary(links),
    )


@router.get("/applications", response_class=HTMLResponse)
def applications(request: Request, session: SessionDep) -> HTMLResponse:
    return render_list(request, session)


@router.get("/companies/{company_id}", response_class=HTMLResponse)
def company(request: Request, company_id: int, session: SessionDep) -> HTMLResponse:
    detail = company_detail(session, company_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Not found")
    return render(request, "job_search/company.html", {"company": detail})


@router.get("/applications/new", response_class=HTMLResponse)
def new_application(request: Request) -> HTMLResponse:
    return render_form(
        request, "job_search/application_form.html", {"applied_on": date.today().isoformat()}
    )


@router.post("/applications", dependencies=[Depends(verify_csrf)])
def add_application(request: Request, session: SessionDep, values: FormValues):
    try:
        entry = ApplicationForm.model_validate(values)
    except ValidationError as e:
        # Show the problems next to the fields; nothing about the input is logged.
        return render_form(request, "job_search/application_form.html", values, form_errors(e), 400)

    create_application(
        session,
        get_or_create_company(session, entry.company),
        entry.role_title,
        entry.role_track,
        entry.applied_on,
        link=entry.link,
        notes=entry.notes,
        follow_up_on=entry.follow_up_on,
    )
    session.commit()
    # Post/redirect/get: refreshing the list can't submit the form again.
    return RedirectResponse("/applications", status_code=303)


# --- Saved jobs (ADR 0009). Declared before /applications/{application_id}, so "saved"
# is never read as an id.

PREFILL_MAX = 200  # a prefill link carries short text only


@router.get("/applications/saved/new", response_class=HTMLResponse)
def new_saved_job(
    request: Request, company: str = "", role_title: str = "", link: str = ""
) -> HTMLResponse:
    """The save-a-job form. The inbox links here with company, role and link (ADR 0011);
    only those three prefill, and the link only if it's a plain http(s) URL."""
    values = {"interested_on": date.today().isoformat()}
    if company.strip():
        values["company"] = company.strip()[:PREFILL_MAX]
    if role_title.strip():
        values["role_title"] = role_title.strip()[:PREFILL_MAX]
    if len(link) <= PREFILL_MAX * 10 and safe_link(link.strip()):
        values["link"] = link.strip()
    return render_form(request, "job_search/saved_form.html", values)


@router.post("/applications/saved", dependencies=[Depends(verify_csrf)])
def save_job(request: Request, session: SessionDep, values: FormValues):
    try:
        entry = SavedJobForm.model_validate(values)
    except ValidationError as e:
        return render_form(request, "job_search/saved_form.html", values, form_errors(e), 400)
    save_interested(
        session,
        get_or_create_company(session, entry.company),
        entry.role_title,
        entry.role_track,
        entry.interested_on,
        link=entry.link,
        notes=entry.notes,
        follow_up_on=entry.follow_up_on,
    )
    session.commit()
    return RedirectResponse("/applications", status_code=303)


@router.post("/applications/{application_id}/applied", dependencies=[Depends(verify_csrf)])
def mark_saved_job_applied(
    request: Request, application_id: int, session: SessionDep, values: FormValues
):
    application = session.get(Application, application_id)
    if application is None or application.applied_on is not None:  # saved jobs only
        raise HTTPException(status_code=404, detail="Not found")
    try:
        entry = MarkAppliedForm.model_validate(values)
    except ValidationError:
        return render_list(request, session, {application_id: "Applied on: a date"}, 400)
    try:
        mark_applied(session, application, entry.applied_on)
    except DateOrderError:
        session.rollback()
        message = "Applied on: must be on or after the day it was saved"
        return render_list(request, session, {application_id: message}, 400)
    session.commit()
    return RedirectResponse("/applications", status_code=303)


def load_application(session: Session, application_id: int) -> Application:
    application = session.get(Application, application_id)
    # A job saved as interested has no edit page yet (it isn't an application).
    if application is None or application.applied_on is None:
        raise HTTPException(status_code=404, detail="Not found")
    return application


def render_edit(
    request: Request,
    session: Session,
    application_id: int,
    values: dict | None = None,
    errors: dict | None = None,
    status_code: int = 200,
    stage_values: dict | None = None,
    stage_errors: dict | None = None,
) -> HTMLResponse:
    detail = application_detail(session, application_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Not found")
    return render_form(
        request,
        "job_search/application_edit.html",
        values if values is not None else detail.values,
        errors,
        status_code,
        detail=detail,
        stage_options=[(s.value, stage_label(s)) for s in recordable_stages()],
        stage_values=stage_values or {"happened_on": date.today().isoformat()},
        stage_errors=stage_errors or {},
    )


@router.get("/applications/{application_id}/edit", response_class=HTMLResponse)
def edit_application(request: Request, application_id: int, session: SessionDep) -> HTMLResponse:
    return render_edit(request, session, application_id)


@router.post("/applications/{application_id}", dependencies=[Depends(verify_csrf)])
def save_application(
    request: Request, application_id: int, session: SessionDep, values: FormValues
):
    application = load_application(session, application_id)
    try:
        entry = ApplicationForm.model_validate(values)
    except ValidationError as e:
        return render_edit(request, session, application_id, values, form_errors(e), 400)
    try:
        update_application(
            session,
            application,
            company_name=entry.company,
            role_title=entry.role_title,
            role_track=entry.role_track,
            applied_on=entry.applied_on,
            link=entry.link,
            notes=entry.notes,
            follow_up_on=entry.follow_up_on,
        )
    except DateOrderError:
        session.rollback()
        errors = {"applied_on": "Applied on: must be on or before the first recorded stage"}
        return render_edit(request, session, application_id, values, errors, 400)
    session.commit()
    return RedirectResponse("/applications", status_code=303)


@router.post("/applications/{application_id}/stages", dependencies=[Depends(verify_csrf)])
def add_application_stage(
    request: Request, application_id: int, session: SessionDep, values: FormValues
):
    application = load_application(session, application_id)

    def refused(errors: dict) -> HTMLResponse:
        return render_edit(
            request,
            session,
            application_id,
            status_code=400,
            stage_values=values,
            stage_errors=errors,
        )

    try:
        entry = StageForm.model_validate(values)
    except ValidationError as e:
        return refused(form_errors(e))
    try:
        add_stage(session, application, entry.stage, entry.happened_on, entry.note)
    except DateOrderError:
        session.rollback()
        return refused({"happened_on": "Date: must be on or after the applied date"})
    session.commit()
    return RedirectResponse(f"/applications/{application_id}/edit", status_code=303)
