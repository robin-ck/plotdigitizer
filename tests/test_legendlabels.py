"""Series names read from the legend text (PDF text layer, OCR fallback)."""

import pytest

from plotdigitizer import legendlabels as ll
from plotdigitizer import raster, vector
from plotdigitizer.ticklabels import ocr_available


def _markers(pdf, card, panel):
    pg, dr = vector.page_drawings(str(pdf), card["figure"]["page_pdf"])
    lb = panel["legend"]["bbox_pt"]
    ms = raster.detect_legend(pg, lb) if raster.is_raster_region(pg, lb) else vector.detect_legend(dr, lb)
    return pg, lb, ms


def test_clean():
    assert ll._clean("— Jun 01") == "Jun 01"
    assert ll._clean("-- 155 .") == "155"
    assert ll._clean("CH4 (%)") == "CH4 (%)"


def test_pdf_text_names(mpl):
    pdf, card, _ = mpl
    for pc in card["panels"]:
        if not pc.get("legend"):
            continue
        pg, lb, ms = _markers(pdf, card, pc)
        got = ll.read_legend_labels(pg, lb, ms, use_ocr=False)
        assert [g["label"] for g in got] == [s["label"] for s in pc["series"]]
        assert {g["source"] for g in got} == {"pdf"}


def test_no_text_gives_none(journal):
    pdf, card, _ = journal
    pg, lb, ms = _markers(pdf, card, card["panels"][0])
    assert len(ms) == 6
    assert all(g["label"] is None for g in ll.read_legend_labels(pg, lb, ms, use_ocr=False))


@pytest.mark.skipif(not ocr_available(), reason="tesseract not installed")
def test_ocr_names_raster(rasterfig):
    pytest.importorskip("cv2")
    pdf, card, _ = rasterfig
    pc = card["panels"][0]
    pg, lb, ms = _markers(pdf, card, pc)
    got = ll.read_legend_labels(pg, lb, ms)
    assert [g["label"] for g in got] == [s["label"] for s in pc["series"]]
    assert {g["source"] for g in got} == {"ocr"}
