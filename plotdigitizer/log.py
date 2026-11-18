"""JSONL event log: one line per event with time, stage, event, detail."""

from __future__ import annotations

import json
import datetime as _dt
from pathlib import Path
from typing import Any


class EventLog:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.events: list[dict[str, Any]] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, stage: str, event: str, **detail: Any) -> dict:
        rec = {
            "time": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "stage": stage,
            "event": event,
            "detail": _jsonable(detail),
        }
        self.events.append(rec)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def warnings(self) -> list[dict]:
        return [e for e in self.events if e["event"].startswith("warning")]


def _jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if hasattr(x, "item") and callable(x.item):  # numpy scalar
        try:
            return x.item()
        except Exception:
            pass
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, (str, int, bool)) or x is None:
        return x
    return str(x)
