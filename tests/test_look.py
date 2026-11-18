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


def test_text_links_have_a_visible_dotted_underline():
    from brain_dock.core.palette import CARD, MUTED, PAPER, contrast

    css = (STATIC_DIR / "app.css").read_text()
    link = re.search(r"(?m)^a \{([^}]*)\}", css).group(1)  # the rule for every link
    assert "underline dotted var(--muted)" in link
    assert re.search(r"--muted:\s*" + MUTED, css, re.I)
    assert contrast(MUTED, CARD) >= 4.5 and contrast(MUTED, PAPER) >= 4.5
    assert re.search(r"a:hover \{[^}]*text-decoration-style: solid", css)
