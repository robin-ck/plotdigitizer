# Project: plotdigitizer

Extracts calibrated data from XY plots in scientific PDFs; every value traceable
to figure, panel, series and page.

- Stack: Python >= 3.9, PyMuPDF, numpy, matplotlib, jsonschema; pytest.
- Package: `plotdigitizer/` (stages: find_figures, figure_card, vector, validate,
  wpd, export, pipeline, cli). Tick values are suggested from tick labels (`ticklabels.py`: PDF text, OCR fallback). Raster figures: `raster.py` (stage 5, template matching, results in PDF pt). LLM steps are stubs.
- Coordinates: PDF points, PyMuPDF origin top left. Values are computed only by
  the Python `Calibration` (piecewise linear, log supported).
- Tests use synthetic PDFs (`tests/synthetic.py`); reference papers are not in
  the repo (copyright).
- Conventions: manual corrections carry `confidence = "manuell geprüft"`;
  every change is logged to `log.jsonl` via `EventLog`.
- Design docs: `docs/superpowers/specs/`.
