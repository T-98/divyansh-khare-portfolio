"""Structured JSON logging.

One line per turn with the full latency breakdown, so prompt and model tuning
before the interview can be done from the log rather than by feel.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_STANDARD = frozenset(
    """
    args asctime created exc_info exc_text filename funcName levelname levelno lineno
    module msecs message msg name pathname process processName relativeCreated stack_info
    thread threadName taskName
    """.split()
)

_REDACT = ("api_key", "openai_api_key", "authorization", "token", "secret")


def _safe(key: str, value: object) -> object:
    return "[redacted]" if any(marker in key.lower() for marker in _REDACT) else value


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD or key.startswith("_"):
                continue
            payload[key] = _safe(key, value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn's access log is noise next to the turn log.
    logging.getLogger("uvicorn.access").setLevel("WARNING")
