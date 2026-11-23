import json
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from tradingbot.__main__ import _make_server
from tradingbot.startup import StartupRefused

_TOKEN = "jeton-factice"
_ENVIRONMENT = {"TRADINGBOT_API_TOKEN": _TOKEN}
_ADDRESS = ("127.0.0.1", 0)


class PaperServerTest(unittest.TestCase):
    def test_default_mode_refuses_intent_when_facts_are_missing(self) -> None:
        body = json.dumps(
            {
                "method": "demo",
                "pair": "BTC-EUR",
                "side": "buy",
                "stop_price": "100.00",
                "annotation": "exemple",
            }
        )
        with _make_server(_ENVIRONMENT, _ADDRESS) as server:
            worker = threading.Thread(target=server.serve_forever)
            worker.start()
            try:
                client = HTTPConnection(*server.server_address, timeout=2)
                try:
                    client.request("POST", "/", body)
                    with client.getresponse() as response:
                        self.assertEqual(response.status, 401)
                        self.assertEqual(json.load(response), {"error": "unauthorized"})

                    client.request(
                        "POST", "/", body, {"Authorization": f"Bearer {_TOKEN}"}
                    )
                    with client.getresponse() as response:
                        self.assertEqual(response.status, 503)
                        self.assertEqual(json.load(response), {"error": "STALE_DATA"})
                finally:
                    client.close()
            finally:
                server.shutdown()
                worker.join()

    def test_live_or_unknown_mode_refuses_startup(self) -> None:
        for mode in ("live", "", "unknown"):
            with self.subTest(mode=mode):
                environment = {**_ENVIRONMENT, "TRADINGBOT_MODE": mode}
                with self.assertRaisesRegex(SystemExit, "TRADINGBOT_MODE"):
                    _make_server(environment, _ADDRESS)

    def test_missing_or_blank_token_refuses_startup(self) -> None:
        for environment in ({}, {"TRADINGBOT_API_TOKEN": "  "}):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(StartupRefused, "TRADINGBOT_API_TOKEN"):
                    _make_server(environment, _ADDRESS)

    def test_empty_mail_events_refuse_startup(self) -> None:
        with patch("tradingbot.startup.MAIL_EVENTS", ()):
            with self.assertRaisesRegex(StartupRefused, "mail_events"):
                _make_server(_ENVIRONMENT, _ADDRESS)
