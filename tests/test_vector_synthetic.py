"""End-to-end vector extraction on synthetic PDFs with known values."""

import csv
import json
import math

import numpy as np
import pytest


def _pts(res, panel, series, source=None):
    return sorted([r for r in res["rows"] if r["panel"] == panel and r["series"] == series
                   and (source is None or r["source"] == source)], key=lambda r: (r["y_value"], r["x_value"]))


def _match(rows, xs, ys, xtol, ytol, logx=False):
    """Every expected point has exactly one extracted point within tolerance."""
    assert len(rows) == len(xs)
    left = list(rows)
    for x, y in zip(xs, ys):
        def d(r):
            dx = abs(math.log10(r["x_value"]) - math.log10(x)) if logx else abs(r["x_value"] - x)
            return dx, abs(r["y_value"] - y)
        cand = [r for r in left if d(r)[0] <= xtol and d(r)[1] <= ytol]
        assert cand, f"no extracted point near ({x}, {y})"
        left.remove(min(cand, key=lambda r: sum(d(r))))


# ---------------- journal-like PDF -----------------

def test_journal_no_errors(journal_run):
    res, _ = journal_run
    assert res["errors"] == []
    assert res["warnings"] == [], res["warnings"]


@pytest.mark.parametrize("series", ["155", "162", "170", "181", "190", "200"])
def test_journal_counts_and_values(journal_run, series):
    res, exp = journal_run
    rows = _pts(res, "a", series)
    e = exp[series]
    # exact count, values within grid quantisation (0.66 pt ~ 0.56 units on x, 0.066 m on y)
    _match(rows, e["x"], e["y"], xtol=1e-3, ytol=1e-3)
    assert {r["shape"] for r in rows} == {e["shape"]}
    assert {r["filled"] for r in rows} == {e["filled"]}
    # nominal (unsnapped) values within the reported uncertainty
    _match(rows, e["x_nominal"], e["y_nominal"], xtol=max(r["uncertainty_x"] for r in rows) + 1e-6,
           ytol=max(r["uncertainty_y"] for r in rows) + 1e-6)


def test_journal_uneven_ticks_and_quantisation_logged(journal_run):
    res, _ = journal_run
    log = [json.loads(l) for l in open(res["outdir"] / "log.jsonl")]
    cal = [e for e in log if e["event"] == "calibration"]
    assert {c["detail"]["axis"] for c in cal} == {"x", "y"}
    assert any(c["detail"]["residual_pt"] > 0.3 for c in cal)  # uneven spacing documented
    unc = next(e for e in log if e["event"] == "uncertainty")
    assert unc["detail"]["quantisation_pt"]["x"] == pytest.approx(0.66, abs=1e-3)
    assert unc["detail"]["quantisation_pt"]["y"] == pytest.approx(0.66, abs=1e-3)
    mk = next(e for e in log if e["event"] == "markers")
    assert mk["detail"]["rejected_by_size"] >= 1  # glyph-like tiny chain filtered


def test_journal_polyline_check(journal_run):
    res, _ = journal_run
    c = next(c for c in res["checks"] if c["check"] == "marker_on_polyline_vertex")
    assert c["ok"] and c["detail"]["median_pt"] < 0.1 and c["detail"]["n"] == 11


def test_journal_text_check_passes(journal_run):
    res, _ = journal_run
    c = next(c for c in res["checks"] if c["check"] == "text_check")
    assert c["ok"], c


def test_journal_outputs(journal_run):
    res, _ = journal_run
    out = res["outdir"]
    for f in ["points.csv", "points_sheet.csv", "figure_card.json", "compare.png", "log.jsonl",
              "panel_a_wpd.json", "panel_a_wpd.tar", "panel_a.png", "state.json"]:
        assert (out / f).exists(), f
    rows = list(csv.DictReader(open(out / "points.csv", encoding="utf-8")))
    assert len(rows) == 38
    r = rows[0]
    assert r["citekey"] == "Synth2026" and r["figure"] == "2" and r["unit"] == "µmol/L"
    assert r["y_unit"] == "m" and r["confidence"] == "gut" and r["series_meaning"].startswith("DOY")


# ---------------- matplotlib PDF -----------------

def test_mpl_no_errors(mpl_run):
    res, _ = mpl_run
    assert res["errors"] == [], res["errors"]
    assert res["warnings"] == [], res["warnings"]


@pytest.mark.parametrize("series", ["Jun 01", "Aug 10", "155"])
def test_mpl_depth_panel(mpl_run, series):
    res, exp = mpl_run
    e = exp["a"][series]
    rows = _pts(res, "a", series)
    _match(rows, e["x"], e["y"], xtol=0.05, ytol=0.005)
    assert {r["shape"] for r in rows} == {e["shape"]} and {r["filled"] for r in rows} == {e["filled"]}


def test_mpl_inset_merge(mpl_run):
    res, exp = mpl_run
    rows = _pts(res, "a", "Oct 09")
    e = exp["a"]["Oct 09"]
    _match(rows, e["x"], e["y"], xtol=0.05, ytol=0.005)
    ins = [r for r in rows if r["source"] == "Inset"]
    assert len(ins) == 5
    for r in ins:  # inset value preferred, both raw values kept and consistent
        assert r["x_raw_inset"] == r["x_value"]
        assert abs(r["x_raw_main"] - r["x_raw_inset"]) < 0.05
        assert r["merge_ok"]
    assert all(r["x_raw_inset"] is None for r in rows if r["source"] == "Hauptpanel")
    c = next(c for c in res["checks"] if c["check"] == "inset_main_agreement")
    assert c["ok"] and c["detail"]["merged"] == 5


@pytest.mark.parametrize("series", ["P", "Q", "R"])
def test_mpl_log_panel(mpl_run, series):
    res, exp = mpl_run
    e = exp["b"][series]
    rows = _pts(res, "b", series)
    _match(rows, e["x"], e["y"], xtol=0.002, ytol=0.005, logx=True)


def test_mpl_shared_position_two_series(mpl_run):
    res, exp = mpl_run
    p = [r for r in res["rows"] if r["panel"] == "b" and abs(r["y_value"] - 1) < 0.01
         and abs(r["x_value"] - exp["b"]["P"]["x"][1]) / exp["b"]["P"]["x"][1] < 0.005]
    assert sorted(r["series"] for r in p) == ["P", "R"]


def test_mpl_expected_counts_checked(mpl_run):
    res, _ = mpl_run
    ec = [c for c in res["checks"] if c["check"] == "expected_count"]
    assert len(ec) == 8 and all(c["ok"] for c in ec)
