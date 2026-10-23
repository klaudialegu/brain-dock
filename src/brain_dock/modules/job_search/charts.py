"""Turn query results into the data the pipeline chart draws: stage labels, colors, counts.

Only stage names and numbers go to the page, never company or role names.
"""

from brain_dock.modules.job_search.queries import PipelineLink
from brain_dock.modules.job_search.stages import STAGES, stage_label, stage_order


def pipeline_chart_data(links: list[PipelineLink]) -> dict:
    stages = sorted({s for link in links for s in (link.source, link.target)}, key=stage_order)
    return {
        "nodes": [
            {
                "name": stage_label(stage),
                "color": STAGES[stage].color,
                "darkColor": STAGES[stage].dark_color,
            }
            for stage in stages
        ],
        "links": [
            {
                "source": stage_label(link.source),
                "target": stage_label(link.target),
                "value": link.count,
            }
            for link in links
        ],
    }


def pipeline_summary(links: list[PipelineLink]) -> str:
    """The chart in words, for screen readers."""
    return "; ".join(
        f"{stage_label(link.source)} to {stage_label(link.target)}: {link.count}" for link in links
    )
