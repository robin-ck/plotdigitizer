"""Synthetic test PDFs with known data (the real test papers are not in the repo).

* ``make_journal_pdf``: hand-written PDF content stream that mimics the path
  topologies of the journal test case (Bastviken 2008): coordinates on a
  0.66 pt grid, uneven tick spacing, axis + ticks in one path, several series
  in one path, filled circles as fill-object + stroke-object pair, rays for
  x/plus/star, rotated triangles, x axis on top, inverted depth axis.
* ``make_mpl_pdf``: matplotlib figure with two panels (depth profile with
  inset and legend; log x axis), all common marker shapes.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

Q = 0.66        # coordinate grid of the journal-like PDF
PAGE_W, PAGE_H = 612.0, 792.0   # 792 = 1200 * 0.66


def g(v: float) -> float:
    return round(round(v / Q) * Q, 4)


def _piecewise(pos, vals, v):
    return float(np.interp(v, vals, pos)) if vals[0] < vals[-1] else float(np.interp(v, vals[::-1], pos[::-1]))


# --------------------------------------------------------------------------
# journal-like PDF
# --------------------------------------------------------------------------

def make_journal_pdf(path: str | Path) -> tuple[Path, dict, dict]:
    import pymupdf

    # x axis (top) ticks: values 0..200, positions with deliberate unevenness
    xv = [0, 50, 100, 150, 200]
    xp = [g(100 + 60 * k + j) for k, j in enumerate([0, 0.66, 0, -0.66, 0])]
    X0, X1 = xp[0], xp[-1]
    # y axis (left), depth 0..20 m downward, ticks at top->bottom
    yv = [0, 5, 10, 15, 20]
    yp = [g(150 + 50 * k + j) for k, j in enumerate([0, 0, 0.66, 0, 0])]
    Y0, Y1 = yp[0], yp[-1]
    R = 3 * Q  # marker half size 1.98 pt

    def pos(x, d):
        return g(_piecewise(xp, xv, x)), g(_piecewise(yp, yv, d))

    def P(x, y):  # page (top-left) -> PDF user space
        return f"{x:.4f} {PAGE_H - y:.4f}"

    cs: list[str] = []
    # ---- axes + ticks, one stroke path; frame lines without ticks
    axp = [f"{P(X0, Y0)} m {P(X1, Y0)} l", f"{P(X0, Y0)} m {P(X0, Y1)} l",
            f"{P(X0, Y1)} m {P(X1, Y1)} l", f"{P(X1, Y0)} m {P(X1, Y1)} l"]
    for x in xp:
        axp.append(f"{P(x, Y0)} m {P(x, Y0 + 4 * Q)} l")      # ticks point inward (down)
    for y in yp:
        axp.append(f"{P(X0, y)} m {P(X0 + 4 * Q, y)} l")
    cs.append("0 0 0 RG 0.5 w " + " ".join(axp) + " S")

    series = {}
    # A "155": filled circles (fill + stroke object pair) with a polyline
    dA = list(range(0, 21, 2))
    xA = [120 - 4 * d for d in dA]
    series["155"] = ("circle", True, [pos(x, d) for x, d in zip(xA, dA)], dA, xA)
    # B "162": open triangles pointing down / right (closed 3-chains)
    dB = [1, 3, 5, 7, 9, 11, 13, 15]
    xB = [30 + 5 * d for d in dB]
    series["162"] = ("triangle", False, [pos(x, d) for x, d in zip(xB, dB)], dB, xB)
    # C "170": x as rays; first point shares the position with B's first point
    dC = [1, 4, 8, 12, 16, 19]
    xC = [xB[0]] + [180 - 6 * d for d in dC[1:]]
    series["170"] = ("x", False, [pos(x, d) for x, d in zip(xC, dC)], dC, xC)
    # D "181": plus as rays
    dD = [2, 6, 10, 14, 18]
    xD = [10 + 2 * d for d in dD]
    series["181"] = ("plus", False, [pos(x, d) for x, d in zip(xD, dD)], dD, xD)
    # E "190": star as rays (DDDDHH)
    dE = [3, 9, 15, 20]
    xE = [150, 140, 130, 125]
    series["190"] = ("star", False, [pos(x, d) for x, d in zip(xE, dE)], dE, xE)
    # F "200": open squares (re)
    dF = [0, 5, 10, 17]
    xF = [190, 170, 100, 60]
    series["200"] = ("square", False, [pos(x, d) for x, d in zip(xF, dF)], dF, xF)

    def circle(cx, cy, r):
        k = 0.5523 * r
        return (f"{P(cx + r, cy)} m "
                f"{P(cx + r, cy - k)} {P(cx + k, cy - r)} {P(cx, cy - r)} c "
                f"{P(cx - k, cy - r)} {P(cx - r, cy - k)} {P(cx - r, cy)} c "
                f"{P(cx - r, cy + k)} {P(cx - k, cy + r)} {P(cx, cy + r)} c "
                f"{P(cx + k, cy + r)} {P(cx + r, cy + k)} {P(cx + r, cy)} c")

    def tri(cx, cy, r, i):
        if i % 2 == 0:  # pointing down
            v = [(cx - r, cy - r), (cx + r, cy - r), (cx, cy + r)]
        else:           # pointing right (rotated)
            v = [(cx - r, cy - r), (cx + r, cy), (cx - r, cy + r)]
        return f"{P(*v[0])} m {P(*v[1])} l {P(*v[2])} l {P(*v[0])} l"

    def rays(cx, cy, r, kind):
        dirs = {"x": [(1, 1), (-1, -1), (1, -1), (-1, 1)],
                "plus": [(-1, 0), (1, 0), (0, -1), (0, 1)],
                "star": [(1, 1), (-1, -1), (1, -1), (-1, 1), (-1, 0), (1, 0)]}[kind]
        return " ".join(f"{P(cx, cy)} m {P(cx + r * a, cy + r * b)} l" for a, b in dirs)

    def square(cx, cy, r):
        return f"{cx - r:.4f} {PAGE_H - cy - r:.4f} {2 * r:.4f} {2 * r:.4f} re"

    def marker_path(shape, pts):
        out = []
        for i, (x, y) in enumerate(pts):
            out.append({"circle": lambda: circle(x, y, R), "triangle": lambda: tri(x, y, R, i),
                        "x": lambda: rays(x, y, R, "x"), "plus": lambda: rays(x, y, R, "plus"),
                        "star": lambda: rays(x, y, R, "star"), "square": lambda: square(x, y, R)}[shape]())
        return " ".join(out)

    # polyline for A
    pa = series["155"][2]
    cs.append("0.3 w " + f"{P(*pa[0])} m " + " ".join(f"{P(*p)} l" for p in pa[1:]) + " S")
    # A: fill object, then stroke object with the same circles
    cs.append("0 0 0 rg " + marker_path("circle", pa) + " f")
    cs.append("0.4 w " + marker_path("circle", pa) + " S")
    # B..F in ONE stroke path (several series in a single PDF path)
    mixed = " ".join(marker_path(series[k][0], series[k][2]) for k in ("162", "170", "181", "190", "200"))
    cs.append("0.4 w " + mixed + " S")
    # tiny glyph-like closed chain inside the panel (must be rejected by the size filter)
    gx, gy = g(X0 + 100), g(Y1 - 20)
    cs.append(f"0.2 w {P(gx, gy)} m {P(gx + 0.66, gy)} l {P(gx, gy + 0.66)} l {P(gx, gy)} l S")

    # ---- legend right of the panel, entries top -> bottom
    LX = g(X1 + 30)
    order = ["155", "162", "170", "181", "190", "200"]
    leg_pts = {k: (LX, g(Y0 + 20 + 15 * i)) for i, k in enumerate(order)}
    cs.append("0 0 0 rg " + circle(*leg_pts["155"], R) + " f")
    cs.append("0.4 w " + circle(*leg_pts["155"], R) + " S")
    cs.append("0.4 w " + " ".join(marker_path(series[k][0], [leg_pts[k]]) for k in order[1:]) + " S")

    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, ("q\n" + "\n".join(cs) + "\nQ\n").encode())
    doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")
    page = doc[0]
    page.insert_text((X0, Y1 + 30), "Fig. 2 Synthetic depth profiles (journal-like paths).", fontsize=8)
    path = Path(path)
    doc.save(str(path))

    card = {
        "paper": {"citekey": "Synth2026", "pdf": path.name},
        "figure": {"number": "2", "page_pdf": 1, "kind": "vector", "caption": "Synthetic depth profiles"},
        "panels": [{
            "id": "a",
            "bbox_pt": [X0 - 10, Y0 - 10, X1 + 10, Y1 + 10],
            "x": {"title": "CH4", "unit": "µmol/L", "scale": "linear", "ticks": xv},
            "y": {"title": "Depth", "unit": "m", "scale": "linear", "inverted": True, "ticks": yv},
            "legend": {"bbox_pt": [LX - 8, Y0 + 10, LX + 40, Y0 + 20 + 15 * 5 + 8]},
            "series": [
                {"label": "155", "meaning": "DOY 155 (2001)", "marker": "circle", "filled": True, "line": "solid"},
                {"label": "162", "meaning": "DOY 162 (2001)", "marker": "triangle", "filled": False, "line": "none"},
                {"label": "170", "meaning": "DOY 170 (2001)", "marker": "x", "filled": False, "line": "none"},
                {"label": "181", "meaning": "DOY 181 (2001)", "marker": "plus", "filled": False, "line": "none"},
                {"label": "190", "meaning": "DOY 190 (2001)", "marker": "star", "filled": False, "line": "none"},
                {"label": "200", "meaning": "DOY 200 (2001)", "marker": "square", "filled": False, "line": "none"},
            ],
        }],
        "text_checks": [{"claim": "surface CH4 of DOY 155 about 120 µmol/L", "where": "synthetic",
                         "check": {"panel": "a", "series": "155", "variable": "x", "where_y": [0, 0.5],
                                   "min": 120, "max": 120, "tolerance": 2}}],
    }
    expected = {}
    for k, (shape, filled, pts, ds, xs) in series.items():
        # truth = value of the grid-snapped position (snap error is part of the PDF)
        tx = [float(np.interp(p[0], xp, xv)) for p in pts]
        ty = [float(np.interp(p[1], yp, yv)) for p in pts]
        expected[k] = {"shape": shape, "filled": filled, "x": tx, "y": ty, "x_nominal": xs, "y_nominal": ds}
    return path, card, expected


# --------------------------------------------------------------------------
# matplotlib PDF
# --------------------------------------------------------------------------

def make_mpl_pdf(path: str | Path) -> tuple[Path, dict, dict]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    matplotlib.rcParams["pdf.fonttype"] = 42
    fig = plt.figure(figsize=(8, 4), dpi=72)
    axa = fig.add_axes([0.08, 0.1, 0.38, 0.75])
    axb = fig.add_axes([0.58, 0.12, 0.38, 0.75])
    exp: dict = {"a": {}, "a_inset": {}, "b": {}}

    # ---- panel a: depth profile, x on top, inverted y, legend + inset
    d = np.arange(0, 21, 2.0)
    s = {
        "Jun 01": dict(x=250 - 10 * d, y=d, marker="o", mfc="none", ls="--", shape="circle", filled=False),
        "Aug 10": dict(x=200 - 9 * d, y=d, marker="s", mfc=None, ls="-", shape="square", filled=True),
        "Oct 09": dict(x=5 + 0.5 * np.arange(1, 20, 2.0), y=np.arange(1, 20, 2.0), marker="v", mfc=None,
                       ls="none", shape="triangle", filled=True),
        "155": dict(x=np.array([200.0, 182.0]), y=np.array([0.0, 2.0]), marker="D", mfc="none", ls="none",
                    shape="diamond", filled=False),
    }
    for lab, v in s.items():
        kw = dict(marker=v["marker"], ls=v["ls"], ms=5, color="k", label=lab, lw=0.6)
        if v["mfc"] == "none":
            kw["mfc"] = "none"
        axa.plot(v["x"], v["y"], **kw)
        exp["a"][lab] = dict(x=list(v["x"]), y=list(v["y"]), shape=v["shape"], filled=v["filled"])
    axa.set_xlim(0, 300)
    axa.set_ylim(20, 0)
    axa.set_xticks([0, 100, 200, 300])
    axa.set_yticks([0, 5, 10, 15, 20])
    axa.xaxis.tick_top()
    axa.set_xlabel("CH4 (µmol/L)")
    axa.xaxis.set_label_position("top")
    axa.set_ylabel("Depth (m)")
    lega = axa.legend(loc="center right", fontsize=6, numpoints=1)
    ins = axa.inset_axes([0.55, 0.05, 0.42, 0.33])
    oy = s["Oct 09"]["y"]
    ox = s["Oct 09"]["x"]
    m = oy >= 10
    ins.plot(ox[m], oy[m], marker="v", ls="none", ms=3.5, color="k")
    ins.set_xlim(0, 20)
    ins.set_ylim(20, 10)
    ins.set_xticks([0, 10, 20])
    ins.set_yticks([10, 15, 20])
    ins.tick_params(labelsize=5)
    exp["a_inset"]["Oct 09"] = dict(x=list(ox[m]), y=list(oy[m]))

    # ---- panel b: log x axis, x/plus/star/open circle, shared positions
    yP = np.arange(0, 11, 1.0)
    xP = 10 ** (yP * 0.25 + 0.2)
    yQ = np.arange(0.5, 10, 1.0)
    xQ = 10 ** (2.8 - 0.2 * yQ)
    yR = np.array([1.0, 3, 5, 7, 9])
    xR = np.array([xP[1], 20, 20, 20, 20])  # first point shares P's position
    sb = {
        "P": dict(x=xP, y=yP, marker="x", ls="-", shape="x", filled=False),
        "Q": dict(x=xQ, y=yQ, marker="+", ls="none", shape="plus", filled=False),
        "R": dict(x=xR, y=yR, marker="*", ls="none", shape="star", filled=True),
    }
    for lab, v in sb.items():
        axb.plot(v["x"], v["y"], marker=v["marker"], ls=v["ls"], ms=5, color="k", label=lab, lw=0.6)
        exp["b"][lab] = dict(x=list(v["x"]), y=list(v["y"]), shape=v["shape"], filled=v["filled"])
    axb.set_xscale("log")
    axb.set_xlim(1, 1000)
    axb.set_ylim(0, 10)
    axb.set_xticks([1, 10, 100, 1000])
    axb.minorticks_off()
    axb.set_yticks([0, 2, 4, 6, 8, 10])
    axb.set_xlabel("MOR")
    legb = axb.legend(loc="center left", fontsize=6, numpoints=1)
    fig.text(0.08, 0.01, "Figure 3. Synthetic matplotlib panels.", fontsize=8)
    fig.canvas.draw()

    H = fig.get_figheight() * 72

    def bb(artist, pad):
        e = artist.get_window_extent()
        return [e.x0 - pad, H - e.y1 - pad, e.x1 + pad, H - e.y0 + pad]

    path = Path(path)
    fig.savefig(str(path))
    plt.close(fig)
    card = {
        "paper": {"citekey": "Mpl2026", "pdf": path.name},
        "figure": {"number": "3", "page_pdf": 1, "kind": "vector"},
        "panels": [
            {"id": "a", "bbox_pt": bb(axa, 6),
             "x": {"title": "CH4", "unit": "µmol/L", "ticks": [0, 100, 200, 300]},
             "y": {"title": "Depth", "unit": "m", "inverted": True, "ticks": [0, 5, 10, 15, 20]},
             "legend": {"bbox_pt": bb(lega, 0)},
             "insets": [{"id": "i1", "bbox_pt": bb(ins, 5),
                         "x": {"ticks": [0, 10, 20]}, "y": {"inverted": True, "ticks": [10, 15, 20]},
                         "expected_counts": {"Oct 09": 5}}],
             "bands": [[8, 9]],
             "series": [
                 {"label": "Jun 01", "meaning": "June 2001", "marker": "circle", "filled": False, "line": "dashed",
                  "expected_count": 11},
                 {"label": "Aug 10", "meaning": "August 2010", "marker": "square", "filled": True, "line": "solid",
                  "expected_count": 11},
                 {"label": "Oct 09", "meaning": "October 2009", "marker": "triangle", "filled": True, "line": "none",
                  "expected_count": 10},
                 {"label": "155", "meaning": "DOY 155", "marker": "diamond", "filled": False, "line": "none",
                  "expected_count": 2},
             ]},
            {"id": "b", "bbox_pt": bb(axb, 6),
             "x": {"title": "MOR", "unit": "nmol/L/h", "scale": "log", "ticks": [1, 10, 100, 1000]},
             "y": {"title": "Height", "unit": "m", "ticks": [0, 2, 4, 6, 8, 10]},
             "legend": {"bbox_pt": bb(legb, 0)},
             "series": [
                 {"label": "P", "marker": "x", "line": "solid", "expected_count": 11},
                 {"label": "Q", "marker": "plus", "line": "none", "expected_count": 10},
                 {"label": "R", "marker": "star", "filled": True, "line": "none", "expected_count": 5},
             ]},
        ],
    }
    return path, card, exp


# --------------------------------------------------------------------------
# raster PDF (figure embedded as a PNG, journal style)
# --------------------------------------------------------------------------

def make_raster_pdf(path: str | Path, dpi: int = 200) -> tuple[Path, dict, dict]:
    """A journal-style figure saved as PNG and embedded in a PDF page.

    Panel a: depth profile (x on top, inverted y), filled circles with a solid
    line, open circles with a dashed line, filled triangles without a line,
    legend. Panel b: open squares and filled diamonds, negative x values, no
    legend (markers come from the card). All four spines, ticks inward.
    """
    import io

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pymupdf

    rc = {"xtick.direction": "in", "ytick.direction": "in", "xtick.top": True, "ytick.right": True,
          "font.size": 8, "axes.linewidth": 0.8}
    with matplotlib.rc_context(rc):
        fig = plt.figure(figsize=(7.0, 3.4), dpi=dpi)
        axa = fig.add_axes([0.08, 0.08, 0.38, 0.76])
        axb = fig.add_axes([0.58, 0.14, 0.38, 0.76])
        exp: dict = {"a": {}, "b": {}}
        d = np.arange(0, 21, 2.0)
        sa = {
            "May": dict(x=40 + 6 * d, y=d, marker="o", mfc="k", ls="-", shape="circle", filled=True),
            "Aug": dict(x=150 - 4 * d, y=d + 1, marker="o", mfc="none", ls="--", shape="circle", filled=False),
            "Oct": dict(x=np.array([20.0, 60, 100, 140, 180]), y=np.array([3.0, 7, 11, 15, 19]), marker="^",
                        mfc="k", ls="none", shape="triangle", filled=True),
        }
        for lab, v in sa.items():
            axa.plot(v["x"], v["y"], marker=v["marker"], mfc=v["mfc"], ls=v["ls"], ms=5, color="k", lw=0.7,
                     label=lab, mew=0.8)
            exp["a"][lab] = dict(x=list(v["x"]), y=list(v["y"]), shape=v["shape"], filled=v["filled"])
        axa.set_xlim(0, 200)
        axa.set_ylim(21, 0)
        axa.set_xticks([0, 50, 100, 150, 200])
        axa.set_yticks([0, 5, 10, 15, 20])
        axa.xaxis.set_label_position("top")
        axa.tick_params(labeltop=True, labelbottom=False)
        axa.set_xlabel("CH$_4$ (µmol L$^{-1}$)")
        axa.set_ylabel("Depth (m)")
        axa.legend(loc="lower left", fontsize=7, numpoints=1, frameon=False)
        yb = np.arange(1, 10, 1.0)
        sb = {
            "S1": dict(x=-8 + 1.5 * yb, y=yb, marker="s", mfc="none", shape="square", filled=False),
            "S2": dict(x=np.array([-6.0, -2, 2, 6]), y=np.array([8.5, 6.5, 4.5, 2.5]), marker="D", mfc="k",
                       shape="diamond", filled=True),
        }
        for lab, v in sb.items():
            axb.plot(v["x"], v["y"], marker=v["marker"], mfc=v["mfc"], ls="none", ms=5, color="k", mew=0.8)
            exp["b"][lab] = dict(x=list(v["x"]), y=list(v["y"]), shape=v["shape"], filled=v["filled"])
        axb.set_xlim(-10, 10)
        axb.set_ylim(0, 10)
        axb.set_xticks([-10, -5, 0, 5, 10])
        axb.set_yticks([0, 2, 4, 6, 8, 10])
        axb.set_xlabel("δ$^{13}$C (‰)")
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi)
        W, H = fig.canvas.get_width_height()
        boxes = {}
        for key, ax in (("a", axa), ("b", axb)):
            tb = ax.get_tightbbox(renderer)
            boxes[key] = (tb.x0, H - tb.y1, tb.x1, H - tb.y0)   # image px, top-left origin
        leg = axa.get_legend().get_window_extent(renderer)
        legbox = (leg.x0, H - leg.y1, leg.x1, H - leg.y0)
        plt.close(fig)

    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    X0, Y0, w_pt = 60.0, 80.0, 490.0
    s = w_pt / W
    rect = pymupdf.Rect(X0, Y0, X0 + w_pt, Y0 + H * s)
    page.insert_image(rect, stream=buf.getvalue())
    page.insert_text((X0, rect.y1 + 14), "Fig. 4. Synthetic raster figure (embedded PNG).", fontsize=8)
    path = Path(path)
    doc.save(path)

    def pt(b, pad=2.0):
        return [round(X0 + b[0] * s - pad, 2), round(Y0 + b[1] * s - pad, 2),
                round(X0 + b[2] * s + pad, 2), round(Y0 + b[3] * s + pad, 2)]

    card = {
        "paper": {"citekey": "Raster2026", "pdf": str(path)},
        "figure": {"number": "4", "page_pdf": 1, "kind": "raster"},
        "panels": [
            {"id": "a", "bbox_pt": pt(boxes["a"]),
             "x": {"title": "CH4", "unit": "µmol/L", "ticks": [0, 50, 100, 150, 200]},
             "y": {"title": "Depth", "unit": "m", "inverted": True, "ticks": [0, 5, 10, 15, 20]},
             "legend": {"bbox_pt": pt(legbox, 1.0)},
             "series": [
                 {"label": "May", "marker": "circle", "filled": True, "line": "solid", "expected_count": 11},
                 {"label": "Aug", "marker": "circle", "filled": False, "line": "dashed", "expected_count": 11},
                 {"label": "Oct", "marker": "triangle", "filled": True, "line": "none", "expected_count": 5},
             ]},
            {"id": "b", "bbox_pt": pt(boxes["b"]),
             "x": {"title": "d13C", "unit": "permil", "ticks": [-10, -5, 0, 5, 10]},
             "y": {"title": "Height", "unit": "m", "ticks": [0, 2, 4, 6, 8, 10]},
             "series": [
                 {"label": "S1", "marker": "square", "filled": False, "line": "none", "expected_count": 9},
                 {"label": "S2", "marker": "diamond", "filled": True, "line": "none", "expected_count": 4},
             ]},
        ],
    }
    return path, card, exp
