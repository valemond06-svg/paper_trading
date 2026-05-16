import json
import re
import os
from datetime import datetime, timezone
from pathlib import Path

_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{20,}\b")
_URL_TOKEN_RE = re.compile(r"(https?://api\.telegram\.org/bot)[^/\s\"']+")
_LIVE_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAMBOTTOKEN") or ""


def redact(text: str) -> str:
    text = _TOKEN_RE.sub("***REDACTED***", str(text))
    text = _URL_TOKEN_RE.sub(r"\1***REDACTED***", text)
    if _LIVE_TOKEN:
        text = text.replace(_LIVE_TOKEN, "***REDACTED***")
    return text


def json_log(log_file: Path, event: str, component: str,
             level: str = "INFO", **data) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "component": component,
        "event": event,
        "data": {k: redact(str(v)) if isinstance(v, str) else v
                 for k, v in data.items()}
    }
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # logging non deve mai crashare il bot
