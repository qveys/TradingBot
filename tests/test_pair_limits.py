import unittest
from decimal import Decimal

from tradingbot.pair_limits import limits_for


class PairLimitsTest(unittest.TestCase):
    def test_btc_eur_snapshot(self) -> None:
        limits = limits_for("BTC/EUR")
        self.assertIsNotNone(limits)
        assert limits is not None
        self.assertEqual(limits, limits_for("BTC-EUR"))
        self.assertEqual(limits.min_order_size, Decimal("0.00000001"))
        self.assertEqual(limits.min_order_size_quote, Decimal("0.1"))
        self.assertEqual(limits.base_step, Decimal("0.00000001"))
        self.assertEqual(limits.quote_step, Decimal("0.01"))

    def test_unknown_pair_has_no_invented_limits(self) -> None:
        self.assertIsNone(limits_for("ETH-EUR"))
