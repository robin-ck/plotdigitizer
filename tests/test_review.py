"""Phase 1 of the web interface: point ids, edits, validation, set-up detection."""

import copy
import csv
import json

import pytest

from plotdigitizer import review, vector
from plotdigitizer.pipeline import digitize, load_state


@pytest.fixture()
def fig(journal, tmp_path):
    pdf, card, exp = journal
    res = digitize(str(pdf), copy.deepcopy(card), tmp_path, reset_log=False, export_wpd=False, source="web")
    return res["outdir"], card


def _log(figdir):
    return [json.loads(l) for l in open(figdir / "log.jsonl")]


def _pt(state, pid="main#0", panel="a"):
    p = next(p for p in state["panels"] if p["id"] == panel)
    key = pid.split("#")[0]
    return next(q for q in p["blocks"][key]["points"] if q["id"] == pid)


def test_ids_stable_and_unique(fig):
    figdir, _ = fig
    st = load_state(figdir)
    ids = [q["id"] for q in st["panels"][0]["blocks"]["main"]["points"]]
    assert len(ids) == len(set(ids)) == 38
    assert st["validation"] is None and st["reviewed_panels"] == []


def test_move_and_set_value(fig):
    figdir, _ = fig
    old = _pt(load_state(figdir))
    review.apply_edits(figdir, [{"op": "move", "panel": "a", "id": "main#0", "pt": [old["px"] + 2.0, old["py"]]}])
    new = _pt(load_state(figdir))
    assert new["px"] == pytest.approx(old["px"] + 2.0, abs=1e-3)
    assert new["x_value"] > old["x_value"] and new["confidence"] == review.MANUAL and new["edited"] == "moved"
    # set by value round-trips through the inverse calibration
    review.apply_edits(figdir, [{"op": "set", "panel": "a", "id": "main#0", "value": [42.0, 7.5]}])
    new = _pt(load_state(figdir))
    assert new["x_value"] == pytest.approx(42.0, abs=1e-3) and new["y_value"] == pytest.approx(7.5, abs=1e-3)
    ev = [e for e in _log(figdir) if e["event"] == "manual_move"]
    assert len(ev) == 2 and ev[1]["detail"]["via"] == "set"


def test_add_delete_and_csv(fig):
    figdir, _ = fig
    res = review.apply_edits(figdir, [
        {"op": "add", "panel": "a", "block": "main", "series": "155", "value": [100.0, 10.0]},
        {"op": "delete", "panel": "a", "id": "main#5"},
    ])
    assert [a["op"] for a in res["applied"]] == ["add", "delete"]
    added = res["applied"][0]["id"]
    st = load_state(figdir)
    pts = st["panels"][0]["blocks"]["main"]["points"]
    assert len(pts) == 38 and added == "main#38" and not any(p["id"] == "main#5" for p in pts)
    rows = list(csv.DictReader(open(figdir / "points.csv")))
    assert len(rows) == 38 and any(r["source"] == "manuell" for r in rows)
    ev = {e["event"] for e in _log(figdir)}
    assert {"manual_add", "manual_delete"} <= ev


def test_bad_edits(fig):
    figdir, _ = fig
    for op in ({"op": "move", "panel": "a", "id": "main#999", "pt": [0, 0]},
               {"op": "move", "panel": "zz", "id": "main#0", "pt": [0, 0]},
               {"op": "add", "panel": "a", "block": "main", "pt": [0, 0]},
               {"op": "fly", "panel": "a"}):
        with pytest.raises(review.EditError):
            review.apply_edits(figdir, [op])


def test_validation_flow(fig):
    figdir, _ = fig
    with pytest.raises(review.EditError, match="not reviewed"):
        review.validate_figure(figdir)
    review.mark_reviewed(figdir, "a")
    res = review.validate_figure(figdir)
    assert res["validation"]["validated"] is True
    rows = list(csv.DictReader(open(figdir / "points.csv")))
    assert {r["confidence"] for r in rows} == {review.MANUAL}
    # any edit clears validation
    review.apply_edits(figdir, [{"op": "delete", "panel": "a", "id": "main#1"}])
    assert load_state(figdir)["validation"] is None
    assert "validation_cleared" in [e["event"] for e in _log(figdir)]


def test_validation_needs_reason_for_failing_check(journal, tmp_path):
    pdf, card, _ = journal
    card = copy.deepcopy(card)
    card["panels"][0]["series"][0]["expected_count"] = 99  # force an error-level check failure
    figdir = digitize(str(pdf), card, tmp_path, reset_log=False, export_wpd=False)["outdir"]
    review.mark_reviewed(figdir, "a")
    with pytest.raises(review.EditError) as ei:
        review.validate_figure(figdir)
    lacking = ei.value.lacking
    assert lacking == ["expected_count:a::155"]
    res = review.validate_figure(figdir, {lacking[0]: "count in card was a guess"})
    assert res["validation"]["reasons"] == {lacking[0]: "count in card was a guess"}


def test_rerun_appends_log(journal, tmp_path):
    pdf, card, _ = journal
    for _ in range(2):
        figdir = digitize(str(pdf), copy.deepcopy(card), tmp_path, reset_log=False, export_wpd=False)["outdir"]
    assert sum(e["event"] == "run_start" for e in _log(figdir)) == 2
    figdir = digitize(str(pdf), copy.deepcopy(card), tmp_path)["outdir"]  # CLI default resets
    assert sum(e["event"] == "run_start" for e in _log(figdir)) == 1


def test_detect_ticks_and_legend(journal):
    pdf, card, _ = journal
    pc = card["panels"][0]
    _, drawings = vector.page_drawings(str(pdf), 1)
    t = vector.detect_ticks(drawings, pc["bbox_pt"], exclude=[pc["legend"]["bbox_pt"]])
    assert len(t["x"]["major"]) == len(pc["x"]["ticks"])
    assert len(t["y"]["major"]) == len(pc["y"]["ticks"])
    leg = vector.detect_legend(drawings, pc["legend"]["bbox_pt"])
    assert [m["marker"] for m in leg] == [s["marker"] for s in pc["series"]]
