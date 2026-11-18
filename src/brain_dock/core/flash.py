"""A one-time message for the next page (ADR 0018): "Removed: … · Undo · ×".

A route sets it on its redirect; the next page that renders reads it and clears it, so a
reload never repeats it. The cookie carries a kind and maybe an id, never any text: the
page looks the title up itself. Anything else in the cookie is ignored.
"""

import re

from fastapi import Request, Response

COOKIE = "bd_message"
VALUE = re.compile(r"[a-z_]{1,32}(?::[0-9]{1,12})?")
MAX_AGE = 120  # seconds: only ever meant for the very next page


def set_message(response: Response, kind: str, item_id: int | None = None) -> None:
    value = kind if item_id is None else f"{kind}:{item_id}"
    if not VALUE.fullmatch(value):
        raise ValueError("a message is a short kind and maybe an id")
    response.set_cookie(COOKIE, value, max_age=MAX_AGE, httponly=True, samesite="strict", path="/")


def read_message(request: Request) -> tuple[str, int | None] | None:
    """The waiting message as (kind, id), or None. Junk counts as no message."""
    value = request.cookies.get(COOKIE, "")
    if not VALUE.fullmatch(value):
        return None
    kind, _, item_id = value.partition(":")
    return kind, int(item_id) if item_id else None


def clear_message(request: Request, response: Response) -> None:
    """Called for every rendered page: whatever was waiting has now had its one showing."""
    if COOKIE in request.cookies:
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
