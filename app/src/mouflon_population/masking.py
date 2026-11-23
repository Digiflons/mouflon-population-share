"""Keep credentials out of logs (MOUL-21).

Stream addresses can carry a login (``rtsp://user:password@host``). Every log record
goes through :class:`SecretFilter`, which masks such logins and any secret value
registered with :func:`register_secret`.
"""

from __future__ import annotations

import logging
import re
import threading

_URL_LOGIN = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<login>[^/@\s]+)@")
_MASK = "***"
_secrets: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    if value and len(value) >= 3:
        with _lock:
            _secrets.add(value)


def mask(text: str) -> str:
    def _login(match: re.Match[str]) -> str:
        login = match.group("login")
        user = login.split(":", 1)[0] if ":" in login else _MASK
        return f"{match.group('scheme')}{user}:{_MASK}@"

    masked = _URL_LOGIN.sub(_login, text)
    with _lock:
        secrets = sorted(_secrets, key=len, reverse=True)
    for secret in secrets:
        masked = masked.replace(secret, _MASK)
    return masked


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = mask(message)
        record.args = None
        return True


def install(logger: logging.Logger | None = None) -> None:
    """Attach the filter to every handler of ``logger`` (root by default)."""
    target = logger or logging.getLogger()
    for handler in target.handlers:
        if not any(isinstance(f, SecretFilter) for f in handler.filters):
            handler.addFilter(SecretFilter())
