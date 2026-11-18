"""The daily brief as text (ADR 0013, ADR 0016): a greeting, then each module's lines.

In the core because the brief needs every shown module's lines, and only the core holds
them all (`app.state.modules`); a module importing the registry would break ADR 0007.
Modules add lines through their manifest's `brief`. Modules hidden in Settings add none.
"""

from collections.abc import Iterable
from datetime import date

from sqlmodel import Session

from brain_dock.core.layout import visible_modules
from brain_dock.core.modules import Manifest

# Text-to-speech is billed per character, so the brief has a hard cap.
MAX_BRIEF_CHARS = 600
CLOSING = "More in the app."
NOTHING = "Nothing needs your attention today."


def greeting(today: date) -> str:
    return f"Good morning. Here's your brief for {today:%A, %B} {today.day}."


def cap(lines: list[str], limit: int = MAX_BRIEF_CHARS) -> str:
    """Join the lines; past the cap, drop whole lines (never cut one) and say there's more."""
    text = " ".join(lines)
    if len(text) <= limit:
        return text
    kept: list[str] = []
    for line in lines:
        if len(" ".join([*kept, line, CLOSING])) > limit:
            break
        kept.append(line)
    return " ".join([*kept, CLOSING])


def lines_by_module(session: Session, today: date, modules: Iterable[Manifest]) -> dict:
    """Each shown module's lines for today, by module name, in order. Hidden modules (all
    their cards off in Settings) add nothing, so their counts never reach the spoken brief."""
    shown = visible_modules(session, list(modules))
    return {m.name: m.brief(session, today) for m in shown if m.brief}


def build_brief(session: Session, today: date, modules: Iterable[Manifest]) -> str:
    body = [line for lines in lines_by_module(session, today, modules).values() for line in lines]
    return cap([greeting(today), *(body or [NOTHING])])
