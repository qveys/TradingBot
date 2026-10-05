"""Survie, drawdown, SPRT et Kelly nul. L'appelant reçoit l'événement : pas d'envoi."""

import random
from collections.abc import Sequence
from decimal import Decimal, localcontext
from typing import NamedTuple

from tradingbot.bounds import clamp_bounds
from tradingbot.sizing import empirical_kelly

_CHANGE = "METHOD_CHANGE_REQUIRED"
_STAKE_START = Decimal("0.10")
_EXPOSURE_START = Decimal("0.25")
_SURVIVAL_START = Decimal("0.40")
_DRAWDOWN_START = Decimal("0.20")
_DECISION_FROM = 30
LOW_BOUND = (Decimal("0.20") / Decimal("0.95")).ln()

_HIGH = Decimal(16).ln()
_TRUNCATION_AT = 300
_KEEP_BAD = Decimal("0.05")
_ABANDON_GOOD = Decimal("0.20")
_RATE_SPAN = Decimal("0.04")
_SEARCH_CEILING = 2000
# Plancher 0,08, pas 0,02 : un effet plus fin demande une grille plus serrée.
_D_MIN_GRID = tuple(
    Decimal(step) / Decimal(100)
    for step in range(8, 42, 2)
)
# 400 tirages : l'écart-type d'une proportion à 20 % passe sous 4 points.
_MC_PATHS = 400
_MC_SEED = 1
_LN_PI = Decimal("1.1447298858494001741434273513530587116472948129153")
_GAMMA_CACHE: dict[Decimal, Decimal] = {}


class MethodEvent(NamedTuple):
    code: str
    reason: str
    statistical: bool = True


class FrozenSprt(NamedTuple):
    low: Decimal
    high: Decimal
    d_min: Decimal


class SprtProbe(NamedTuple):
    d_min: Decimal
    mean_trades: Decimal
    keep_bad: Decimal
    abandon_good: Decimal
    open_good: int
    open_bad: int = 0


class SprtCalibration(NamedTuple):
    d_min: Decimal
    mean_trades: Decimal
    keep_bad: Decimal
    abandon_good: Decimal
    open_good: int
    open_bad: int
    rejected: tuple[SprtProbe, ...] = ()


def survival_breach(
    trade_count: int,
    capital: Decimal,
    peak: Decimal,
    survival: Decimal = _SURVIVAL_START,
) -> MethodEvent | None:
    _count(trade_count)
    capital = _finite(capital)
    peak = _finite(peak)
    if peak <= 0:
        raise ValueError("pic nul")
    kept = clamp_bounds(
        survival, _DRAWDOWN_START, _STAKE_START, _EXPOSURE_START
    ).survival
    if trade_count < 1:
        return None
    if capital <= (Decimal(1) - kept) * peak:
        return MethodEvent(_CHANGE, "survival")
    return None


def method_drawdown(
    trade_count: int,
    peak: Decimal,
    equity: Decimal,
    drawdown: Decimal = _DRAWDOWN_START,
) -> MethodEvent | None:
    _count(trade_count)
    peak = _finite(peak)
    equity = _finite(equity)
    if peak <= 0:
        raise ValueError("pic nul")
    kept = clamp_bounds(
        _SURVIVAL_START, drawdown, _STAKE_START, _EXPOSURE_START
    ).drawdown
    if trade_count < 1:
        return None
    if (peak - equity) / peak >= kept:
        return MethodEvent(_CHANGE, "drawdown")
    return None


def sequential_t_llr(multiples: Sequence[Decimal], d_min: Decimal) -> Decimal:
    d_min = _finite(d_min)
    if d_min <= 0:
        raise ValueError("d_min")
    values = tuple(_finite(item) for item in multiples)
    total = sum(values, start=Decimal(0))
    total_sq = sum((item * item for item in values), start=Decimal(0))
    return _llr_moments(len(values), total, total_sq, d_min)


def sprt_low_bound(
    multiples: Sequence[Decimal], d_min: Decimal
) -> MethodEvent | None:
    llr = sequential_t_llr(multiples, d_min)
    if len(multiples) < _DECISION_FROM:
        return None
    if llr <= LOW_BOUND:
        return MethodEvent(_CHANGE, "sprt_low")
    return None


def sprt_high_bound(
    multiples: Sequence[Decimal], d_min: Decimal
) -> MethodEvent | None:
    if len(multiples) < _DECISION_FROM:
        return None
    llr = sequential_t_llr(multiples, d_min)
    if llr >= _HIGH:
        return MethodEvent("METHOD_VALIDATED", "sprt_high")
    return None


def freeze_sprt(d_min: Decimal) -> FrozenSprt:
    d_min = _finite(d_min)
    if d_min <= 0:
        raise ValueError("d_min")
    return FrozenSprt(LOW_BOUND, _HIGH, d_min)


def sprt_outcome(
    multiples: Sequence[Decimal], frozen: FrozenSprt
) -> MethodEvent | None:
    if not isinstance(frozen, FrozenSprt):
        raise TypeError("gel requis")
    count = len(multiples)
    if count < _DECISION_FROM:
        return None
    llr = sequential_t_llr(multiples, frozen.d_min)
    if llr >= frozen.high:
        return MethodEvent("METHOD_VALIDATED", "sprt_high")
    if llr <= frozen.low:
        return MethodEvent(_CHANGE, "sprt_low")
    if count >= _TRUNCATION_AT:
        return MethodEvent(_CHANGE, "truncation", False)
    return None


def sprt_operating(
    d_min: Decimal, *, seed: int = _MC_SEED, paths: int = _MC_PATHS
) -> SprtCalibration:
    d_min = _finite(d_min)
    if d_min <= 0:
        raise ValueError("d_min")
    if type(seed) is not int or type(paths) is not int:
        raise TypeError("int requis")
    if paths < 1:
        raise ValueError("tirages")
    alternatives, _slow = _alternative_paths(d_min, seed, paths, abort=False)
    generator = random.Random(seed + 1)
    nulls = [_path(generator, Decimal(0), d_min) for _ in range(paths)]
    return _assemble(d_min, alternatives, nulls)


def _probe_passes(measured: SprtCalibration) -> bool:
    return (
        measured.open_good == 0
        and measured.open_bad == 0
        and measured.mean_trades <= _TRUNCATION_AT
        and _near(measured.keep_bad, _KEEP_BAD)
        and _near(measured.abandon_good, _ABANDON_GOOD)
    )


def calibrate_d_min(
    *, seed: int = _MC_SEED, paths: int = _MC_PATHS
) -> SprtCalibration:
    if type(seed) is not int or type(paths) is not int:
        raise TypeError("int requis")
    if paths < 1:
        raise ValueError("tirages")
    rejected: list[SprtProbe] = []
    for candidate in _D_MIN_GRID:
        _finite(candidate)
        alternatives, probe = _alternative_paths(
            candidate, seed, paths, abort=True
        )
        if probe is not None:
            rejected.append(probe)
            continue
        generator = random.Random(seed + 1)
        nulls = [_path(generator, Decimal(0), candidate) for _ in range(paths)]
        measured = _assemble(candidate, alternatives, nulls)
        if _probe_passes(measured):
            return measured._replace(rejected=tuple(rejected))
        rejected.append(
            SprtProbe(
                measured.d_min,
                measured.mean_trades,
                measured.keep_bad,
                measured.abandon_good,
                measured.open_good,
                measured.open_bad,
            )
        )
    raise LookupError("d_min")


def kelly_null(multiples: Sequence[Decimal]) -> MethodEvent | None:
    values = tuple(_finite(item) for item in multiples)
    if len(values) < _DECISION_FROM:
        return None
    if empirical_kelly(values) <= 0:
        return MethodEvent(_CHANGE, "kelly")
    return None


def _rushton_llr(t_stat: Decimal, df: Decimal, ncp: Decimal) -> Decimal:
    zed = t_stat * ncp * Decimal(2).sqrt() / (df + t_stat * t_stat).sqrt()
    term = Decimal(1)
    total = term
    for index in range(1, 10001):
        step = Decimal(index)
        log_ratio = _ln_gamma((df + step + 1) / 2) - _ln_gamma((df + step) / 2)
        term *= zed * log_ratio.exp() / step
        total += term
        if term.copy_abs() <= total.copy_abs() * Decimal("1e-12"):
            break
    else:
        raise ValueError("série SPRT")
    if total <= 0:
        raise ValueError("série SPRT")
    return total.ln() - ncp * ncp / Decimal(2)


def _llr_moments(
    count: int, total: Decimal, total_sq: Decimal, d_min: Decimal
) -> Decimal:
    if count < 2:
        return Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 28
        width = Decimal(count)
        mean = total / width
        var_sum = total_sq - total * total / width
        if var_sum <= 0:
            if mean <= 0:
                return Decimal("-Infinity")
            return Decimal("Infinity")
        df = Decimal(count - 1)
        deviation = (var_sum / df).sqrt()
        t_stat = mean * width.sqrt() / deviation
        ncp = d_min * width.sqrt()
        if t_stat == 0:
            return -ncp * ncp / Decimal(2)
        return _rushton_llr(t_stat, df, ncp)


def _ln_gamma(value: Decimal) -> Decimal:
    doubled = value * 2
    if doubled != doubled.to_integral_value() or doubled < 1:
        raise ValueError("série SPRT")
    cached = _GAMMA_CACHE.get(doubled)
    if cached is not None:
        return cached
    one = Decimal(1)
    two = Decimal(2)
    if one not in _GAMMA_CACHE:
        _GAMMA_CACHE[one] = _LN_PI / 2
        _GAMMA_CACHE[two] = Decimal(0)
    have = doubled
    while have not in _GAMMA_CACHE:
        have -= two
    while have < doubled:
        nxt = have + two
        _GAMMA_CACHE[nxt] = _GAMMA_CACHE[have] + (have / two).ln()
        have = nxt
    return _GAMMA_CACHE[doubled]


def _assemble(
    d_min: Decimal,
    alternatives: list[tuple[int, str]],
    nulls: list[tuple[int, str]],
) -> SprtCalibration:
    width = Decimal(len(alternatives))
    return SprtCalibration(
        d_min,
        sum((Decimal(length) for length, _side in alternatives), start=Decimal(0))
        / width,
        Decimal(sum(side == "high" for _length, side in nulls)) / width,
        Decimal(sum(side == "low" for _length, side in alternatives)) / width,
        sum(side == "open" for _length, side in alternatives),
        sum(side == "open" for _length, side in nulls),
    )


def _alternative_paths(
    d_min: Decimal, seed: int, paths: int, *, abort: bool
) -> tuple[list[tuple[int, str]], SprtProbe | None]:
    generator = random.Random(seed)
    alternatives: list[tuple[int, str]] = []
    open_good = 0
    length_sum = 0
    for index in range(paths):
        length, side = _path(generator, d_min, d_min)
        alternatives.append((length, side))
        length_sum += length
        if side == "open":
            open_good += 1
        remaining = paths - index - 1
        floor = length_sum + _DECISION_FROM * remaining
        if abort and (open_good or floor > _TRUNCATION_AT * paths):
            # Plancher du nombre moyen : il ne sert qu'à écarter un effet trop lent.
            return alternatives, SprtProbe(
                d_min,
                Decimal(floor) / Decimal(paths),
                _KEEP_BAD,
                _ABANDON_GOOD,
                open_good,
            )
    return alternatives, None


def _count(trade_count: object) -> int:
    if type(trade_count) is not int:
        raise TypeError("int requis")
    if trade_count < 0:
        raise ValueError("compteur négatif")
    return trade_count


def _finite(value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("Decimal requis")
    if not value.is_finite():
        raise ValueError("décimal non fini")
    return value


def _near(rate: Decimal, target: Decimal) -> bool:
    return (rate - target).copy_abs() <= _RATE_SPAN


def _normal(generator: random.Random) -> Decimal:
    draw = Decimal(0)
    for _ in range(12):
        draw += Decimal(generator.randrange(1_000_000)) / Decimal(1_000_000)
    return draw - Decimal(6)


def _path(
    generator: random.Random, mean: Decimal, d_min: Decimal
) -> tuple[int, str]:
    total = Decimal(0)
    total_sq = Decimal(0)
    for count in range(1, _SEARCH_CEILING + 1):
        draw = mean + _normal(generator)
        total += draw
        total_sq += draw * draw
        if count < _DECISION_FROM:
            continue
        ratio = _llr_moments(count, total, total_sq, d_min)
        if ratio >= _HIGH:
            return count, "high"
        if ratio <= LOW_BOUND:
            return count, "low"
    return _SEARCH_CEILING + 1, "open"
