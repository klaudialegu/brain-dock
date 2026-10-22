"""Everything about stages that isn't stored in the database: one place to change them.

The badge colors (/stages.css), the pipeline chart, and the stage pickers in forms all
read from STAGES. tests/test_stages.py fails if a Stage is missing here.
"""

from dataclasses import dataclass

from brain_dock.models import Stage


@dataclass(frozen=True)
class StageInfo:
    label: str
    order: int  # position in the pipeline, left to right
    kind: str  # "active" (still moving), "won" (offer) or "closed" (ended without one)
    color: str  # light mode
    dark_color: str  # dark mode


STAGES: dict[Stage, StageInfo] = {
    Stage.applied: StageInfo("Applied", 0, "active", "#1f2328", "#e8e6e3"),
    Stage.screen: StageInfo("Screen", 1, "active", "#3b6ea8", "#7aa7d9"),
    Stage.interview: StageInfo("Interview", 2, "active", "#3b6ea8", "#7aa7d9"),
    Stage.onsite: StageInfo("Onsite", 3, "active", "#3b6ea8", "#7aa7d9"),
    Stage.offer: StageInfo("Offer", 4, "won", "#2f7d4f", "#6cc191"),
    Stage.rejected: StageInfo("Rejected", 5, "closed", "#6b6f76", "#9a9ea6"),
    Stage.ghosted: StageInfo("Ghosted", 6, "closed", "#6b6f76", "#9a9ea6"),
    Stage.withdrawn: StageInfo("Withdrawn", 7, "closed", "#6b6f76", "#9a9ea6"),
}

KINDS = {"active", "won", "closed"}

# Stages that count as hearing back from the company (for the response rate).
# Ghosted and withdrawn are endings without a reply.
REPLY_STAGES = frozenset({Stage.screen, Stage.interview, Stage.onsite, Stage.offer, Stage.rejected})
# Stages that mean the application got as far as interviewing.
INTERVIEW_STAGES = frozenset({Stage.interview, Stage.onsite, Stage.offer})


def stage_order(stage: Stage | str) -> int:
    return STAGES[Stage(stage)].order


def stage_label(stage: Stage | str) -> str:
    return STAGES[Stage(stage)].label


def recordable_stages() -> list[Stage]:
    """Stages a person can record; "applied" comes from the applied date."""
    return [s for s in sorted(STAGES, key=lambda s: STAGES[s].order) if s != Stage.applied]


def stage_css() -> str:
    """Badge colors for every stage, light and dark, served as /stages.css."""
    light = [f".stage-{s.value} {{ color: {i.color}; }}" for s, i in STAGES.items()]
    dark = [f"  .stage-{s.value} {{ color: {i.dark_color}; }}" for s, i in STAGES.items()]
    won = [
        f".stage-{s.value} {{ font-weight: 600; }}" for s, i in STAGES.items() if i.kind == "won"
    ]
    return "\n".join(light + won + ["@media (prefers-color-scheme: dark) {", *dark, "}"]) + "\n"
