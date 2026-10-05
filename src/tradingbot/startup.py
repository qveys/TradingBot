"""Démarrage : un paramètre obligatoire vide refuse le processus."""

from collections.abc import Mapping

MAIL_EVENTS: tuple[str, ...] = (
    "METHOD_CHANGE_REQUIRED",
    "HARD_STOP",
    "SAFETY_NET_FIRED",
    "BROKER_UNREACHABLE",
    "LEDGER_ANOMALY",
    "METHOD_VALIDATED",
)
STOP_POLICY = "refuse_naked"
KEY_RIGHTS_CHECK = "manual_ui"


class StartupRefused(RuntimeError):
    def __init__(self, parameter: str) -> None:
        self.parameter = parameter
        super().__init__(f"paramètre vide : {parameter}")


def check_startup(parameters: Mapping[str, object]) -> None:
    """Tout chemin de démarrage passe ici. Rien n'est rempli à sa place."""
    for name, value in parameters.items():
        if _is_empty(value):
            raise StartupRefused(name)


def start() -> None:
    check_startup({"mail_events": MAIL_EVENTS})


def start_real(key_rights_record: object) -> None:
    # Le premier paramètre vide est celui qui est nommé.
    check_startup(
        {
            "key_rights_record": key_rights_record,
            "mail_events": MAIL_EVENTS,
        }
    )


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False
