# HTTP API contract (web interface)

All JSON. Coordinates are PDF points (PyMuPDF, origin top left). Every
endpoint except session creation is under `/api/s/{token}`; an unknown or
expired token gives 404 `{"detail": "expired or unknown session"}`. Errors:
`{"detail": "<message>"}` with 400 (bad input), 409 (conflict), 413 (too
large), 422 (validation needs reasons), 429 (rate limit), 504 (job timeout),
507 (disk cap).

Long work (find figures, render, detect, extract) runs in a worker subprocess;
the request waits for it (up to the job timeout). The front end needs no polling.

## Session
- `POST /api/sessions` multipart `file` (PDF), `citekey` (string, optional;
  default from file name) → 201 `Session`.
- `GET /api/s/{t}` → `Session`.

`Session` = `{token, citekey, created_at, expires_at, n_pages,
page_sizes: [[w_pt, h_pt], ...], figures: [Figure], results: [{number,
validated, n_points}]}`

`Figure` (from stage 1 detection) = `{number, page_pdf, bbox, kind:
"vector"|"raster", mixed, caption, supported: bool, reason?: string}`.
`supported` is false for raster/mixed figures (reason "Raster: coming later").

## Pages
- `GET /api/s/{t}/pages/{n}.png?zoom=1|2|4` → PNG of 1-based page `n` at
  72*zoom dpi (page width in px = w_pt * zoom). Cached.

## Set-up helpers
- `POST /api/s/{t}/detect` `{page, bbox, exclude?: [bbox], side?: {x?: "bottom"|"top", y?: "left"|"right"}}`
  → `{x: Axis, y: Axis}`, `Axis` = `{coord, lo, hi, ticks: [pos], tick_lengths,
  major: [pos]}` or `{error, ticks: [], major: []}`. x positions are x
  coordinates along a horizontal line at y=`coord`; y positions are y
  coordinates along a vertical line at x=`coord`.
- `POST /api/s/{t}/legend` `{page, bbox}` → `[{marker, filled, color, x, y, size}]`
  top to bottom.

## Figures (results)
`{num}` is the figure number string (e.g. "2").

- `GET /api/s/{t}/figures/{num}/card` → saved Figure Card or 404.
- `POST /api/s/{t}/figures/{num}/extract` `{card, confirm_discard?: bool}` →
  `Review`. The server sets `card.paper.citekey`, `card.figure.number`; the
  client supplies `figure.page_pdf` and `panels`. 400 with a message if the
  card is invalid or extraction fails (e.g. tick count mismatch). 409
  `{"detail": "...", "edits": n}` if the figure has manual edits and
  `confirm_discard` is not true.
- `GET /api/s/{t}/figures/{num}` → `Review`.
- `POST /api/s/{t}/figures/{num}/panels/{pid}/reviewed` → `{reviewed_panels}`.
- `POST /api/s/{t}/figures/{num}/edits` `{edits: [Edit]}` → `Review` plus
  `applied: [{op, id}]`. 400 on unknown ids/ops (nothing applied).
- `POST /api/s/{t}/figures/{num}/validate` `{reasons?: {check_id: text}}` →
  `Review`. 409 if panels not reviewed; 422 `{"detail": ..., "lacking":
  [check_id]}` if failing error-level checks lack reasons.
- `GET /api/s/{t}/figures/{num}/points.csv` and `points_sheet.csv`.
- `GET /api/s/{t}/all_points.csv` → all figures of the session.

`Edit` (see `plotdigitizer/review.py`):
`{op: "move", panel, id, pt: [x, y]}`, `{op: "set", panel, id, value: [xv, yv]}`,
`{op: "add", panel, block, series, pt | value}`, `{op: "delete", panel, id}`.

`Review` = `{number, page_pdf, card, panels: [Panel], checks: [Check],
validation: null | {validated, at, reasons}, reviewed_panels: [pid],
n_edits}`

`Panel` = `{id, clip: bbox (area to show, incl. legend, padded),
signatures: [{label, shape, filled, color, size}], series: [{label, meaning}],
x: {title, unit, scale, inverted}, y: {...}, blocks: {key: Block}}`
(`key` = "main" or "inset:<id>")

`Block` = `{bbox, calibration: {x: {positions, values, scale}, y: {...}},
axis_extent: {x: [lo, hi], y: [lo, hi]}, axis_coord: {x, y},
points: [Point]}`

`Point` = `{id, series, shape, filled, px, py, x_value, y_value,
uncertainty_x, uncertainty_y, confidence, source, edited?: "moved"|"added"}`

`Check` = `{id, check, ok, level: "ok"|"warning"|"error"|"info", detail}`.
