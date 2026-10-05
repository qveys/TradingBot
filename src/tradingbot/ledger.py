"""Registre append-only reconstruit depuis des lignes d'historique.

Pas de lecture HTTP. Un rapport qui n'est pas une ligne d'historique
n'écrit ni prix ni quantité. Aucune fonction ne modifie ni ne supprime une ligne.
"""

import sqlite3
import uuid
from collections import deque
from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple


class HistoryRow(NamedTuple):
    price: Decimal
    quantity: Decimal
    side: str
    fee: Decimal


class PartialFill(NamedTuple):
    order_id: str
    price: Decimal
    quantity: Decimal
    side: str
    fee: Decimal


class Annotation(NamedTuple):
    client_id: str
    method_id: str
    signal: str
    justification: str


class Execution(NamedTuple):
    client_id: str
    quantity: Decimal
    side: str


class Intention(NamedTuple):
    client_id: str
    quantity: Decimal
    side: str


class LedgerAnomaly(NamedTuple):
    code: str
    reason: str
    client_id: str


class ClosedBook(NamedTuple):
    trade_count: int
    pnl: Decimal


class _Lot(NamedTuple):
    quantity: Decimal
    price: Decimal
    fee: Decimal


def rebuild(connection: sqlite3.Connection, rows: Sequence[object]) -> None:
    _open_transaction(connection)
    _ensure_history(connection)
    connection.execute("SAVEPOINT tradingbot_ledger_rebuild")
    try:
        for row in _aggregated(rows):
            price = _finite(row.price)
            quantity = _finite(row.quantity)
            fee = _finite(row.fee)
            if not isinstance(row.side, str):
                raise TypeError("str requis")
            connection.execute(
                "INSERT INTO history (price, quantity, side, fee) VALUES (?, ?, ?, ?)",
                (format(price, "f"), format(quantity, "f"), row.side, format(fee, "f")),
            )
        connection.execute("RELEASE SAVEPOINT tradingbot_ledger_rebuild")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT tradingbot_ledger_rebuild")
        connection.execute("RELEASE SAVEPOINT tradingbot_ledger_rebuild")
        raise


def store_annotation(
    connection: sqlite3.Connection,
    method_id: str,
    signal: str,
    justification: str,
) -> str:
    _open_transaction(connection)
    _ensure_annotation(connection)
    connection.execute("SAVEPOINT tradingbot_ledger_annotation")
    try:
        client_id = uuid.uuid4().hex
        stored = Annotation(client_id, method_id, signal, justification)
        for value in (
            stored.client_id,
            stored.method_id,
            stored.signal,
            stored.justification,
        ):
            if not isinstance(value, str) or value.strip() == "":
                raise ValueError("annotation incomplète")
        connection.execute(
            """
            INSERT INTO annotation (client_id, method_id, signal, justification)
            VALUES (?, ?, ?, ?)
            """,
            (stored.client_id, stored.method_id, stored.signal, stored.justification),
        )
        connection.execute("RELEASE SAVEPOINT tradingbot_ledger_annotation")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT tradingbot_ledger_annotation")
        connection.execute("RELEASE SAVEPOINT tradingbot_ledger_annotation")
        raise
    return client_id


def reconcile(
    connection: sqlite3.Connection,
    executions: Sequence[Execution],
    intentions: Sequence[Intention],
) -> tuple[LedgerAnomaly, ...]:
    _connection(connection)
    annotations = _read_annotations(connection)
    executed = _by_client(executions)
    intended = _by_client(intentions)
    known = {item.client_id for item in annotations}
    found: list[LedgerAnomaly] = []
    for execution in executions:
        if execution.client_id not in known:
            found.append(
                LedgerAnomaly(
                    "LEDGER_ANOMALY",
                    "order_without_annotation",
                    execution.client_id,
                )
            )
        intention = intended.get(execution.client_id)
        if intention is None:
            continue
        if intention.quantity != execution.quantity:
            found.append(
                LedgerAnomaly("LEDGER_ANOMALY", "quantity", execution.client_id)
            )
        if intention.side != execution.side:
            found.append(
                LedgerAnomaly("LEDGER_ANOMALY", "side", execution.client_id)
            )
    for annotation in annotations:
        if annotation.client_id not in executed:
            found.append(
                LedgerAnomaly(
                    "LEDGER_ANOMALY",
                    "annotation_without_order",
                    annotation.client_id,
                )
            )
    return tuple(found)


def load_annotation(connection: sqlite3.Connection, client_id: str) -> Annotation:
    _ensure_annotation(connection)
    if not isinstance(client_id, str):
        raise TypeError("str requis")
    found = connection.execute(
        """
        SELECT client_id, method_id, signal, justification
        FROM annotation
        WHERE client_id = ?
        ORDER BY id
        """,
        (client_id,),
    ).fetchall()
    if len(found) != 1:
        raise LookupError("annotation introuvable")
    client, method_id, signal, justification = found[0]
    if (
        not isinstance(client, str)
        or not isinstance(method_id, str)
        or not isinstance(signal, str)
        or not isinstance(justification, str)
    ):
        raise TypeError("annotation illisible")
    return Annotation(client, method_id, signal, justification)


def closed_book(rows: Sequence[HistoryRow]) -> ClosedBook:
    open_side: str | None = None
    lots: deque[_Lot] = deque()
    trade_count = 0
    pnl = Decimal("0")
    pending = Decimal("0")
    for row in rows:
        if type(row) is not HistoryRow:
            raise TypeError("ligne de registre requise")
        price = _finite(row.price)
        quantity = _finite(row.quantity)
        fee = _finite(row.fee)
        if not isinstance(row.side, str):
            raise TypeError("str requis")
        if row.side not in ("buy", "sell"):
            raise ValueError("côté inconnu")
        if quantity <= 0:
            raise ValueError("quantité invalide")
        if open_side is None or open_side == row.side:
            lots.append(_Lot(quantity, price, fee))
            open_side = row.side
            continue
        remaining = quantity
        matched = Decimal("0")
        while lots and remaining > 0:
            lot = lots[0]
            take = lot.quantity if lot.quantity <= remaining else remaining
            open_fee = lot.fee * take / lot.quantity
            close_fee = fee * take / quantity
            if open_side == "buy":
                pending += (price - lot.price) * take
            else:
                pending += (lot.price - price) * take
            pending -= open_fee + close_fee
            matched += take
            remaining -= take
            if take == lot.quantity:
                lots.popleft()
            else:
                lots[0] = _Lot(lot.quantity - take, lot.price, lot.fee - open_fee)
        if matched > 0 and not lots:
            trade_count += 1
            pnl += pending
            pending = Decimal("0")
        if not lots:
            open_side = None
        if remaining > 0:
            lots.append(_Lot(remaining, price, fee * remaining / quantity))
            open_side = row.side
    return ClosedBook(trade_count, pnl)


def load(connection: sqlite3.Connection) -> tuple[HistoryRow, ...]:
    _ensure_history(connection)
    found = connection.execute(
        "SELECT price, quantity, side, fee FROM history ORDER BY id"
    )
    loaded: list[HistoryRow] = []
    for price, quantity, side, fee in found:
        if (
            not isinstance(price, str)
            or not isinstance(quantity, str)
            or not isinstance(side, str)
            or not isinstance(fee, str)
        ):
            raise TypeError("ligne de registre illisible")
        loaded.append(
            HistoryRow(Decimal(price), Decimal(quantity), side, Decimal(fee))
        )
    return tuple(loaded)


def _aggregated(rows: Sequence[object]) -> list[HistoryRow]:
    partials: dict[str, list[PartialFill]] = {}
    sequence: list[HistoryRow | str] = []
    for row in rows:
        if type(row) is PartialFill:
            if not isinstance(row.order_id, str) or row.order_id.strip() == "":
                raise ValueError("identifiant d'ordre vide")
            bucket = partials.get(row.order_id)
            if bucket is None:
                partials[row.order_id] = [row]
            else:
                bucket.append(row)
                # La ligne unique est datée de la dernière exécution.
                sequence = [item for item in sequence if item != row.order_id]
            sequence.append(row.order_id)
        elif type(row) is HistoryRow:
            sequence.append(row)
    aggregated: list[HistoryRow] = []
    for item in sequence:
        if isinstance(item, str):
            aggregated.append(_one_fill(partials[item]))
        else:
            aggregated.append(item)
    return aggregated


def _one_fill(parts: Sequence[PartialFill]) -> HistoryRow:
    side = parts[0].side
    if not isinstance(side, str):
        raise TypeError("str requis")
    total_qty = Decimal("0")
    notional = Decimal("0")
    total_fee = Decimal("0")
    for part in parts:
        if not isinstance(part.side, str):
            raise TypeError("str requis")
        if part.side != side:
            raise ValueError("côtés d'un même ordre différents")
        price = _finite(part.price)
        quantity = _finite(part.quantity)
        fee = _finite(part.fee)
        if quantity <= 0:
            raise ValueError("quantité invalide")
        total_qty += quantity
        notional += price * quantity
        total_fee += fee
    return HistoryRow(notional / total_qty, total_qty, side, total_fee)


def _connection(connection: sqlite3.Connection) -> None:
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connexion sqlite requise")


def _open_transaction(connection: sqlite3.Connection) -> None:
    _connection(connection)
    # RELEASE du savepoint qui a ouvert la transaction la commite.
    if not connection.in_transaction:
        connection.execute("BEGIN")


def _ensure_history(connection: sqlite3.Connection) -> None:
    _connection(connection)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            price TEXT NOT NULL,
            quantity TEXT NOT NULL,
            side TEXT NOT NULL,
            fee TEXT NOT NULL
        )
        """
    )


def _read_annotations(connection: sqlite3.Connection) -> tuple[Annotation, ...]:
    exists = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'annotation'
        """
    ).fetchone()
    if exists is None:
        return ()
    found = connection.execute(
        """
        SELECT client_id, method_id, signal, justification
        FROM annotation
        ORDER BY id
        """
    )
    loaded: list[Annotation] = []
    for client_id, method_id, signal, justification in found:
        if (
            not isinstance(client_id, str)
            or not isinstance(method_id, str)
            or not isinstance(signal, str)
            or not isinstance(justification, str)
        ):
            raise TypeError("annotation illisible")
        loaded.append(Annotation(client_id, method_id, signal, justification))
    return tuple(loaded)


def _by_client[Row: (Execution, Intention)](
    rows: Sequence[Row],
) -> dict[str, Row]:
    indexed: dict[str, Row] = {}
    for row in rows:
        if type(row) is not Execution and type(row) is not Intention:
            raise TypeError("ligne de rapprochement requise")
        if not isinstance(row.client_id, str) or row.client_id.strip() == "":
            raise ValueError("identifiant vide")
        _finite(row.quantity)
        if not isinstance(row.side, str):
            raise TypeError("str requis")
        if row.client_id in indexed:
            raise ValueError("identifiant dupliqué")
        indexed[row.client_id] = row
    return indexed


def _ensure_annotation(connection: sqlite3.Connection) -> None:
    _connection(connection)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS annotation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT NOT NULL,
            method_id TEXT NOT NULL,
            signal TEXT NOT NULL,
            justification TEXT NOT NULL
        )
        """
    )


def _finite(value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("Decimal requis")
    if not value.is_finite():
        raise ValueError("décimal non fini")
    return value
