"""Manual review: point edits, panel review tracking and figure validation.

Used by the web interface. All position <-> value conversions use the panel
block's own piecewise-linear :class:`~plotdigitizer.vector.Calibration`, so a
corrected value is computed exactly as an extracted one. Every change is logged
with old and new position and value (same events as the WPD re-import).

Edit operations (positions in PDF points, PyMuPDF coordinates)::

    {"op": "move",   "panel": "a", "id": "main#3", "pt": [x, y]}
    {"op": "set",    "panel": "a", "id": "main#3", "value": [xv, yv]}
    {"op": "add",    "panel": "a", "block": "main", "series": "A", "pt": [x, y]}
    {"op": "add",    "panel": "a", "block": "main", "series": "A", "value": [xv, yv]}
    {"op": "delete", "panel": "a", "id": "main#3"}
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from .log import EventLog
from .pipeline import finalize, load_state, write_state
from .vector import Calibration

MANUAL = "manuell geprüft"


class EditError(ValueError):
    pass


def _cals(blk):
    return Calibration.from_dict(blk["calibration"]["x"]), Calibration.from_dict(blk["calibration"]["y"])


def _panel(state, pid):
    for p in state["panels"]:
        if p["id"] == pid:
            return p
    raise EditError(f"unknown panel {pid!r}")


def _find(panel, pid_point):
    key = pid_point.split("#", 1)[0]
    blk = panel["blocks"].get(key)
    if blk is None:
        raise EditError(f"unknown point {pid_point!r}")
    for i, p in enumerate(blk["points"]):
        if p.get("id") == pid_point:
            return key, blk, i
    raise EditError(f"unknown point {pid_point!r}")


def _pos(op, cx, cy):
    if "pt" in op:
        x, y = (float(v) for v in op["pt"])
    elif "value" in op:
        x, y = float(cx.inverse(float(op["value"][0]))), float(cy.inverse(float(op["value"][1])))
    else:
        raise EditError("edit needs 'pt' or 'value'")
    return x, y


def check_id(c: dict) -> str:
    d = c.get("detail", {})
    parts = [c["check"], str(d.get("panel", "")), str(d.get("block", d.get("inset", ""))), str(d.get("series", ""))]
    return ":".join(parts).rstrip(":")


def _rerun(figdir: Path, state: dict, log) -> dict:
    pdf = state["pdf"] if Path(state["pdf"]).exists() else None
    res = finalize(state["card"], state["panels"], figdir, pdf, log, export_wpd=False)
    for c in res["checks"]:
        c["id"] = check_id(c)
    return res


def _clear_validation(state, log):
    if state.get("validation"):
        state["validation"] = None
        log("review", "validation_cleared")


def apply_edits(figdir: str | Path, edits: list[dict]) -> dict:
    """Apply a batch of edits, log them, rerun checks and outputs."""
    figdir = Path(figdir)
    state = load_state(figdir)
    log = EventLog(figdir / "log.jsonl")
    sigs_by_panel = {p["id"]: {s["label"]: s for s in p.get("signatures", [])} for p in state["panels"]}
    applied = []
    for op in edits:
        kind = op.get("op")
        panel = _panel(state, op.get("panel"))
        if kind in ("move", "set"):
            key, blk, i = _find(panel, op.get("id", ""))
            cx, cy = _cals(blk)
            x, y = _pos(op, cx, cy)
            p = blk["points"][i]
            q = dict(p)
            q.update(px=round(x, 3), py=round(y, 3), x_value=cx(x), y_value=cy(y), vertex_dist=None,
                     confidence=MANUAL, edited=p.get("edited") or "moved")
            blk["points"][i] = q
            log("review", "manual_move", panel=panel["id"], block=key, id=p["id"], series=p["series"],
                via=kind, old_pt=[p["px"], p["py"]], new_pt=[q["px"], q["py"]],
                old_value=[p["x_value"], p["y_value"]], new_value=[q["x_value"], q["y_value"]])
            applied.append({"op": kind, "id": p["id"]})
        elif kind == "delete":
            key, blk, i = _find(panel, op.get("id", ""))
            p = blk["points"].pop(i)
            log("review", "manual_delete", panel=panel["id"], block=key, id=p["id"], series=p["series"],
                old_pt=[p["px"], p["py"]], old_value=[p["x_value"], p["y_value"]])
            applied.append({"op": kind, "id": p["id"]})
        elif kind == "add":
            key = op.get("block", "main")
            blk = panel["blocks"].get(key)
            if blk is None:
                raise EditError(f"unknown block {key!r}")
            series = op.get("series")
            if not series:
                raise EditError("add needs 'series'")
            cx, cy = _cals(blk)
            x, y = _pos(op, cx, cy)
            g = sigs_by_panel[panel["id"]].get(series, {})
            q_ = blk.get("quantisation_pt", {"x": 0.01, "y": 0.01})
            n = blk.get("next_id", len(blk["points"]))
            q = dict(id=f"{key}#{n}", series=series, shape=g.get("shape"), filled=g.get("filled", False),
                     px=round(x, 3), py=round(y, 3), w=None, h=None, x_value=cx(x), y_value=cy(y),
                     uncertainty_x=cx.half_width(x, max(q_["x"], 0.01) / 2),
                     uncertainty_y=cy.half_width(y, max(q_["y"], 0.01) / 2),
                     confidence=MANUAL, source="manuell", vertex_dist=None, draw_index=None, edited="added")
            if key != "main":
                q["source"] = "manuell (Inset)"
            blk["next_id"] = n + 1
            blk["points"].append(q)
            log("review", "manual_add", panel=panel["id"], block=key, id=q["id"], series=series,
                new_pt=[q["px"], q["py"]], new_value=[q["x_value"], q["y_value"]])
            applied.append({"op": kind, "id": q["id"]})
        else:
            raise EditError(f"unknown op {kind!r}")
    if applied:
        _clear_validation(state, log)
    res = _rerun(figdir, state, log)
    write_state(figdir, state)
    res["applied"] = applied
    return res


def mark_reviewed(figdir: str | Path, panel_id: str) -> list[str]:
    figdir = Path(figdir)
    state = load_state(figdir)
    _panel(state, panel_id)
    rv = state.setdefault("reviewed_panels", [])
    if panel_id not in rv:
        rv.append(panel_id)
        write_state(figdir, state)
    return rv


def failing_errors(res: dict) -> list[dict]:
    return [c for c in res["checks"] if not c["ok"] and c["level"] == "error"]


def validate_figure(figdir: str | Path, reasons: dict[str, str] | None = None) -> dict:
    """Mark a figure validated.

    Every panel must have been reviewed; every failing error-level check needs a
    non-empty reason (keyed by check id). Sets all points to ``manuell geprüft``.
    """
    figdir = Path(figdir)
    reasons = {k: v.strip() for k, v in (reasons or {}).items() if v and v.strip()}
    state = load_state(figdir)
    missing_panels = [p["id"] for p in state["panels"] if p["id"] not in state.get("reviewed_panels", [])]
    if missing_panels:
        raise EditError(f"panels not reviewed yet: {missing_panels}")
    log = EventLog(figdir / "log.jsonl")
    res = _rerun(figdir, state, log)
    need = [c["id"] for c in failing_errors(res)]
    lacking = [k for k in need if k not in reasons]
    if lacking:
        err = EditError(f"reason needed for failing checks: {lacking}")
        err.lacking = lacking
        raise err
    for panel in state["panels"]:
        for blk in panel["blocks"].values():
            for p in blk["points"]:
                p["confidence"] = MANUAL
    at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    state["validation"] = {"validated": True, "at": at, "reasons": {k: reasons[k] for k in need}}
    log("review", "validated", at=at, reasons=state["validation"]["reasons"])
    res = _rerun(figdir, state, log)
    write_state(figdir, state)
    res["validation"] = state["validation"]
    return res
