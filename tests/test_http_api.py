import json
import threading
import unittest
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

from tradingbot.http_api import handle_intent, make_handler

_TOKEN = "test-token"
_COMPLETE = {
    "method": "m1",
    "pair": "BTC-EUR",
    "side": "buy",
    "stop_price": "100.00",
    "annotation": "signal",
}


class HttpApiTest(unittest.TestCase):
    def test_no_token_is_rejected_before_rules(self) -> None:
        seen: list[str] = []
        status, body = _post(_TOKEN, lambda: seen.append("rules"), None, {})
        self.assertEqual(status, 401)
        self.assertEqual(seen, [])
        self.assertNotIn(_TOKEN, body)
        self.assertIn("unauthorized", body)

    def test_wrong_token_is_rejected_before_rules(self) -> None:
        seen: list[str] = []
        status, body = _post(
            _TOKEN,
            lambda: seen.append("rules"),
            "other-token",
            _COMPLETE,
        )
        self.assertEqual(status, 401)
        self.assertEqual(seen, [])
        self.assertNotIn("other-token", body)

    def test_incomplete_intent_is_rejected(self) -> None:
        for field in ("method", "pair", "side", "stop_price", "annotation"):
            with self.subTest(field=field):
                body = dict(_COMPLETE)
                del body[field]
                seen: list[str] = []
                status, payload = _post(
                    _TOKEN,
                    lambda: seen.append("rules"),
                    _TOKEN,
                    body,
                )
                self.assertEqual(status, 400)
                self.assertIn("incomplete_intent", payload)
                self.assertEqual(seen, [])

    def test_blank_annotation_is_rejected(self) -> None:
        body = dict(_COMPLETE)
        body["annotation"] = "  "
        status, payload = _post(_TOKEN, None, _TOKEN, body)
        self.assertEqual(status, 400)
        self.assertIn("incomplete_intent", payload)

    def test_quantity_is_rejected(self) -> None:
        body = dict(_COMPLETE)
        body["quantity"] = "1"
        seen: list[str] = []
        status, payload = _post(_TOKEN, lambda: seen.append("rules"), _TOKEN, body)
        self.assertEqual(status, 400)
        self.assertEqual(seen, [])
        self.assertIn("incomplete_intent", payload)

    def test_json_constant_stop_price_is_rejected(self) -> None:
        for raw in ('"stop_price": NaN', '"stop_price": Infinity', '"stop_price": -Infinity'):
            with self.subTest(raw=raw):
                seen: list[str] = []
                body = (
                    '{"method": "m1", "pair": "BTC-EUR", "side": "buy", '
                    + raw
                    + ', "annotation": "signal"}'
                )
                status, payload = _post_raw(
                    _TOKEN,
                    lambda: seen.append("rules"),
                    _TOKEN,
                    body.encode("utf-8"),
                )
                self.assertEqual(status, 400)
                self.assertIn("incomplete_intent", payload)
                self.assertEqual(seen, [])

    def test_non_text_field_is_rejected(self) -> None:
        seen: list[str] = []
        body = dict(_COMPLETE)
        body["stop_price"] = float("nan")
        status, payload = handle_intent(
            f"Bearer {_TOKEN}",
            _TOKEN,
            lambda: body,
            lambda: seen.append("rules"),
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "incomplete_intent")
        self.assertEqual(seen, [])

    def test_complete_intent_with_token_passes(self) -> None:
        seen: list[str] = []
        status, payload = _post(
            _TOKEN,
            lambda: seen.append("rules"),
            _TOKEN,
            _COMPLETE,
        )
        self.assertEqual(status, 200)
        self.assertEqual(seen, ["rules"])
        self.assertIn("pass", payload)
        self.assertNotIn(_TOKEN, payload)


def _post_raw(
    configured: str,
    rules: Callable[[], None] | None,
    presented: str | None,
    data: bytes,
) -> tuple[int, str]:
    with _served(configured, rules) as url:
        headers = {"Content-Type": "application/json"}
        if presented is not None:
            headers["Authorization"] = f"Bearer {presented}"
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            payload = error.read().decode("utf-8")
            error.close()
            return error.code, payload


def _post(
    configured: str,
    rules: Callable[[], None] | None,
    presented: str | None,
    body: object,
) -> tuple[int, str]:
    return _post_raw(configured, rules, presented, json.dumps(body).encode("utf-8"))


@contextmanager
def _served(token: str, rules: Callable[[], None] | None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(token, rules))
    server.daemon_threads = True
    server.block_on_close = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
