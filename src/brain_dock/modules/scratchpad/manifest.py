"""Scratchpad: module #4 (ADR 0007, ADR 0017)."""

from pathlib import Path

from brain_dock.core.modules import Manifest, NavEntry
from brain_dock.modules.scratchpad.card import CARD
from brain_dock.modules.scratchpad.routes import router

MODULE_DIR = Path(__file__).parent

manifest = Manifest(
    name="scratchpad",
    description="Quick notes on paper, by day; typing now, room for drawing later.",
    home="/scratchpad",
    router=router,
    paths=("/scratchpad",),
    nav=(NavEntry("Scratchpad", "/scratchpad"),),
    tables=("scratchpad_page", "scratchpad_layer"),
    migrations=MODULE_DIR / "migrations",
    templates=MODULE_DIR / "templates",
    static=MODULE_DIR / "static",
    stylesheets=("/static/modules/scratchpad/scratchpad.css",),
    permissions=("storage",),
    label="Scratchpad",
    color="butter",
    icon="M5 19l1-4L16 5l3 3L9 18zM14 7l3 3M5 19h4",
    cards=(CARD,),
    capture="/scratchpad/capture",
)
