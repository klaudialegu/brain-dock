"""The color system (ADR 0016): every pair of colors that carries meaning is readable."""

from brain_dock.core.palette import CARD, INK, MUTED, PALETTE, PAPER, contrast, palette_css


def test_tape_text_reads_at_4_5_to_1_on_its_tint():
    for color in PALETTE.values():
        assert contrast(color.tape_text, color.tint) >= 4.5, color.name
    assert contrast(INK, CARD) >= 4.5 and contrast(MUTED, CARD) >= 4.5
    assert contrast(MUTED, PAPER) >= 4.5  # secondary text on the page background


def test_ring_and_dot_inks_read_at_3_to_1_on_the_card():
    # Rings and dots are UI, not text: WCAG asks 3:1 against what's next to them.
    for color in PALETTE.values():
        assert contrast(color.ink, CARD) >= 3, color.name
        assert contrast(color.ink, PAPER) >= 3, color.name
    assert abs(contrast("#000000", "#FFFFFF") - 21) < 0.01  # the formula itself


def test_palette_css_has_every_module_color():
    css = palette_css()

    for color in PALETTE.values():
        assert f".c-{color.name} {{ --tint: {color.tint}; --ink: {color.ink};" in css
        assert f".hl-{color.name} {{ --highlighter: {color.tint};" in css
    assert len(PALETTE) == 7
