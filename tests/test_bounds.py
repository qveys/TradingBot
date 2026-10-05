import unittest
from decimal import Decimal

from tradingbot.bounds import Clamped, clamp_bounds


class ClampBoundsTest(unittest.TestCase):
    def test_below_low_is_raised(self) -> None:
        self.assertEqual(
            clamp_bounds(
                Decimal("0.29"),
                Decimal("0.14"),
                Decimal("0.09"),
                Decimal("0.24"),
            ),
            Clamped(
                Decimal("0.30"),
                Decimal("0.15"),
                Decimal("0.10"),
                Decimal("0.25"),
            ),
        )

    def test_above_high_is_lowered(self) -> None:
        self.assertEqual(
            clamp_bounds(
                Decimal("0.80"),
                Decimal("0.40"),
                Decimal("0.40"),
                Decimal("0.90"),
            ),
            Clamped(
                Decimal("0.50"),
                Decimal("0.25"),
                Decimal("0.25"),
                Decimal("0.50"),
            ),
        )

    def test_inside_is_unchanged(self) -> None:
        current = Clamped(
            Decimal("0.40"),
            Decimal("0.20"),
            Decimal("0.175"),
            Decimal("0.30"),
        )
        self.assertEqual(clamp_bounds(*current), current)

    def test_on_bound_is_unchanged(self) -> None:
        current = Clamped(
            Decimal("0.30"),
            Decimal("0.25"),
            Decimal("0.10"),
            Decimal("0.50"),
        )
        self.assertEqual(clamp_bounds(*current), current)

    def test_float_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            clamp_bounds(
                0.4,  # type: ignore[arg-type]
                Decimal("0.20"),
                Decimal("0.10"),
                Decimal("0.25"),
            )


if __name__ == "__main__":
    unittest.main()
