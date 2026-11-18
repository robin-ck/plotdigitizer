"""Stage 7: WebPlotDigitizer (WPD) project export and re-import.

One project per panel: an image (vector figures rendered at 300 dpi) plus a
JSON with axis calibration and one data set per series (insets get their own
axes and data sets).

UNVERIFIED: the JSON layout follows the spec's expected WPD-4 structure
(``version``, ``axesColl``, ``datasetColl``, ``measurementColl``) and the .tar
layout (``<name>/info.json``, ``<name>/wpd.json``, ``<name>/<image>``) is
from memory. Both must be checked against a real WPD export before relying on
them.

WPD calibrates linearly from two points per axis. The tool never uses WPD's
values: on re-import it converts the corrected pixel positions itself with its
piecewise-linear calibration, so WPD only serves to move/add/delete points.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any

from .vector import Calibration, UNASSIGNED

DPI = 300
MANUAL = "manuell geprüft"
WPD_VERSION = [4, 2]

_COLORS = [(200, 0, 0), (0, 0, 200), (0, 150, 0), (200, 120, 0), (150, 0, 150), (0, 150, 150),
           (120, 120, 0), (90, 90, 90), (230, 60, 140), (60, 200, 60), (40, 40, 160), (160, 80, 40)]


def _axes_name(panel_id: str, key: str) -> str:
    return f"Panel {panel_id}" if key == "main" else f"Panel {panel_id} inset {key.split(':', 1)[1]}"


def _ds_name(series: str, key: str) -> str:
    return series if key == "main" else f"{series} [inset {key.split(':', 1)[1]}]"


def panel_clip(panel: dict, card_panel: dict, pad: float = 12.0) -> list[float]:
    boxes = [b["bbox"] for b in panel["blocks"].values()]
    lb = (card_panel.get("legend") or {}).get("bbox_pt")
    if lb:
        boxes.append(lb)
    return [min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad,
            max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad]


def export_panel(pdf_path: str, page_1based: int, panel: dict, card_panel: dict, outdir: str | Path,
                 log=None) -> dict:
    import pymupdf
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    clip = panel_clip(panel, card_panel)
    s = DPI / 72.0
    doc = pymupdf.open(pdf_path)
    pix = doc[page_1based - 1].get_pixmap(dpi=DPI, clip=pymupdf.Rect(*clip))
    img_name = f"panel_{panel['id']}.png"
    pix.save(str(outdir / img_name))

    def to_px(x, y):
        return (x - clip[0]) * s, (y - clip[1]) * s

    axes, datasets = [], []
    color_i = 0
    for key, blk in panel["blocks"].items():
        cx = Calibration.from_dict(blk["calibration"]["x"])
        cy = Calibration.from_dict(blk["calibration"]["y"])
        ac = blk.get("axis_coord") or {}
        xline = ac.get("x") if ac.get("x") is not None else blk["bbox"][3]
        yline = ac.get("y") if ac.get("y") is not None else blk["bbox"][0]
        xa, xb = cx.positions[0], cx.positions[-1]
        ya, yb = cy.positions[0], cy.positions[-1]
        pts = [
            (*to_px(xa, xline), cx.values[0], 0),
            (*to_px(xb, xline), cx.values[-1], 0),
            (*to_px(yline, ya), 0, cy.values[0]),
            (*to_px(yline, yb), 0, cy.values[-1]),
        ]
        name = _axes_name(panel["id"], key)
        axes.append({
            "name": name, "type": "XYAxes", "isLogX": cx.log, "isLogY": cy.log,
            "calibrationPoints": [{"px": round(px, 3), "py": round(py, 3), "dx": f"{dx:g}", "dy": f"{dy:g}",
                                   "dz": None} for px, py, dx, dy in pts],
        })
        series = []
        for p in blk["points"]:
            if p["series"] not in series:
                series.append(p["series"])
        for sname in series:
            r, g, b = _COLORS[color_i % len(_COLORS)]
            color_i += 1
            data = []
            for p in blk["points"]:
                if p["series"] != sname:
                    continue
                x, y = to_px(p["px"], p["py"])
                data.append({"x": round(x, 3), "y": round(y, 3), "value": [p["x_value"], p["y_value"]]})
            datasets.append({"name": _ds_name(sname, key), "axesName": name, "colorRGB": [r, g, b, 255],
                             "metadataKeys": [], "data": data, "autoDetectionData": None})
    project = {"version": WPD_VERSION, "axesColl": axes, "datasetColl": datasets, "measurementColl": []}
    jpath = outdir / f"panel_{panel['id']}_wpd.json"
    jpath.write_text(json.dumps(project, indent=1), encoding="utf-8")
    # .tar project bundle (layout unverified, see module docstring)
    tname = outdir / f"panel_{panel['id']}_wpd.tar"
    proj = f"panel_{panel['id']}"
    with tarfile.open(tname, "w") as tf:
        for arc, data in ((f"{proj}/wpd.json", json.dumps(project).encode()),
                          (f"{proj}/info.json", json.dumps({"version": WPD_VERSION, "json": "wpd.json",
                                                            "images": [img_name]}).encode()),
                          (f"{proj}/{img_name}", (outdir / img_name).read_bytes())):
            ti = tarfile.TarInfo(arc)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    meta = {"panel": panel["id"], "image": img_name, "json": jpath.name, "tar": tname.name,
            "clip_pt": clip, "scale_px_per_pt": s}
    if log:
        log("wpd", "export", **meta, n_axes=len(axes), n_datasets=len(datasets),
            note="WPD format unverified against a real export")
    return meta


def load_project(path: str | Path) -> dict:
    path = Path(path)
    if path.suffix == ".tar":
        with tarfile.open(path) as tf:
            m = next(m for m in tf.getmembers() if m.name.endswith("wpd.json"))
            return json.loads(tf.extractfile(m).read().decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def _match(old: list[tuple], new: list[tuple], same_px: float, move_px: float):
    """Greedy nearest matching of old and new pixel positions."""
    pairs = []
    for i, (ox, oy) in enumerate(old):
        for j, (nx, ny) in enumerate(new):
            pairs.append((((ox - nx) ** 2 + (oy - ny) ** 2) ** 0.5, i, j))
    pairs.sort()
    used_o, used_n, m = set(), set(), {}
    for d, i, j in pairs:
        if d > move_px or i in used_o or j in used_n:
            continue
        used_o.add(i)
        used_n.add(j)
        m[i] = (j, d)
    return m


def reimport_panel(project: dict, panel: dict, meta: dict, signatures: list[dict], log=None,
                   same_px: float = 0.5, move_px: float = 20.0) -> dict:
    """Apply a corrected WPD project to a panel's blocks (in place).

    Pixel positions are converted back with the tool's own piecewise-linear
    calibration. Every change is logged with old and new position; all points
    of the panel get confidence ``manuell geprüft``.
    """
    s = meta["scale_px_per_pt"]
    clip = meta["clip_pt"]
    sig = {g["label"]: g for g in signatures}
    stats = {"unchanged": 0, "moved": 0, "deleted": 0, "added": 0}
    ds_by_name = {d["name"]: d for d in project.get("datasetColl", [])}
    for key, blk in panel["blocks"].items():
        cx = Calibration.from_dict(blk["calibration"]["x"])
        cy = Calibration.from_dict(blk["calibration"]["y"])
        axes_name = _axes_name(panel["id"], key)
        series = sorted({p["series"] for p in blk["points"]} |
                        {_strip_inset(d["name"]) for d in ds_by_name.values() if d.get("axesName") == axes_name})
        new_points = []
        for sname in series:
            dname = _ds_name(sname, key)
            old = [p for p in blk["points"] if p["series"] == sname]
            ds = ds_by_name.get(dname)
            new_px = [(d["x"], d["y"]) for d in ds["data"]] if ds else []
            old_px = [((p["px"] - clip[0]) * s, (p["py"] - clip[1]) * s) for p in old]
            m = _match(old_px, new_px, same_px, move_px)
            matched_new = set()
            for i, p in enumerate(old):
                if i not in m:
                    stats["deleted"] += 1
                    if log:
                        log("wpd", "manual_delete", panel=panel["id"], block=key, series=sname,
                            old_pt=[p["px"], p["py"]], old_value=[p["x_value"], p["y_value"]])
                    continue
                j, d = m[i]
                matched_new.add(j)
                q = dict(p)
                if d > same_px:
                    nx, ny = new_px[j][0] / s + clip[0], new_px[j][1] / s + clip[1]
                    q.update(px=round(nx, 3), py=round(ny, 3), x_value=cx(nx), y_value=cy(ny),
                             vertex_dist=None)
                    stats["moved"] += 1
                    if log:
                        log("wpd", "manual_move", panel=panel["id"], block=key, series=sname,
                            old_pt=[p["px"], p["py"]], new_pt=[q["px"], q["py"]],
                            old_value=[p["x_value"], p["y_value"]], new_value=[q["x_value"], q["y_value"]])
                else:
                    stats["unchanged"] += 1
                q["confidence"] = MANUAL
                new_points.append(q)
            for j, (x, y) in enumerate(new_px):
                if j in matched_new:
                    continue
                nx, ny = x / s + clip[0], y / s + clip[1]
                g = sig.get(sname, {})
                half = 0.5 / s
                q = dict(series=sname, shape=g.get("shape"), filled=g.get("filled", False),
                         px=round(nx, 3), py=round(ny, 3), w=None, h=None,
                         x_value=cx(nx), y_value=cy(ny),
                         uncertainty_x=cx.half_width(nx, half), uncertainty_y=cy.half_width(ny, half),
                         confidence=MANUAL, source="manuell", vertex_dist=None, draw_index=None)
                new_points.append(q)
                stats["added"] += 1
                if log:
                    log("wpd", "manual_add", panel=panel["id"], block=key, series=sname,
                        new_pt=[q["px"], q["py"]], new_value=[q["x_value"], q["y_value"]])
        new_points.sort(key=lambda p: (p["series"], p["py"], p["px"]))
        blk["points"] = new_points
        blk["marker_counts"] = {"manual": len(new_points)}
    if log:
        log("wpd", "reimport", panel=panel["id"], **stats)
    return stats


def _strip_inset(name: str) -> str:
    i = name.find(" [inset ")
    return name[:i] if i >= 0 else name
