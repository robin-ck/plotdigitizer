# Reference test fixtures

The two reference papers are not in the repository (copyright). To run the
acceptance tests in `tests/test_reference_papers.py`, put here:

| File | Content |
| --- | --- |
| `Bastviken2008.pdf` | Bastviken et al. (2008), vector test case, Fig. 2 (p. 6) |
| `Bastviken2008_fig2.json` | hand-written Figure Card (panel bboxes in PDF pt, tick values, legend bboxes, insets) |
| `Bastviken2008_fig2_reference.csv` | reference values from the sheet "Digitalisierte Daten: CH4-Profile" |
| `Blees2014.pdf` | Blees et al. (2014), raster test case, Fig. 1 b-d |
| `Blees2014_fig1.json` | hand-written Figure Card incl. text_checks (p. 315, Results) |
| `Blees2014_fig1_reference.csv` | reference values |

PDFs are git-ignored (`tests/fixtures/*.pdf`).
