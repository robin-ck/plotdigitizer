# plotdigitizer

Extracts calibrated data from XY scatter/line plots in scientific PDFs. Every
value is traceable to figure, panel, series and page.

**Status: LLM-free core.** Positions are measured by deterministic code from the
PDF drawing commands (vector figures). Tick values are read from the tick
labels without an LLM (PDF text layer, OCR fallback) and offered as
suggestions; the hand-written **Figure Card** (`schemas/figure_card.schema.json`)
stays the authority for tick values, legend meanings and context. Raster
figures (embedded images) go through stage 5 (template matching). LLM steps
P1–P5 are stubs.

| Stage | Module | State |
| --- | --- | --- |
| 1 find figures | `find_figures.py` | captions + graphics clusters, no LLM check |
| 2 selection | `select.py` | by figure number |
| 3 Figure Card | `figure_card.py` | hand-written, schema-validated |
| 4 vector | `vector.py` | implemented (spec parser + extensions) |
| tick values | `ticklabels.py` | PDF text + OCR fallback, suggestions only |
| 5 raster | `raster.py` | implemented (pixels -> PDF pt, template matching) |
| 6 validation | `validate.py` | checks + comparison PNG |
| 7 WebPlotDigitizer | `wpd.py` | export + re-import with diff log (format unverified) |
| export | `export.py` | long-format CSV, sheet variant, collect |

## Usage

```bash
pip install -e .[test]
plotdigitizer list-figures paper.pdf
plotdigitizer digitize paper.pdf --card fig2_card.json --out out
plotdigitizer reimport out/Key2008/fig2/corrected_wpd.json out/Key2008/fig2
plotdigitizer collect out
plotdigitizer ticks paper.pdf --page 6 --bbox 40,37,271,265   # suggest tick values
```

Output per figure in `out/<citekey>/fig<N>/`: `points.csv`, `points_sheet.csv`
(date-like labels forced to text), `figure_card.json`, `compare.png`,
`panel_<id>_wpd.json/.tar/.png`, `state.json`, `log.jsonl`.

## Web interface

A browser interface for other researchers: upload a PDF, set up a figure by
drawing boxes on the page, review the extracted points next to the original
and download the CSV. No Figure Card JSON needed.

```bash
pip install -e .[web]
plotdigitizer serve --port 8000
```

Open http://127.0.0.1:8000. Sessions are anonymous (private link) and are
deleted after 7 days, PDF and results included. Configuration is by
environment variables (`PD_DATA_ROOT`, `PD_MAX_UPLOAD_MB`, `PD_MAX_PAGES`,
`PD_JOB_TIMEOUT_S`, `PD_MAX_JOBS`, `PD_DISK_CAP_GB`, `PD_RETENTION_DAYS`,
`PD_TRUSTED_PROXY`, `PD_UPLOADS_PER_HOUR`, `PD_JOBS_PER_10MIN`). Running it on
a public server: see `docs/deployment.md`. Design:
`docs/superpowers/specs/2026-11-18-web-review-ui-design.md`; API:
`openspec/changes/add-web-interface/api.md`.

## Tick values from the labels

`plotdigitizer ticks` and the web set-up screen read the numbers printed next to
the detected ticks:

1. **PDF text layer** (exact): characters with their boxes; `10` with a smaller
   raised number is read as a power of ten; Unicode minus, decimal comma and
   thousands separators are handled.
2. **OCR fallback** when the text layer has nothing usable (labels converted to
   outlines, embedded images): one small window per tick, read by Tesseract.
   Needs `pip install -e .[ocr]` plus the `tesseract` binary
   (`apt install tesseract-ocr`); without it the step is skipped.

Each label goes to the nearest major tick. The values must then be evenly
spaced on a linear or log axis; ticks without a label are filled in from that
fit, and a single OCR misread that breaks the pattern is replaced. OCR results
are always marked "check every value". The web form fills empty tick fields
with the suggestion and sets log scale and inverted; typed values are never
overwritten. Labels are looked for on both frame lines (ticks are often
mirrored on all four sides).

## Raster figures (stage 5)

Needs `pip install -e .[raster]` (OpenCV). `figure.kind`: `raster`, or `auto`
(raster for each panel covered by an embedded image; the web interface always
uses `auto`).

* The panel is rendered at the native resolution of the embedded image and all
  results are converted to PDF points, so calibration, checks, review and CSV
  are the same as for vector figures.
* Axes: long dark lines; ticks: short, thin, isolated strokes attached to them
  (a tick hidden in a frame corner is added when the spacing puts one there).
  Vector axes in mixed figures are used when present.
* Markers: template matching. Templates come from the legend markers (legend
  box) or are drawn from the card's `marker`/`filled` at the best-fitting size.
  `confidence` per point from the match score: `gut` >= 0.8, `mittel` >= 0.65,
  `gering` below (shown as "check: weak match" in the review table).
  `match_threshold` (default 0.6) per panel/inset.
* Uncertainty: one image pixel, converted to values.
* Known limits: markers drawn exactly on top of each other count once; a marker
  cut by the axis frame can be missed (the `expected_count` check reports it);
  axis breaks are not handled. Review every raster figure before export.

## Figure Card essentials (vector)

* `figure.page_pdf`: 1-based page index.
* `panels[].bbox_pt`: panel box in PDF points (PyMuPDF coordinates, origin top left),
  including the tick marks.
* `x/y.ticks`: tick **values** only (any order; direction follows `inverted`).
  Positions are detected. `[position, value]` pairs override detection.
* `legend.bbox_pt`: legend markers are mapped top-to-bottom to the card's series
  with a marker. Without a legend box the card's `marker`/`filled`/`color` are used.
* `insets[]`: own `bbox_pt` and ticks; merged with main points over `merge_on`
  (default `y`) within `merge_tol` (default 0.2); inset value preferred.
* `coord_grid_pt`: PDF coordinate grid (e.g. 0.66) that sets the reading
  uncertainty when it cannot be detected (real journal PDFs).
* optional: `marker_size_pt`, `expected_count`, `bands`, machine-checkable
  `text_checks[].check`.

## Tests

```bash
pytest
```

The reference papers (Bastviken 2008, Blees 2014) are not included (copyright);
see `tests/fixtures/README.md`. With `Bastviken2008.pdf` in place, Fig. 2 is
extracted with all 418 points matching the reference sheet 1:1 (max deviation
0.07 umol/L, 0.06 m). Blees (raster) needs its PDF and a Figure Card; stage 5 is tested on a synthetic PNG figure. Tests use synthetic PDFs: a hand-written content
stream mimicking journal path topologies (0.66 pt grid, uneven ticks, several
series per path, fill/stroke pairs, rays) and a matplotlib figure (inset,
log axis, legends).
