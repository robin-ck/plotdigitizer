# Design notes: add-web-interface

Full design and rationale: `docs/superpowers/specs/2026-11-18-web-review-ui-design.md`.
Implementation choices on top of it:

- **Server:** FastAPI + uvicorn, one web process. Static files served by FastAPI.
- **Worker / job queue:** no Redis. A small in-app job manager runs each job
  (find figures, render page, detect ticks, extract) in its own
  `multiprocessing` child with a hard timeout (killed on expiry). A semaphore
  caps concurrent jobs; excess jobs queue in memory. Jobs are polled by id.
  Trade-off: single-instance only, queue lost on restart (acceptable: sessions
  hold all durable state on disk).
- **Storage:** `<data_root>/<token>/` with `meta.json` (created, expires,
  citekey), `paper.pdf`, page PNG cache, and the existing
  `<citekey>/fig<N>/` tree. Token: `secrets.token_urlsafe(24)` (192 bits).
  Cleanup loop deletes expired session dirs hourly.
- **Rate limits:** in-memory sliding window per client IP (honours
  `X-Forwarded-For` only from a configured trusted proxy). Separate limits for
  uploads and jobs.
- **Edits:** client sends `{op: move|add|delete, panel, block, point_id,
  pt: [x, y] (PDF pt) | value: [x, y]}` batches; server applies with
  `Calibration`/`Calibration.inverse`, logs `manual_*`, reruns `finalize`.
  Points get stable ids (`<block>:<n>`) assigned at extraction.
- **Page images:** rendered on demand at fixed zoom steps (1x, 2x, 4x of 72 dpi),
  cached as PNG in the session dir.
- **Front end:** vanilla JS modules, one SVG overlay per view, coordinates in
  PDF points via `viewBox`, so zoom/pan is a viewBox change shared by both
  review views.
- **Config:** env vars `PD_DATA_ROOT`, `PD_MAX_UPLOAD_MB` (50), `PD_MAX_PAGES`
  (100), `PD_JOB_TIMEOUT_S` (60), `PD_MAX_JOBS` (2), `PD_DISK_CAP_GB` (10),
  `PD_TRUSTED_PROXY`, `PD_RETENTION_DAYS` (7).
