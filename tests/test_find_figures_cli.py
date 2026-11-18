import json

import pytest

from plotdigitizer.cli import main
from plotdigitizer.find_figures import find_figures


def test_find_figures_journal(journal):
    pdf, card, _ = journal
    figs = find_figures(str(pdf))
    assert [f["number"] for f in figs] == ["2"]
    f = figs[0]
    assert f["kind"] == "vector" and f["page_pdf"] == 1
    bx = card["panels"][0]["bbox_pt"]
    assert f["bbox"][0] <= bx[0] + 15 and f["bbox"][2] >= bx[2] - 15


def test_find_figures_mpl(mpl):
    pdf, _, _ = mpl
    figs = find_figures(str(pdf))
    assert [f["number"] for f in figs] == ["3"] and figs[0]["kind"] == "vector"


def test_cli_digitize_and_list(journal, tmp_path, capsys):
    pdf, card, _ = journal
    cp = tmp_path / "card.json"
    cp.write_text(json.dumps(card))
    assert main(["digitize", str(pdf), "--card", str(cp), "--out", str(tmp_path / "o")]) == 0
    assert "points: 38" in capsys.readouterr().out
    assert main(["list-figures", str(pdf)]) == 0
    assert "Fig.   2" in capsys.readouterr().out
    assert main(["collect", str(tmp_path / "o")]) == 0


def test_card_schema_rejects_missing_ticks(journal):
    import jsonschema
    import pytest
    from plotdigitizer.figure_card import validate_card
    _, card, _ = journal
    bad = json.loads(json.dumps(card))
    del bad["panels"][0]["x"]["ticks"]
    with pytest.raises(jsonschema.ValidationError):
        validate_card(bad)


def test_tick_count_mismatch_gives_clear_error(journal, tmp_path):
    import pytest
    from plotdigitizer.pipeline import digitize
    from plotdigitizer.vector import AxisError
    pdf, card, _ = journal
    bad = json.loads(json.dumps(card))
    bad["panels"][0]["x"]["ticks"] = [0, 100, 200]
    with pytest.raises(AxisError, match="override"):
        digitize(str(pdf), bad, tmp_path)


def test_card_tick_position_override(journal, tmp_path):
    from plotdigitizer.pipeline import digitize
    pdf, card, _ = journal
    c2 = json.loads(json.dumps(card))
    # explicit [position, value] pairs taken from the detected calibration
    res = digitize(str(pdf), card, tmp_path / "a")
    st = json.loads((res["outdir"] / "state.json").read_text())
    cal = st["panels"][0]["blocks"]["main"]["calibration"]["x"]
    c2["panels"][0]["x"]["ticks"] = [[p, v] for p, v in zip(cal["positions"], cal["values"])]
    res2 = digitize(str(pdf), c2, tmp_path / "b")
    assert [r["x_value"] for r in res2["rows"]] == pytest.approx([r["x_value"] for r in res["rows"]])
