"""The dock: builds the web app from the core plus the enabled modules (ADR 0007)."""

from contextlib import asynccontextmanager
from pathlib import Path

import jinja2
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from brain_dock.core import db
from brain_dock.core.db import get_engine, is_at_head, is_demo_database
from brain_dock.core.modules import Manifest
from brain_dock.core.security import ALLOWED_HOSTS, CONTENT_SECURITY_POLICY, add_security_headers
from brain_dock.core.web import render

TEMPLATES_DIR = Path(__file__).parents[1] / "templates"
STATIC_DIR = Path(__file__).parents[1] / "static"


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


# What each error page says. Fixed text only: never the path, the input, or the exception,
# so an error page can't echo personal data or internals.
ERROR_PAGES = {
    403: (
        "That form wasn't accepted",
        "Forms only work from Brain Dock's own pages. Reload the page and try again.",
    ),
    404: ("Page not found", "There's nothing at this address."),
    405: ("That action isn't available here", "This address doesn't accept that kind of request."),
    422: (
        "That request didn't make sense",
        "Part of the address or form wasn't in the expected format.",
    ),
    500: (
        "Something went wrong",
        "The app hit an unexpected error. The details are only in the server's terminal, "
        "on purpose.",
    ),
}


def render_error(request: Request, status_code: int, headers: dict | None = None) -> HTMLResponse:
    title, message = ERROR_PAGES.get(status_code, ERROR_PAGES[500])
    response = request.app.state.templates.TemplateResponse(
        request,
        "error.html",
        {"title": title, "message": message},
        status_code=status_code,
        headers=headers,
    )
    # The 500 handler runs outside the security-headers middleware, so set the CSP here too.
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    return response


async def http_error(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    # Keeps headers like Allow (for 405); ignores exc.detail, which can carry details.
    return render_error(request, exc.status_code, getattr(exc, "headers", None))


async def invalid_request(request: Request, exc: RequestValidationError) -> HTMLResponse:
    # FastAPI's default reply includes the submitted values; this one never does.
    return render_error(request, 422)


async def server_error(request: Request, exc: Exception) -> HTMLResponse:
    # The traceback still goes to the server's terminal; the page shows none of it.
    return render_error(request, 500)


def build_templates(modules: list[Manifest]) -> Jinja2Templates:
    """Core templates by plain name ("base.html"); each module's as "<name>/<file>"."""
    loader = jinja2.ChoiceLoader(
        [
            jinja2.FileSystemLoader(TEMPLATES_DIR),
            jinja2.PrefixLoader({m.name: jinja2.FileSystemLoader(m.templates) for m in modules}),
        ]
    )
    templates = Jinja2Templates(env=jinja2.Environment(loader=loader, autoescape=True))
    templates.env.globals["nav"] = [entry for m in modules for entry in m.nav]
    templates.env.globals["home_path"] = modules[0].home if modules else "/"
    templates.env.globals["stylesheets"] = [href for m in modules for href in m.stylesheets]
    for m in modules:
        templates.env.globals.update(m.template_globals)
    return templates


def api_routes(app: FastAPI) -> list[APIRoute]:
    """Every route the app serves: its own, plus each enabled module's. Included routers
    are nested inside app.routes, so checks over "all routes" must use this, or they'd
    quietly check only the top level."""
    own = [r for r in app.routes if isinstance(r, APIRoute)]
    return own + [r for m in app.state.modules for r in m.router.routes if isinstance(r, APIRoute)]


def create_app(modules: list[Manifest]) -> FastAPI:
    """The app with these modules enabled. Disabling a module only leaves it out here:
    its data and migrations are untouched (ADR 0007, rule 3)."""
    app = FastAPI(title="Brain Dock", lifespan=lifespan)
    # Only answer to our own host names, so a site that points its domain at 127.0.0.1
    # (DNS rebinding) can't talk to the app.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    app.middleware("http")(add_security_headers)
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.add_exception_handler(Exception, server_error)

    app.state.modules = modules
    app.state.templates = build_templates(modules)

    # Module static files first: the core mount at /static would otherwise catch them.
    for m in modules:
        if m.static is not None:
            app.mount(f"/static/modules/{m.name}", StaticFiles(directory=m.static))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    for m in modules:
        app.include_router(m.router)

    @app.get("/", response_model=None)
    def home(request: Request) -> RedirectResponse | HTMLResponse:
        # The first enabled module's page is the home page; one address keeps links simple.
        if modules:
            return RedirectResponse(modules[0].home, status_code=303)
        return render(request, "home.html")

    return app
