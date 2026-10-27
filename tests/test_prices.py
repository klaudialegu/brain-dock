"""Model prices and costs (ADR 0008): sourced and dated, estimates marked, costs in whole
micro-dollars rounded up."""

from decimal import Decimal

import pytest

from brain_dock.core.agents.prices import PriceError, Usage, load_prices

PRICES = load_prices()


def test_every_model_has_a_source_a_date_and_four_prices():
    assert set(PRICES) == {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"}
    for p in PRICES.values():
        assert p.source and p.verified_on == "2026-10-26"
        assert all(getattr(p, f) > 0 for f in ("input", "output", "cache_read", "cache_write"))


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        # 1000 input, 500 output, 2000 cache read, 400 cache write tokens
        ("claude-haiku-5-5", 1000 * 0.10 + 500 * 0.50 + 2000 * 0.01 + 400 * 0.125),  # 420
        ("claude-sonnet-5-5", 1000 * 2 + 500 * 10 + 2000 * 0.20 + 400 * 2.50),  # 8400
        ("claude-opus-5-5", 1000 * 4 + 500 * 20 + 2000 * 0.20 + 400 * 5),  # 16400
    ],
    ids=["haiku", "sonnet", "opus"],
)
def test_cost_in_micro_dollars_counts_every_kind_of_token(model, expected):
    usage = Usage(
        input_tokens=1000, output_tokens=500, cache_read_tokens=2000, cache_write_tokens=400
    )

    assert PRICES[model].cost_micro_usd(usage) == round(expected)


def test_costs_round_up_to_whole_micro_dollars():
    # 3 Haiku input tokens cost 0.3 micro-dollars: never recorded as 0.
    assert PRICES["claude-haiku-5-5"].cost_micro_usd(Usage(input_tokens=3)) == 1


def test_estimated_prices_are_marked_and_not_verified():
    haiku, sonnet = PRICES["claude-haiku-5-5"], PRICES["claude-sonnet-5-5"]

    assert haiku.estimates == {"cache_read", "cache_write"} and not haiku.verified
    assert sonnet.estimates == {"cache_write"} and not sonnet.verified
    assert sonnet.cache_read == Decimal("0.20")  # read from the source, not estimated


def test_worst_case_takes_the_dearest_input_rate_and_every_output_token():
    sonnet = PRICES["claude-sonnet-5-5"]

    # Writing the cache (2.50) costs more than plain input (2.00), so the worst case uses it.
    assert sonnet.worst_case_micro_usd(input_tokens=1000, max_tokens=100) == 1000 * 2.5 + 100 * 10


def test_tokens_beyond_the_priced_range_are_refused():
    haiku = PRICES["claude-haiku-5-5"]

    with pytest.raises(PriceError, match="100000"):
        haiku.worst_case_micro_usd(input_tokens=100_001, max_tokens=10)
    with pytest.raises(PriceError):
        haiku.cost_micro_usd(Usage(input_tokens=90_000, cache_read_tokens=20_000))
