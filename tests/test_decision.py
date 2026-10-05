import logging
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from pathlib import Path

from tradingbot import decision as decision_module
from tradingbot import evaluation, ledger, sizing, startup
from tradingbot.decision import (
    Decision,
    Facts,
    Intent,
    RulesConfig,
    decide,
    min_order_fits_risk,
    r5_risk_cap,
    r6_stake_cap,
)
from tradingbot.sizing import bootstrap_quantity

_SECRET = "super-secret-revolut-key"


class DecisionTest(unittest.TestCase):
    def test_intent_has_no_quantity(self) -> None:
        self.assertEqual(
            Intent._fields,
            ("method", "pair", "side", "stop_price", "annotation"),
        )
        self.assertNotIn("entry_price", Intent._fields)

    def test_refusal_is_logged_with_code_and_values_not_secret(self) -> None:
        facts = _facts(balance_age_s=Decimal("11"))
        with _logs() as lines:
            decision = decide(_intent(), facts)
        self.assertEqual(decision, Decision("STALE_DATA", None))
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIn("code=STALE_DATA", line)
        self.assertIn("balance_age_s=11", line)
        self.assertIn("max_age_s=10", line)
        self.assertNotIn(_SECRET, line)
        self.assertNotIn("annotation", line)
        self.assertNotIn("SURVIVAL_STATE", line)

    def test_acceptance_is_logged_with_values_not_secret(self) -> None:
        intent = _intent()
        facts = _facts()
        with _logs() as lines:
            decision = decide(intent, facts)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(decision.code, "ACCEPT")
        self.assertIsInstance(decision.quantity, Decimal)
        assert decision.quantity is not None
        self.assertIn("code=ACCEPT", line)
        self.assertIn(f"quantity={format(decision.quantity, 'f')}", line)
        self.assertIn("entry_price=100", line)
        self.assertIn("fee_rate=0.001", line)
        self.assertIn("capital=1000", line)
        self.assertNotIn(_SECRET, line)
        self.assertNotIn("annotation", line)
        self.assertNotIn("0.0009", line)
        assert intent.stop_price is not None
        self.assertEqual(
            decision.quantity,
            bootstrap_quantity(
                facts.capital,
                facts.entry_price,
                intent.stop_price,
                facts.fee_rate,
                facts.trade_count,
            ),
        )

    def test_fresh_data_is_not_stale(self) -> None:
        facts = _facts(
            balance_age_s=Decimal("9.999"),
            price_age_s=Decimal("9.999"),
            book_age_s=Decimal("9.999"),
        )
        self.assertEqual(decide(_intent(), facts).code, "ACCEPT")

    def test_age_equal_to_n_is_stale(self) -> None:
        for field in ("balance_age_s", "price_age_s", "book_age_s"):
            with self.subTest(field=field):
                facts = _facts(**{field: Decimal("10")})
                self.assertEqual(decide(_intent(), facts).code, "STALE_DATA")

    def test_each_feed_older_than_n_is_stale(self) -> None:
        for field in ("balance_age_s", "price_age_s", "book_age_s"):
            with self.subTest(field=field):
                facts = _facts(**{field: Decimal("10.0000001")})
                self.assertEqual(decide(_intent(), facts).code, "STALE_DATA")

    def test_missing_age_is_stale(self) -> None:
        for field in ("balance_age_s", "price_age_s", "book_age_s"):
            with self.subTest(field=field):
                with _logs() as lines:
                    decision = decide(_intent(), _facts(**{field: None}))
                self.assertEqual(decision.code, "STALE_DATA")
                self.assertIn(f"{field}=absent", lines[0])

    def test_max_age_is_configurable(self) -> None:
        facts = _facts(price_age_s=Decimal("12"))
        self.assertEqual(decide(_intent(), facts).code, "STALE_DATA")
        allowed = decide(_intent(), facts, RulesConfig(max_age_s=Decimal("13")))
        self.assertEqual(allowed.code, "ACCEPT")
        equal = decide(_intent(), facts, RulesConfig(max_age_s=Decimal("12")))
        self.assertEqual(equal.code, "STALE_DATA")
        still = decide(_intent(), facts, RulesConfig(max_age_s=Decimal("11")))
        self.assertEqual(still.code, "STALE_DATA")

    def test_active_method_without_change_is_not_inactive(self) -> None:
        self.assertEqual(decide(_intent(), _facts()).code, "ACCEPT")

    def test_other_method_is_inactive(self) -> None:
        decision = decide(_intent(method="other"), _facts())
        self.assertEqual(decision.code, "METHOD_INACTIVE")

    def test_method_change_in_progress_is_inactive(self) -> None:
        facts = _facts(change_in_progress=True)
        self.assertEqual(decide(_intent(), facts).code, "METHOD_INACTIVE")

    def test_declared_pair_and_frequency_are_compatible(self) -> None:
        self.assertEqual(decide(_intent(), _facts()).code, "ACCEPT")

    def test_pair_outside_mandate_is_incompatible(self) -> None:
        decision = decide(_intent(pair="ETH-EUR"), _facts())
        self.assertEqual(decision.code, "METHOD_INCOMPATIBLE")

    def test_frequency_outside_mandate_is_incompatible(self) -> None:
        facts = _facts(frequency="1m")
        self.assertEqual(decide(_intent(), facts).code, "METHOD_INCOMPATIBLE")

    def test_spread_below_cap_is_not_filtered(self) -> None:
        facts = _facts(spread=Decimal("0.001999"))
        self.assertEqual(decide(_intent(), facts).code, "ACCEPT")

    def test_spread_at_and_above_cap_is_filtered(self) -> None:
        for spread in (Decimal("0.002"), Decimal("0.0021")):
            with self.subTest(spread=spread):
                with _logs() as lines:
                    decision = decide(_intent(), _facts(spread=spread))
                self.assertEqual(decision.code, "PAIR_FILTER")
                self.assertIn("spread_cap=0.002", lines[0])
                self.assertNotIn("min_volume_eur", lines[0])

    def test_spread_cap_is_not_a_config_knob(self) -> None:
        facts = _facts(spread=Decimal("0.002"), volume_24h=Decimal("1"))
        decision = decide(_intent(), facts, RulesConfig(min_volume_eur=Decimal("1")))
        self.assertEqual(decision.code, "PAIR_FILTER")

    def test_volume_at_minimum_is_not_filtered(self) -> None:
        facts = _facts(volume_24h=Decimal("100000"))
        self.assertEqual(decide(_intent(), facts).code, "ACCEPT")

    def test_volume_under_minimum_is_filtered(self) -> None:
        with _logs() as lines:
            decision = decide(_intent(), _facts(volume_24h=Decimal("99999.99")))
        self.assertEqual(decision.code, "PAIR_FILTER")
        self.assertIn("volume_24h=99999.99", lines[0])
        self.assertIn("min_volume_eur=100000", lines[0])

    def test_min_volume_is_configurable(self) -> None:
        facts = _facts(volume_24h=Decimal("50000"))
        self.assertEqual(decide(_intent(), facts).code, "PAIR_FILTER")
        allowed = decide(
            _intent(),
            facts,
            RulesConfig(min_volume_eur=Decimal("50000")),
        )
        self.assertEqual(allowed.code, "ACCEPT")
        still = decide(
            _intent(),
            facts,
            RulesConfig(min_volume_eur=Decimal("50001")),
        )
        self.assertEqual(still.code, "PAIR_FILTER")

    def test_stop_on_the_correct_side_passes(self) -> None:
        buy = decide(_intent(side="buy", stop_price=Decimal("99.99")), _facts())
        sell = decide(_intent(side="sell", stop_price=Decimal("100.01")), _facts())
        self.assertEqual(buy.code, "ACCEPT")
        self.assertEqual(sell.code, "ACCEPT")

    def test_missing_or_wrong_side_stop_is_refused(self) -> None:
        cases = (
            _intent(side="buy", stop_price=None),
            _intent(side="buy", stop_price=Decimal("100")),
            _intent(side="buy", stop_price=Decimal("101")),
            _intent(side="sell", stop_price=None),
            _intent(side="sell", stop_price=Decimal("100")),
            _intent(side="sell", stop_price=Decimal("99")),
            _intent(side="hold", stop_price=Decimal("90")),
        )
        for intent in cases:
            with self.subTest(intent=intent):
                self.assertEqual(decide(intent, _facts()).code, "NO_STOP")

    def test_clear_survival_state_passes(self) -> None:
        self.assertEqual(decide(_intent(), _facts()).code, "ACCEPT")

    def test_survival_flag_or_hard_stop_is_refused(self) -> None:
        flagged = _facts(survival_flag=True, hard_stop_active=False)
        stopped = _facts(survival_flag=False, hard_stop_active=True)
        both = _facts(survival_flag=True, hard_stop_active=True)
        self.assertEqual(decide(_intent(), flagged).code, "SURVIVAL_STATE")
        self.assertEqual(decide(_intent(), stopped).code, "SURVIVAL_STATE")
        self.assertEqual(decide(_intent(), both).code, "SURVIVAL_STATE")

    def test_first_refusal_wins(self) -> None:
        stale = _facts(balance_age_s=Decimal("11"), survival_flag=True)
        with _logs() as lines:
            decision = decide(_intent(), stale)
        self.assertEqual(decision.code, "STALE_DATA")
        self.assertNotIn("SURVIVAL_STATE", lines[0])

        with _logs() as lines:
            decision = decide(_intent(method="other", pair="ETH-EUR"), _facts())
        self.assertEqual(decision.code, "METHOD_INACTIVE")
        self.assertNotIn("METHOD_INCOMPATIBLE", lines[0])

    def test_bootstrap_limit_does_not_hide_an_earlier_refusal(self) -> None:
        facts = _facts(book_age_s=Decimal("50"), trade_count=30)
        self.assertEqual(decide(_intent(), facts).code, "STALE_DATA")

    def test_thirty_trades_is_not_bootstrap_acceptance(self) -> None:
        with _logs() as lines:
            with self.assertRaises(ValueError):
                decide(_intent(), _facts(trade_count=30))
        self.assertNotIn("ACCEPT", "\n".join(lines))

    def test_float_and_non_finite_do_not_pass(self) -> None:
        with self.assertRaises(TypeError):
            decide(_intent(), _facts(spread=0.001))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            decide(_intent(), _facts(spread=Decimal("NaN")))

    def test_provided_fee_is_used_and_missing_fee_does_not_size(self) -> None:
        low = decide(_intent(), _facts(fee_rate=Decimal("0")))
        high = decide(_intent(), _facts(fee_rate=Decimal("0.01")))
        assert low.quantity is not None and high.quantity is not None
        self.assertGreater(low.quantity, high.quantity)
        with _logs() as lines:
            missing = decide(
                _intent(),
                _facts(fee_rate=None, trade_count=30, survival_flag=True),
                paper=False,
                on_accept=lambda _quantity: self.fail("envoi"),
            )
        self.assertEqual(missing, Decision("FEE_UNAVAILABLE", None))
        self.assertIn("fee_rate=absent", lines[0])
        self.assertNotIn("SURVIVAL_STATE", lines[0])
        source = Path(decision_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("0.0009", source)
        self.assertNotIn("0.09", source)

    def test_missing_fee_loses_to_an_earlier_refusal(self) -> None:
        facts = _facts(fee_rate=None, book_age_s=None)
        self.assertEqual(decide(_intent(), facts).code, "STALE_DATA")
        stopped = decide(_intent(stop_price=None), _facts(fee_rate=None))
        self.assertEqual(stopped.code, "NO_STOP")

    def test_step_rounds_down_and_absent_step_does_not(self) -> None:
        intent = _intent()
        facts = _facts()
        assert intent.stop_price is not None
        raw = bootstrap_quantity(
            facts.capital,
            facts.entry_price,
            intent.stop_price,
            facts.fee_rate,
            facts.trade_count,
        )
        assert isinstance(facts.fee_rate, Decimal)
        step = Decimal("0.01")
        decision = decide(_intent(), facts, RulesConfig(quantity_step=step))
        self.assertEqual(decision.code, "ACCEPT")
        assert decision.quantity is not None
        self.assertEqual(decision.quantity, (raw // step) * step)
        self.assertLess(decision.quantity, raw)
        self.assertEqual(decision.quantity % step, 0)
        untouched = decide(_intent(), facts)
        self.assertEqual(untouched.quantity, raw)

    def test_quantity_under_minimum_is_refused_after_step(self) -> None:
        at_min = decide(
            _intent(),
            _facts(),
            RulesConfig(min_quantity=Decimal("0.01")),
        )
        self.assertEqual(at_min.code, "ACCEPT")
        under = decide(
            _intent(),
            _facts(),
            RulesConfig(min_quantity=Decimal("2")),
        )
        self.assertEqual(under, Decision("BELOW_MIN_SIZE", None))
        rounded_under = decide(
            _intent(),
            _facts(),
            RulesConfig(quantity_step=Decimal("0.5"), min_quantity=Decimal("0.9")),
        )
        self.assertEqual(rounded_under.code, "BELOW_MIN_SIZE")
        exact = decide(
            _intent(),
            _facts(),
            RulesConfig(quantity_step=Decimal("0.5"), min_quantity=Decimal("0.5")),
        )
        self.assertEqual(exact.quantity, Decimal("0.5"))

    def test_risk_cap_includes_open_risk_and_fees(self) -> None:
        self.assertEqual(decide(_intent(), _facts(open_risk=Decimal("0"))).code, "ACCEPT")
        over = decide(_intent(), _facts(open_risk=Decimal("0.01")))
        self.assertEqual(over.code, "RISK_CAP")
        room = _facts(
            entry_price=Decimal("100"),
            fee_rate=Decimal("0"),
            open_risk=Decimal("8"),
        )
        # stop à 1 : la mise bootstrap (1) laisse de la place sous 1 % de 1000.
        held = decide(_intent(stop_price=Decimal("99")), room)
        self.assertEqual(held.code, "ACCEPT")
        consumed = decide(
            _intent(stop_price=Decimal("99")),
            room._replace(open_risk=Decimal("9.01")),
        )
        self.assertEqual(consumed.code, "RISK_CAP")
        with _logs() as lines:
            both = decide(_intent(), _facts(open_risk=Decimal("1"), survival_flag=True))
        self.assertEqual(both.code, "RISK_CAP")
        self.assertNotIn("SURVIVAL_STATE", lines[0])

    def test_stake_cap_refuses_a_quantity_above_the_fraction(self) -> None:
        self.assertEqual(
            r6_stake_cap(
                Decimal("2"),
                Decimal("100"),
                Decimal("1000"),
                Decimal("0.10"),
            ),
            "STAKE_CAP",
        )
        self.assertIsNone(
            r6_stake_cap(
                Decimal("1"),
                Decimal("100"),
                Decimal("1000"),
                Decimal("0.10"),
            )
        )
        self.assertEqual(decide(_intent(), _facts()).code, "ACCEPT")
        tight = decide(
            _intent(),
            _facts(),
            RulesConfig(stake_fraction=Decimal("0.09")),
        )
        self.assertEqual(tight.code, "STAKE_CAP")

    def test_exposure_cap_default_is_one_quarter(self) -> None:
        self.assertEqual(RulesConfig().exposure_fraction, Decimal("0.25"))
        self.assertEqual(
            decide(_intent(), _facts(open_notional=Decimal("0"))).code,
            "ACCEPT",
        )
        # Mise bootstrap exacte de 100, ouvert de 150 : pile 25 % de 1000.
        level = _facts(
            fee_rate=Decimal("0"),
            open_notional=Decimal("150"),
        )
        exact = decide(_intent(stop_price=Decimal("99")), level)
        self.assertEqual(exact.code, "ACCEPT")
        over = decide(
            _intent(stop_price=Decimal("99")),
            level._replace(open_notional=Decimal("150.01")),
        )
        self.assertEqual(over.code, "EXPOSURE_CAP")

    def test_cap_binding_quantities_stay_inside_the_budget(self) -> None:
        stake = decide(
            _intent(stop_price=Decimal("3.0969")),
            _facts(
                capital=Decimal("3190.00"),
                entry_price=Decimal("3.1"),
                fee_rate=Decimal("0"),
            ),
        )
        self.assertEqual(stake.code, "ACCEPT")
        assert stake.quantity is not None
        self.assertLessEqual(
            stake.quantity * Decimal("3.1"),
            Decimal("0.10") * Decimal("3190.00"),
        )
        risk = decide(
            _intent(stop_price=Decimal("1")),
            _facts(
                capital=Decimal("250.5"),
                entry_price=Decimal("3"),
                fee_rate=Decimal("0.002"),
                open_risk=Decimal("0"),
            ),
        )
        self.assertEqual(risk.code, "ACCEPT")
        assert risk.quantity is not None
        denominator = abs(Decimal("3") - Decimal("1")) + Decimal("0.002") * (
            Decimal("3") + Decimal("1")
        )
        self.assertLessEqual(risk.quantity * denominator, Decimal("0.01") * Decimal("250.5"))

    def test_negative_aggregate_or_fraction_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            decide(_intent(), _facts(open_risk=Decimal("-0.01")))
        with self.assertRaises(ValueError):
            decide(_intent(), _facts(open_notional=Decimal("-1")))
        with self.assertRaises(ValueError):
            decide(_intent(), _facts(), RulesConfig(stake_fraction=Decimal("0")))
        with self.assertRaises(ValueError):
            decide(_intent(), _facts(), RulesConfig(stake_fraction=Decimal("-0.1")))
        with self.assertRaises(ValueError):
            decide(_intent(), _facts(), RulesConfig(exposure_fraction=Decimal("0")))
        with self.assertRaises(ValueError):
            decide(_intent(), _facts(), RulesConfig(exposure_fraction=Decimal("-0.25")))
        self.assertEqual(RulesConfig().stake_fraction, Decimal("0.10"))
        self.assertEqual(RulesConfig().exposure_fraction, Decimal("0.25"))
        self.assertEqual(decide(_intent(), _facts()).code, "ACCEPT")

    def test_zero_quantity_after_step_is_refused(self) -> None:
        sent: list[Decimal] = []
        decision = decide(
            _intent(),
            _facts(),
            RulesConfig(quantity_step=Decimal("1000")),
            paper=False,
            on_accept=sent.append,
        )
        self.assertEqual(decision, Decision("BELOW_MIN_SIZE", None))
        self.assertEqual(sent, [])

    def test_paper_default_does_not_send_and_live_sends_once(self) -> None:
        sent: list[Decimal] = []
        accepted = decide(_intent(), _facts(), on_accept=sent.append)
        self.assertEqual(accepted.code, "ACCEPT")
        self.assertEqual(sent, [])
        self.assertIs(decide.__kwdefaults__["paper"], True)  # type: ignore[index]
        live = decide(_intent(), _facts(), paper=False, on_accept=sent.append)
        assert live.quantity is not None
        self.assertEqual(sent, [live.quantity])
        decide(
            _intent(),
            _facts(balance_age_s=Decimal("11")),
            paper=False,
            on_accept=sent.append,
        )
        decide(
            _intent(),
            _facts(open_risk=Decimal("1")),
            paper=False,
            on_accept=sent.append,
        )
        stepped = decide(
            _intent(),
            _facts(),
            RulesConfig(quantity_step=Decimal("0.01")),
            paper=False,
            on_accept=sent.append,
        )
        self.assertEqual(sent, [live.quantity, stepped.quantity])

    def test_first_broken_rule_wins_and_writes_nothing(self) -> None:
        sent: list[Decimal] = []

        def refuse(
            intent: Intent,
            facts: Facts,
            config: RulesConfig | None = None,
        ) -> tuple[Decision, str]:
            with _logs() as lines:
                decision = decide(
                    intent,
                    facts,
                    config,
                    paper=False,
                    on_accept=sent.append,
                )
            self.assertEqual(sent, [])
            self.assertIsNone(decision.quantity)
            self.assertNotEqual(decision.code, "ACCEPT")
            self.assertEqual(len(lines), 1)
            return decision, lines[0]

        decision, line = refuse(
            _intent(stop_price=None),
            _facts(balance_age_s=Decimal("11"), trade_count=30),
        )
        self.assertEqual(decision.code, "STALE_DATA")
        self.assertNotIn("NO_STOP", line)

        decision, line = refuse(
            _intent(method="other", pair="ETH-EUR", stop_price=None),
            _facts(spread=Decimal("0.002"), volume_24h=Decimal("1"), fee_rate=None),
        )
        self.assertEqual(decision.code, "METHOD_INACTIVE")
        self.assertNotIn("METHOD_INCOMPATIBLE", line)
        self.assertNotIn("PAIR_FILTER", line)

        decision, line = refuse(
            _intent(pair="ETH-EUR", stop_price=None),
            _facts(spread=Decimal("0.002"), volume_24h=Decimal("1"), fee_rate=None),
        )
        self.assertEqual(decision.code, "METHOD_INCOMPATIBLE")
        self.assertNotIn("PAIR_FILTER", line)

        decision, line = refuse(
            _intent(stop_price=None),
            _facts(spread=Decimal("0.002"), volume_24h=Decimal("1"), fee_rate=None),
        )
        self.assertEqual(decision.code, "PAIR_FILTER")
        self.assertIn("spread_cap=0.002", line)
        self.assertNotIn("min_volume_eur", line)
        self.assertNotIn("NO_STOP", line)

        decision, line = refuse(
            _intent(stop_price=None),
            _facts(volume_24h=Decimal("1"), fee_rate=None, survival_flag=True),
        )
        self.assertEqual(decision.code, "PAIR_FILTER")
        self.assertIn("volume_24h=1", line)
        self.assertNotIn("NO_STOP", line)
        self.assertNotIn("SURVIVAL_STATE", line)

        decision, line = refuse(
            _intent(stop_price=None),
            _facts(fee_rate=None, survival_flag=True),
            RulesConfig(min_quantity=Decimal("999")),
        )
        self.assertEqual(decision.code, "NO_STOP")
        self.assertNotIn("FEE_UNAVAILABLE", line)
        self.assertNotIn("BELOW_MIN_SIZE", line)

        decision, line = refuse(
            _intent(),
            _facts(fee_rate=None, trade_count=30, survival_flag=True),
            RulesConfig(quantity_step=Decimal("-1"), min_quantity=Decimal("999")),
        )
        self.assertEqual(decision.code, "FEE_UNAVAILABLE")
        self.assertNotIn("BELOW_MIN_SIZE", line)
        self.assertNotIn("SURVIVAL_STATE", line)

        decision, line = refuse(
            _intent(),
            _facts(open_risk=Decimal("100"), survival_flag=True),
            RulesConfig(quantity_step=Decimal("1000"), min_quantity=Decimal("0.01")),
        )
        self.assertEqual(decision.code, "BELOW_MIN_SIZE")
        self.assertNotIn("min_quantity", line)
        self.assertNotIn("RISK_CAP", line)
        self.assertNotIn("SURVIVAL_STATE", line)

        decision, line = refuse(
            _intent(),
            _facts(open_risk=Decimal("100"), survival_flag=True),
            RulesConfig(
                quantity_step=Decimal("0.5"),
                min_quantity=Decimal("0.9"),
                stake_fraction=Decimal("0.01"),
            ),
        )
        self.assertEqual(decision.code, "BELOW_MIN_SIZE")
        self.assertIn("min_quantity=0.9", line)
        self.assertNotIn("RISK_CAP", line)
        self.assertNotIn("STAKE_CAP", line)
        self.assertNotIn("SURVIVAL_STATE", line)

        decision, line = refuse(
            _intent(),
            _facts(open_risk=Decimal("1"), open_notional=Decimal("1000"), survival_flag=True),
            RulesConfig(stake_fraction=Decimal("0.09")),
        )
        self.assertEqual(decision.code, "RISK_CAP")
        self.assertNotIn("STAKE_CAP", line)
        self.assertNotIn("EXPOSURE_CAP", line)
        self.assertNotIn("SURVIVAL_STATE", line)

        decision, line = refuse(
            _intent(),
            _facts(open_notional=Decimal("1000"), survival_flag=True),
            RulesConfig(stake_fraction=Decimal("0.09")),
        )
        self.assertEqual(decision.code, "STAKE_CAP")
        self.assertNotIn("EXPOSURE_CAP", line)
        self.assertNotIn("SURVIVAL_STATE", line)

        decision, line = refuse(
            _intent(),
            _facts(open_notional=Decimal("200"), survival_flag=True),
        )
        self.assertEqual(decision.code, "EXPOSURE_CAP")
        self.assertNotIn("SURVIVAL_STATE", line)

    def test_hard_stop_is_min_size_against_the_risk_cap(self) -> None:
        entry = Decimal("100")
        stop = Decimal("90")
        fee = Decimal("0.001")
        capital = Decimal("1000")
        self.assertTrue(
            min_order_fits_risk(
                Decimal("0.01"),
                entry,
                stop,
                fee,
                capital,
                Decimal("0"),
            )
        )
        allowed = decide(
            _intent(),
            _facts(survival_flag=False, hard_stop_active=False),
            RulesConfig(min_quantity=Decimal("0.01")),
        )
        self.assertEqual(allowed.code, "ACCEPT")
        survived = decide(
            _intent(),
            _facts(survival_flag=True, hard_stop_active=False),
            RulesConfig(min_quantity=Decimal("0.01")),
        )
        self.assertEqual(survived.code, "SURVIVAL_STATE")
        self.assertTrue(
            min_order_fits_risk(
                Decimal("0.01"),
                entry,
                stop,
                fee,
                capital,
                Decimal("0"),
            )
        )

        self.assertFalse(
            min_order_fits_risk(
                Decimal("2"),
                entry,
                stop,
                fee,
                capital,
                Decimal("0"),
            )
        )
        sent: list[Decimal] = []
        blocked = decide(
            _intent(),
            _facts(survival_flag=False, hard_stop_active=False),
            RulesConfig(min_quantity=Decimal("2")),
            paper=False,
            on_accept=sent.append,
        )
        self.assertEqual(blocked, Decision("BELOW_MIN_SIZE", None))
        self.assertEqual(sent, [])
        self.assertNotEqual(
            decide(
                _intent(),
                _facts(),
                RulesConfig(min_quantity=Decimal("2")),
            ).code,
            "ACCEPT",
        )

        self.assertTrue(
            min_order_fits_risk(
                Decimal("0.5"),
                Decimal("100"),
                Decimal("99"),
                Decimal("0"),
                capital,
                Decimal("9.2"),
            )
        )
        capped = decide(
            _intent(stop_price=Decimal("99")),
            _facts(
                entry_price=Decimal("100"),
                fee_rate=Decimal("0"),
                open_risk=Decimal("9.2"),
                survival_flag=True,
            ),
            RulesConfig(min_quantity=Decimal("0.5")),
        )
        self.assertEqual(capped.code, "RISK_CAP")

        self.assertFalse(
            min_order_fits_risk(
                Decimal("0.8"),
                Decimal("100"),
                Decimal("99"),
                Decimal("0"),
                capital,
                Decimal("9.5"),
            )
        )
        impossible = decide(
            _intent(stop_price=Decimal("99")),
            _facts(
                entry_price=Decimal("100"),
                fee_rate=Decimal("0"),
                open_risk=Decimal("9.5"),
                survival_flag=False,
                hard_stop_active=False,
            ),
            RulesConfig(min_quantity=Decimal("0.8")),
            paper=False,
            on_accept=sent.append,
        )
        self.assertEqual(impossible, Decision("BELOW_MIN_SIZE", None))
        self.assertEqual(sent, [])

    def test_half_kelly_sizes_from_thirty_trades(self) -> None:
        multiples = [Decimal("10")] * 16 + [Decimal("-10")] * 14
        early = decide(
            _intent(),
            _facts(trade_count=29, fee_rate=Decimal("0")),
            RulesConfig(stake_fraction=Decimal("0.25")),
            r_multiples=multiples,
        )
        assert early.quantity is not None
        self.assertEqual(early.quantity, Decimal("1"))
        tight = decide(
            _intent(),
            _facts(trade_count=30, fee_rate=Decimal("0")),
            r_multiples=multiples,
        )
        assert tight.quantity is not None
        self.assertLess(abs(tight.quantity - Decimal(1) / Decimal(3)), Decimal("1e-18"))
        sized = decide(
            _intent(),
            _facts(trade_count=30, entry_price=Decimal("100"), fee_rate=Decimal("0")),
            RulesConfig(stake_fraction=Decimal("0.25")),
            r_multiples=([Decimal("1")] * 30),
        )
        self.assertEqual(sized.quantity, Decimal("1"))
        wide = decide(
            _intent(stop_price=Decimal("99")),
            _facts(trade_count=30, entry_price=Decimal("100"), fee_rate=Decimal("0")),
            RulesConfig(stake_fraction=Decimal("0.25")),
            r_multiples=([Decimal("1")] * 30),
        )
        self.assertEqual(wide.quantity, Decimal("2.5"))
        sent: list[Decimal] = []
        refused = decide(
            _intent(),
            _facts(trade_count=30),
            r_multiples=([Decimal("0")] * 30),
            paper=False,
            on_accept=sent.append,
        )
        self.assertEqual(refused, Decision("METHOD_CHANGE_REQUIRED", None))
        self.assertEqual(sent, [])
        with self.assertRaises(ValueError):
            decide(
                _intent(),
                _facts(trade_count=30, fee_rate=Decimal("0")),
                RulesConfig(stake_fraction=Decimal("0")),
                r_multiples=([Decimal("1")] * 30),
            )
        with self.assertRaises(ValueError):
            decide(
                _intent(),
                _facts(trade_count=30, fee_rate=Decimal("0")),
                RulesConfig(stake_fraction=Decimal("-0.1")),
                r_multiples=([Decimal("1")] * 30),
            )

    def test_sized_quotient_stays_inside_the_risk_cap(self) -> None:
        sent: list[Decimal] = []
        decision = decide(
            _intent(stop_price=Decimal("86")),
            _facts(
                trade_count=30,
                capital=Decimal("200"),
                entry_price=Decimal("100"),
                fee_rate=Decimal("0"),
            ),
            r_multiples=([Decimal("1")] * 30),
            paper=False,
            on_accept=sent.append,
        )
        self.assertEqual(decision.code, "ACCEPT")
        assert decision.quantity is not None
        self.assertLessEqual(decision.quantity * Decimal("14"), Decimal("2"))
        self.assertIsNone(
            r5_risk_cap(
                decision.quantity,
                Decimal("100"),
                Decimal("86"),
                Decimal("0"),
                Decimal("200"),
                Decimal("0"),
            )
        )
        self.assertEqual(sent, [decision.quantity])

    def test_survival_breach_refuses_only_the_outgoing_method(self) -> None:
        sent: list[Decimal] = []
        blocked = decide(
            _intent(),
            _facts(hard_stop_active=False, survival_flag=False),
            outgoing_method="m1",
            paper=False,
            on_accept=sent.append,
        )
        self.assertEqual(blocked.code, "SURVIVAL_STATE")
        self.assertIsNone(blocked.quantity)
        self.assertEqual(sent, [])
        other = _facts(active_method="m2")
        allowed = decide(
            _intent(method="m2"),
            other,
            outgoing_method="m1",
        )
        self.assertEqual(allowed.code, "ACCEPT")
        self.assertFalse(other.hard_stop_active)

    def test_upper_bounds_cannot_be_loosened(self) -> None:
        sized = decide(
            _intent(stop_price=Decimal("99")),
            _facts(
                trade_count=30,
                entry_price=Decimal("100"),
                capital=Decimal("1000"),
                fee_rate=Decimal("0"),
            ),
            RulesConfig(
                stake_fraction=Decimal("0.40"),
                exposure_fraction=Decimal("0.50"),
            ),
            r_multiples=[Decimal("1")] * 30,
        )
        self.assertEqual(sized.code, "ACCEPT")
        self.assertEqual(sized.quantity, Decimal("2.5"))
        sent: list[Decimal] = []
        exposed = decide(
            _intent(),
            _facts(open_notional=Decimal("700")),
            RulesConfig(exposure_fraction=Decimal("0.90")),
            paper=False,
            on_accept=sent.append,
        )
        self.assertEqual(exposed.code, "EXPOSURE_CAP")
        self.assertEqual(sent, [])
        self.assertEqual(
            decide(
                _intent(),
                _facts(),
                RulesConfig(stake_fraction=Decimal("0.09")),
            ).code,
            "STAKE_CAP",
        )

    def test_caller_supplies_quote_min_and_max_size(self) -> None:
        sent: list[Decimal] = []
        wide = _facts(capital=Decimal("100"), fee_rate=Decimal("0"))
        sell = _intent(side="sell", stop_price=Decimal("10000"))
        step = Decimal("0.00000001")
        bare = decide(
            sell,
            wide,
            RulesConfig(quantity_step=step, min_quantity=step),
            paper=False,
            on_accept=sent.append,
        )
        self.assertEqual(bare.code, "ACCEPT")
        assert bare.quantity is not None
        self.assertLess(bare.quantity * wide.entry_price, Decimal("0.1"))
        self.assertEqual(sent, [bare.quantity])
        blocked = decide(
            sell,
            wide,
            RulesConfig(
                quantity_step=step,
                min_quantity=step,
                min_order_size_quote=Decimal("0.1"),
            ),
            paper=False,
            on_accept=sent.append,
        )
        self.assertEqual(blocked, Decision("BELOW_MIN_SIZE", None))
        self.assertEqual(sent, [bare.quantity])
        small = _facts(capital=Decimal("5"), fee_rate=Decimal("0"))
        self.assertEqual(
            decide(_intent(stop_price=Decimal("1")), small).code,
            "ACCEPT",
        )
        self.assertEqual(
            decide(
                _intent(stop_price=Decimal("1")),
                small,
                RulesConfig(min_order_size_quote=Decimal("0.1")),
            ).code,
            "BELOW_MIN_SIZE",
        )
        self.assertEqual(
            decide(
                _intent(),
                _facts(),
                RulesConfig(max_order_size=Decimal("0.5")),
                paper=False,
                on_accept=sent.append,
            ),
            Decision("BELOW_MIN_SIZE", None),
        )
        self.assertEqual(
            decide(
                _intent(),
                _facts(fee_rate=Decimal("0")),
                RulesConfig(max_order_size_quote=Decimal("50")),
                paper=False,
                on_accept=sent.append,
            ),
            Decision("BELOW_MIN_SIZE", None),
        )
        self.assertEqual(sent, [bare.quantity])
        allowed = decide(
            _intent(),
            _facts(),
            RulesConfig(
                max_order_size=Decimal("1000"),
                max_order_size_quote=Decimal("100000"),
            ),
        )
        self.assertEqual(allowed.code, "ACCEPT")

    def test_paper_accept_does_not_place_a_native_stop_or_reach_revolut(self) -> None:
        sent: list[Decimal] = []
        decision = decide(_intent(), _facts(), on_accept=sent.append)
        self.assertEqual(decision.code, "ACCEPT")
        self.assertIsNotNone(decision.quantity)
        self.assertEqual(sent, [])
        forbidden = (
            "tpsl",
            "on_fill",
            "placeOrder",
            "revx.revolut.com",
            "urllib.request",
            "http.client",
        )
        for module in (decision_module, sizing, ledger, evaluation, startup):
            path = module.__file__
            self.assertIsNotNone(path)
            assert path is not None
            source = Path(path).read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, source, module.__name__)


def _intent(**overrides: object) -> Intent:
    base = Intent(
        method="m1",
        pair="BTC-EUR",
        side="buy",
        stop_price=Decimal("90"),
        annotation=_SECRET,
    )
    if not overrides:
        return base
    return base._replace(**overrides)


def _facts(**overrides: object) -> Facts:
    base = Facts(
        balance_age_s=Decimal("1"),
        price_age_s=Decimal("1"),
        book_age_s=Decimal("1"),
        entry_price=Decimal("100"),
        spread=Decimal("0.001"),
        volume_24h=Decimal("100000"),
        capital=Decimal("1000"),
        fee_rate=Decimal("0.001"),
        active_method="m1",
        change_in_progress=False,
        frequency="1h",
        declared_pairs=frozenset({"BTC-EUR"}),
        declared_frequencies=frozenset({"1h"}),
        trade_count=0,
        survival_flag=False,
        hard_stop_active=False,
    )
    if not overrides:
        return base
    return base._replace(**overrides)


class _ListHandler(logging.Handler):
    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self._lines = lines

    def emit(self, record: logging.LogRecord) -> None:
        self._lines.append(record.getMessage())


@contextmanager
def _logs() -> Iterator[list[str]]:
    logger = logging.getLogger("tradingbot.decision")
    previous_level = logger.level
    previous_propagate = logger.propagate
    logger.setLevel(logging.INFO)
    logger.propagate = False
    lines: list[str] = []
    handler = _ListHandler(lines)
    logger.addHandler(handler)
    try:
        yield lines
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


if __name__ == "__main__":
    unittest.main()
