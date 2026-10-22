"""Protection for form posts on a localhost app (ADR 0005).

Any website open in the same browser can send a form to http://127.0.0.1, so every
POST must prove it came from Brain Dock's own pages:
- a CSRF token in the form that matches the token in a SameSite=Strict cookie,
- an Origin (or, failing that, Referer) of this app on its own port,
- and no "Sec-Fetch-Site: cross-site".
Host names are limited separately with TrustedHostMiddleware (DNS rebinding).
"""

import re
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import Response

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_COOKIE = "csrf_token"
CSRF_FIELD = "csrf_token"
_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{43}$")  # secrets.token_urlsafe(32)


def csrf_token(request: Request) -> tuple[str, bool]:
    """The token to put in a form, and whether it's new (needs setting as a cookie).
    Reuses a well-formed existing cookie, so two open tabs don't invalidate each other."""
    existing = request.cookies.get(CSRF_COOKIE, "")
    if _TOKEN_SHAPE.match(existing):
        return existing, False
    return secrets.token_urlsafe(32), True


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="strict", path="/")


def no_store(response: Response) -> Response:
    """Pages with personal data shouldn't be kept in the browser cache."""
    response.headers["Cache-Control"] = "no-store"
    return response


def _allowed_origins(request: Request) -> set[str]:
    port = request.url.port
    suffix = f":{port}" if port else ""
    return {f"http://{host}{suffix}" for host in ALLOWED_HOSTS}


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _forbidden() -> HTTPException:
    # No details: the reason stays on the server side of the decision.
    return HTTPException(status_code=403, detail="Forbidden")


async def verify_csrf(request: Request) -> None:
    """FastAPI dependency for every POST route. Raises 403 unless the request is ours."""
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise _forbidden()

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if origin is not None:
        if origin not in _allowed_origins(request):
            raise _forbidden()
    elif referer:
        if _origin_of(referer) not in _allowed_origins(request):
            raise _forbidden()
    else:
        raise _forbidden()

    form = await request.form()
    sent = form.get(CSRF_FIELD)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not isinstance(sent, str) or not cookie or not secrets.compare_digest(sent, cookie):
        raise _forbidden()
