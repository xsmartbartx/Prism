"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

from core.clock import utcnow

_REDACT = [
    (
        re.compile(r"(/s/|/embed/|/api/public/shares/|/invite/|/api/v1/invites/)[A-Za-z0-9_\-]+"),
        r"\1***",
    ),
    (re.compile(r"prism_[0-9a-f]{8}_[A-Za-z0-9_\-]+"), "prism_***"),
]


def redact(text: str) -> str:
    for pat, repl in _REDACT:
        text = pat.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": utcnow().isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms", "ip", "user"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = redact(str(val)) if key == "path" else val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).disabled = True
