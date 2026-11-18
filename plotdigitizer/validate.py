"""Stage 6: automatic checks and the comparison PNG.

No data set leaves the tool without these checks and the comparison image.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .vector import Calibration, UNASSIGNED

VERTEX_MEDIAN_MAX_PT = 0.1
DUPLICATE_PT = 0.05


def _check(name, ok, level="error", **detail):
    return {"check": name, "ok": bool(ok), "level": "ok" if ok else level, "detail": detail}


def run_checks(card: dict, panels: list[dict], points: list[dict], kind: str = "vector") -> list[dict]:
    """Run all automatic checks; returns a list of check records."""
    results = []
    by_panel_card = {p["id"]: p for p in card["panels"]}
    for panel in panels:
        pid = panel["id"]
        pc = by_panel_card[pid]
        pts = [p for p in points if p["panel"] == pid]
        main = panel["blocks"]["main"]
        main_pts = main["points"]
        # 1) counts: points per series vs markers of that signature in the panel
        series_counts: dict[str, int] = {}
        for p in main_pts:
            series_counts[p["series"]] = series_counts.get(p["series"], 0) + 1
        n_markers = sum(main["marker_counts"].values())
        results.append(_check("marker_count", n_markers == len(main_pts), panel=pid,
                              markers=n_markers, points=len(main_pts), per_series=series_counts))
        unassigned = series_counts.get(UNASSIGNED, 0)
        results.append(_check("all_assigned", unassigned == 0, "warning", panel=pid, unassigned=unassigned))
        for s in pc["series"]:
            if "expected_count" in s:
                got = series_counts.get(s["label"], 0)
                results.append(_check("expected_count", got == s["expected_count"], panel=pid,
                                      series=s["label"], expected=s["expected_count"], got=got))
        for key, blk in panel["blocks"].items():
            if key == "main":
                continue
            ins = next((i for i in pc.get("insets", []) if f"inset:{i['id']}" == key), {})
            exp = ins.get("expected_counts") or {}
            for lab, n in exp.items():
                got = sum(1 for p in blk["points"] if p["series"] == lab)
                results.append(_check("expected_count", got == n, panel=pid, inset=key, series=lab,
                                      expected=n, got=got))
        # 2) vector: markers lie on polyline vertices
        if kind == "vector":
            line_series = {s["label"] for s in pc["series"]
                           if s.get("line") and s.get("line") not in ("none", "")}
            for key, blk in panel["blocks"].items():
                d = [p["vertex_dist"] for p in blk["points"]
                     if p["series"] in line_series and p.get("vertex_dist") is not None]
                if d:
                    med = float(np.median(d))
                    results.append(_check("marker_on_polyline_vertex", med < VERTEX_MEDIAN_MAX_PT, "warning",
                                          panel=pid, block=key, median_pt=med, max_pt=float(np.max(d)), n=len(d)))
        # 3) inset vs main agreement
        bad = [p for p in pts if p.get("merge_ok") is False]
        merged = [p for p in pts if "merge_ok" in p]
        if merged:
            results.append(_check("inset_main_agreement", not bad, "warning", panel=pid, merged=len(merged),
                                  mismatches=[{k: p.get(k) for k in ("series", "y_value", "x_raw_main",
                                                                      "x_raw_inset", "merge_deviation")}
                                              for p in bad]))
        # 4) values within axis range
        for key, blk in panel["blocks"].items():
            cx = Calibration.from_dict(blk["calibration"]["x"])
            cy = Calibration.from_dict(blk["calibration"]["y"])
            ex, ey = blk["axis_extent"]["x"], blk["axis_extent"]["y"]
            xr = sorted([cx(ex[0]), cx(ex[1])])
            yr = sorted([cy(ey[0]), cy(ey[1])])
            out = []
            for p in blk["points"]:
                tx = 1e-6 + p["uncertainty_x"] * 2 + 0.02 * (xr[1] - xr[0])
                ty = 1e-6 + p["uncertainty_y"] * 2 + 0.02 * (yr[1] - yr[0])
                if not (xr[0] - tx <= p["x_value"] <= xr[1] + tx and yr[0] - ty <= p["y_value"] <= yr[1] + ty):
                    out.append({"series": p["series"], "x": p["x_value"], "y": p["y_value"]})
            results.append(_check("within_axis_range", not out, "warning", panel=pid, block=key,
                                  x_range=xr, y_range=yr, outside=out))
        # 5) duplicates
        for key, blk in panel["blocks"].items():
            dups = []
            P = blk["points"]
            for i in range(len(P)):
                for j in range(i + 1, len(P)):
                    a, b = P[i], P[j]
                    if (a["series"] == b["series"] and abs(a["px"] - b["px"]) < DUPLICATE_PT
                            and abs(a["py"] - b["py"]) < DUPLICATE_PT):
                        dups.append({"series": a["series"], "px": a["px"], "py": a["py"]})
            results.append(_check("no_duplicates", not dups, "warning", panel=pid, block=key, duplicates=dups))
    # 6) text checks from the Figure Card
    for tc in card.get("text_checks", []):
        c = tc.get("check")
        if not c:
            results.append(_check("text_check", True, "info", claim=tc["claim"], where=tc.get("where"),
                                  note="no machine-checkable form; check by hand"))
            continue
        sel = [p for p in points
               if (not c.get("panel") or p["panel"] == c["panel"])
               and (not c.get("series") or p["series"] == c["series"])
               and (not c.get("where_y") or c["where_y"][0] <= p["y_value"] <= c["where_y"][1])]
        var = c.get("variable", "x")
        vals = [p[f"{var}_value"] for p in sel]
        if not vals:
            results.append(_check("text_check", False, "warning", claim=tc["claim"], where=tc.get("where"),
                                  note="no points selected"))
            continue
        lo, hi = min(vals), max(vals)
        span = (c.get("max", hi) - c.get("min", lo)) or 1.0
        tol = c.get("tolerance", 0.1 * abs(span))
        ok = True
        if "min" in c:
            ok &= abs(lo - c["min"]) <= tol
        if "max" in c:
            ok &= abs(hi - c["max"]) <= tol
        results.append(_check("text_check", ok, "warning", claim=tc["claim"], where=tc.get("where"),
                              observed=[lo, hi], expected=[c.get("min"), c.get("max")], tolerance=tol,
                              n=len(vals)))
    return results


# --------------------------------------------------------------------------
# Comparison PNG
# --------------------------------------------------------------------------

_MPL_MARKER = {"square": "s", "circle": "o", "triangle": "^", "diamond": "D", "x": "x",
               "plus": "+", "star": "*"}


def _palette(n):
    import matplotlib
    cmap = matplotlib.colormaps["tab10"]
    return [cmap(i % 10) for i in range(max(n, 1))]


def comparison_png(card: dict, panels: list[dict], points: list[dict], out_path: str | Path,
                   pdf_path: str | None = None, image_path: str | None = None, dpi: int = 200) -> Path:
    """Left: original (PDF render) with coloured points. Right: replot with
    identical axes, proportions, insets and grey bands."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # clip region = union of panel bboxes (+ legends)
    boxes = []
    for p in panels:
        for blk in p["blocks"].values():
            boxes.append(blk["bbox"])
        lb = (next(pc for pc in card["panels"] if pc["id"] == p["id"]).get("legend") or {}).get("bbox_pt")
        if lb:
            boxes.append(lb)
    B = np.array(boxes, float)
    pad = 14.0
    C = [B[:, 0].min() - pad, B[:, 1].min() - pad, B[:, 2].max() + pad, B[:, 3].max() + pad]
    W, H = C[2] - C[0], C[3] - C[1]
    scale_in = 6.0 / max(W, H)
    fig = plt.figure(figsize=(2 * W * scale_in, H * scale_in), dpi=dpi / 2)
    left = fig.add_axes([0, 0, 0.5, 1])
    left.set_axis_off()
    if pdf_path:
        import pymupdf
        doc = pymupdf.open(pdf_path)
        page = doc[card["figure"]["page_pdf"] - 1]
        pix = page.get_pixmap(dpi=dpi, clip=pymupdf.Rect(*C))
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3]
        left.imshow(img, extent=[C[0], C[2], C[3], C[1]], interpolation="lanczos")
    left.set_xlim(C[0], C[2])
    left.set_ylim(C[3], C[1])

    labels = sorted({p["series"] for p in points})
    colors = dict(zip(labels, _palette(len(labels))))
    for p in points:
        for (xx, yy) in [(p["px"], p["py"])] + ([(p["main_px"], p["main_py"])] if "main_px" in p else []):
            left.plot(xx, yy, "o", ms=4, mfc="none", mec=colors[p["series"]], mew=0.8)
    left.set_title("Original + extracted points", fontsize=7)

    by_card = {pc["id"]: pc for pc in card["panels"]}
    handles = {}
    for panel in panels:
        pc = by_card[panel["id"]]
        for key, blk in panel["blocks"].items():
            axc = pc if key == "main" else next(i for i in pc.get("insets", []) if f"inset:{i['id']}" == key)
            cx = Calibration.from_dict(blk["calibration"]["x"])
            cy = Calibration.from_dict(blk["calibration"]["y"])
            ex, ey = blk["axis_extent"]["x"], blk["axis_extent"]["y"]
            rect = [0.5 + 0.5 * (ex[0] - C[0]) / W, (C[3] - ey[1]) / H,
                    0.5 * (ex[1] - ex[0]) / W, (ey[1] - ey[0]) / H]
            ax = fig.add_axes(rect)
            ax.set_xscale("log" if cx.log else "linear")
            ax.set_yscale("log" if cy.log else "linear")
            # limits from the axis line extents; orientation follows the original
            ax.set_xlim(cx(ex[0]), cx(ex[1]))
            ax.set_ylim(cy(ey[1]), cy(ey[0]))
            ax.set_xticks(cx.values)
            ax.set_yticks(cy.values)
            ax.tick_params(labelsize=5, length=2)
            if axc["x"].get("side") == "top" or _xaxis_on_top(blk):
                ax.xaxis.tick_top()
            for band in pc.get("bands", []) if key == "main" else []:
                ax.axhspan(band[0], band[1], color="0.85", zorder=0)
            if key == "main":
                ax.set_xlabel(f"{pc['x'].get('title', '')} [{pc['x'].get('unit', '')}]", fontsize=5)
                ax.set_ylabel(f"{pc['y'].get('title', '')} [{pc['y'].get('unit', '')}]", fontsize=5)
                ax.set_title(f"Panel {pc['id']} (replot)", fontsize=6)
            src = [p for p in points if p["panel"] == panel["id"]
                   and ((key == "main" and p.get("source") != "Inset")
                        or (key != "main" and p.get("inset") == key.split(":", 1)[1]))]
            if key == "main":  # main replot also shows merged values at their main position
                src = [p for p in points if p["panel"] == panel["id"]
                       and (p.get("source") != "Inset" or p.get("x_raw_main") is not None)]
            for s in sorted({p["series"] for p in src}):
                sp = sorted([p for p in src if p["series"] == s], key=lambda p: p["y_value"])
                xs = [p["x_raw_main"] if key == "main" and p.get("x_raw_main") is not None else p["x_value"]
                      for p in sp]
                ys = [p["y_value"] for p in sp]
                mk = _MPL_MARKER.get(sp[0].get("shape"), "o")
                sc = next((x for x in pc["series"] if x["label"] == s), {})
                ls = "-" if sc.get("line") not in (None, "", "none") else "none"
                filled = sp[0].get("filled", False)
                h, = ax.plot(xs, ys, mk, ms=3 if key == "main" else 2, color=colors[s],
                             mfc=colors[s] if filled else "none", mew=0.7, ls=ls, lw=0.4)
                handles[s] = h
    if handles:
        fig.legend(list(handles.values()), list(handles.keys()), loc="upper right", fontsize=4,
                   ncol=min(len(handles), 8), frameon=False)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    return out_path


def _xaxis_on_top(blk) -> bool:
    """The calibrated x axis line lies in the upper half of the block."""
    c = (blk.get("axis_coord") or {}).get("x")
    if c is None:
        return False
    y0, y1 = blk["bbox"][1], blk["bbox"][3]
    return c < (y0 + y1) / 2
