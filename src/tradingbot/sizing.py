"""Quantité : bootstrap sous 30 trades, puis demi-Kelly empirique."""

from collections.abc import Sequence
from decimal import Decimal

_RISK = Decimal("0.01")
_STAKE = Decimal("0.10")
_TRADE_LIMIT = 30


def bootstrap_quantity(
    capital: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    fee_rate: Decimal,
    trade_count: int,
) -> Decimal:
    capital = _finite(capital)
    entry_price = _finite(entry_price)
    stop_price = _finite(stop_price)
    fee_rate = _finite(fee_rate)
    if type(trade_count) is not int:
        raise TypeError("int requis")
    if trade_count < 0 or trade_count >= _TRADE_LIMIT:
        raise ValueError("bootstrap seulement sous 30 trades")
    if capital < 0 or entry_price <= 0 or fee_rate < 0:
        raise ValueError("entrées de quantité invalides")
    denominator = abs(entry_price - stop_price) + fee_rate * (entry_price + stop_price)
    if denominator <= 0:
        raise ValueError("entrées de quantité invalides")
    risk_term = _RISK * capital / denominator
    stake_term = _STAKE * capital / entry_price
    return min(risk_term, stake_term)


def empirical_kelly(multiples: Sequence[Decimal]) -> Decimal:
    values = _values(multiples)
    if not values:
        raise ValueError("multiples R")
    total = sum(values, start=Decimal(0))
    if total <= 0:
        return Decimal(0)
    negatives = [item for item in values if item < 0]
    if not negatives:
        return Decimal("Infinity")
    f_max = min(-Decimal(1) / item for item in negatives)
    lo = Decimal(0)
    best = Decimal(0)
    hi = f_max
    for _ in range(120):
        mid = (lo + hi) / 2
        if _slope(values, mid) > 0:
            best = mid
            lo = mid
        else:
            hi = mid
    return best


def half_kelly_risk(multiples: Sequence[Decimal]) -> Decimal | None:
    f_star = empirical_kelly(multiples)
    if f_star <= 0:
        return None
    if not f_star.is_finite():
        return _RISK
    return min(_RISK, f_star / Decimal(2))


def _values(multiples: Sequence[Decimal]) -> tuple[Decimal, ...]:
    return tuple(_finite(item) for item in multiples)


def _slope(values: Sequence[Decimal], fraction: Decimal) -> Decimal:
    total = Decimal(0)
    for item in values:
        denominator = Decimal(1) + fraction * item
        if denominator <= 0:
            return Decimal("-Infinity")
        total += item / denominator
    return total


def _finite(value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("Decimal requis")
    if not value.is_finite():
        raise ValueError("décimal non fini")
    return value
