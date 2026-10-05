"""Validation pré-ordre R0 à R8. ACCEPT ne parle au courtier que hors mode à blanc.

Spread en fraction, plafond fixe 0,002. Volume en EUR. Âges en secondes.
Le taux de frais vient de l'appelant : absent, on ne dimensionne pas.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import NamedTuple, cast

from tradingbot.bounds import clamp_bounds
from tradingbot.sizing import bootstrap_quantity, half_kelly_risk

_LOG = logging.getLogger("tradingbot.decision")
_LOG.setLevel(logging.INFO)

_SPREAD_CAP = Decimal("0.002")
_RISK_CAP = Decimal("0.01")
# Même fraction que le bootstrap : R6 ne refuse pas la quantité qu'il produit.
_BOOTSTRAP_STAKE = Decimal("0.10")
_DEFAULT_EXPOSURE = Decimal("0.25")


class Intent(NamedTuple):
    method: str
    pair: str
    side: str
    stop_price: Decimal | None
    annotation: str


class Facts(NamedTuple):
    balance_age_s: Decimal | None
    price_age_s: Decimal | None
    book_age_s: Decimal | None
    entry_price: Decimal
    spread: Decimal
    volume_24h: Decimal
    capital: Decimal
    fee_rate: Decimal | None
    active_method: str
    change_in_progress: bool
    frequency: str
    declared_pairs: frozenset[str]
    declared_frequencies: frozenset[str]
    trade_count: int
    survival_flag: bool
    hard_stop_active: bool
    open_risk: Decimal = Decimal("0")
    open_notional: Decimal = Decimal("0")


class RulesConfig(NamedTuple):
    max_age_s: Decimal = Decimal("10")
    min_volume_eur: Decimal = Decimal("100000")
    quantity_step: Decimal | None = None
    min_quantity: Decimal | None = None
    stake_fraction: Decimal = _BOOTSTRAP_STAKE
    exposure_fraction: Decimal = _DEFAULT_EXPOSURE
    min_order_size_quote: Decimal | None = None
    max_order_size: Decimal | None = None
    max_order_size_quote: Decimal | None = None


class Decision(NamedTuple):
    code: str
    quantity: Decimal | None


def r0_stale_data(
    balance_age_s: Decimal | None,
    price_age_s: Decimal | None,
    book_age_s: Decimal | None,
    max_age_s: Decimal,
) -> str | None:
    limit = _finite(max_age_s)
    for age in (balance_age_s, price_age_s, book_age_s):
        if age is None or _finite(age) >= limit:
            return "STALE_DATA"
    return None


def r1_method_inactive(
    method: str,
    active_method: str,
    change_in_progress: bool,
) -> str | None:
    if not isinstance(change_in_progress, bool):
        raise TypeError("bool requis")
    if method != active_method or change_in_progress:
        return "METHOD_INACTIVE"
    return None


def r2_method_incompatible(
    pair: str,
    frequency: str,
    declared_pairs: frozenset[str],
    declared_frequencies: frozenset[str],
) -> str | None:
    if pair not in declared_pairs or frequency not in declared_frequencies:
        return "METHOD_INCOMPATIBLE"
    return None


def r3_spread(spread: Decimal) -> str | None:
    if _finite(spread) >= _SPREAD_CAP:
        return "PAIR_FILTER"
    return None


def r3_volume(volume_24h: Decimal, minimum_eur: Decimal) -> str | None:
    if _finite(volume_24h) < _finite(minimum_eur):
        return "PAIR_FILTER"
    return None


def r4_no_stop(
    side: str,
    stop_price: Decimal | None,
    entry_price: Decimal,
) -> str | None:
    entry = _finite(entry_price)
    if stop_price is None:
        return "NO_STOP"
    stop = _finite(stop_price)
    if side == "buy":
        return None if stop < entry else "NO_STOP"
    if side == "sell":
        return None if stop > entry else "NO_STOP"
    return "NO_STOP"


def r5_risk_cap(
    quantity: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    fee_rate: Decimal,
    capital: Decimal,
    open_risk: Decimal,
) -> str | None:
    opened = _finite(open_risk)
    if opened < 0:
        raise ValueError("risque ouvert négatif")
    loss = _finite(quantity) * (
        abs(_finite(entry_price) - _finite(stop_price))
        + _finite(fee_rate) * (_finite(entry_price) + _finite(stop_price))
    )
    if opened + loss > _RISK_CAP * _finite(capital):
        return "RISK_CAP"
    return None


def min_order_fits_risk(
    min_quantity: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    fee_rate: Decimal,
    capital: Decimal,
    open_risk: Decimal,
) -> bool:
    return (
        r5_risk_cap(
            min_quantity,
            entry_price,
            stop_price,
            fee_rate,
            capital,
            open_risk,
        )
        is None
    )


def r6_stake_cap(
    quantity: Decimal,
    entry_price: Decimal,
    capital: Decimal,
    stake_fraction: Decimal,
) -> str | None:
    fraction = _finite(stake_fraction)
    if fraction <= 0:
        raise ValueError("fraction de mise invalide")
    if _finite(quantity) * _finite(entry_price) > fraction * _finite(capital):
        return "STAKE_CAP"
    return None


def r7_exposure_cap(
    quantity: Decimal,
    entry_price: Decimal,
    capital: Decimal,
    open_notional: Decimal,
    exposure_fraction: Decimal,
) -> str | None:
    opened = _finite(open_notional)
    if opened < 0:
        raise ValueError("notionnel ouvert négatif")
    fraction = _finite(exposure_fraction)
    if fraction <= 0:
        raise ValueError("fraction d'exposition invalide")
    stake = _finite(quantity) * _finite(entry_price)
    if opened + stake > fraction * _finite(capital):
        return "EXPOSURE_CAP"
    return None


def r8_survival_state(survival_flag: bool, hard_stop_active: bool) -> str | None:
    if not isinstance(survival_flag, bool) or not isinstance(hard_stop_active, bool):
        raise TypeError("bool requis")
    if survival_flag or hard_stop_active:
        return "SURVIVAL_STATE"
    return None


def decide(
    intent: Intent,
    facts: Facts,
    config: RulesConfig | None = None,
    *,
    paper: bool = True,
    on_accept: Callable[[Decimal], None] | None = None,
    r_multiples: Sequence[Decimal] = (),
    outgoing_method: str | None = None,
) -> Decision:
    if not isinstance(paper, bool):
        raise TypeError("bool requis")
    settings = RulesConfig() if config is None else config
    _finite(settings.max_age_s)
    _finite(settings.min_volume_eur)
    _finite(settings.stake_fraction)
    _finite(settings.exposure_fraction)
    kept = clamp_bounds(
        Decimal("0.40"),
        Decimal("0.20"),
        settings.stake_fraction,
        settings.exposure_fraction,
    )
    # Plafond seulement : une fraction déjà sous la borne basse ne grossit pas l'ordre.
    stake_fraction = min(settings.stake_fraction, kept.stake_fraction)
    exposure_fraction = min(settings.exposure_fraction, kept.exposure_fraction)

    code = r0_stale_data(
        facts.balance_age_s,
        facts.price_age_s,
        facts.book_age_s,
        settings.max_age_s,
    )
    if code is not None:
        return _logged(
            code,
            {
                "balance_age_s": facts.balance_age_s,
                "price_age_s": facts.price_age_s,
                "book_age_s": facts.book_age_s,
                "max_age_s": settings.max_age_s,
            },
            None,
        )

    code = r1_method_inactive(
        intent.method,
        facts.active_method,
        facts.change_in_progress,
    )
    if code is not None:
        return _logged(
            code,
            {
                "method": intent.method,
                "active_method": facts.active_method,
                "change_in_progress": facts.change_in_progress,
            },
            None,
        )

    code = r2_method_incompatible(
        intent.pair,
        facts.frequency,
        facts.declared_pairs,
        facts.declared_frequencies,
    )
    if code is not None:
        return _logged(
            code,
            {
                "pair": intent.pair,
                "frequency": facts.frequency,
                "declared_pairs": ",".join(sorted(facts.declared_pairs)),
                "declared_frequencies": ",".join(sorted(facts.declared_frequencies)),
            },
            None,
        )

    code = r3_spread(facts.spread)
    if code is not None:
        return _logged(
            code,
            {"spread": facts.spread, "spread_cap": _SPREAD_CAP},
            None,
        )

    code = r3_volume(facts.volume_24h, settings.min_volume_eur)
    if code is not None:
        return _logged(
            code,
            {
                "volume_24h": facts.volume_24h,
                "min_volume_eur": settings.min_volume_eur,
            },
            None,
        )

    code = r4_no_stop(intent.side, intent.stop_price, facts.entry_price)
    if code is not None:
        return _logged(
            code,
            {
                "side": intent.side,
                "stop_price": intent.stop_price,
                "entry_price": facts.entry_price,
            },
            None,
        )
    stop = cast(Decimal, intent.stop_price)

    fee_rate = facts.fee_rate
    if fee_rate is None:
        return _logged("FEE_UNAVAILABLE", {"fee_rate": None}, None)

    if type(facts.trade_count) is not int:
        raise TypeError("int requis")
    if facts.trade_count < 30:
        quantity = bootstrap_quantity(
            facts.capital,
            facts.entry_price,
            stop,
            fee_rate,
            facts.trade_count,
        )
        # Le quotient par défaut peut dépasser d'un ulp le budget dont il est issu.
        denominator = abs(facts.entry_price - stop) + fee_rate * (
            facts.entry_price + stop
        )
        quantity = min(
            quantity,
            _quot_down(_RISK_CAP * facts.capital, denominator),
            _quot_down(_BOOTSTRAP_STAKE * facts.capital, facts.entry_price),
        )
    else:
        if len(r_multiples) != facts.trade_count:
            raise ValueError("r_multiples")
        risk = half_kelly_risk(r_multiples)
        if risk is None:
            return _logged(
                "METHOD_CHANGE_REQUIRED",
                {"reason": "kelly", "trade_count": facts.trade_count},
                None,
            )
        capital = _finite(facts.capital)
        entry = _finite(facts.entry_price)
        fee_rate = _finite(fee_rate)
        if capital < 0 or entry <= 0 or fee_rate < 0:
            raise ValueError("entrées de quantité invalides")
        denominator = abs(entry - stop) + fee_rate * (entry + stop)
        if denominator <= 0:
            raise ValueError("entrées de quantité invalides")
        if stake_fraction <= 0:
            raise ValueError("fraction de mise invalide")
        quantity = min(
            _quot_down(risk * capital, denominator),
            _quot_down(stake_fraction * capital, entry),
        )
    step = settings.quantity_step
    if step is not None:
        step = _finite(step)
        if step <= 0:
            raise ValueError("pas de quantité invalide")
        quantity = (quantity // step) * step
    if quantity <= 0:
        return _logged("BELOW_MIN_SIZE", {"quantity": quantity}, None)

    minimum = settings.min_quantity
    if minimum is not None:
        minimum = _finite(minimum)
        fits = min_order_fits_risk(
            minimum,
            facts.entry_price,
            stop,
            fee_rate,
            facts.capital,
            facts.open_risk,
        )
        if quantity < minimum or not fits:
            return _logged(
                "BELOW_MIN_SIZE",
                {"quantity": quantity, "min_quantity": minimum},
                None,
            )

    entry = _finite(facts.entry_price)
    notional = quantity * entry
    quote_min = settings.min_order_size_quote
    if quote_min is not None:
        quote_min = _finite(quote_min)
        if quote_min <= 0:
            raise ValueError("minimum coté invalide")
        if notional < quote_min:
            return _logged(
                "BELOW_MIN_SIZE",
                {"quantity": quantity, "min_order_size_quote": quote_min},
                None,
            )
    base_max = settings.max_order_size
    if base_max is not None:
        base_max = _finite(base_max)
        if base_max <= 0:
            raise ValueError("maximum de base invalide")
        if quantity > base_max:
            return _logged(
                "BELOW_MIN_SIZE",
                {"quantity": quantity, "max_order_size": base_max},
                None,
            )
    quote_max = settings.max_order_size_quote
    if quote_max is not None:
        quote_max = _finite(quote_max)
        if quote_max <= 0:
            raise ValueError("maximum coté invalide")
        if notional > quote_max:
            return _logged(
                "BELOW_MIN_SIZE",
                {"quantity": quantity, "max_order_size_quote": quote_max},
                None,
            )

    code = r5_risk_cap(
        quantity,
        facts.entry_price,
        stop,
        fee_rate,
        facts.capital,
        facts.open_risk,
    )
    if code is not None:
        return _logged(
            code,
            {
                "quantity": quantity,
                "entry_price": facts.entry_price,
                "stop_price": stop,
                "fee_rate": fee_rate,
                "capital": facts.capital,
                "open_risk": facts.open_risk,
            },
            None,
        )

    code = r6_stake_cap(
        quantity,
        facts.entry_price,
        facts.capital,
        stake_fraction,
    )
    if code is not None:
        return _logged(
            code,
            {
                "quantity": quantity,
                "entry_price": facts.entry_price,
                "capital": facts.capital,
                "stake_fraction": stake_fraction,
            },
            None,
        )

    code = r7_exposure_cap(
        quantity,
        facts.entry_price,
        facts.capital,
        facts.open_notional,
        exposure_fraction,
    )
    if code is not None:
        return _logged(
            code,
            {
                "quantity": quantity,
                "entry_price": facts.entry_price,
                "capital": facts.capital,
                "open_notional": facts.open_notional,
                "exposure_fraction": exposure_fraction,
            },
            None,
        )

    code = r8_survival_state(facts.survival_flag, facts.hard_stop_active)
    if code is not None:
        return _logged(
            code,
            {
                "survival_flag": facts.survival_flag,
                "hard_stop_active": facts.hard_stop_active,
            },
            None,
        )
    if outgoing_method is not None and intent.method == outgoing_method:
        return _logged(
            "SURVIVAL_STATE",
            {
                "method": intent.method,
                "outgoing_method": outgoing_method,
                "hard_stop_active": facts.hard_stop_active,
            },
            None,
        )

    decision = _logged(
        "ACCEPT",
        {
            "method": intent.method,
            "pair": intent.pair,
            "side": intent.side,
            "stop_price": stop,
            "entry_price": facts.entry_price,
            "spread": facts.spread,
            "volume_24h": facts.volume_24h,
            "capital": facts.capital,
            "fee_rate": fee_rate,
            "quantity": quantity,
            "balance_age_s": facts.balance_age_s,
            "price_age_s": facts.price_age_s,
            "book_age_s": facts.book_age_s,
            "max_age_s": settings.max_age_s,
            "active_method": facts.active_method,
            "change_in_progress": facts.change_in_progress,
            "frequency": facts.frequency,
            "min_volume_eur": settings.min_volume_eur,
            "trade_count": facts.trade_count,
            "survival_flag": facts.survival_flag,
            "hard_stop_active": facts.hard_stop_active,
            "open_risk": facts.open_risk,
            "open_notional": facts.open_notional,
            "quantity_step": settings.quantity_step,
            "min_quantity": settings.min_quantity,
            "stake_fraction": stake_fraction,
            "exposure_fraction": exposure_fraction,
            "min_order_size_quote": settings.min_order_size_quote,
            "max_order_size": settings.max_order_size,
            "max_order_size_quote": settings.max_order_size_quote,
        },
        quantity,
    )
    if not paper and on_accept is not None:
        on_accept(quantity)
    return decision


def _quot_down(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.rounding = ROUND_DOWN
        return _finite(numerator) / _finite(denominator)


def _logged(
    code: str,
    values: Mapping[str, object],
    quantity: Decimal | None,
) -> Decision:
    _LOG.info("%s", _line(code, values))
    return Decision(code, quantity)


def _line(code: str, values: Mapping[str, object]) -> str:
    parts = [f"code={code}"]
    for name, value in values.items():
        parts.append(f"{name}={_render(value)}")
    return " ".join(parts)


def _render(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if value is None:
        return "absent"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    raise TypeError("valeur de journal non prise en charge")


def _finite(value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("Decimal requis")
    if not value.is_finite():
        raise ValueError("décimal non fini")
    return value
