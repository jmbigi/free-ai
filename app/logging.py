from __future__ import annotations
import logging
import os
import re

_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:key|api_key|apikey|access_token|token)=)([^&\s\"]+)"
)


def _redact(value: str) -> str:
    return _QUERY_SECRET_RE.sub(lambda m: m.group(1) + "[REDACTED]", value)


class _RedactQueryFilter(logging.Filter):
    """Redact API keys passed as query params from uvicorn access/error logs.

    Keeps record.args structure intact: uvicorn's AccessFormatter unpacks a
    five-value tuple, so replacing it with an empty tuple breaks access logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(_redact(a) if isinstance(a, str) else a for a in args)
        elif isinstance(args, dict):
            record.args = {k: (_redact(v) if isinstance(v, str) else v) for k, v in args.items()}
        return True


def install_access_log_redaction() -> None:
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, _RedactQueryFilter) for f in logger.filters):
            logger.addFilter(_RedactQueryFilter())


def setup_logging() -> logging.Logger:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger("free-ai")
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(h)
    logger.setLevel(getattr(logging, level, logging.INFO))
    return logger

log = setup_logging()
install_access_log_redaction()