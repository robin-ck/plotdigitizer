"""Stage 5: raster extraction on a synthetic journal-style PNG figure."""

import copy

import numpy as np
import pytest

pytest.importorskip("cv2")

from plotdigitizer import raster, ticklabels, vector  # noqa: E402
from plotdigitizer.pipeline import digitize  # noqa: E402


def _match(rows, exp, panel, xr, yr):
    """Max error per series as a fraction of the axis range, and misses."""
    out = {}
    for lab, e in exp[panel].items():
        mine = [r for r in rows if r["panel"] == panel and r["series"] == lab]
        errs = []
        for x, y in zip(e["x"], e["y"]):
            d = [max(abs(r["x_value"] - x) / xr, abs(r["y_value"] - y) / yr) for r in mine] or [1.0]
            errs.append(min(d))
        out[lab] = (len(mine), sorted(errs))
    return out


@pytest.fixture(scope="module")
def run(rasterfig, tmp_path_factory):
    pdf, card, exp = rasterfig
    return digitize(str(pdf), card, tmp_path_factory.mktemp("out_raster")), exp


def test_values_and_counts(run):
    res, exp = run
    a = _match(res["rows"], exp, "a", 200, 21)
    b = _match(res["rows"], exp, "b", 20, 10)
    for lab in ("May", "Oct"):
        assert a[lab][0] == len(exp["a"][lab]["x"]) and a[lab][1][-1] < 0.005, (lab, a[lab])
    # the last "Aug" circle is cut in half by the bottom axis: known miss
    n, errs = a["Aug"]
    assert n == 10 and sum(e < 0.005 for e in errs) == 10
    for lab in ("S1", "S2"):
        assert b[lab][0] == len(exp["b"][lab]["x"]) and b[lab][1][-1] < 0.005, (lab, b[lab])
    failed = [(c["check"], c["detail"].get("series")) for c in res["checks"] if not c["ok"]]
    assert failed == [("expected_count", "Aug")]   # the miss is reported, not hidden


def test_points_carry_confidence_and_uncertainty(run):
    res, _ = run
    assert {r["confidence"] for r in res["rows"]} <= {"gut", "mittel", "gering"}
    assert all(0 < r["uncertainty_x"] < 1.0 for r in res["rows"] if r["panel"] == "a")


def test_auto_picks_raster(rasterfig, tmp_path):
    pdf, card, _ = rasterfig
    c = copy.deepcopy(card)
    c["figure"]["kind"] = "auto"
    res = digitize(str(pdf), c, tmp_path)
    assert len(res["rows"]) == 39


def test_ticks_and_legend(rasterfig):
    pdf, card, _ = rasterfig
    page, drawings = vector.page_drawings(str(pdf), 1)
    for pc in card["panels"]:
        assert raster.is_raster_region(page, pc["bbox_pt"])
        ex = [pc["legend"]["bbox_pt"]] if pc.get("legend") else []
        det = raster.detect_ticks(page, drawings, pc["bbox_pt"], ex)
        assert det["method"] == "raster" and det["axes_from"] == "raster"
        for o in ("x", "y"):
            assert len(det[o]["major"]) == len(pc[o]["ticks"]), (pc["id"], o, det[o])
    leg = raster.detect_legend(page, card["panels"][0]["legend"]["bbox_pt"])
    assert [(m["marker"], m["filled"]) for m in leg] == [("circle", True), ("circle", False), ("triangle", True)]


@pytest.mark.parametrize("shape", ["circle", "square", "diamond", "triangle"])
@pytest.mark.parametrize("filled", [True, False])
def test_classify_drawn_markers(shape, filled):
    t = raster.draw_template(shape, filled, 24)
    assert raster.classify(t < 128) == {"shape": shape, "filled": filled}


@pytest.mark.skipif(not ticklabels.ocr_available(), reason="tesseract/pytesseract not installed")
def test_ocr_reads_raster_tick_labels(rasterfig):
    pdf, card, _ = rasterfig
    page, drawings = vector.page_drawings(str(pdf), 1)
    pc = card["panels"][1]
    det = raster.detect_ticks(page, drawings, pc["bbox_pt"])
    res = ticklabels.read_tick_labels(page, pc["bbox_pt"], det)
    for o in ("x", "y"):
        assert res[o]["source"] == "ocr"
        assert sorted(res[o]["suggested"]) == pytest.approx(pc[o]["ticks"]), (o, res[o])
