# Proposal: add-web-interface

## Why
Using plotdigitizer today means hand-writing a Figure Card in JSON and correcting
points in WebPlotDigitizer, whose file format is unverified. Other researchers
cannot do that. A public web interface lets anyone upload a PDF, set up a figure
by drawing on the page, review points against the original and download a CSV.
Approved design: `docs/superpowers/specs/2026-11-18-web-review-ui-design.md`.

## What changes
- New `plotdigitizer/web/` package: FastAPI app, worker process for extraction
  and rendering, static HTML/JS front end (no build step).
- Anonymous sessions with unguessable links; whole session deleted after 7 days.
- Three screens: upload and pick figure; set up figure (boxes, ticks, series);
  review (original and detected side by side, edit, checks, validate, CSV).
- Point edits and validation recorded in `log.jsonl` and `state.json`.
- Pipeline split into callable steps (extract, apply edits, finalize) so the
  web and CLI share one code path; `digitize` keeps its CLI behaviour.
- Public-server protection: upload limits, per-job timeout, rate limits, disk cap.
- New optional dependency group `web` (fastapi, uvicorn, python-multipart).

## Impact
- New capability spec: `web-interface`. No existing specs (first use of openspec).
- Touched code: `pipeline.py` (refactor into steps, log append mode),
  `vector.py` (expose tick detection for a drawn box), `pyproject.toml`, README.
- Risks: untrusted PDFs parsed on a public server; copyright of uploaded papers
  (mitigated by 7-day deletion, private sessions); correctness of client edits
  (mitigated: all conversions server-side).
- No breaking changes to the CLI.
