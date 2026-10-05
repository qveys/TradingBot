"""API interne : jeton, puis intention complète. Pas de règle de trading."""

import hmac
import json
from collections.abc import Callable, Mapping
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
from typing import NoReturn, cast

_MAX_BODY = 65536
_FIELDS = ("method", "pair", "side", "stop_price", "annotation")


def handle_intent(
    authorization: str | None,
    token: str,
    read_body: Callable[[], object],
    rules: Callable[[], None],
) -> tuple[int, dict[str, str]]:
    if not _token_ok(authorization, token):
        return 401, {"error": "unauthorized"}
    if not _intent_complete(read_body()):
        return 400, {"error": "incomplete_intent"}
    rules()
    return 200, {"check": "pass"}


def make_handler(
    token: str,
    rules: Callable[[], None] | None = None,
) -> type[BaseHTTPRequestHandler]:
    check = rules if rules is not None else lambda: None

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            status, payload = handle_intent(
                self.headers.get("Authorization"),
                token,
                lambda: _read_json(self),
                check,
            )
            self.close_connection = True
            _write(self, status, payload)

        def log_message(self, format: str, *args: object) -> None:
            # Le jeton ne doit pas finir dans les logs.
            return None

    return Handler


def _token_ok(authorization: str | None, token: str) -> bool:
    if authorization is None or token == "":
        return False
    scheme, _, presented = authorization.partition(" ")
    if scheme != "Bearer" or presented == "":
        return False
    return hmac.compare_digest(presented.encode(), token.encode())


def _intent_complete(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    if "quantity" in body:
        return False
    for field in _FIELDS:
        if field not in body:
            return False
        value = body[field]
        if isinstance(value, str):
            if value.strip() == "":
                return False
        elif not isinstance(value, Decimal):
            return False
    return True


def _read_json(handler: BaseHTTPRequestHandler) -> object:
    length_header = handler.headers.get("Content-Length")
    if length_header is None:
        return None
    try:
        length = int(length_header)
    except ValueError:
        return None
    if length < 0 or length > _MAX_BODY:
        return None
    raw = handler.rfile.read(length)
    try:
        return cast(
            object,
            json.loads(
                raw.decode("utf-8"),
                parse_float=Decimal,
                parse_int=Decimal,
                parse_constant=_reject_json_constant,
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _reject_json_constant(constant: str) -> NoReturn:
    raise json.JSONDecodeError("constante numérique refusée", constant, 0)


def _write(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: Mapping[str, str],
) -> None:
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)
