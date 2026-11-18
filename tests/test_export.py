import csv

from plotdigitizer.export import collect_csv, is_date_like, write_points_csv


def test_date_like():
    for s in ["Aug 10", "Oct 09", "Jan 10", "Apr 08", "12.05.", "2009-10", "Okt 09"]:
        assert is_date_like(s), s
    for s in ["155", "Peter", "MOR", "DOY 155 (2001)"]:
        assert not is_date_like(s), s


def test_sheet_variant_forces_text(tmp_path):
    rows = [{"series": "Aug 10", "x_value": 1.0}, {"series": "155", "x_value": 2.0}]
    write_points_csv(rows, tmp_path / "a" / "fig1" / "points.csv")
    write_points_csv(rows, tmp_path / "s.csv", sheet=True)
    plain = list(csv.DictReader(open(tmp_path / "a" / "fig1" / "points.csv")))
    sheet = list(csv.DictReader(open(tmp_path / "s.csv")))
    assert plain[0]["series"] == "Aug 10"
    assert sheet[0]["series"] == "'Aug 10" and sheet[1]["series"] == "155"
    out = collect_csv(tmp_path)
    assert len(list(csv.DictReader(open(out)))) == 2
