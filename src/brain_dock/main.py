from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlmodel import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from brain_dock import db
from brain_dock.charts import pipeline_chart_data, pipeline_summary
from brain_dock.db import get_engine, is_at_head, is_demo_database
from brain_dock.models import (
    Application,
    DateOrderError,
    add_stage,
    create_application,
    get_or_create_company,
    update_application,
)
from brain_dock.queries import (
    RESPONSE_MIN_AGE_DAYS,
    application_detail,
    list_applications,
    pipeline_links,
    stats,
)
from brain_dock.schemas import ApplicationForm, StageForm, form_errors
from brain_dock.security import (
    ALLOWED_HOSTS,
    CSRF_FIELD,
    add_security_headers,
    csrf_token,
    no_store,
    set_csrf_cookie,
    verify_csrf,
)
from brain_dock.stages import recordable_stages, stage_css, stage_label

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


class DatabaseNotReadyError(RuntimeError):
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Never migrates on its own: changing the only copy of the data should be a choice.
    # Reads db.DB_PATH at startup time, so tests can point it at a temp file.
    if not db.DB_PATH.exists():
        raise DatabaseNotReadyError("No database yet. Run: uv run python -m brain_dock.db")
    engine = get_engine()
    if not is_at_head(engine):
        engine.dispose()
        raise DatabaseNotReadyError(
            "The database needs migrating. Run: uv run python -m brain_dock.db"
        )
    app.state.engine = engine
    # Shown as a banner, so fake demo data can't be mistaken for real data (or vice versa).
    app.state.is_demo = is_demo_database(db.DB_PATH)
    yield
    engine.dispose()


app = FastAPI(title="Brain Dock", lifespan=lifespan)
# Only answer to our own host names, so a site that points its domain at 127.0.0.1
# (DNS rebinding) can't talk to the app.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.middleware("http")(add_security_headers)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["stage_label"] = stage_label


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> PlainTextResponse:
    # FastAPI's default reply includes the submitted values; this one never does.
    return PlainTextResponse("Invalid request", status_code=422)


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@app.get("/stages.css")
def stages_css() -> Response:
    return Response(stage_css(), media_type="text/css")


@app.get("/")
def home() -> RedirectResponse:
    # The pipeline is the home page; one address for it keeps links and bookmarks simple.
    return RedirectResponse("/applications", status_code=303)


@app.get("/applications", response_class=HTMLResponse)
def applications(request: Request, session: SessionDep) -> HTMLResponse:
    links = pipeline_links(session)
    context = {
        "applications": list_applications(session),
        "stats": stats(session, date.today()),
        "min_age": RESPONSE_MIN_AGE_DAYS,
        "pipeline": pipeline_chart_data(links),
        "pipeline_summary": pipeline_summary(links),
    }
    return no_store(templates.TemplateResponse(request, "applications.html", context))


def render_form(
    request: Request,
    values: dict,
    errors: dict | None = None,
    status_code: int = 200,
    template: str = "application_form.html",
    **extra,
) -> HTMLResponse:
    """Render a page with a form: CSRF token (reused if the cookie has one), no caching."""
    token, is_new = csrf_token(request)
    context = {
        "values": values,
        "errors": errors or {},
        "csrf_field": CSRF_FIELD,
        "csrf_token": token,
        **extra,
    }
    response = templates.TemplateResponse(request, template, context, status_code=status_code)
    if is_new:
        set_csrf_cookie(response, token)
    return no_store(response)


@app.get("/applications/new", response_class=HTMLResponse)
def new_application(request: Request) -> HTMLResponse:
    return render_form(request, {"applied_on": date.today().isoformat()})


@app.post("/applications", dependencies=[Depends(verify_csrf)])
async def add_application(request: Request, session: SessionDep):
    values = form_values(await request.form())
    try:
        entry = ApplicationForm.model_validate(values)
    except ValidationError as e:
        # Show the problems next to the fields; nothing about the input is logged.
        return render_form(request, values, form_errors(e), status_code=400)

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


def form_values(form) -> dict[str, str]:
    """The submitted fields without the CSRF token, as strings only."""
    return {k: v for k, v in form.items() if k != CSRF_FIELD and isinstance(v, str)}


def load_application(session: Session, application_id: int) -> Application:
    application = session.get(Application, application_id)
    if application is None:
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
        values if values is not None else detail.values,
        errors,
        status_code,
        template="application_edit.html",
        detail=detail,
        stage_options=[(s.value, stage_label(s)) for s in recordable_stages()],
        stage_values=stage_values or {"happened_on": date.today().isoformat()},
        stage_errors=stage_errors or {},
    )


@app.get("/applications/{application_id}/edit", response_class=HTMLResponse)
def edit_application(request: Request, application_id: int, session: SessionDep) -> HTMLResponse:
    return render_edit(request, session, application_id)


@app.post("/applications/{application_id}", dependencies=[Depends(verify_csrf)])
async def save_application(request: Request, application_id: int, session: SessionDep):
    application = load_application(session, application_id)
    values = form_values(await request.form())
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


@app.post("/applications/{application_id}/stages", dependencies=[Depends(verify_csrf)])
async def add_application_stage(request: Request, application_id: int, session: SessionDep):
    application = load_application(session, application_id)
    values = form_values(await request.form())

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
