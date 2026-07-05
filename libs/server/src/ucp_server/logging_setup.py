"""Logging: human-readable by default, JSON lines when UCP_LOG_JSON is set.

Secrets never reach the log stream: anything that looks like a bearer token
or an api-key-ish value is masked before formatting.
"""
from __future__ import annotations

import json
import logging
import re
import time

_SECRET_RE = re.compile(
    r"(?i)(bearer\s+|token[=:\s]+|api[_-]?key[=:\s]+)([A-Za-z0-9._\-]{6,})"
)


def mask_secrets(text: str) -> str:
    return _SECRET_RE.sub(lambda m: m.group(1) + "***", text)


class _MaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = mask_secrets(message)
        record.args = None
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(*, json_logs: bool, level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_MaskingFilter())
    if json_logs:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
