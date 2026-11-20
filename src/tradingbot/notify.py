"""Notifications par mail, événement par événement (cahier 1 §9, ADR 0002).

Un événement part par mail seulement s'il figure dans la liste configurée. La
liste n'est pas choisie ici : elle est passée en entrée (issue #52). Le
transport est injecté et reste testable sans réseau.
"""

from collections.abc import Callable
from typing import NamedTuple

KNOWN_EVENTS = frozenset(
    {
        "METHOD_CHANGE_REQUIRED",
        "HARD_STOP",
        "SAFETY_NET_FIRED",
        "BROKER_UNREACHABLE",
        "LEDGER_ANOMALY",
        "METHOD_VALIDATED",
    }
)


class MailDelivery(NamedTuple):
    event: str
    sent: bool


class Mailer:
    """Envoie un mail par événement s'il est dans la liste configurée.

    `send` est un port injecté (le SMTP réel hors périmètre) ; en test, on le
    remplace par un enregistreur.
    """

    def __init__(
        self,
        configured: object,
        send: Callable[[str], None] | None = None,
    ) -> None:
        if isinstance(configured, (list, tuple, set, frozenset)):
            configured = frozenset(configured)
        if not isinstance(configured, frozenset) or not configured:
            raise ValueError("liste d'événements configurée vide")
        unknown = configured - KNOWN_EVENTS
        if unknown:
            raise ValueError("événement inconnu : " + ", ".join(sorted(unknown)))
        self._configured = configured
        self._send = send

    def notify(self, event: str) -> MailDelivery:
        if event not in KNOWN_EVENTS:
            raise ValueError("événement inconnu : " + event)
        if event not in self._configured:
            return MailDelivery(event, False)
        if self._send is not None:
            self._send(event)
        return MailDelivery(event, True)
