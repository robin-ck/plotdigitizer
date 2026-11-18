"""Functions that run in a worker subprocess (see ``jobs.py``).

They take and return plain picklable data. Expected user errors are returned
as ``{"_error": message, "_status": http_code, ...}`` instead of raised.
"""

from __future__ import annotations

import json
from pathlib import Path


def inspect_pdf(pdf: str, max_pages: int) -> dict:
    import pymupdf
    try:
        doc = pymupdf.open(pdf)
    except Exception as e:  # noqa: BLE001
        return {"_error": f"not a readable PDF ({e.__class__.__name__})", "_status": 400}
    if not doc.is_pdf:
        return {"_error": "not a PDF", "_status": 400}
    if doc.needs_pass:
        return {"_error": "password-protected PDFs are not supported", "_status": 400}
    if doc.page_count > max_pages:
        return {"_error": f"too many pages ({doc.page_count} > {max_pages})", "_status": 413}
    sizes = [[round(p.rect.width, 3), round(p.rect.height, 3)] for p in doc]
    from ..find_figures import find_figures
    try:
        figs = find_figures(pdf)
    except Exception:  # noqa: BLE001  detection failing must not block manual set-up
        figs = []
    for f in figs:
        f.pop("image_xrefs", None)
        f["supported"] = f["kind"] == "vector" and not f.get("mixed")
        if not f["supported"]:
            f["reason"] = "Raster: coming later"
    return {"n_pages": doc.page_count, "page_sizes": sizes, "figures": figs}


def render_page(pdf: str, page: int, zoom: int, out: str) -> dict:
    import pymupdf
    doc = pymupdf.open(pdf)
    pix = doc[page - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    tmp = out + ".tmp"
    pix.save(tmp, output="png")
    Path(tmp).replace(out)
    return {"ok": True}


def detect(pdf: str, page: int, bbox, exclude, side) -> dict:
    """Tick positions (drawing commands) plus suggested tick values (PDF text,
    OCR fallback) under ``labels`` on each axis."""
    from .. import ticklabels, vector
    pg, drawings = vector.page_drawings(pdf, page)
    det = vector.detect_ticks(drawings, bbox, exclude=exclude or (), side=side)
    try:
        labels = ticklabels.read_tick_labels(pg, bbox, det, exclude=exclude or ())
    except Exception as e:  # noqa: BLE001  reading labels must never block set-up
        labels = {o: {"error": f"tick labels could not be read ({e.__class__.__name__})", "suggested": None}
                  for o in ("x", "y")}
    for o in ("x", "y"):
        det[o]["labels"] = labels.get(o)
    return det


def legend(pdf: str, page: int, bbox) -> list:
    from .. import vector
    _, drawings = vector.page_drawings(pdf, page)
    return vector.detect_legend(drawings, bbox)


def _save_checks(figdir: Path, res: dict) -> None:
    from ..review import check_id
    for c in res["checks"]:
        c["id"] = check_id(c)
    (figdir / "checks.json").write_text(json.dumps(res["checks"], default=float), encoding="utf-8")


def extract(pdf: str, card: dict, out_root: str) -> dict:
    import jsonschema
    from ..pipeline import digitize
    from ..vector import AxisError
    try:
        res = digitize(pdf, card, out_root, reset_log=False, export_wpd=False, source="web")
    except jsonschema.ValidationError as e:
        return {"_error": f"Figure Card invalid: {e.message}", "_status": 400}
    except (AxisError, ValueError, KeyError) as e:
        return {"_error": str(e), "_status": 400}
    _save_checks(Path(res["outdir"]), res)
    return {"ok": True}


def edits(figdir: str, ops: list) -> dict:
    from ..review import EditError, apply_edits
    try:
        res = apply_edits(figdir, ops)
    except EditError as e:
        return {"_error": str(e), "_status": 400}
    _save_checks(Path(figdir), res)
    return {"applied": res["applied"]}


def validate(figdir: str, reasons: dict) -> dict:
    from ..review import EditError, validate_figure
    try:
        res = validate_figure(figdir, reasons)
    except EditError as e:
        lacking = getattr(e, "lacking", None)
        if lacking:
            return {"_error": str(e), "_status": 422, "lacking": lacking}
        return {"_error": str(e), "_status": 409}
    _save_checks(Path(figdir), res)
    return {"ok": True}


def _sleep(seconds: float) -> dict:
    """Test helper: a job that hangs (checks the hard timeout)."""
    import time
    time.sleep(seconds)
    return {"ok": True}
