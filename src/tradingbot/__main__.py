"""Serveur HTTP local réservé au mode à blanc."""

import os
from collections.abc import Mapping
from http.server import ThreadingHTTPServer

from tradingbot.decision import RulesConfig, r0_stale_data
from tradingbot.http_api import make_handler
from tradingbot.startup import StartupRefused, check_startup, start


def _check_freshness() -> tuple[int, dict[str, str]] | None:
    # Le conteneur à blanc ne dispose d'aucune source de faits courtier.
    refusal = r0_stale_data(None, None, None, RulesConfig().max_age_s)
    if refusal is None:
        return None
    return 503, {"error": refusal}


def _make_server(
    environment: Mapping[str, str], address: tuple[str, int]
) -> ThreadingHTTPServer:
    if environment.get("TRADINGBOT_MODE", "paper") != "paper":
        raise SystemExit("TRADINGBOT_MODE : seul le mode paper est autorisé")
    token = environment.get("TRADINGBOT_API_TOKEN", "")
    check_startup({"TRADINGBOT_API_TOKEN": token})
    start()
    return ThreadingHTTPServer(address, make_handler(token, _check_freshness))


def main() -> None:
    try:
        with _make_server(os.environ, ("0.0.0.0", 8080)) as server:
            server.serve_forever()
    except StartupRefused as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
