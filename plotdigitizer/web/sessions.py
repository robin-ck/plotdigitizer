"""Anonymous sessions on disk: ``<data_root>/<token>/``.

Layout: ``meta.json``, ``paper.pdf``, ``pages/<n>@<zoom>.png``,
``out/<citekey>/fig<N>/`` (the pipeline's figure folders).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import secrets
import shutil
from pathlib import Path

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def safe_name(s: str, default: str = "paper", maxlen: int = 60) -> str:
    s = SAFE_RE.sub("_", (s or "").strip()).strip("._-")[:maxlen]
    return s or default


class Store:
    def __init__(self, root: Path, retention_days: float):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention = _dt.timedelta(days=retention_days)

    def create(self, citekey: str) -> tuple[str, Path]:
        token = secrets.token_urlsafe(24)  # 32 chars, 192 bits
        d = self.root / token
        d.mkdir()
        created = now()
        meta = {"token": token, "citekey": safe_name(citekey), "created_at": created.isoformat(timespec="seconds"),
                "expires_at": (created + self.retention).isoformat(timespec="seconds")}
        self.write_meta(d, meta)
        return token, d

    def dir(self, token: str) -> Path | None:
        if not TOKEN_RE.match(token or ""):
            return None
        d = self.root / token
        meta = d / "meta.json"
        if not meta.exists():
            return None
        m = json.loads(meta.read_text(encoding="utf-8"))
        if "n_pages" not in m:  # upload not finished
            return None
        if _dt.datetime.fromisoformat(m["expires_at"]) <= now():
            self.delete(token)
            return None
        return d

    @staticmethod
    def meta(d: Path) -> dict:
        return json.loads((d / "meta.json").read_text(encoding="utf-8"))

    @staticmethod
    def write_meta(d: Path, meta: dict) -> None:
        tmp = d / "meta.json.tmp"
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        tmp.replace(d / "meta.json")

    def delete(self, token: str) -> None:
        if TOKEN_RE.match(token or ""):
            shutil.rmtree(self.root / token, ignore_errors=True)

    def cleanup(self) -> int:
        """Delete expired and abandoned (unfinished, > 1 h old) sessions."""
        n = 0
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            try:
                m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                exp = _dt.datetime.fromisoformat(m["expires_at"])
                created = _dt.datetime.fromisoformat(m["created_at"])
                dead = exp <= now() or ("n_pages" not in m and now() - created > _dt.timedelta(hours=1))
            except Exception:  # noqa: BLE001  broken folder
                dead = True
            if dead:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        return n

    def disk_usage(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())
