"""Caviardage des journaux : clé et signature n'en sortent pas."""

import logging
import re

# Clé Revolut X : 64 alphanumériques. Signature Ed25519 : base64, souvent 88.
_SECRET = re.compile(r"[A-Za-z0-9+/]{64,}={0,2}")
_REDACTED = "[redacted]"
_FORMATTER = logging.Formatter()


def redact(text: str) -> str:
    return _SECRET.sub(_REDACTED, text)


class SecretRedaction(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = _FORMATTER.formatException(record.exc_info)
            record.exc_info = None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


class _Logger(logging.Logger):
    def __init__(self, name: str, level: int = logging.NOTSET) -> None:
        super().__init__(name, level)
        if _in_scope(name):
            _attach(self)


def _in_scope(name: str) -> bool:
    return name == "tradingbot" or name.startswith("tradingbot.")


def _attach(logger: logging.Logger) -> None:
    if any(isinstance(item, SecretRedaction) for item in logger.filters):
        return
    logger.addFilter(SecretRedaction())


def install_secret_redaction() -> None:
    logging.setLoggerClass(_Logger)
    for name, found in list(logging.Logger.manager.loggerDict.items()):
        if _in_scope(name) and isinstance(found, logging.Logger):
            _attach(found)
    _attach(logging.getLogger("tradingbot"))
