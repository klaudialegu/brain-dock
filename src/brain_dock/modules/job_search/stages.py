"""Everything about stages that isn't stored in the database: one place to change them.

The badge colors (/stages.css), the pipeline chart, and the stage pickers in forms all
read from STAGES. tests/test_stages.py fails if a Stage is missing here.
"""

from dataclasses import dataclass

from brain_dock.modules.job_search.models import Stage


@dataclass(frozen=True)
class StageInfo:
    label: str
    order: int  # position in the pipeline, left to right
    # "saved" (interested, not an application yet), "active" (still moving), "won" (offer)
    # or "closed" (ended without one)
    kind: str
    color: str  # chip text: a dark ink, 4.5:1 or better on the chip's cream background
    dark_color: str  # dark mode (parked, ADR 0016)
    chart: str = "#3F3C37"  # pipeline chart node: the module ink, 3:1 or better on cards


STAGES: dict[Stage, StageInfo] = {
    # Warm: chips use the palette's dark tape inks, the chart its module inks (core/palette).
    Stage.interested: StageInfo("Interested", 0, "saved", "#3A2F66", "#ad98dc", "#8C7BD0"),
    Stage.applied: StageInfo("Applied", 1, "active", "#3F3C37", "#e8e6e3", "#3F3C37"),
    Stage.screen: StageInfo("Screen", 2, "active", "#1E3F63", "#7aa7d9", "#4A86C2"),
    Stage.interview: StageInfo("Interview", 3, "active", "#3A2F66", "#7aa7d9", "#8C7BD0"),
    Stage.onsite: StageInfo("Onsite", 4, "active", "#6A3414", "#7aa7d9", "#C2703D"),
    Stage.offer: StageInfo("Offer", 5, "won", "#1F4A33", "#6cc191", "#4E9A6E"),
    Stage.rejected: StageInfo("Rejected", 6, "closed", "#6B6862", "#9a9ea6", "#7D776E"),
    Stage.ghosted: StageInfo("Ghosted", 7, "closed", "#6B6862", "#9a9ea6", "#857F75"),
    Stage.withdrawn: StageInfo("Withdrawn", 8, "closed", "#6B6862", "#9a9ea6", "#8A8378"),
}

KINDS = {"saved", "active", "won", "closed"}

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
    """Stages a person can record on an application; "applied" comes from the applied date,
    and "interested" only from saving a job before applying."""
    skip = {Stage.interested, Stage.applied}
    return [s for s in sorted(STAGES, key=lambda s: STAGES[s].order) if s not in skip]


def stage_css() -> str:
    """Badge colors for every stage, served as /stages.css. Light only for now (ADR 0016);
    `dark_color` is kept for a dark palette later."""
    light = [f".stage-{s.value} {{ color: {i.color}; }}" for s, i in STAGES.items()]
    won = [
        f".stage-{s.value} {{ font-weight: 600; }}" for s, i in STAGES.items() if i.kind == "won"
    ]
    return "\n".join(light + won) + "\n"
