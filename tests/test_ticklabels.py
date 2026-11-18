"""Tick values read from tick labels (PDF text layer, OCR fallback)."""

import pytest

from plotdigitizer import ticklabels as tl
from plotdigitizer import vector


@pytest.mark.parametrize("text,val", [
    ("0", 0.0), ("-5", -5.0), ("−5", -5.0), ("0,5", 0.5), ("1,000", 1000.0),
    ("1,000.5", 1000.5), ("2.5e3", 2500.0), (".5", 0.5), ("Aug", None), ("10a", None), ("", None),
])
def test_parse_number(text, val):
    assert tl.parse_number(text) == val


def test_check_values_infers_missing_and_flags_bad():
    pos = [0, 10, 20, 30, 40]
    r = tl.check_values(pos, [0, None, 100, 150, 200])
    assert r["scale"] == "linear" and r["suggested"] == [0, 50, 100, 150, 200] and r["inferred"] == [1]
    assert not r["ok"]
    r = tl.check_values(pos, [1, 10, 100, 1000, None])
    assert r["scale"] == "log" and r["suggested"][-1] == pytest.approx(10000)
    r = tl.check_values(pos, [0, 50, 300, 150, 200])
    assert r["suggested"] is None and "not evenly spaced" in r["message"]
    assert tl.check_values(pos, [0, None, None, None, None])["suggested"] is None


def test_powers_of_ten_from_flat_ocr():
    assert tl._powers_of_ten(["100", "101", "102"]) == [1.0, 10.0, 100.0]
    assert tl._powers_of_ten(["100", "200"]) is None


def _panels(card):
    for pc in card["panels"]:
        ex = ([pc["legend"]["bbox_pt"]] if pc.get("legend") else []) + [i["bbox_pt"] for i in pc.get("insets", [])]
        yield pc, ex


def _read(pdf, card, ocr):
    page, drawings = vector.page_drawings(str(pdf), 1)
    for pc, ex in _panels(card):
        det = vector.detect_ticks(drawings, pc["bbox_pt"], exclude=ex)
        yield pc, tl.read_tick_labels(page, pc["bbox_pt"], det, exclude=ex, ocr=ocr)


def test_pdf_text_matches_card(mpl):
    pdf, card, _ = mpl
    for pc, res in _read(pdf, card, "never"):
        for o in ("x", "y"):
            r = res[o]
            assert r["source"] == "pdf_text"
            assert sorted(r["suggested"]) == sorted(pc[o]["ticks"]), (pc["id"], o, r)
            assert r["scale"] == pc[o].get("scale", "linear")
            assert r["inverted"] == bool(pc[o].get("inverted", False))
            assert r["ok"]


def test_inset_labels(mpl):
    pdf, card, _ = mpl
    page, drawings = vector.page_drawings(str(pdf), 1)
    pc = card["panels"][0]
    ins = pc["insets"][0]
    det = vector.detect_ticks(drawings, ins["bbox_pt"], exclude=[pc["legend"]["bbox_pt"]])
    res = tl.read_tick_labels(page, ins["bbox_pt"], det, ocr="never", margin=10)
    for o in ("x", "y"):
        assert sorted(res[o]["suggested"]) == ins[o]["ticks"]


def test_no_labels_gives_message(journal):
    pdf, card, _ = journal
    for _, res in _read(pdf, card, "never"):
        for o in ("x", "y"):
            assert res[o]["suggested"] is None and "by hand" in res[o]["message"]


@pytest.mark.skipif(not tl.ocr_available(), reason="tesseract/pytesseract not installed")
def test_ocr_matches_card(mpl):
    pdf, card, _ = mpl
    for pc, res in _read(pdf, card, "always"):
        for o in ("x", "y"):
            r = res[o]
            assert r["source"] == "ocr" and not r["ok"]   # OCR always asks for a check
            assert sorted(r["suggested"]) == pytest.approx(sorted(pc[o]["ticks"])), (pc["id"], o, r)


def test_cli_ticks(mpl, capsys):
    from plotdigitizer.cli import main
    pdf, card, _ = mpl
    pc = card["panels"][1]
    bbox = ",".join(str(v) for v in pc["bbox_pt"])
    assert main(["ticks", str(pdf), "--page", "1", "--bbox", bbox, "--ocr", "never",
                 "--exclude", ",".join(str(v) for v in pc["legend"]["bbox_pt"])]) == 0
    out = capsys.readouterr().out
    assert "x: [1, 10, 100, 1000]  scale=log" in out
