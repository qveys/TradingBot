"""Limites de paire mesurées. L'appelant les passe à decide()."""

from decimal import Decimal
from typing import NamedTuple


class PairLimits(NamedTuple):
    min_order_size: Decimal
    min_order_size_quote: Decimal
    base_step: Decimal
    quote_step: Decimal
    max_order_size: Decimal
    max_order_size_quote: Decimal


# GET /1.0/public/configuration/pairs, clé BTC/EUR, le 2026-10-04. ADR 0003.
_BTC_EUR = PairLimits(
    min_order_size=Decimal("0.00000001"),
    min_order_size_quote=Decimal("0.1"),
    base_step=Decimal("0.00000001"),
    quote_step=Decimal("0.01"),
    max_order_size=Decimal("200"),
    max_order_size_quote=Decimal("1000000"),
)


def limits_for(pair: str) -> PairLimits | None:
    if pair in {"BTC/EUR", "BTC-EUR"}:
        return _BTC_EUR
    return None
