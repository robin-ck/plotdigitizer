# plotdigitizer

Extracts calibrated data from XY scatter/line plots in scientific PDFs. Every
value is traceable to figure, panel, series and page.

**Status: LLM-free core.** Positions are measured by deterministic code from the
PDF drawing commands (vector figures). Everything that needs understanding
(axis tick values, legend meanings, context) comes from a hand-written
**Figure Card** (`schemas/figure_card.schema.json`). LLM steps P1–P5 and raster
extraction (stage 5) are stubs.

| Stage | Module | State |
| --- | --- | --- |
| 1 find figures | `find_figures.py` | captions + graphics clusters, no LLM check |
| 2 selection | `select.py` | by figure number |
| 3 Figure Card | `figure_card.py` | hand-written, schema-validated |
| 4 vector | `vector.py` | implemented (spec parser + extensions) |
| 5 raster | `raster.py` | stub |
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
0.07 umol/L, 0.06 m). Blees (raster) waits for stage 5. Tests use synthetic PDFs: a hand-written content
stream mimicking journal path topologies (0.66 pt grid, uneven ticks, several
series per path, fill/stroke pairs, rays) and a matplotlib figure (inset,
log axis, legends).
