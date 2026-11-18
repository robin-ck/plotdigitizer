"""Stage 5: extraction from raster images.

The figure region is rendered from the PDF at (at least) the native resolution
of the embedded image, and everything found in the pixels is converted back to
PDF points. Calibration, checks, review and export therefore work exactly as
for vector figures.

* Axes and ticks: long dark runs (axis lines) and short perpendicular runs
  attached to them (ticks) become pseudo line segments, which go through the
  same ``vector.find_axis`` / ``calibrate_axis`` code as vector drawings. If the
  axes of a mixed figure are vector drawings, those are used instead (exact).
* Markers: template matching (normalised cross-correlation). Templates are cut
  from the legend markers when a legend box is given, otherwise drawn from the
  card's ``marker``/``filled`` at the size that matches the image best. Every
  location is assigned to the template that matches best there.
* Confidence per point from the match score: ``gut`` >= 0.8, ``mittel`` >=
  0.65, ``gering`` below. Uncertainty: one image pixel, converted to values.

Limits: markers drawn exactly on top of each other count once; markers cut by
the axis frame and very busy regions match worse (lower confidence). Review in
the web interface (or WebPlotDigitizer) is part of the raster workflow.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from . import vector

GOOD, MEDIUM, LOW = "gut", "mittel", "gering"
MIN_ZOOM, MAX_ZOOM = 3.0, 8.0


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def image_coverage(page, bbox: Sequence[float]) -> tuple[float, float | None]:
    """(fraction of ``bbox`` covered by embedded images, native px per pt)."""
    import pymupdf
    box = pymupdf.Rect(*bbox)
    if box.is_empty:
        return 0.0, None
    cov, dens = 0.0, None
    for img in page.get_images(full=True):
        xref, w_px = img[0], img[2]
        try:
            rects = page.get_image_rects(xref)
        except Exception:  # noqa: BLE001
            continue
        for r in rects:
            inter = r & box
            if inter.is_empty:
                continue
            cov = max(cov, inter.get_area() / box.get_area())
            if r.width > 0:
                d = w_px / r.width
                dens = d if dens is None else max(dens, d)
    return cov, dens


def is_raster_region(page, bbox: Sequence[float], min_cover: float = 0.3) -> bool:
    return image_coverage(page, bbox)[0] >= min_cover


class Render:
    """Grey image of a page region; ``pt(x_px, y_px)`` maps back to PDF pt."""

    def __init__(self, page, region: Sequence[float], zoom: float | None = None):
        import pymupdf
        _, dens = image_coverage(page, region)
        self.native = dens                  # native image px per pt (None: no image)
        self.zoom = float(np.clip(zoom or (dens or 4.0), MIN_ZOOM, MAX_ZOOM))
        r = pymupdf.Rect(*region) & page.rect
        self.x0, self.y0 = r.x0, r.y0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom), clip=r, alpha=False,
                              colorspace=pymupdf.csGRAY)
        self.gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
        self.ink = self.gray < ink_threshold(self.gray)

    def pt(self, xp, yp):
        return self.x0 + np.asarray(xp, float) / self.zoom, self.y0 + np.asarray(yp, float) / self.zoom

    def px(self, x, y):
        return (np.asarray(x, float) - self.x0) * self.zoom, (np.asarray(y, float) - self.y0) * self.zoom

    def blank(self, boxes: Sequence[Sequence[float]], pad: float = 0.0):
        """White out page boxes (legend, insets) so they do not count as ink."""
        for b in boxes:
            c0, r0 = self.px(b[0] - pad, b[1] - pad)
            c1, r1 = self.px(b[2] + pad, b[3] + pad)
            c0, r0 = max(int(np.floor(c0)), 0), max(int(np.floor(r0)), 0)
            c1, r1 = int(np.ceil(c1)), int(np.ceil(r1))
            self.gray[r0:r1, c0:c1] = 255
            self.ink[r0:r1, c0:c1] = False

    @property
    def px_pt(self) -> float:
        """Size of one source pixel in pt (the resolution limit)."""
        return 1.0 / (self.native if self.native else self.zoom)


def ink_threshold(gray: np.ndarray) -> int:
    import cv2
    t, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return int(min(max(t, 90), 200))


# --------------------------------------------------------------------------
# Axes and ticks -> pseudo segments for vector.find_axis
# --------------------------------------------------------------------------

def _runs(mask_1d: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate([[0], mask_1d.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1))


def raster_segments(R: Render, bbox: Sequence[float], min_frac: float = 0.3,
                    tick_max_pt: float = 6.0, exclude: Sequence[Sequence[float]] = ()) -> tuple[list[tuple], np.ndarray]:
    """Axis lines and ticks found in the pixels, as ``(x0, y0, x1, y1)`` in pt.

    Ticks are short, thin, isolated strokes leaving a line on either side
    (a marker cut by the axis is neither thin nor isolated). A tick hidden in
    a frame corner is added when the other ticks put one there. Also returns
    a mask of the tick pixels (removed before marker matching; axis lines
    stay, so markers sitting on the frame keep their shape)."""
    import cv2
    ink = R.ink.astype(np.uint8)
    used = np.zeros_like(ink, dtype=bool)
    span = {"x": (bbox[2] - bbox[0]) * R.zoom, "y": (bbox[3] - bbox[1]) * R.zoom}
    lines = {"x": [], "y": []}     # (a0, a1, lo, hi) in px: thickness range, extent
    for orient in ("x", "y"):
        L = int(min_frac * span[orient])
        if L < 10:
            continue
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1) if orient == "x" else (1, L))
        op = cv2.morphologyEx(ink, cv2.MORPH_OPEN, k)
        n, lab, st, _ = cv2.connectedComponentsWithStats(op, connectivity=8)
        for i in range(1, n):
            x, y, w, h, _ = st[i]
            thick = h if orient == "x" else w
            if thick > max(4, 2.5 * R.zoom):       # a filled area, not a line
                continue
            px0, py0 = R.pt(x, y)
            px1, py1 = R.pt(x + w - 1, y + h - 1)
            if vector._seg_excluded((float(px0), float(py0), float(px1), float(py1)), exclude):
                continue                           # e.g. the axes of an inset
            lines[orient].append((y, y + h - 1, x, x + w - 1) if orient == "x" else (x, x + w - 1, y, y + h - 1))
    segs: list[tuple] = []
    for orient in ("x", "y"):
        for a0, a1, lo, hi in lines[orient]:
            c = (a0 + a1) / 2
            if orient == "x":
                p0, p1 = R.pt(lo, c), R.pt(hi, c)
            else:
                p0, p1 = R.pt(c, lo), R.pt(c, hi)
            segs.append((float(p0[0]), float(p0[1]), float(p1[0]), float(p1[1])))
            ticks = _snap_lengths(_line_ticks(ink, R.zoom, orient, a0, a1, lo, hi, tick_max_pt, used))
            other = lines["y" if orient == "x" else "x"]
            ticks += _corner_ticks(ticks, lo, hi, other)
            for pc, length, sgn in ticks:
                edge = a0 if sgn < 0 else a1
                e = edge + sgn * length
                if orient == "x":
                    q0, q1 = R.pt(pc, c), R.pt(pc, e)
                else:
                    q0, q1 = R.pt(c, pc), R.pt(e, pc)
                segs.append((float(q0[0]), float(q0[1]), float(q1[0]), float(q1[1])))
    return segs, used


def _line_ticks(ink, zoom, orient, a0, a1, lo, hi, tick_max_pt, used) -> list[tuple[float, int, int]]:
    """Ticks ``(position_px, length_px, side)`` along one axis line."""
    H, W = ink.shape
    A = ink if orient == "x" else ink.T      # rows = perpendicular direction
    U = used if orient == "x" else used.T
    tmax = int(tick_max_pt * zoom)
    tick_w = max(3, int(round(1.3 * zoom)))
    minlen = max(2, int(round(0.8 * zoom)))
    out = []
    for sgn in (-1, 1):
        start = a0 - 1 if sgn < 0 else a1 + 1
        rows = np.arange(start, start + sgn * (tmax + 2), sgn)
        rows = rows[(rows >= 0) & (rows < A.shape[0])]
        if not len(rows):
            continue
        band = A[rows, lo:hi + 1].astype(bool)          # (len, n_cols)
        # run length from the line outward per column
        notink = ~band
        first_gap = np.where(notink.any(axis=0), notink.argmax(axis=0), len(rows))
        ok = (first_gap >= minlen) & (first_gap <= tmax)
        for r0, r1 in _runs(ok):
            if r1 - r0 + 1 > tick_w:                     # too wide: marker or diagonal line
                continue
            length = int(first_gap[r0:r1 + 1].max())
            # isolated: little ink right beside the stroke over its length
            sl = band[:length]
            left = sl[:, max(r0 - 1 - tick_w, 0):max(r0 - 1, 0)]
            right = sl[:, r1 + 2:r1 + 2 + tick_w]
            side = np.concatenate([left.ravel(), right.ravel()]) if left.size + right.size else np.zeros(1)
            if side.mean() > 0.12:
                continue
            out.append((lo + (r0 + r1) / 2, length, sgn))
            rr = rows[:length]
            if orient == "x":
                used[rr.min():rr.max() + 1, lo + r0:lo + r1 + 1] = True
            else:
                used[lo + r0:lo + r1 + 1, rr.min():rr.max() + 1] = True
    return out


def _snap_lengths(ticks):
    """Pixel lengths of equal ticks differ by a pixel or so; give ticks within
    20 % of the longest on their side the same length (major/minor classes)."""
    out = []
    for sgn in (-1, 1):
        side = [t for t in ticks if t[2] == sgn]
        if not side:
            continue
        L = max(t[1] for t in side)
        out += [(p, L if l >= L - max(1.5, 0.2 * L) else l, g) for p, l, g in side]
    return sorted(out)


def _corner_ticks(ticks, lo, hi, other_lines) -> list[tuple[float, int, int]]:
    """A tick at a line end that meets a perpendicular line is invisible (it
    lies on that line). Add it when the regular tick spacing puts one there."""
    if len(ticks) < 2:
        return []
    sgn = max((-1, 1), key=lambda s: sum(t[2] == s for t in ticks))
    side = sorted(t for t in ticks if t[2] == sgn)
    pos = [t[0] for t in side]
    if len(pos) < 2:
        return []
    step = float(np.median(np.diff(pos)))
    length = int(np.median([t[1] for t in side]))
    out = []
    for end in (lo, hi):
        meets = any(abs((b0 + b1) / 2 - end) <= 3 for b0, b1, _, _ in other_lines)
        if not meets or any(abs(p - end) < 0.3 * step for p in pos):
            continue
        near = min(pos, key=lambda p: abs(p - end))
        if abs(abs(near - end) - step) <= 0.12 * step:
            out.append((float(end), length, sgn))
    return out


def axis_segments(page, drawings, bbox, exclude=(), R: Render | None = None) -> tuple[list, list, str, np.ndarray | None]:
    """Segments for each axis: vector drawings where they give an axis, pixels otherwise.

    Returns ``(segs_for_x, segs_for_y, source, used_mask)``."""
    vsegs = vector.stroke_segments(drawings, bbox, exclude=exclude)

    def has(segs, o):
        try:
            vector.find_axis(segs, bbox, o, 10 ** 6)
            return True
        except vector.AxisError:
            return False

    vx, vy = has(vsegs, "x"), has(vsegs, "y")
    if vx and vy:
        return vsegs, vsegs, "vector", None
    if R is None:
        R = Render(page, _grow(bbox, 8))
    # no blanking here: a legend box drawn over the frame must not cut ticks
    rsegs, used = raster_segments(R, bbox, exclude=exclude)
    return (vsegs if vx else rsegs), (vsegs if vy else rsegs), "vector+raster" if (vx or vy) else "raster", used


def _grow(b, m):
    return [b[0] - m, b[1] - m, b[2] + m, b[3] + m]


def detect_ticks(page, drawings, bbox, exclude=(), side=None) -> dict:
    """Same result as ``vector.detect_ticks``, for raster (or mixed) regions."""
    side = side or {}
    sx, sy, src, _ = axis_segments(page, drawings, bbox, exclude)
    out = vector.detect_ticks_from_segments({"x": sx, "y": sy}, bbox, side)
    out["method"] = "raster"
    out["axes_from"] = src
    return out


# --------------------------------------------------------------------------
# Marker templates
# --------------------------------------------------------------------------

def _crop_component(R: Render, lab, i, st, pad=2):
    x, y, w, h, _ = st[i]
    r0, c0 = max(y - pad, 0), max(x - pad, 0)
    sub = R.gray[r0:y + h + pad, c0:x + w + pad].copy()
    keep = lab[r0:y + h + pad, c0:x + w + pad] == i
    sub[~keep & (sub < 250)] = 255     # remove neighbouring ink
    return sub


def legend_templates(page, box, zoom: float, size_pt=(1.0, 12.0)) -> list[dict]:
    """Marker templates from a legend box, top to bottom.

    The marker of an entry is its left-most component of marker size; a line
    through the marker (``-o-``) is cut to a square around the marker."""
    import cv2
    R = Render(page, _grow(box, 1), zoom)
    n, lab, st, cen = cv2.connectedComponentsWithStats(R.ink.astype(np.uint8), connectivity=8)
    lo, hi = size_pt[0] * R.zoom, size_pt[1] * R.zoom
    comps = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if not (lo <= h <= hi) or w < lo:
            continue
        comps.append(i)
    # rows by vertical centre
    comps.sort(key=lambda i: cen[i][1])
    rows: list[list[int]] = []
    for i in comps:
        if rows and abs(cen[i][1] - np.mean([cen[j][1] for j in rows[-1]])) < 0.5 * st[i][3]:
            rows[-1].append(i)
        else:
            rows.append([i])
    out = []
    for row in rows:
        i = min(row, key=lambda j: st[j][0])
        x, y, w, h, _ = st[i]
        sub = _crop_component(R, lab, i, st)
        if w > 1.6 * h:
            # marker with a legend line: keep the densest h x h window
            inkc = (sub < 128).sum(axis=0)
            win = h + 2
            best = max(range(0, max(1, sub.shape[1] - win + 1)), key=lambda c: inkc[c:c + win].sum())
            sub = sub[:, best:best + win]
            sub = _cut_line(sub)
        cx, cy = R.pt(x + w / 2, y + h / 2)
        out.append({"gray": sub, "x": float(cx), "y": float(cy), "line": bool(w > 1.6 * h), **classify(sub < 128)})
    return out


def _cut_line(sub: np.ndarray) -> np.ndarray:
    """Remove a horizontal legend line from a template crop (it would not
    match lines of other angles in the data)."""
    ink = sub < 128
    H, W = ink.shape
    rows = ink.sum(axis=1)
    out = sub.copy()
    for r in range(H):
        if rows[r] >= 0.9 * W:      # a row fully inked from edge to edge: the line
            left = ink[r, :max(1, W // 5)].all()
            right = ink[r, -max(1, W // 5):].all()
            if left and right:
                # keep the marker body: pixels with ink just above or below
                for c in range(W):
                    above = r > 0 and ink[r - 1, c]
                    below = r < H - 1 and ink[r + 1, c]
                    if not (above or below):
                        out[r, c] = 255
    return out


def classify(ink: np.ndarray) -> dict:
    """Guess (shape, filled) of one marker image."""
    import cv2
    if ink.sum() < 4:
        return {"shape": "circle", "filled": False}
    m = ink.astype(np.uint8)
    cnts, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    big = max(cnts, key=cv2.contourArea)
    hull = cv2.convexHull(big)
    harea = max(cv2.contourArea(hull), 1.0)
    solidity = float(m.sum()) / harea
    holes = hier is not None and any(h[3] >= 0 and cv2.contourArea(c) > 0.08 * harea
                                     for c, h in zip(cnts, hier[0]))
    x, y, w, h = cv2.boundingRect(big)
    extent = cv2.contourArea(hull) / max(w * h, 1)
    peri = cv2.arcLength(hull, True)
    approx = cv2.approxPolyDP(hull, 0.09 * peri, True)
    nv = len(approx)
    if solidity < 0.55 and not holes:
        # thin cross shapes
        rows = ink.sum(axis=1)
        cols = ink.sum(axis=0)
        mid_r, mid_c = rows[len(rows) // 2 - 1:len(rows) // 2 + 2].max(), cols[len(cols) // 2 - 1:len(cols) // 2 + 2].max()
        shape = "plus" if mid_r > 0.7 * w and mid_c > 0.7 * h else ("star" if solidity > 0.4 else "x")
        return {"shape": shape, "filled": False}
    filled = solidity > 0.8 and not holes
    # hull area / bounding box: square ~1, circle ~0.79, diamond and triangle ~0.5
    if extent > 0.88:
        shape = "square"
    elif extent > 0.66:
        shape = "circle"
    else:
        rows = ink[y:y + h].sum(axis=1).astype(float)
        top, bot = rows[: h // 2].sum(), rows[(h + 1) // 2:].sum()
        shape = "triangle" if max(top, bot) > 1.35 * max(min(top, bot), 1) else "diamond"
    return {"shape": shape, "filled": bool(filled)}


def draw_template(shape: str, filled: bool, size_px: float, lw_px: float | None = None) -> np.ndarray:
    """Grey template (ink dark on white) of a marker of ``size_px``."""
    import cv2
    s = max(int(round(size_px)), 5)
    pad = 3
    N = s + 2 * pad
    sc = 8  # supersampling
    img = np.full((N * sc, N * sc), 255, np.uint8)
    c = N * sc / 2
    r = s * sc / 2
    lw = max(1, int(round((lw_px or max(1.0, s / 7)) * sc)))
    th = -1 if filled else lw
    if shape == "circle":
        cv2.circle(img, (int(c), int(c)), int(r - (0 if filled else lw / 2)), 0, th, cv2.LINE_AA)
    else:
        if shape == "square":
            pts = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
            k = 0.88
        elif shape == "diamond":
            pts = [(0, -1), (1, 0), (0, 1), (-1, 0)]
            k = 1.0
        elif shape == "triangle":
            pts = [(0, -1), (1, 0.75), (-1, 0.75)]
            k = 1.0
        elif shape == "triangle_down":
            pts = [(0, 1), (1, -0.75), (-1, -0.75)]
            k = 1.0
        elif shape in ("x", "plus"):
            d = [(-1, -1, 1, 1), (-1, 1, 1, -1)] if shape == "x" else [(-1, 0, 1, 0), (0, -1, 0, 1)]
            kk = 0.75 if shape == "x" else 1.0
            for a, b, e, f in d:
                cv2.line(img, (int(c + a * r * kk), int(c + b * r * kk)), (int(c + e * r * kk), int(c + f * r * kk)),
                         0, lw, cv2.LINE_AA)
            pts = None
        elif shape == "star":
            pts = []
            for j in range(10):
                ang = -np.pi / 2 + j * np.pi / 5
                rr = 1.0 if j % 2 == 0 else 0.42
                pts.append((rr * np.cos(ang), rr * np.sin(ang)))
            k = 1.0
        else:
            raise ValueError(f"unknown marker shape {shape!r}")
        if pts is not None:
            poly = np.array([(c + x * r * k, c + y * r * k) for x, y in pts], np.int32)
            if filled:
                cv2.fillPoly(img, [poly], 0, cv2.LINE_AA)
            else:
                cv2.polylines(img, [poly], True, 0, lw, cv2.LINE_AA)
    return cv2.resize(img, (N, N), interpolation=cv2.INTER_AREA)


def _match(gray: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    import cv2
    if tpl.shape[0] > gray.shape[0] or tpl.shape[1] > gray.shape[1]:
        return np.full((1, 1), -1, np.float32)
    a = 255 - gray.astype(np.float32)
    t = 255 - tpl.astype(np.float32)
    return cv2.matchTemplate(a, t, cv2.TM_CCOEFF_NORMED)


def _peaks(score: np.ndarray, thr: float, radius: int) -> list[tuple[float, float, float]]:
    """Local maxima (score, x, y) with sub-pixel refinement."""
    import cv2
    if score.size <= 1:
        return []
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * radius + 1, 2 * radius + 1))
    mx = cv2.dilate(score, k)
    ys, xs = np.nonzero((score >= mx - 1e-6) & (score >= thr))
    out = []
    for y, x in zip(ys, xs):
        dx = dy = 0.0
        if 0 < x < score.shape[1] - 1:
            l, c, r = score[y, x - 1], score[y, x], score[y, x + 1]
            den = l - 2 * c + r
            dx = 0.5 * (l - r) / den if den < 0 else 0.0
        if 0 < y < score.shape[0] - 1:
            u, c, d = score[y - 1, x], score[y, x], score[y + 1, x]
            den = u - 2 * c + d
            dy = 0.5 * (u - d) / den if den < 0 else 0.0
        out.append((float(score[y, x]), x + float(np.clip(dx, -0.5, 0.5)), y + float(np.clip(dy, -0.5, 0.5))))
    return out


def best_size(gray: np.ndarray, sigs: list[dict], zoom: float, sizes_pt=None) -> float:
    """Marker size (pt) whose drawn templates match the image best."""
    sizes_pt = sizes_pt or np.arange(2.0, 9.01, 0.5)
    best, bs = None, -1.0
    for s in sizes_pt:
        tot = 0.0
        for g in sigs:
            sc = _match(gray, draw_template(g["shape_draw"], g["filled"], s * zoom))
            pk = sorted((p[0] for p in _peaks(sc, 0.5, max(2, int(s * zoom / 2)))), reverse=True)[:3]
            tot += sum(pk)
        if tot > bs:
            best, bs = float(s), tot
    return best


# --------------------------------------------------------------------------
# Panel extraction
# --------------------------------------------------------------------------

def _signatures(page, panel_card, legend_box, zoom, log, label):
    series = [s for s in panel_card["series"] if s.get("marker", "x") != "none"]
    sigs = []
    if legend_box:
        tpls = legend_templates(page, legend_box, zoom)
        if len(tpls) != len(series) and log:
            log("raster", "warning_legend_count", panel=label, legend_markers=len(tpls), series=len(series))
        for s, t in zip(series, tpls):
            shape = s.get("marker") or t["shape"]
            filled = bool(s["filled"]) if "filled" in s else t["filled"]
            if log and s.get("marker") and (t["shape"] != s["marker"] or ("filled" in s and t["filled"] != s["filled"])):
                log("raster", "info_legend_shape", panel=label, series=s["label"], card=[s.get("marker"), s.get("filled")],
                    legend=[t["shape"], t["filled"]])
            sigs.append(dict(label=s["label"], shape=shape, filled=filled, tpl=t["gray"], color=None,
                             size=max(t["gray"].shape) / zoom))
    else:
        for s in series:
            if "marker" not in s:
                raise ValueError(f"series {s['label']!r}: need 'marker' in card or a legend bbox")
            sigs.append(dict(label=s["label"], shape=s["marker"], filled=bool(s.get("filled", False)), tpl=None,
                             color=None, size=None))
    for g in sigs:
        g["shape_draw"] = g["shape"]
    if log:
        log("raster", "legend", panel=label, mapping=[{k: v for k, v in g.items() if k != "tpl"} for g in sigs],
            templates="legend" if legend_box else "drawn from card")
    return sigs


def _templates(sigs, gray, zoom, size_pt, log, label):
    """List of (sig, template) pairs. Drawn templates get the best-fitting size;
    triangles are tried pointing up and down."""
    out = []
    need = [g for g in sigs if g["tpl"] is None]
    for g in need:
        s = size_pt or best_size(gray, [g], zoom)
        if log:
            log("raster", "marker_size", panel=label, series=g["label"], size_pt=s,
                source="card" if size_pt else "best match")
        if True:
            g["size"] = s
            shapes = ["triangle", "triangle_down"] if g["shape"] == "triangle" else [g["shape"]]
            for sh in shapes:
                out.append((g, draw_template(sh, g["filled"], s * zoom)))
    for g in sigs:
        if g["tpl"] is not None:
            out.append((g, g["tpl"]))
    return out


def extract_axes_block(page, drawings, bbox, axis_x, axis_y, sigs, exclude=(), log=None, label="",
                       source="Hauptpanel", size_pt=None, threshold=0.6, scales=(1.0,)):
    R = Render(page, _grow(bbox, 8))
    sx, sy, axes_from, used = axis_segments(page, drawings, bbox, exclude, R)
    R.blank(exclude, pad=1.0)
    calx, linex = vector.calibrate_axis(sx, bbox, axis_x, "x", log, label)
    caly, liney = vector.calibrate_axis(sy, bbox, axis_y, "y", log, label)
    # data area: inside the axis lines (a little margin for markers on the frame)
    gray = R.gray.copy()
    if used is not None:
        gray[used] = 255                      # ticks are not data
    H, W = gray.shape
    lo_x, hi_x = (linex.lo, linex.hi) if linex else (bbox[0], bbox[2])
    lo_y, hi_y = (liney.lo, liney.hi) if liney else (bbox[1], bbox[3])
    c0, r0 = R.px(lo_x, lo_y)
    c1, r1 = R.px(hi_x, hi_y)
    mask_out = np.ones_like(gray, bool)
    m = 4 * R.zoom
    mask_out[max(int(r0 - m), 0):int(r1 + m) + 1, max(int(c0 - m), 0):int(c1 + m) + 1] = False
    gray[mask_out] = 255                      # tick labels, axis titles
    # templates: legend crops at several scales (insets), or drawn shapes
    import cv2
    pairs = []
    for g, t in _templates(sigs, gray, R.zoom, size_pt, log, label):
        if g["tpl"] is None:          # drawn templates already have the fitted size
            pairs.append((g, t, 1.0))
            continue
        for f in scales:
            tt = t if f == 1.0 else cv2.resize(t, (max(5, int(t.shape[1] * f)), max(5, int(t.shape[0] * f))),
                                               interpolation=cv2.INTER_AREA)
            pairs.append((g, tt, f))
    cands = []
    for g, t, f in pairs:
        sc = _match(gray, t)
        rad = max(2, int(min(t.shape) * 0.35))
        for s, x, y in _peaks(sc, threshold, rad):
            cx, cy = x + (t.shape[1] - 1) / 2, y + (t.shape[0] - 1) / 2
            if not (c0 - m <= cx <= c1 + m and r0 - m <= cy <= r1 + m):
                continue
            cands.append((s, cx, cy, g, t.shape, f))
    if len(scales) > 1 and cands:
        # keep the scale that explains the image best (insets draw smaller markers)
        tot = {f: sum(c[0] for c in cands if c[5] == f) for f in scales}
        fbest = max(tot, key=tot.get)
        cands = [c for c in cands if c[5] == fbest]
    cands.sort(key=lambda c: -c[0])
    kept = []
    for s, cx, cy, g, shp, f in cands:
        r = 0.55 * min(shp)
        if any(np.hypot(cx - k[1], cy - k[2]) < r for k in kept):
            continue
        kept.append((s, cx, cy, g, shp, f))
    dpos = max(R.px_pt, 1.0 / R.zoom)
    points = []
    for s, cx, cy, g, shp, f in kept:
        x, y = R.pt(cx, cy)
        x, y = float(x), float(y)
        w_pt = (shp[1] - 4) / R.zoom
        h_pt = (shp[0] - 4) / R.zoom
        points.append(dict(
            series=g["label"], shape=g["shape"], filled=g["filled"],
            px=round(x, 3), py=round(y, 3), w=round(w_pt, 3), h=round(h_pt, 3),
            x_value=calx(x), y_value=caly(y),
            uncertainty_x=calx.half_width(x, dpos), uncertainty_y=caly.half_width(y, dpos),
            confidence=GOOD if s >= 0.8 else (MEDIUM if s >= 0.65 else LOW),
            match_score=round(s, 3), source=source, vertex_dist=None, draw_index=None,
        ))
    points.sort(key=lambda p: (p["series"], p["py"], p["px"]))
    counts: dict[str, int] = {}
    for p in points:
        k = f"{p['shape']}|{'filled' if p['filled'] else 'open'}|None"
        counts[k] = counts.get(k, 0) + 1
    if log:
        per = {}
        for p in points:
            per[p["series"]] = per.get(p["series"], 0) + 1
        log("raster", "markers", panel=label, axes_from=axes_from, zoom=R.zoom, native_px_per_pt=R.native,
            threshold=threshold, candidates=len(cands), kept=len(points), per_series=per,
            confidence={c: sum(p["confidence"] == c for p in points) for c in (GOOD, MEDIUM, LOW)})
    return dict(
        label=label, source=source, bbox=list(bbox), points=points, method="raster",
        calibration={"x": calx.to_dict(), "y": caly.to_dict()},
        axis_extent={"x": [lo_x, hi_x], "y": [lo_y, hi_y]},
        axis_coord={"x": linex.coord if linex else None, "y": liney.coord if liney else None},
        quantisation_pt={"x": dpos, "y": dpos},
        marker_counts=counts, polylines=[],
    )


def extract_panel(page, drawings, panel_card: dict, log=None) -> dict:
    """Raster counterpart of ``vector.extract_panel`` (same result structure)."""
    pid = panel_card["id"]
    bbox = panel_card.get("bbox_pt")
    if not bbox:
        raise ValueError(f"panel {pid}: raster extraction needs bbox_pt (PDF points)")
    insets = panel_card.get("insets") or []
    legend_box = (panel_card.get("legend") or {}).get("bbox_pt")
    zoom = Render(page, _grow(bbox, 8)).zoom
    sigs = _signatures(page, panel_card, legend_box, zoom, log, pid)
    size_pt = None
    if panel_card.get("marker_size_pt"):
        size_pt = float(np.mean(panel_card["marker_size_pt"]))
    thr = float(panel_card.get("match_threshold", 0.6))
    exclude = [i["bbox_pt"] for i in insets] + ([legend_box] if legend_box else [])
    main = extract_axes_block(page, drawings, bbox, panel_card["x"], panel_card["y"], sigs, exclude, log, pid,
                              "Hauptpanel", size_pt, thr)
    blocks = {"main": main}
    for ins in insets:
        iid = f"{pid}:{ins['id']}"
        isigs = [dict(g) for g in sigs]
        isize = float(np.mean(ins["marker_size_pt"])) if ins.get("marker_size_pt") else None
        if all(g["tpl"] is None for g in isigs):
            for g in isigs:
                g["size"] = None
        blk = extract_axes_block(page, drawings, ins["bbox_pt"], ins["x"], ins["y"], isigs,
                                 [legend_box] if legend_box else [], log, iid, "Inset", isize,
                                 float(ins.get("match_threshold", thr)), scales=(0.5, 0.6, 0.7, 0.8, 0.9, 1.0))
        blk["merge_on"] = ins.get("merge_on", "y")
        blk["merge_tol"] = float(ins.get("merge_tol", 0.2))
        blocks[f"inset:{ins['id']}"] = blk
    return {"id": pid, "blocks": blocks, "method": "raster",
            "signatures": [{"label": g["label"], "shape": g["shape"], "filled": g["filled"], "color": None,
                            "size": g.get("size")} for g in sigs]}


def detect_legend(page, bbox) -> list[dict]:
    """Legend markers of a raster legend box (as ``vector.detect_legend``)."""
    zoom = Render(page, _grow(bbox, 1)).zoom
    return [{"marker": t["shape"], "filled": t["filled"], "color": None, "x": t["x"], "y": t["y"],
             "size": max(t["gray"].shape) / zoom} for t in legend_templates(page, bbox, zoom)]
