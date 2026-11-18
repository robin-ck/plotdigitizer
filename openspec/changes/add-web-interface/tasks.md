# Tasks: add-web-interface

## 1. Core refactor (no web yet)
- [x] 1.1 Split `pipeline.digitize` into `extract(pdf, card) -> panels` and `finalize`; give points stable ids; CLI behaviour unchanged
- [x] 1.2 Add `run_start` events and append-mode logging for the web path (CLI keeps reset)
- [x] 1.3 Add `pipeline.apply_edits(state, edits, log)` (move/add/delete/set-value via `Calibration`/`inverse`), logging `manual_*`
- [x] 1.4 Add `pipeline.validate_figure(state, reasons, log)` and clearing on edit
- [x] 1.5 Expose `vector.detect_ticks(pdf, page, bbox)` returning tick positions per axis
- [x] 1.6 Tests for 1.1–1.5 on synthetic PDFs; existing tests stay green

## 2. Server
- [ ] 2.1 `web` extra in `pyproject.toml`; `plotdigitizer/web/` package; `plotdigitizer serve` CLI command
- [ ] 2.2 Config from env vars (design.md)
- [ ] 2.3 Session store: create, load by token, expiry, cleanup loop, disk cap
- [ ] 2.4 Job manager: subprocess per job, hard timeout, concurrency cap, job status endpoint
- [ ] 2.5 Rate limiter per IP with trusted-proxy handling
- [ ] 2.6 Endpoints: upload, figures, page image, detect ticks, save card + extract, get panel state, edits, validate, CSV downloads
- [ ] 2.7 API tests (FastAPI TestClient) for every endpoint, limits, isolation and expiry

## 3. Front end
- [ ] 3.1 Shell, routing between the three screens, session link display
- [ ] 3.2 Upload and figure picker screen
- [ ] 3.3 Set-up screen: page view, draw/resize boxes, tick markers, panel/axis/series form, validation of tick counts
- [ ] 3.4 Review screen: two synced views (original, re-plotted), crosshair, move/add/delete/undo
- [ ] 3.5 Points table with inline editing, checks panel, validate dialog with reasons, CSV download
- [ ] 3.6 Browser smoke test with Playwright on a synthetic PDF (upload → set up → extract → edit → validate → CSV)

## 4. Docs and deploy
- [ ] 4.1 README section: run locally, configuration
- [ ] 4.2 Deployment note: uvicorn behind a reverse proxy, data dir, trusted proxy, upload size in proxy
