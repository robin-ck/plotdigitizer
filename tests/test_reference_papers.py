"""Acceptance tests on the real reference papers (spec: Testfälle).

The PDFs are not in the repository. Drop them into tests/fixtures/ (see
tests/fixtures/README.md) together with hand-written Figure Cards and the
reference CSVs, then implement these tests.
"""

from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
BASTVIKEN = FIX / "Bastviken2008.pdf"
BLEES = FIX / "Blees2014.pdf"


CARD = FIX / "Bastviken2008_fig2.json"
REF = FIX / "Bastviken2008_fig2_reference.csv"
needs_bastviken = pytest.mark.skipif(not BASTVIKEN.exists(), reason="Bastviken2008.pdf not provided")


@pytest.fixture(scope="module")
def bastviken(tmp_path_factory):
    from plotdigitizer.figure_card import load_card
    from plotdigitizer.pipeline import digitize

    return digitize(str(BASTVIKEN), load_card(CARD), tmp_path_factory.mktemp("out"))


@needs_bastviken
def test_bastviken_fig2_counts(bastviken):
    """Main panels: Paul 151, Peter 208, Hummingbird 59; insets: Paul 75, Peter 89."""
    import json
    log = [json.loads(l) for l in (bastviken["outdir"] / "log.jsonl").read_text().splitlines()]
    kept = {e["detail"]["panel"]: e["detail"]["kept"] for e in log if e["event"] == "markers"}
    assert kept == {"Paul": 151, "Paul:Paul_inset": 75, "Peter": 208, "Peter:Peter_inset": 89,
                    "Hummingbird": 59}
    assert len(bastviken["rows"]) == 418
    assert not bastviken["errors"] and not bastviken["warnings"]


@needs_bastviken
def test_bastviken_fig2_legend(bastviken):
    """Paul 11, Peter 10, Hummingbird 6 series; every point assigned; DOY with year 2001."""
    rows = bastviken["rows"]
    series = {}
    for r in rows:
        series.setdefault(r["panel"], set()).add(r["series"])
    assert {k: len(v) for k, v in series.items()} == {"Paul": 11, "Peter": 10, "Hummingbird": 6}
    assert all(r["series_meaning"] == f"DOY {r['series']} (2001)" for r in rows)


@needs_bastviken
def test_bastviken_fig2_reference_values(bastviken):
    """Each reference point matched 1:1 (same lake, DOY, source) within +-1 umol/L (Peter +-2)."""
    import csv
    ref = list(csv.DictReader(REF.open(encoding="utf-8")))
    assert len(ref) == 418
    pool = {}
    for r in bastviken["rows"]:
        pool.setdefault((r["panel"], r["series"]), []).append(r)
    used = set()
    for x in ref:
        cands = pool[(x["See"], x["DOY (2001)"])]
        best = min(cands, key=lambda p: abs(p["y_value"] - float(x["Tiefe (m)"])))
        assert id(best) not in used
        used.add(id(best))
        tol = 2.0 if x["See"] == "Peter" else 1.0
        assert best["source"] == x["Quelle"]
        assert abs(best["y_value"] - float(x["Tiefe (m)"])) < 0.1
        assert abs(best["x_value"] - float(x["CH4 (µmol/L)"])) <= tol


@pytest.mark.skip(reason="Blees2014.pdf and its Figure Card not provided")
def test_blees_fig1_raster():
    """44 CH4, 40 d13C, 25 MOR values after WPD correction, plus axis points."""


@pytest.mark.skip(reason="needs Figure Card with text_checks for Blees2014 (p. 315, Results)")
def test_blees_text_checks():
    """near-bottom 40-160 umol/L CH4; sediment from 20 cm ~5 mmol/L."""


@pytest.mark.skip(reason="axis breaks are not handled by the raster path yet")
def test_blees_axis_break_open_question():
    """one tick after the break -> open question, no invented values."""
