"""La clé et la signature n'apparaissent dans aucun journal."""

import logging
import re
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from tradingbot.decision import Facts, Intent, _logged, decide

# Factice : forme d'une clé Revolut X, 64 alphanumériques (ADR 0001). Jamais une vraie clé.
_KEY = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2W3x4Y5z6A7B8C9D0E1F2"
# Factice : signature Ed25519 en base64 (88 caractères, + et /).
_SIGNATURE = "Ab+/" * 21 + "Ab=="


class _Config:
    def __repr__(self) -> str:
        return f"KeyConfig(api_key={_KEY})"


class _Collecting(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@contextmanager
def _logs() -> Iterator[list[str]]:
    logger = logging.getLogger("tradingbot.decision")
    handler = _Collecting()
    handler.setLevel(logging.DEBUG)
    previous = logger.propagate
    logger.propagate = False
    logger.addHandler(handler)
    try:
        yield handler.lines
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous


def _intent() -> Intent:
    return Intent("m1", "BTC-EUR", "buy", Decimal("90"), "signal")


def _facts() -> Facts:
    return Facts(
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


class NoLeakTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertEqual(len(_KEY), 64)
        self.assertEqual(len(_SIGNATURE), 88)
        self.assertIn("+", _SIGNATURE)
        self.assertIn("/", _SIGNATURE)

    def test_key_is_not_in_source(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src"
        shape = re.compile(r"[A-Za-z0-9]{64}")
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(_KEY, text, path.name)
            self.assertNotIn(_SIGNATURE, text, path.name)
            for number, line in enumerate(text.splitlines(), 1):
                self.assertIsNone(
                    shape.search(line),
                    f"valeur de forme clé dans {path.name}:{number}",
                )

    def test_logged_value_redacts_key_and_signature(self) -> None:
        with _logs() as lines:
            _logged("PROBE", {"note": f"clef {_KEY} signe {_SIGNATURE}"}, None)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIn("code=PROBE", line)
        self.assertNotIn(_KEY, line)
        self.assertNotIn(_SIGNATURE, line)
        self.assertIn("[redacted]", line)

    def test_exception_text_redacts_key(self) -> None:
        logger = logging.getLogger("tradingbot.decision")
        with _logs() as lines:
            try:
                raise RuntimeError(_KEY)
            except RuntimeError:
                logger.exception("echec")
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIn("RuntimeError", line)
        self.assertNotIn(_KEY, line)
        self.assertIn("[redacted]", line)

    def test_config_repr_redacts_key(self) -> None:
        logger = logging.getLogger("tradingbot.decision")
        with _logs() as lines:
            logger.info("config %s", _Config())
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIn("KeyConfig", line)
        self.assertNotIn(_KEY, line)
        self.assertIn("[redacted]", line)

    def test_decision_without_secret_stays_readable(self) -> None:
        with _logs() as lines:
            decision = decide(_intent(), _facts())
        self.assertEqual(decision.code, "ACCEPT")
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIn("code=ACCEPT", line)
        self.assertIn("entry_price=100", line)
        self.assertNotIn(_KEY, line)
        self.assertNotIn(_SIGNATURE, line)
        self.assertNotIn("[redacted]", line)


if __name__ == "__main__":
    unittest.main()
