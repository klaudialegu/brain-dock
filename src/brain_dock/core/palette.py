"""The color system (ADR 0016): a paper background, cream cards, near-black ink, and one
soft color per module. Each color has a tint (washi-tape labels, highlighter swipes), an
ink (dots and the needs-attention ring) and a dark tape-text ink.

Text always sits in near-black or a dark tape ink on top of soft color, so it reads at
4.5:1 or better; dots and rings read at 3:1 or better on cards (tests/test_palette.py).
"""

from dataclasses import dataclass

INK = "#1D1B18"
MUTED = "#6B6862"
PAPER = "#F8F5EF"
CARD = "#FFFEFB"
RING = "#E9E3D8"


@dataclass(frozen=True)
class Color:
    name: str
    label: str
    tint: str  # solid tint: highlighter swipes, swatches
    ink: str  # dots, rings
    tape_a: str  # the two stripes of a washi-tape label
    tape_b: str
    tape_text: str  # text on the tape


PALETTE: dict[str, Color] = {
    c.name: c
    for c in [
        Color(
            "graphite",
            "Graphite",
            "#E6DFD3",
            "#6B6862",
            "rgba(222,214,201,.8)",
            "rgba(232,226,215,.8)",
            "#3F3C37",
        ),
        Color(
            "lavender",
            "Lavender",
            "#D9CCF2",
            "#8C7BD0",
            "rgba(196,182,232,.85)",
            "rgba(206,194,238,.85)",
            "#3A2F66",
        ),
        Color(
            "sage",
            "Sage",
            "#C9E3CF",
            "#4E9A6E",
            "rgba(178,214,190,.85)",
            "rgba(192,222,202,.85)",
            "#1F4A33",
        ),
        Color(
            "sky",
            "Sky",
            "#CBDDF2",
            "#4A86C2",
            "rgba(176,204,234,.85)",
            "rgba(190,213,238,.85)",
            "#1E3F63",
        ),
        Color(
            "apricot",
            "Apricot",
            "#F6CDB6",
            "#C2703D",
            "rgba(242,200,170,.88)",
            "rgba(246,212,188,.88)",
            "#6A3414",
        ),
        # The butter ink is darker than its tint suggests, so its dots and ring reach 3:1.
        Color(
            "butter",
            "Butter",
            "#F3E2A6",
            "#9E7F24",
            "rgba(240,218,140,.9)",
            "rgba(245,228,165,.9)",
            "#5A4512",
        ),
        Color(
            "rose",
            "Rose",
            "#F2CCD9",
            "#B25C7A",
            "rgba(236,190,206,.85)",
            "rgba(242,204,217,.85)",
            "#6A2A42",
        ),
    ]
}
DEFAULT_HIGHLIGHTER = "lavender"


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two #RRGGBB colors."""

    def luminance(color: str) -> float:
        r, g, b_ = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))

        def channel(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b_)

    light, dark = sorted([luminance(a), luminance(b)], reverse=True)
    return (light + 0.05) / (dark + 0.05)


def palette_css() -> str:
    """One class per color, setting the custom properties the shell's styles use. Served
    as /palette.css, so no page needs an inline style (CSP)."""
    rules = []
    for c in PALETTE.values():
        rules.append(
            f".c-{c.name} {{ --tint: {c.tint}; --ink: {c.ink}; --tape-a: {c.tape_a}; "
            f"--tape-b: {c.tape_b}; --tape-text: {c.tape_text}; }}"
        )
        rules.append(f".hl-{c.name} {{ --highlighter: {c.tint}; --highlighter-ink: {c.ink}; }}")
    return "\n".join(rules) + "\n"
