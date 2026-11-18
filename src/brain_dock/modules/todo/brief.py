"""The to-do lines for the daily brief and the morning show (ADR 0015).

A count of today's open tasks, then, only for tasks marked "ok to read aloud", their
titles: at most 2, cleaned and trimmed. The one exception to "the brief holds counts and
dates only" (ADR 0013), and only for tasks you mark.
"""

import re
from datetime import date

from sqlmodel import Session

from brain_dock.core.masking import scrub
from brain_dock.modules.todo.models import todays_open

MAX_TITLES = 2
TITLE_LIMIT = 40
UNSAFE = re.compile(r"[^\w .,:'&/+()\[\]-]+")  # \w keeps letters in any language


def spoken_title(title: str) -> str:
    """Masked first (an email or a "pwd=…" needs its "@" or "=" to be found), then
    cleaned, then trimmed to TITLE_LIMIT at a word boundary."""
    text = " ".join(UNSAFE.sub(" ", scrub(title)).replace("_", " ").split())
    if len(text) <= TITLE_LIMIT:
        return text
    head = text[: TITLE_LIMIT + 1]
    cut = head.rsplit(" ", 1)[0] if " " in head else ""
    return cut.rstrip(" .,:-/&+(") or text[:TITLE_LIMIT]


def brief_lines(session: Session, today: date) -> list[str]:
    tasks = todays_open(session, today)
    if not tasks:
        return []  # nothing for today: the show says nothing about to-dos
    things = "1 thing" if len(tasks) == 1 else f"{len(tasks)} things"
    lines = [f"On today's list: {things}."]
    named = [spoken_title(t.title) for t in tasks if t.ok_to_read_aloud]
    named = [title for title in named if title][:MAX_TITLES]
    if named:
        lines.append(f"First up: {', and '.join(named)}.")
    return lines
