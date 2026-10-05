"""Valeurs courantes ramenées dans des bornes fixes."""

from decimal import Decimal
from typing import NamedTuple

_SURVIVAL = (Decimal("0.30"), Decimal("0.50"))
_DRAWDOWN = (Decimal("0.15"), Decimal("0.25"))
_STAKE = (Decimal("0.10"), Decimal("0.25"))
_EXPOSURE = (Decimal("0.25"), Decimal("0.50"))


class Clamped(NamedTuple):
    survival: Decimal
    drawdown: Decimal
    stake_fraction: Decimal
    exposure_fraction: Decimal


def _clamp(value: Decimal, bounds: tuple[Decimal, Decimal]) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("Decimal requis")
    low, high = bounds
    return min(high, max(low, value))


def clamp_bounds(
    survival: Decimal,
    drawdown: Decimal,
    stake_fraction: Decimal,
    exposure_fraction: Decimal,
) -> Clamped:
    return Clamped(
        _clamp(survival, _SURVIVAL),
        _clamp(drawdown, _DRAWDOWN),
        _clamp(stake_fraction, _STAKE),
        _clamp(exposure_fraction, _EXPOSURE),
    )
