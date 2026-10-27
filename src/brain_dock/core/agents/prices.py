"""Model prices and costs (ADR 0008). Costs are whole micro-dollars (millionths of a dollar),
rounded up, so sums never drift and an estimate never comes out cheaper than it was."""

import math
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

PRICES_PATH = Path(__file__).with_name("prices.toml")
PRICE_FIELDS = ("input", "output", "cache_read", "cache_write")


class PriceError(ValueError):
    """No price is known for this model or this many tokens. Nothing is sent."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class ModelPrices:
    model: str
    input: Decimal  # dollars per million tokens
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal
    estimates: frozenset[str]  # fields not read from a source
    source: str
    verified_on: str
    priced_up_to_input_tokens: int | None = None

    @property
    def verified(self) -> bool:
        return not self.estimates

    def _check_size(self, input_tokens: int) -> None:
        limit = self.priced_up_to_input_tokens
        if limit is not None and input_tokens > limit:
            raise PriceError(f"{self.model} is only priced up to {limit} input tokens")

    def cost_micro_usd(self, usage: Usage) -> int:
        """What a call cost: tokens times dollars per MTok is micro-dollars."""
        self._check_size(usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens)
        total = (
            usage.input_tokens * self.input
            + usage.output_tokens * self.output
            + usage.cache_read_tokens * self.cache_read
            + usage.cache_write_tokens * self.cache_write
        )
        return math.ceil(total)

    def worst_case_micro_usd(self, input_tokens: int, max_tokens: int) -> int:
        """The most a call can cost: every input token at the dearest input rate (writing
        the cache costs more than plain input) and every allowed output token."""
        self._check_size(input_tokens)
        dearest_input = max(self.input, self.cache_write)
        return math.ceil(input_tokens * dearest_input + max_tokens * self.output)


def load_prices(path: Path = PRICES_PATH) -> dict[str, ModelPrices]:
    raw = tomllib.loads(path.read_text())["models"]
    prices = {}
    for model, entry in raw.items():
        estimates = frozenset(entry.get("estimates", []))
        unknown = estimates - set(PRICE_FIELDS)
        if unknown:
            raise PriceError(f"{model}: unknown estimate fields {sorted(unknown)}")
        prices[model] = ModelPrices(
            model=model,
            **{f: Decimal(entry[f]) for f in PRICE_FIELDS},
            estimates=estimates,
            source=entry["source"],
            verified_on=entry["verified_on"],
            priced_up_to_input_tokens=entry.get("priced_up_to_input_tokens"),
        )
    return prices
