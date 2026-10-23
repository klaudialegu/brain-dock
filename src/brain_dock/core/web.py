"""What every module's routes use: the database session, submitted forms, and page rendering
(with the CSRF token and no caching for pages with personal data)."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from brain_dock.core.security import CSRF_FIELD, csrf_token, no_store, set_csrf_cookie


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


async def form_values(request: Request) -> dict[str, str]:
    """The submitted fields without the CSRF token, as strings only.

    Reading the body needs `await`, so it happens here, in an async dependency. The POST
    routes can then be plain `def`: FastAPI runs those in worker threads, so their
    synchronous database calls never block the event loop.
    """
    form = await request.form()
    return {k: v for k, v in form.items() if k != CSRF_FIELD and isinstance(v, str)}


FormValues = Annotated[dict[str, str], Depends(form_values)]


def render(
    request: Request, template: str, context: dict | None = None, status_code: int = 200
) -> HTMLResponse:
    """A page from this app's templates, never cached (pages can hold personal data)."""
    templates = request.app.state.templates
    response = templates.TemplateResponse(request, template, context or {}, status_code=status_code)
    return no_store(response)


def render_form(
    request: Request,
    template: str,
    values: dict,
    errors: dict | None = None,
    status_code: int = 200,
    **extra,
) -> HTMLResponse:
    """A page with a form: CSRF token (reused if the cookie has one), no caching."""
    token, is_new = csrf_token(request)
    context = {
        "values": values,
        "errors": errors or {},
        "csrf_field": CSRF_FIELD,
        "csrf_token": token,
        **extra,
    }
    response = render(request, template, context, status_code)
    if is_new:
        set_csrf_cookie(response, token)
    return response
