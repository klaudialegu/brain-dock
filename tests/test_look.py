"""The look (ADR 0016): rules that every stylesheet keeps, checked in the CSS itself."""

import re

from brain_dock import registry
from brain_dock.main import STATIC_DIR

SHEETS = [STATIC_DIR / "app.css"] + [
    css for m in registry.installed() if m.static for css in sorted(m.static.glob("*.css"))
]


def rules(css: str):
    """(selector, body) pairs, comments removed; @font-face and @media bodies flattened."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def test_buttons_are_pills_in_every_stylesheet():
    checked = 0
    for sheet in SHEETS:
        for selector, body in rules(sheet.read_text()):
            classes = re.findall(r"\.(button(?:-quiet)?|play-brief)\b", selector)
            radius = re.search(r"border-radius:\s*([^;]+)", body)
            if classes and radius:
                checked += 1
                assert radius.group(1).strip() == "999px", f"{sheet.name}: {selector.strip()}"
    assert checked >= 2  # app.css really sets the pill radius for both button kinds
    assert len(SHEETS) >= 3  # module stylesheets are included in the check
