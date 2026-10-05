import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

from tradingbot import ledger as ledger_module
from tradingbot.ledger import (
    Annotation,
    ClosedBook,
    Execution,
    HistoryRow,
    Intention,
    LedgerAnomaly,
    PartialFill,
    closed_book,
    load,
    load_annotation,
    rebuild,
    reconcile,
    store_annotation,
)


class ExecutorReport(NamedTuple):
    price: Decimal
    quantity: Decimal
    side: str
    fee: Decimal


class LedgerTest(unittest.TestCase):
    def test_history_rows_are_appended_and_round_trip(self) -> None:
        connection = sqlite3.connect(":memory:")
        first = HistoryRow(
            Decimal("100.5"),
            Decimal("0.001"),
            "buy",
            Decimal("0.00000001"),
        )
        second = HistoryRow(
            Decimal("101"),
            Decimal("0.002"),
            "sell",
            Decimal("0.02"),
        )
        rebuild(connection, [first])
        rebuild(connection, [second])
        rows = load(connection)
        self.assertEqual(rows, (first, second))
        self.assertEqual(rows[0].price, Decimal("100.5"))
        self.assertEqual(rows[0].quantity, Decimal("0.001"))

    def test_executor_report_does_not_create_a_price_or_a_quantity(self) -> None:
        connection = sqlite3.connect(":memory:")
        report = ExecutorReport(
            Decimal("42"),
            Decimal("3"),
            "buy",
            Decimal("1"),
        )
        rebuild(
            connection,
            [
                report,
                {
                    "price": Decimal("7"),
                    "quantity": Decimal("8"),
                    "side": "buy",
                    "fee": Decimal("0"),
                },
            ],
        )
        self.assertEqual(load(connection), ())
        kept = HistoryRow(Decimal("10"), Decimal("1"), "buy", Decimal("0.1"))
        rebuild(connection, [report, kept])
        self.assertEqual(load(connection), (kept,))

    def test_rebuild_does_not_commit_or_erase_the_caller_transaction(self) -> None:
        descriptor, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(descriptor)
        try:
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE other (n INTEGER)")
            connection.commit()
            connection.execute("INSERT INTO other VALUES (1)")
            row = HistoryRow(Decimal("10"), Decimal("1"), "buy", Decimal("0.1"))
            rebuild(connection, [row])
            outsider = sqlite3.connect(path)
            self.assertEqual(
                outsider.execute("SELECT COUNT(*) FROM other").fetchone(),
                (0,),
            )
            self.assertIsNone(
                outsider.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'history'"
                ).fetchone()
            )
            self.assertEqual(connection.execute("SELECT n FROM other").fetchone(), (1,))
            self.assertEqual(load(connection), (row,))
            with self.assertRaises(ValueError):
                rebuild(
                    connection,
                    [row, HistoryRow(Decimal("9"), Decimal("NaN"), "buy", Decimal("0"))],
                )
            self.assertEqual(connection.execute("SELECT n FROM other").fetchone(), (1,))
            self.assertEqual(load(connection), (row,))
            connection.commit()
            connection.close()
            outsider.close()
            committed = sqlite3.connect(path)
            self.assertEqual(committed.execute("SELECT n FROM other").fetchone(), (1,))
            self.assertEqual(load(committed), (row,))
            committed.close()
        finally:
            os.remove(path)

    def test_float_is_rejected_and_rows_are_not_updated_or_deleted(self) -> None:
        connection = sqlite3.connect(":memory:")
        with self.assertRaises(TypeError):
            rebuild(
                connection,
                [HistoryRow(1.5, Decimal("1"), "buy", Decimal("0"))],  # type: ignore[arg-type]
            )
        self.assertEqual(load(connection), ())
        source = Path(ledger_module.__file__).read_text(encoding="utf-8").upper()
        self.assertNotIn("UPDATE", source)
        self.assertNotIn("DELETE", source)

    def test_annotation_is_reread_by_client_id_without_financial_facts(self) -> None:
        self.assertEqual(
            Annotation._fields,
            ("client_id", "method_id", "signal", "justification"),
        )
        connection = sqlite3.connect(":memory:")
        first = store_annotation(connection, "m1", "breakout", "range cassé")
        second = store_annotation(connection, "m2", "mean-revert", "écart-type")
        self.assertNotEqual(first, second)
        self.assertEqual(
            load_annotation(connection, first),
            Annotation(first, "m1", "breakout", "range cassé"),
        )
        self.assertEqual(
            load_annotation(connection, second),
            Annotation(second, "m2", "mean-revert", "écart-type"),
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(annotation)")
        }
        self.assertEqual(
            columns,
            {"id", "client_id", "method_id", "signal", "justification"},
        )
        self.assertEqual(load(connection), ())
        with self.assertRaises(TypeError):
            store_annotation(  # type: ignore[call-arg]
                connection,
                method_id="m1",
                signal="breakout",
                justification="range cassé",
                price=Decimal("1"),
            )
        self.assertEqual(load(connection), ())
        kept = load_annotation(connection, first)
        self.assertEqual(kept.method_id, "m1")

    def test_annotation_savepoint_does_not_commit_the_caller(self) -> None:
        descriptor, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(descriptor)
        try:
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE other (n INTEGER)")
            connection.commit()
            connection.execute("INSERT INTO other VALUES (1)")
            client_id = store_annotation(connection, "m1", "s", "j")
            outsider = sqlite3.connect(path)
            self.assertEqual(
                outsider.execute("SELECT COUNT(*) FROM other").fetchone(),
                (0,),
            )
            self.assertIsNone(
                outsider.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'annotation'"
                ).fetchone()
            )
            self.assertEqual(
                load_annotation(connection, client_id),
                Annotation(client_id, "m1", "s", "j"),
            )
            with self.assertRaises(ValueError):
                store_annotation(connection, " ", "s", "j")
            self.assertEqual(connection.execute("SELECT n FROM other").fetchone(), (1,))
            self.assertEqual(load_annotation(connection, client_id).signal, "s")
            connection.commit()
            connection.close()
            outsider.close()
            committed = sqlite3.connect(path)
            self.assertEqual(
                load_annotation(committed, client_id).justification,
                "j",
            )
            committed.close()
        finally:
            os.remove(path)

    def test_partial_fills_of_one_order_are_one_weighted_line(self) -> None:
        connection = sqlite3.connect(":memory:")
        first = PartialFill("ord-1", Decimal("100"), Decimal("1"), "buy", Decimal("0.01"))
        second = PartialFill("ord-1", Decimal("200"), Decimal("3"), "buy", Decimal("0.02"))
        other = PartialFill("ord-2", Decimal("50"), Decimal("1"), "sell", Decimal("0.05"))
        kept = HistoryRow(Decimal("10"), Decimal("1"), "buy", Decimal("0.1"))
        rebuild(connection, [first, kept, second, other])
        rows = load(connection)
        self.assertEqual(len(rows), 3)
        vwap = HistoryRow(Decimal("175"), Decimal("4"), "buy", Decimal("0.03"))
        sell = HistoryRow(Decimal("50"), Decimal("1"), "sell", Decimal("0.05"))
        self.assertEqual(rows[0], kept)
        self.assertEqual(rows[1], vwap)
        self.assertIsInstance(rows[1].price, Decimal)
        self.assertIsInstance(rows[1].quantity, Decimal)
        self.assertEqual(rows[2], sell)
        self.assertEqual(closed_book(rows), ClosedBook(0, Decimal("0")))
        self.assertEqual(closed_book((vwap, kept, sell)), ClosedBook(0, Decimal("0")))
        with self.assertRaises(TypeError):
            rebuild(
                connection,
                [PartialFill("ord-3", 1.5, Decimal("1"), "buy", Decimal("0"))],  # type: ignore[arg-type]
            )
        self.assertEqual(len(load(connection)), 3)
        with self.assertRaises(ValueError):
            rebuild(
                connection,
                [
                    PartialFill("ord-4", Decimal("1"), Decimal("1"), "buy", Decimal("0")),
                    PartialFill("ord-4", Decimal("2"), Decimal("1"), "sell", Decimal("0")),
                ],
            )
        self.assertEqual(len(load(connection)), 3)

    def test_open_position_does_not_count_and_close_includes_fees(self) -> None:
        opened = HistoryRow(Decimal("100"), Decimal("1"), "buy", Decimal("0.5"))
        self.assertEqual(closed_book([opened]), ClosedBook(0, Decimal("0")))
        closed = closed_book(
            [opened, HistoryRow(Decimal("110"), Decimal("1"), "sell", Decimal("0.25"))]
        )
        self.assertEqual(closed, ClosedBook(1, Decimal("9.25")))
        self.assertNotEqual(closed.pnl, Decimal("10"))

        opened_lot = HistoryRow(Decimal("100"), Decimal("2"), "buy", Decimal("2"))
        scale_out = HistoryRow(Decimal("110"), Decimal("1"), "sell", Decimal("0.5"))
        still_open = closed_book([opened_lot, scale_out])
        self.assertEqual(still_open, ClosedBook(0, Decimal("0")))
        flat = closed_book(
            [opened_lot, scale_out, HistoryRow(Decimal("110"), Decimal("1"), "sell", Decimal("0.5"))]
        )
        self.assertEqual(flat, ClosedBook(1, Decimal("17")))

        both = closed_book(
            [
                HistoryRow(Decimal("100"), Decimal("1"), "buy", Decimal("0.1")),
                HistoryRow(Decimal("102"), Decimal("1"), "buy", Decimal("0.1")),
                HistoryRow(Decimal("110"), Decimal("2"), "sell", Decimal("0.2")),
            ]
        )
        self.assertEqual(both.trade_count, 1)
        self.assertEqual(both.pnl, Decimal("17.6"))

        flipped = closed_book(
            [
                HistoryRow(Decimal("100"), Decimal("1"), "buy", Decimal("0")),
                HistoryRow(Decimal("110"), Decimal("2"), "sell", Decimal("0")),
            ]
        )
        self.assertEqual(flipped, ClosedBook(1, Decimal("10")))

        short = HistoryRow(Decimal("100"), Decimal("1"), "sell", Decimal("0.1"))
        self.assertEqual(closed_book([short]), ClosedBook(0, Decimal("0")))
        covered = closed_book(
            [short, HistoryRow(Decimal("90"), Decimal("1"), "buy", Decimal("0.1"))]
        )
        self.assertEqual(covered, ClosedBook(1, Decimal("9.8")))

        with self.assertRaises(TypeError):
            closed_book(
                [HistoryRow(1.0, Decimal("1"), "buy", Decimal("0"))]  # type: ignore[list-item]
            )

    def test_fresh_file_write_waits_for_the_caller_commit(self) -> None:
        descriptor, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(descriptor)
        try:
            connection = sqlite3.connect(path)
            row = HistoryRow(Decimal("10"), Decimal("1"), "buy", Decimal("0.1"))
            rebuild(connection, [row])
            client_id = store_annotation(connection, "m1", "s", "j")
            outsider = sqlite3.connect(path)
            self.assertIsNone(_table(outsider, "history"))
            self.assertIsNone(_table(outsider, "annotation"))
            self.assertEqual(load(connection), (row,))
            self.assertEqual(
                load_annotation(connection, client_id),
                Annotation(client_id, "m1", "s", "j"),
            )
            connection.rollback()
            self.assertFalse(connection.in_transaction)
            self.assertIsNone(_table(connection, "history"))
            self.assertIsNone(_table(connection, "annotation"))
            self.assertIsNone(_table(outsider, "history"))
            self.assertIsNone(_table(outsider, "annotation"))

            with self.assertRaises(ValueError):
                rebuild(
                    connection,
                    [HistoryRow(Decimal("9"), Decimal("NaN"), "buy", Decimal("0"))],
                )
            with self.assertRaises(ValueError):
                store_annotation(connection, " ", "s", "j")
            self.assertIsNone(_table(sqlite3.connect(path), "history"))
            self.assertIsNone(_table(sqlite3.connect(path), "annotation"))
            connection.commit()
            committed = sqlite3.connect(path)
            if _table(committed, "history") is not None:
                self.assertEqual(
                    committed.execute("SELECT COUNT(*) FROM history").fetchone(),
                    (0,),
                )
            if _table(committed, "annotation") is not None:
                self.assertEqual(
                    committed.execute("SELECT COUNT(*) FROM annotation").fetchone(),
                    (0,),
                )
            connection.close()
            outsider.close()
            committed.close()
        finally:
            os.remove(path)


class ReconcileTest(unittest.TestCase):
    def test_order_without_annotation_is_an_anomaly(self) -> None:
        connection = sqlite3.connect(":memory:")
        linked = store_annotation(connection, "m1", "s", "j")
        naked = Execution("ext", Decimal("1"), "buy")
        covered = Execution(linked, Decimal("2"), "sell")
        found = reconcile(
            connection,
            [naked, covered],
            [Intention(linked, Decimal("2"), "sell")],
        )
        self.assertEqual(
            found,
            (LedgerAnomaly("LEDGER_ANOMALY", "order_without_annotation", "ext"),),
        )

    def test_annotation_without_order_is_an_anomaly(self) -> None:
        connection = sqlite3.connect(":memory:")
        missing = store_annotation(connection, "m1", "s", "j")
        linked = store_annotation(connection, "m2", "s2", "j2")
        found = reconcile(
            connection,
            [Execution(linked, Decimal("1"), "buy")],
            [
                Intention(linked, Decimal("1"), "buy"),
                Intention(missing, Decimal("4"), "sell"),
            ],
        )
        self.assertEqual(
            found,
            (LedgerAnomaly("LEDGER_ANOMALY", "annotation_without_order", missing),),
        )

    def test_quantity_or_side_gap_is_an_anomaly_and_equals_are_not(self) -> None:
        connection = sqlite3.connect(":memory:")
        same = store_annotation(connection, "m1", "s", "j")
        qty = store_annotation(connection, "m2", "s", "j")
        side = store_annotation(connection, "m3", "s", "j")
        both = store_annotation(connection, "m4", "s", "j")
        found = reconcile(
            connection,
            [
                Execution(same, Decimal("1.0"), "buy"),
                Execution(qty, Decimal("3"), "buy"),
                Execution(side, Decimal("1"), "sell"),
                Execution(both, Decimal("9"), "sell"),
            ],
            [
                Intention(same, Decimal("1"), "buy"),
                Intention(qty, Decimal("2"), "buy"),
                Intention(side, Decimal("1"), "buy"),
                Intention(both, Decimal("8"), "buy"),
            ],
        )
        self.assertEqual(
            found,
            (
                LedgerAnomaly("LEDGER_ANOMALY", "quantity", qty),
                LedgerAnomaly("LEDGER_ANOMALY", "side", side),
                LedgerAnomaly("LEDGER_ANOMALY", "quantity", both),
                LedgerAnomaly("LEDGER_ANOMALY", "side", both),
            ),
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(annotation)")
        }
        self.assertEqual(
            columns,
            {"id", "client_id", "method_id", "signal", "justification"},
        )

    def test_one_pass_reports_every_reason(self) -> None:
        connection = sqlite3.connect(":memory:")
        orphan = store_annotation(connection, "m1", "s", "j")
        linked = store_annotation(connection, "m2", "s", "j")
        found = reconcile(
            connection,
            [
                Execution("ext", Decimal("1"), "buy"),
                Execution(linked, Decimal("5"), "sell"),
            ],
            [Intention(linked, Decimal("4"), "buy")],
        )
        reasons = [item.reason for item in found]
        self.assertEqual(
            reasons,
            [
                "order_without_annotation",
                "quantity",
                "side",
                "annotation_without_order",
            ],
        )
        self.assertTrue(all(item.code == "LEDGER_ANOMALY" for item in found))
        self.assertIn(orphan, [item.client_id for item in found])

    def test_missing_intention_keeps_the_other_anomalies(self) -> None:
        connection = sqlite3.connect(":memory:")
        linked = store_annotation(connection, "m1", "s", "j")
        found = reconcile(
            connection,
            [
                Execution("ext", Decimal("1"), "buy"),
                Execution(linked, Decimal("2"), "sell"),
            ],
            [],
        )
        self.assertEqual(
            found,
            (LedgerAnomaly("LEDGER_ANOMALY", "order_without_annotation", "ext"),),
        )

    def test_reconcile_does_not_commit_the_caller(self) -> None:
        descriptor, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(descriptor)
        try:
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE other (n INTEGER)")
            connection.commit()
            connection.execute("INSERT INTO other VALUES (1)")
            client_id = store_annotation(connection, "m1", "s", "j")
            reconcile(
                connection,
                [Execution(client_id, Decimal("1"), "buy")],
                [Intention(client_id, Decimal("1"), "buy")],
            )
            outsider = sqlite3.connect(path)
            self.assertEqual(
                outsider.execute("SELECT COUNT(*) FROM other").fetchone(),
                (0,),
            )
            connection.rollback()
            self.assertIsNone(_table(connection, "annotation"))
            outsider.close()
            connection.close()
        finally:
            os.remove(path)


def _table(connection: sqlite3.Connection, name: str) -> tuple[object, ...] | None:
    found = connection.execute(
        "SELECT name FROM sqlite_master WHERE name = ?",
        (name,),
    ).fetchone()
    if found is None:
        return None
    return tuple(found)


if __name__ == "__main__":
    unittest.main()
