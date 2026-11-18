"""WPD export and re-import with diff log."""

import json
import shutil

import pytest

from plotdigitizer import wpd
from plotdigitizer.pipeline import digitize, reimport


@pytest.fixture()
def run(journal, tmp_path):
    pdf, card, exp = journal
    res = digitize(str(pdf), card, tmp_path)
    return res, tmp_path


def test_export_structure(run):
    res, _ = run
    proj = json.loads((res["outdir"] / "panel_a_wpd.json").read_text())
    assert proj["version"] == [4, 2]
    ax = proj["axesColl"][0]
    assert ax["name"] == "Panel a" and ax["type"] == "XYAxes" and len(ax["calibrationPoints"]) == 4
    assert {d["name"] for d in proj["datasetColl"]} == {"155", "162", "170", "181", "190", "200"}
    assert sum(len(d["data"]) for d in proj["datasetColl"]) == 38
    # tar bundle carries the same json
    assert wpd.load_project(res["outdir"] / "panel_a_wpd.tar") == proj


def test_reimport_diff(run):
    res, _ = run
    out = res["outdir"]
    proj = json.loads((out / "panel_a_wpd.json").read_text())
    ds = {d["name"]: d for d in proj["datasetColl"]}
    moved = ds["162"]["data"][0]
    moved["x"] += 10.0                       # move ~2.4 pt to the right
    deleted = ds["200"]["data"].pop()        # delete one
    ds["181"]["data"].append({"x": 400.0, "y": 600.0, "value": [0, 0]})  # add one
    edited = out / "corrected.json"
    edited.write_text(json.dumps(proj))
    r = reimport(edited, out)
    assert r["stats"] == {"unchanged": 36, "moved": 1, "deleted": 1, "added": 1}
    assert len(r["rows"]) == 38
    assert {row["confidence"] for row in r["rows"]} == {"manuell geprüft"}
    log = [json.loads(l) for l in open(out / "log.jsonl")]
    ev = [e["event"] for e in log]
    for e in ("manual_move", "manual_delete", "manual_add", "reimport"):
        assert e in ev
    mv = next(e for e in log if e["event"] == "manual_move")
    assert mv["detail"]["new_pt"][0] - mv["detail"]["old_pt"][0] == pytest.approx(10 * 72 / 300, abs=1e-2)
    # values recomputed with the tool's piecewise calibration
    add = next(e for e in log if e["event"] == "manual_add")
    assert add["detail"]["new_value"] != [0, 0]
    assert any(row["source"] == "manuell" for row in r["rows"])
    # checks were rerun after re-import
    assert any(e["stage"] == "validate" for e in log[log.index(next(e for e in log if e["event"] == "reimport")):])
