"""Pipeline: Figure Card -> extraction -> checks -> outputs.

Output folder per figure: ``<out>/<citekey>/fig<N>/`` with points.csv,
points_sheet.csv, figure_card.json, compare.png, WPD projects, state.json and
log.jsonl.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import validate as V
from . import vector, wpd
from .export import write_points_csv
from .figure_card import validate_card
from .log import EventLog


def figure_dir(out_root: str | Path, card: dict) -> Path:
    return Path(out_root) / card["paper"]["citekey"] / f"fig{card['figure']['number']}"


def build_rows(card: dict, panels: list[dict], log=None) -> list[dict]:
    """Merge insets and add citekey/figure/variable metadata to each point."""
    rows = []
    by_card = {p["id"]: p for p in card["panels"]}
    for panel in panels:
        pc = by_card[panel["id"]]
        meaning = {s["label"]: s.get("meaning", "") for s in pc["series"]}
        for p in vector.merge_insets(panel, log):
            r = dict(p)
            r.update(
                citekey=card["paper"]["citekey"], figure=card["figure"]["number"], panel=panel["id"],
                variable=pc["x"].get("title", ""), unit=pc["x"].get("unit", ""),
                series_meaning=meaning.get(p["series"], ""), y_unit=pc["y"].get("unit", ""),
            )
            rows.append(r)
    return rows


def finalize(card: dict, panels: list[dict], outdir: Path, pdf_path: str | None, log: EventLog,
             export_wpd: bool = True) -> dict:
    rows = build_rows(card, panels, log)
    kind = card["figure"].get("kind", "vector")
    checks = V.run_checks(card, panels, rows, kind=kind)
    for c in checks:
        ev = "check_ok" if c["ok"] else ("warning_check" if c["level"] != "error" else "error_check")
        log("validate", ev, check=c["check"], **c["detail"])
    V.comparison_png(card, panels, rows, outdir / "compare.png", pdf_path=pdf_path)
    write_points_csv(rows, outdir / "points.csv")
    write_points_csv(rows, outdir / "points_sheet.csv", sheet=True)
    wpd_meta = {}
    if export_wpd and pdf_path:
        by_card = {p["id"]: p for p in card["panels"]}
        for panel in panels:
            wpd_meta[panel["id"]] = wpd.export_panel(pdf_path, card["figure"]["page_pdf"], panel,
                                                    by_card[panel["id"]], outdir, log)
    errors = [c for c in checks if not c["ok"] and c["level"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["level"] == "warning"]
    return {"rows": rows, "checks": checks, "errors": errors, "warnings": warnings, "wpd": wpd_meta}


def digitize(pdf_path: str, card: dict, out_root: str | Path = "out") -> dict:
    validate_card(card)
    outdir = figure_dir(out_root, card)
    outdir.mkdir(parents=True, exist_ok=True)
    logp = outdir / "log.jsonl"
    if logp.exists():
        logp.unlink()
    log = EventLog(logp)
    log("cli", "start", pdf=str(pdf_path), citekey=card["paper"]["citekey"], figure=card["figure"]["number"])
    kind = card["figure"].get("kind", "vector")
    if kind != "vector":
        from . import raster
        raster.extract_panel()
    page, drawings = vector.page_drawings(pdf_path, card["figure"]["page_pdf"])
    log("vector", "page", page=card["figure"]["page_pdf"], n_drawings=len(drawings))
    panels = [vector.extract_panel(drawings, pc, log) for pc in card["panels"]]
    res = finalize(card, panels, outdir, pdf_path, log)
    (outdir / "figure_card.json").write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
    state = {"pdf": str(Path(pdf_path).resolve()), "card": card, "panels": panels, "wpd": res["wpd"]}
    (outdir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    log("cli", "done", points=len(res["rows"]), errors=len(res["errors"]), warnings=len(res["warnings"]))
    res["outdir"] = outdir
    return res


def reimport(project_path: str | Path, figdir: str | Path, panel_id: str | None = None) -> dict:
    """Re-import a corrected WPD project and rerun checks and outputs."""
    figdir = Path(figdir)
    state = json.loads((figdir / "state.json").read_text(encoding="utf-8"))
    log = EventLog(figdir / "log.jsonl")
    project = wpd.load_project(project_path)
    if panel_id is None:
        names = {a["name"] for a in project.get("axesColl", [])}
        panel_id = next(p["id"] for p in state["panels"] if f"Panel {p['id']}" in names)
    panel = next(p for p in state["panels"] if p["id"] == panel_id)
    log("wpd", "reimport_start", project=str(project_path), panel=panel_id)
    stats = wpd.reimport_panel(project, panel, state["wpd"][panel_id], panel["signatures"], log)
    pdf = state["pdf"] if Path(state["pdf"]).exists() else None
    res = finalize(state["card"], state["panels"], figdir, pdf, log, export_wpd=False)
    (figdir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    res["stats"] = stats
    return res
