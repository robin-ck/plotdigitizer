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
* optional: `marker_size_pt`, `expected_count`, `bands`, machine-checkable
  `text_checks[].check`.

## Tests

```bash
pytest
```

The reference papers (Bastviken 2008, Blees 2014) are not included; see
`tests/fixtures/README.md`. Tests use synthetic PDFs: a hand-written content
stream mimicking journal path topologies (0.66 pt grid, uneven ticks, several
series per path, fill/stroke pairs, rays) and a matplotlib figure (inset,
log axis, legends).
