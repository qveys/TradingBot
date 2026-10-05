import unittest
from decimal import Decimal

from tradingbot.evaluation import (
    LOW_BOUND,
    FrozenSprt,
    MethodEvent,
    calibrate_d_min,
    freeze_sprt,
    kelly_null,
    method_drawdown,
    sequential_t_llr,
    sprt_high_bound,
    sprt_low_bound,
    sprt_outcome,
    survival_breach,
)


class SurvivalTest(unittest.TestCase):
    def test_floor_is_inclusive_from_trade_one(self) -> None:
        self.assertEqual(
            survival_breach(1, Decimal("60"), Decimal("100")),
            MethodEvent("METHOD_CHANGE_REQUIRED", "survival"),
        )
        self.assertIsNone(survival_breach(1, Decimal("60.01"), Decimal("100")))
        self.assertIsNone(
            survival_breach(0, Decimal("1"), Decimal("100"), Decimal("0.40"))
        )

    def test_bounds_are_inclusive_and_out_of_range_is_clamped(self) -> None:
        self.assertIsNotNone(
            survival_breach(1, Decimal("70"), Decimal("100"), Decimal("0.30"))
        )
        self.assertIsNone(
            survival_breach(1, Decimal("70.01"), Decimal("100"), Decimal("0.30"))
        )
        self.assertIsNone(
            survival_breach(1, Decimal("60"), Decimal("100"), Decimal("0.50"))
        )
        self.assertIsNotNone(
            survival_breach(1, Decimal("50"), Decimal("100"), Decimal("0.50"))
        )
        self.assertIsNone(
            survival_breach(1, Decimal("80"), Decimal("100"), Decimal("0.10"))
        )
        self.assertIsNotNone(
            survival_breach(1, Decimal("70"), Decimal("100"), Decimal("0.10"))
        )
        self.assertIsNotNone(
            survival_breach(2, Decimal("50"), Decimal("100"), Decimal("0.90"))
        )

    def test_non_positive_peak_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            survival_breach(1, Decimal("0"), Decimal("0"))
        with self.assertRaises(ValueError):
            survival_breach(1, Decimal("10"), Decimal("-1"))

    def test_float_survival_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            survival_breach(1, Decimal("60"), Decimal("100"), 0.4)  # type: ignore[arg-type]


class DrawdownTest(unittest.TestCase):
    def test_threshold_is_inclusive_before_thirty_trades(self) -> None:
        self.assertEqual(
            method_drawdown(1, Decimal("100"), Decimal("80")),
            MethodEvent("METHOD_CHANGE_REQUIRED", "drawdown"),
        )
        self.assertIsNone(method_drawdown(5, Decimal("100"), Decimal("80.01")))
        self.assertIsNone(method_drawdown(0, Decimal("100"), Decimal("50")))
        self.assertIsNotNone(method_drawdown(29, Decimal("100"), Decimal("80")))

    def test_drawdown_bounds_clamp(self) -> None:
        self.assertIsNotNone(
            method_drawdown(1, Decimal("100"), Decimal("85"), Decimal("0.15"))
        )
        self.assertIsNone(
            method_drawdown(1, Decimal("100"), Decimal("85.01"), Decimal("0.15"))
        )
        self.assertIsNone(
            method_drawdown(1, Decimal("100"), Decimal("86"), Decimal("0.10"))
        )
        self.assertIsNotNone(
            method_drawdown(1, Decimal("100"), Decimal("75"), Decimal("0.40"))
        )
        with self.assertRaises(TypeError):
            method_drawdown(1, Decimal("100"), Decimal("80"), 0.2)  # type: ignore[arg-type]


class SprtTest(unittest.TestCase):
    def setUp(self) -> None:
        self.d_min = Decimal("0.5")
        self.bad = [Decimal("-0.8")] * 25 + [Decimal("0.2")] * 5
        self.between = [Decimal("0.02")] * 15 + [Decimal("-0.01")] * 15
        self.good = [Decimal("0.8")] * 25 + [Decimal("-0.2")] * 5

    def test_bounds_match_the_cahier(self) -> None:
        self.assertEqual(LOW_BOUND, (Decimal("0.20") / Decimal("0.95")).ln())

    def test_low_bound_is_read_only_from_trade_thirty(self) -> None:
        self.assertLessEqual(sequential_t_llr(self.bad, self.d_min), LOW_BOUND)
        self.assertIsNone(sprt_low_bound(self.bad[:29], self.d_min))
        self.assertEqual(
            sprt_low_bound(self.bad, self.d_min),
            MethodEvent("METHOD_CHANGE_REQUIRED", "sprt_low"),
        )

    def test_between_and_above_do_not_validate(self) -> None:
        high = Decimal(16).ln()
        between = sequential_t_llr(self.between, self.d_min)
        self.assertGreater(between, LOW_BOUND)
        self.assertLess(between, high)
        self.assertIsNone(sprt_low_bound(self.between, self.d_min))
        above = sequential_t_llr(self.good, self.d_min)
        self.assertGreaterEqual(above, high)
        event = sprt_low_bound(self.good, self.d_min)
        self.assertIsNone(event)
        self.assertNotEqual(getattr(event, "code", None), "METHOD_VALIDATED")

    def test_first_trade_changes_the_ratio(self) -> None:
        shifted = [Decimal("5")] + self.bad[1:]
        self.assertNotEqual(
            sequential_t_llr(self.bad, self.d_min),
            sequential_t_llr(shifted, self.d_min),
        )

    def test_omitted_d_min_is_named(self) -> None:
        with self.assertRaises(TypeError) as caught:
            sprt_low_bound(self.bad)  # type: ignore[call-arg]
        self.assertIn("d_min", str(caught.exception))


class SprtHighTest(unittest.TestCase):
    def test_high_bound_validates_only_from_trade_thirty(self) -> None:
        d_min = Decimal("0.5")
        early = [Decimal("0.8")] * 29
        self.assertGreaterEqual(sequential_t_llr(early, d_min), Decimal(16).ln())
        self.assertIsNone(sprt_high_bound(early, d_min))
        self.assertEqual(
            sprt_high_bound(early + [Decimal("0.8")], d_min),
            MethodEvent("METHOD_VALIDATED", "sprt_high"),
        )

    def test_below_the_high_bound_emits_nothing(self) -> None:
        d_min = Decimal("0.5")
        between = [Decimal("0.02")] * 15 + [Decimal("-0.01")] * 15
        losing = [Decimal("-0.8")] * 25 + [Decimal("0.2")] * 5
        ratio = sequential_t_llr(between, d_min)
        self.assertGreater(ratio, LOW_BOUND)
        self.assertLess(ratio, Decimal(16).ln())
        self.assertIsNone(sprt_high_bound(between, d_min))
        self.assertIsNone(sprt_high_bound(losing, d_min))


class SprtFreezeTest(unittest.TestCase):
    def test_activation_keeps_bounds_and_d_min(self) -> None:
        frozen = freeze_sprt(Decimal("0.5"))
        captured = (frozen.low, frozen.high, frozen.d_min)
        later = freeze_sprt(Decimal("0.2"))
        self.assertEqual((frozen.low, frozen.high, frozen.d_min), captured)
        self.assertEqual(frozen.low, LOW_BOUND)
        self.assertEqual(frozen.high, Decimal(16).ln())
        self.assertNotEqual(later.d_min, frozen.d_min)
        sample = [Decimal("0.8")] * 30
        self.assertEqual(
            sprt_outcome(sample, frozen),
            sprt_high_bound(sample, frozen.d_min),
        )
        self.assertIsInstance(frozen, FrozenSprt)


class SprtTruncationTest(unittest.TestCase):
    def test_three_hundred_between_bounds_is_not_a_verdict(self) -> None:
        frozen = freeze_sprt(Decimal("0.05"))
        flat = [Decimal("1"), Decimal("-1")] * 150
        ratio = sequential_t_llr(flat, frozen.d_min)
        self.assertGreater(ratio, frozen.low)
        self.assertLess(ratio, frozen.high)
        self.assertIsNone(sprt_outcome(flat[:299], frozen))
        event = sprt_outcome(flat, frozen)
        self.assertEqual(
            event,
            MethodEvent("METHOD_CHANGE_REQUIRED", "truncation", False),
        )
        assert event is not None
        self.assertFalse(event.statistical)


class SprtCalibrationTest(unittest.TestCase):
    def test_monte_carlo_picks_an_effect_inside_three_hundred(self) -> None:
        found = calibrate_d_min()
        self.assertEqual(found.open_good, 0)
        self.assertEqual(found.open_bad, 0)
        self.assertLessEqual(found.mean_trades, Decimal(300))
        self.assertLessEqual(
            (found.keep_bad - Decimal("0.05")).copy_abs(), Decimal("0.04")
        )
        self.assertLessEqual(
            (found.abandon_good - Decimal("0.20")).copy_abs(), Decimal("0.04")
        )
        self.assertGreater(len(found.rejected), 0)
        for earlier in found.rejected:
            self.assertLess(earlier.d_min, found.d_min)
            failed = (
                earlier.open_good != 0
                or earlier.open_bad != 0
                or earlier.mean_trades > Decimal(300)
                or (earlier.keep_bad - Decimal("0.05")).copy_abs()
                > Decimal("0.04")
                or (earlier.abandon_good - Decimal("0.20")).copy_abs()
                > Decimal("0.04")
            )
            self.assertTrue(failed)


class KellyNullTest(unittest.TestCase):
    def test_non_positive_after_thirty_trades(self) -> None:
        self.assertIsNone(kelly_null([Decimal("-1")] * 29))
        self.assertEqual(
            kelly_null([Decimal("-1")] * 30),
            MethodEvent("METHOD_CHANGE_REQUIRED", "kelly"),
        )
        self.assertEqual(
            kelly_null([Decimal("1")] * 15 + [Decimal("-1")] * 15),
            MethodEvent("METHOD_CHANGE_REQUIRED", "kelly"),
        )
        self.assertIsNone(kelly_null([Decimal("1")] * 16 + [Decimal("-1")] * 14))


if __name__ == "__main__":
    unittest.main()
