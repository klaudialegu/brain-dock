from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlmodel import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from brain_dock import db
from brain_dock.clocks import load_cities, world_clocks
from brain_dock.db import get_engine, is_at_head
from brain_dock.models import RoleTrack, create_application, get_or_create_company
from brain_dock.queries import list_applications
from brain_dock.schemas import ApplicationForm, form_errors
from brain_dock.security import (
    ALLOWED_HOSTS,
    CSRF_FIELD,
    add_security_headers,
    csrf_token,
    no_store,
    set_csrf_cookie,
    verify_csrf,
)
from brain_dock.stages import stage_css, stage_label

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
# Local, gitignored settings at the repo root. See config.example.toml for the format.
CONFIG_PATH = Path(__file__).parents[2] / "config.toml"


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


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    cities = load_cities(CONFIG_PATH)
    context = {"clocks": world_clocks(cities=cities), "reference_tz": cities[0][1]}
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/applications", response_class=HTMLResponse)
def applications(request: Request, session: SessionDep) -> HTMLResponse:
    context = {"applications": list_applications(session)}
    return no_store(templates.TemplateResponse(request, "applications.html", context))


def render_form(
    request: Request, values: dict, errors: dict | None = None, status_code: int = 200
) -> HTMLResponse:
    token, is_new = csrf_token(request)
    context = {
        "values": values,
        "errors": errors or {},
        "tracks": list(RoleTrack),
        "csrf_field": CSRF_FIELD,
        "csrf_token": token,
    }
    response = templates.TemplateResponse(
        request, "application_form.html", context, status_code=status_code
    )
    if is_new:
        set_csrf_cookie(response, token)
    return no_store(response)


@app.get("/applications/new", response_class=HTMLResponse)
def new_application(request: Request) -> HTMLResponse:
    return render_form(request, {"applied_on": date.today().isoformat()})


@app.post("/applications", dependencies=[Depends(verify_csrf)])
async def add_application(request: Request, session: SessionDep):
    form = await request.form()
    values = {k: v for k, v in form.items() if k != CSRF_FIELD}
    try:
        entry = ApplicationForm.model_validate(values)
    except ValidationError as e:
        # Show the problems next to the fields; nothing about the input is logged.
        shown = {k: v for k, v in values.items() if isinstance(v, str)}
        return render_form(request, shown, form_errors(e), status_code=400)

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
