# Web interface for figure set-up and point review

Date: 2026-11-18. Status: draft for approval (builder check done, questions answered).
Mockups: https://claude.ai/artifact/VLGw7WCorEnMxHBoNRHP56 (three artboards: Upload, Set up figure, Review).

## Intent

Other researchers should be able to extract data from XY plots in their own
papers without writing JSON or installing anything. Today, using the tool means
hand-writing a Figure Card and correcting points in WebPlotDigitizer (WPD),
whose file format in `plotdigitizer/wpd.py` is unverified. The web interface
replaces both steps: the user builds the Figure Card by drawing on the page,
then reviews the extracted points against the original and validates them.

Success: a researcher who has never seen the repository uploads a PDF, sets up
a vector figure, corrects the points and downloads a CSV with every value
traceable to figure, panel, series and page, all in the browser.

## Goals

- Upload a PDF, list its figures (stage 1, `find_figures.py`), pick one.
- Build the Figure Card in the browser (panel boxes, legend box, insets, axis
  tick values, units, log/inverted, series names), producing a card that passes
  `schemas/figure_card.schema.json`.
- Run extraction (`pipeline.digitize`) and show the result.
- Review screen with the original plot and the detected points side by side,
  correct points, see the automatic checks, validate the figure, download CSV.
- Runs online on the author's server for multiple anonymous users.

## Non-goals (for this version)

- Raster figures (stage 5 is a stub): shown in the figure list as "coming later".
- LLM-drafted Figure Cards (P1 to P5 are stubs). The design must not block
  adding them later as a "suggest card" step before the set-up screen.
- Accounts, logins, sharing data between users, a common dataset.
- Suggesting the location of a missing point. The mockup's "missing? click to
  add" marker is aspirational; v1 only shows the count mismatch from
  `run_checks`.

## Anti-goals

- Values computed in the browser. All pixel-to-value conversion stays in Python
  with the tool's piecewise-linear `Calibration`, so the web path and CLI path
  give identical numbers.
- Two renderers of the PDF whose coordinates must agree (rules out PDF.js).
- Keeping publishers' PDFs on a public server indefinitely.

## Constraints

- Existing core is Python (PyMuPDF, numpy, matplotlib); keep the CLI working
  and the existing tests green.
- Untrusted uploads: size limit, page limit, per-job timeout, PDF-only.
- Coordinates on the wire are PDF points (PyMuPDF, origin top left), the same
  unit as `bbox_pt` in the card and `px`/`py` on points.

## Approaches considered

1. **Server renders page images; plain HTML/JS front end (chosen).** PyMuPDF
   renders the page as PNG at a requested zoom; the browser draws boxes and
   points on an SVG overlay in PDF-point coordinates. No build step, one
   renderer, `pip install` plus one server process.
2. PDF.js in the browser: smooth zoom and clickable tick text, but a second
   renderer whose coordinates must match PyMuPDF to a fraction of a point.
3. React/Svelte front end: richer components, but Node toolchain and build step
   for a small research tool.

Chosen: 1. Server framework: FastAPI (builder's call to swap for Flask if there is a reason).

## Decisions made with the author

- Scope B: the interface covers Figure Card set-up and review, not review only.
- Hosted online on the author's server.
- No accounts: each upload creates a private session link (unguessable token),
  valid for 7 days.
- Retention: after 7 days the whole session is deleted (PDF, Figure Card,
  points, CSVs, logs). Users download their CSV before then; the upload page
  says so.
- Each user's data is private; nothing is shared between sessions.
- Public: anyone on the internet can use it, no access code. The author accepts
  a public upload form for publishers' PDFs.
- Validation is allowed while checks fail, but every failing error-level check
  needs a short typed reason from the user, which is logged and stored.
- Review screen shows the original plot (read-only) and the detected points
  re-plotted on the same axes (editable) side by side.

## Screens (see mockups)

1. **Upload and pick a figure.** Drop PDF, enter citekey, figure cards from
   `find_figures` with page thumbnails; unsupported kinds greyed out.
2. **Set up figure.** Page image on the left with tools: draw panel box, draw
   legend box, draw inset. Detected tick positions are marked on the page
   (needs a server call that runs axis detection for a drawn box). Right form
   per panel: x/y variable, unit, tick values, log, inverted; series list
   filled top to bottom from the legend markers, user enters names and
   meanings. "Extract points" saves the card and runs the pipeline.
3. **Review.** Left: original crop (PDF render). Right: extracted points
   plotted from their values on the same axes, coloured per series. Both
   views zoom and pan together; selecting a point on either side shows a
   crosshair at the same position on both. Tools: move, add (choose series),
   delete, undo. Side column: failed checks, points table (click row to
   select, values editable), "Download CSV", "Mark validated".

## Validation semantics (proposed by Claude, accepted with the mockups)

- Point edits go to the server as positions in PDF points; the server converts
  them with the panel's `Calibration` and logs `manual_move`, `manual_add`,
  `manual_delete` to `log.jsonl`, mirroring `wpd.reimport_panel`.
- Editing a value in the table converts back to a position server-side.
- Validation is per figure (Claude's call): the button is enabled once every
  panel has been opened in review. If error-level checks fail, a dialog asks
  for one reason per failing check before validating.
- "Mark validated" sets all points of that figure to
  `confidence = "manuell geprüft"` (same as WPD re-import does today) and writes
  `validated: true` with a timestamp to `state.json`. Further edits clear it.
- Checks and CSV outputs are rerun after every edit batch (`pipeline.finalize`).
- Re-extraction after edits (Claude's call): going back to set-up and pressing
  "Extract points" warns that manual edits will be discarded. On confirm,
  extraction reruns; `log.jsonl` is appended to, not deleted, with a
  `run_start` event marking each run, so the audit trail survives.

## Architecture

- `plotdigitizer/web/` package: FastAPI app, static front end
  (`index.html`, JS, CSS), no build step.
- Storage: one directory per session under a configurable data root,
  `<root>/<session-token>/` containing the PDF and the existing
  `<citekey>/fig<N>/` output tree. A cleanup task deletes expired PDFs and
  sessions.
- Refactor where needed so the pipeline can be called per step (card in,
  panels out; edits in, rows out) rather than only via `digitize`/`reimport`;
  WPD export becomes optional in the web path.
- Existing CLI keeps working (it may keep its current log-reset behaviour).
- Public deployment: extraction and page rendering run in a separate worker
  process with a job queue, so a hard timeout can kill a stuck PyMuPDF job and
  the web process stays responsive. Rate limits per IP (uploads and jobs), a
  cap on concurrent jobs, a cap on total disk use (refuse new uploads when
  full), and session tokens of at least 128 bits. Exact values are the
  builder's call, configurable.

## Left to the builder

- Endpoint shapes, front-end code structure, SVG interaction details.
- Page image zoom levels and caching.
- Exact upload limits and timeout values (sensible defaults, configurable).
- Deployment wiring (uvicorn behind the author's reverse proxy); provide a
  run command and a short deployment note.
- Tests: API tests with the synthetic PDFs in `tests/`.
