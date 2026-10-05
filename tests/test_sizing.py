import unittest
from decimal import Decimal
from pathlib import Path

from tradingbot import sizing
from tradingbot.sizing import bootstrap_quantity, empirical_kelly, half_kelly_risk


class BootstrapQuantityTest(unittest.TestCase):
    def test_quantity_is_the_min_of_risk_and_stake(self) -> None:
        capital = Decimal("1000")
        entry = Decimal("100")
        stop = Decimal("50")
        fee = Decimal("0.01")
        quantity = bootstrap_quantity(capital, entry, stop, fee, 0)
        risk = Decimal("0.01") * capital / (abs(entry - stop) + fee * (entry + stop))
        stake = Decimal("0.10") * capital / entry
        self.assertEqual(quantity, min(risk, stake))
        self.assertEqual(quantity, risk)
        self.assertIsInstance(quantity, Decimal)
        self.assertNotEqual(quantity, quantity.to_integral_value())

    def test_stake_term_uses_ten_percent_under_thirty_trades(self) -> None:
        capital = Decimal("1000")
        entry = Decimal("100")
        stop = Decimal("99")
        quantity = bootstrap_quantity(capital, entry, stop, Decimal("0"), 29)
        self.assertEqual(quantity, Decimal("0.10") * capital / entry)

    def test_fee_changes_the_risk_term(self) -> None:
        low = bootstrap_quantity(
            Decimal("1000"),
            Decimal("100"),
            Decimal("50"),
            Decimal("0"),
            0,
        )
        high = bootstrap_quantity(
            Decimal("1000"),
            Decimal("100"),
            Decimal("50"),
            Decimal("0.01"),
            0,
        )
        self.assertNotEqual(low, high)
        self.assertGreater(low, high)

    def test_quantity_is_not_rounded_to_a_step(self) -> None:
        quantity = bootstrap_quantity(
            Decimal("1000"),
            Decimal("100"),
            Decimal("50"),
            Decimal("0.01"),
            0,
        )
        stepped = quantity.quantize(Decimal("0.00000001"))
        self.assertNotEqual(quantity, stepped)

    def test_thirty_trades_is_outside_bootstrap(self) -> None:
        with self.assertRaises(ValueError):
            bootstrap_quantity(
                Decimal("1000"),
                Decimal("100"),
                Decimal("90"),
                Decimal("0.001"),
                30,
            )

    def test_missing_fee_has_no_default(self) -> None:
        with self.assertRaises(TypeError):
            bootstrap_quantity(  # type: ignore[call-arg]
                Decimal("1000"),
                Decimal("100"),
                Decimal("90"),
                trade_count=0,
            )

    def test_float_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            bootstrap_quantity(
                1000.0,  # type: ignore[arg-type]
                Decimal("100"),
                Decimal("90"),
                Decimal("0.001"),
                0,
            )

    def test_non_finite_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            bootstrap_quantity(
                Decimal("1000"),
                Decimal("100"),
                Decimal("90"),
                Decimal("NaN"),
                0,
            )

    def test_bool_trade_count_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            bootstrap_quantity(
                Decimal("1000"),
                Decimal("100"),
                Decimal("90"),
                Decimal("0.001"),
                True,  # type: ignore[arg-type]
            )

    def test_fee_rate_is_not_hardcoded(self) -> None:
        source = Path(sizing.__file__).read_text(encoding="utf-8")
        self.assertNotIn("0.0009", source)
        self.assertNotIn("0.09", source)


class EmpiricalKellyTest(unittest.TestCase):
    def test_symmetric_payoff_matches_the_closed_form(self) -> None:
        multiples = [Decimal("10")] * 16 + [Decimal("-10")] * 14
        found = empirical_kelly(multiples)
        self.assertLess(abs(found - Decimal(1) / Decimal(150)), Decimal("1e-18"))
        self.assertEqual(half_kelly_risk(multiples), found / 2)
        self.assertLess(found / 2, Decimal("0.01"))

    def test_non_positive_has_no_risk_and_no_loss_is_capped(self) -> None:
        self.assertEqual(empirical_kelly([Decimal("-1")] * 5), Decimal(0))
        self.assertIsNone(half_kelly_risk([Decimal("0")] * 4))
        self.assertEqual(half_kelly_risk([Decimal("1")] * 3), Decimal("0.01"))
        self.assertEqual(empirical_kelly([Decimal("1")] * 3), Decimal("Infinity"))

    def test_float_multiple_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            empirical_kelly([1])  # type: ignore[list-item]


if __name__ == "__main__":
    unittest.main()
