"""Job search: module #1 (ADR 0007)."""

from pathlib import Path

from brain_dock.core.modules import Manifest, NavEntry
from brain_dock.modules.job_search.brief import brief_lines
from brain_dock.modules.job_search.card import CARD
from brain_dock.modules.job_search.routes import router
from brain_dock.modules.job_search.stages import stage_label

MODULE_DIR = Path(__file__).parent
TABLES = ("company", "application", "stageevent")

manifest = Manifest(
    name="job_search",
    description="Career Radar: applications, saved roles, stages, the pipeline chart and stats.",
    home="/applications",
    router=router,
    paths=("/applications", "/companies", "/stages.css"),
    nav=(
        NavEntry("Career Radar", "/applications"),
        NavEntry("Add application", "/applications/new"),
        NavEntry("Save a job", "/applications/saved/new"),
    ),
    tables=TABLES,
    migrations=MODULE_DIR / "migrations",
    templates=MODULE_DIR / "templates",
    static=MODULE_DIR / "static",
    stylesheets=("/stages.css",),
    template_globals={"stage_label": stage_label},
    permissions=("storage",),
    brief=brief_lines,
    # Job search predates module prefixes; ADR 0007 keeps these names as the documented
    # exception, and the contract test allows exactly these.
    legacy_table_names=TABLES,
    label="Career Radar",
    color="sage",
    icon="M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8M12 12l6-6",
    cards=(CARD,),
)
