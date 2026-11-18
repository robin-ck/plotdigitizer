"""CSV export: one row per data point (long format)."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable

CSV_COLUMNS = [
    "citekey", "figure", "panel", "variable", "unit", "series", "series_meaning",
    "y_value", "y_unit", "x_value", "source", "x_raw_main", "x_raw_inset",
    "px", "py", "confidence", "uncertainty_x", "uncertainty_y",
]

_MONTHS = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|mär|mai|okt|dez)[a-z]*\.?"
_DATE_LIKE = re.compile(
    rf"^\s*({_MONTHS}\s*['’]?\d{{1,4}}|\d{{1,4}}\s*{_MONTHS}|\d{{1,2}}[./-]\d{{1,2}}([./-](\d{{2,4}})?)?|\d{{4}}-\d{{1,2}}(-\d{{1,2}})?)\s*$",
    re.IGNORECASE,
)


def is_date_like(s) -> bool:
    return isinstance(s, str) and bool(_DATE_LIKE.match(s))


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    return v


def write_points_csv(rows: Iterable[dict], path: str | Path, sheet: bool = False) -> Path:
    """Write the long-format CSV.

    ``sheet=True`` is the variant for spreadsheet upload: text that looks like a
    date (campaign labels such as "Aug 10") is forced to text with a leading
    apostrophe. The plain CSV keeps the labels unchanged.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {k: _fmt(r.get(k)) for k in CSV_COLUMNS}
            if sheet:
                for k in ("series", "series_meaning", "panel"):
                    if is_date_like(out[k]):
                        out[k] = "'" + out[k]
            w.writerow(out)
    return path


def collect_csv(root: str | Path, out: str | Path | None = None) -> Path:
    """Concatenate all ``*/fig*/points.csv`` below ``root`` into one CSV."""
    root = Path(root)
    out = Path(out) if out else root / "all_points.csv"
    rows = []
    for p in sorted(root.glob("*/fig*/points.csv")):
        with p.open(encoding="utf-8") as f:
            rows += list(csv.DictReader(f))
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return out
