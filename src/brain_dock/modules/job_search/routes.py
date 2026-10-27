"""Job search pages: the list with stats and pipeline, add, edit and record a stage."""

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
    update_application,
)
from brain_dock.modules.job_search.queries import (
    RESPONSE_MIN_AGE_DAYS,
    application_detail,
    company_detail,
    list_applications,
    pipeline_links,
    stats,
)
from brain_dock.modules.job_search.schemas import ApplicationForm, StageForm, form_errors
from brain_dock.modules.job_search.stages import recordable_stages, stage_css, stage_label

router = APIRouter()


@router.get("/stages.css")
def stages_css() -> Response:
    return Response(stage_css(), media_type="text/css")


@router.get("/applications", response_class=HTMLResponse)
def applications(request: Request, session: SessionDep) -> HTMLResponse:
    links = pipeline_links(session)
    context = {
        "applications": list_applications(session),
        "stats": stats(session, date.today()),
        "min_age": RESPONSE_MIN_AGE_DAYS,
        "pipeline": pipeline_chart_data(links),
        "pipeline_summary": pipeline_summary(links),
    }
    return render(request, "job_search/applications.html", context)


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
