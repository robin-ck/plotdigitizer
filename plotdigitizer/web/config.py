"""Configuration from environment variables (see openspec design notes)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name, default, cast=str):
    v = os.environ.get(name)
    return cast(v) if v not in (None, "") else default


@dataclass
class Config:
    data_root: Path = field(default_factory=lambda: Path(_env("PD_DATA_ROOT", "./pd-data")).resolve())
    max_upload_mb: float = field(default_factory=lambda: _env("PD_MAX_UPLOAD_MB", 50.0, float))
    max_pages: int = field(default_factory=lambda: _env("PD_MAX_PAGES", 100, int))
    job_timeout_s: float = field(default_factory=lambda: _env("PD_JOB_TIMEOUT_S", 60.0, float))
    max_jobs: int = field(default_factory=lambda: _env("PD_MAX_JOBS", 2, int))
    disk_cap_gb: float = field(default_factory=lambda: _env("PD_DISK_CAP_GB", 10.0, float))
    retention_days: float = field(default_factory=lambda: _env("PD_RETENTION_DAYS", 7.0, float))
    trusted_proxy: str = field(default_factory=lambda: _env("PD_TRUSTED_PROXY", ""))
    # rate limits: (max events, window seconds)
    upload_rate: tuple = field(default_factory=lambda: (_env("PD_UPLOADS_PER_HOUR", 20, int), 3600))
    job_rate: tuple = field(default_factory=lambda: (_env("PD_JOBS_PER_10MIN", 600, int), 600))
