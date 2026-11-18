"""Stage 4: extraction from vector figures.

Markers are read directly from the PDF drawing commands (PyMuPDF
``page.get_drawings()``). The marker parser ``markers_of`` / ``collect`` is the
reference code from the specification, with these documented extensions:

* circles: a run of Bezier curves closing on its start point is one circle, so
  both 4-curve (journal PDFs) and 8-curve (matplotlib) circles work, and two
  circles drawn back to back in one path stay two circles;
* the chain size limit (spec: 5 pt) is a parameter ``max_size``;
* a closed 4-chain whose segments are all horizontal/vertical is a square
  (the spec maps every closed 4-chain to a diamond, which stays the case for
  diagonal segments);
* a closed 10-chain is a star (matplotlib ``*``);
* two consecutive single segments with a common midpoint are an ``x`` (two
  diagonals) or a ``plus`` (horizontal + vertical), as matplotlib draws them.

Positions are always measured here; tick VALUES come from the Figure Card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

# spec short names -> Figure Card names
SHAPE_NAMES = {
    "sq": "square",
    "circ": "circle",
    "tri": "triangle",
    "dia": "diamond",
    "x": "x",
    "plus": "plus",
    "star": "star",
}
CARD_TO_SHORT = {v: k for k, v in SHAPE_NAMES.items()}

UNASSIGNED = "nicht zuordenbar"


# --------------------------------------------------------------------------
# Marker parser (reference code from the spec, extended as described above)
# --------------------------------------------------------------------------

RAY_PATTERNS = (("DDDDHH", "star"), ("DDDDVV", "star"), ("DDDD", "x"), ("HHVV", "plus"), ("VVHH", "plus"))


def markers_of(d: dict, max_size: float = 5.0) -> list[tuple]:
    """Return markers ``(shape, cx, cy, w, h)`` found in one drawing dict."""
    out = []
    groups = []
    cur = None
    cbuf: list = []  # points of the current curve run (start/end of each curve)

    def close():
        nonlocal cur
        if cur:
            groups.append(cur)
        cur = None

    for it in d["items"]:
        k = it[0]
        if k != "l":
            close()
        if k != "c" and cbuf:
            cbuf = []
        if k == "re":
            r = it[1]
            out.append(("sq", (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, r.width, r.height))
        elif k == "qu":
            q = it[1]
            xs = [q.ul.x, q.ur.x, q.ll.x, q.lr.x]
            ys = [q.ul.y, q.ur.y, q.ll.y, q.lr.y]
            out.append(("dia", (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                        max(xs) - min(xs), max(ys) - min(ys)))
        elif k == "c":
            p0, p3 = it[1], it[4]
            if cbuf and (abs(cbuf[-1].x - p0.x) > 1e-2 or abs(cbuf[-1].y - p0.y) > 1e-2):
                cbuf = []  # discontinuity: a new subpath starts
            cbuf += [p0, p3]
            closed = abs(p3.x - cbuf[0].x) < 1e-2 and abs(p3.y - cbuf[0].y) < 1e-2
            if closed and len(cbuf) >= 6:  # at least 3 curves
                # curve end points only lie on the circle; extent via all ends
                xs = [p.x for p in cbuf]
                ys = [p.y for p in cbuf]
                out.append(("circ", (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                            max(xs) - min(xs), max(ys) - min(ys)))
                cbuf = []
        elif k == "l":
            a, b = it[1], it[2]
            seg = (a.x, a.y, b.x, b.y)
            if cur:
                last = cur["segs"][-1]
                first = cur["segs"][0]
                if cur["mode"] == "chain" and abs(last[2] - a.x) < 1e-2 and abs(last[3] - a.y) < 1e-2:
                    cur["segs"].append(seg)
                    continue
                if cur["mode"] != "chain" and abs(first[0] - a.x) < 0.15 and abs(first[1] - a.y) < 0.15:
                    cur["mode"] = "ray"
                    cur["segs"].append(seg)
                    continue
                if len(cur["segs"]) == 1 and abs(last[2] - a.x) < 1e-2 and abs(last[3] - a.y) < 1e-2:
                    cur["mode"] = "chain"
                    cur["segs"].append(seg)
                    continue
                close()
            cur = {"mode": "?", "segs": [seg]}
    close()

    def dirc(s):
        dx = abs(s[2] - s[0])
        dy = abs(s[3] - s[1])
        m = max(dx, dy)
        return "D" if dx > 0.4 * m and dy > 0.4 * m else ("H" if dx > dy else "V")

    singles: list[tuple] = []  # consecutive single-segment groups (extension)

    def flush_singles():
        # pair consecutive single segments sharing their midpoint: x or plus
        i = 0
        while i + 1 < len(singles):
            s1, s2 = singles[i], singles[i + 1]
            m1 = ((s1[0] + s1[2]) / 2, (s1[1] + s1[3]) / 2)
            m2 = ((s2[0] + s2[2]) / 2, (s2[1] + s2[3]) / 2)
            if abs(m1[0] - m2[0]) < 0.15 and abs(m1[1] - m2[1]) < 0.15:
                tok = "".join(sorted(dirc(s1) + dirc(s2)))
                name = {"DD": "x", "HV": "plus"}.get(tok)
                if name:
                    sx = [s1[0], s1[2], s2[0], s2[2]]
                    sy = [s1[1], s1[3], s2[1], s2[3]]
                    w = max(sx) - min(sx)
                    h = max(sy) - min(sy)
                    if max(w, h) <= max_size:
                        out.append((name, (min(sx) + max(sx)) / 2, (min(sy) + max(sy)) / 2, w, h))
                    i += 2
                    continue
            i += 1
        singles.clear()

    for g in groups:
        S = g["segs"]
        xs = [v for s in S for v in (s[0], s[2])]
        ys = [v for s in S for v in (s[1], s[3])]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        if len(S) == 1 and g["mode"] != "ray":
            singles.append(S[0])
            continue
        flush_singles()
        if g["mode"] == "chain":
            closed = abs(S[0][0] - S[-1][2]) < 1e-2 and abs(S[0][1] - S[-1][3]) < 1e-2
            if closed and max(w, h) < max_size:
                if len(S) == 3:
                    out.append(("tri", cx, cy, w, h))
                elif len(S) == 4:
                    hv = all(dirc(s) in "HV" for s in S)
                    out.append(("sq" if hv else "dia", cx, cy, w, h))
                elif len(S) == 10:
                    # star outline is not symmetric in y: use the vertex mean
                    out.append(("star", float(np.mean([s[0] for s in S])),
                                float(np.mean([s[1] for s in S])), w, h))
        elif g["mode"] == "ray":
            if max(w, h) > max_size:
                continue
            tok = "".join(dirc(s) for s in S)
            pos = 0
            while pos < len(tok):
                # Bastviken draws star as DDDDVV and plus as VVHH in the legend
                hit = next(((p, n) for p, n in RAY_PATTERNS
                            if tok.startswith(p, pos)), None)
                if not hit:
                    pos += 1
                    continue
                sub = S[pos:pos + len(hit[0])]
                sx = [v for s in sub for v in (s[0], s[2])]
                sy = [v for s in sub for v in (s[1], s[3])]
                out.append((hit[1], (min(sx) + max(sx)) / 2, (min(sy) + max(sy)) / 2,
                            max(sx) - min(sx), max(sy) - min(sy)))
                pos += len(hit[0])
    flush_singles()
    return out


def collect(drawings: Sequence[dict], bbox: Sequence[float], max_size: float = 5.0) -> list[dict]:
    """Markers of all drawings inside ``bbox`` (spec reference, plus colours).

    A pure fill object directly followed by a pure stroke object with the same
    marker centres is one filled marker.
    """
    x0, y0, x1, y1 = bbox
    res = []
    prev = None
    for i, d in enumerate(drawings):
        r = d["rect"]
        if not (r.x0 >= x0 - 3 and r.x1 <= x1 + 3 and r.y0 >= y0 - 3 and r.y1 <= y1 + 3):
            prev = None
            continue
        ms = [m for m in markers_of(d, max_size) if x0 - 3 <= m[1] <= x1 + 3 and y0 - 3 <= m[2] <= y1 + 3]
        if (d["type"] == "s" and prev and prev[0] == i - 1 and prev[1] == "f" and ms
                and all(any(abs(m[1] - q[1]) < 0.2 and abs(m[2] - q[2]) < 0.2 for q in prev[2]) for m in ms)):
            prev = (i, d["type"], ms)
            continue
        color = d.get("fill") if "f" in d["type"] else d.get("color")
        res += [dict(shape=m[0], x=m[1], y=m[2], w=m[3], h=m[4], filled="f" in d["type"],
                     draw_index=i, color=tuple(round(c, 3) for c in color) if color else None)
                for m in ms]
        prev = (i, d["type"], ms)
    return res


# --------------------------------------------------------------------------
# Segments, axes and ticks
# --------------------------------------------------------------------------

def stroke_segments(drawings: Iterable[dict], bbox: Sequence[float], margin: float = 8.0,
                    exclude: Sequence[Sequence[float]] = (), marker_max: float = 12.0) -> list[tuple]:
    """All straight stroked segments (from ``l`` and stroked ``re``) near bbox."""
    x0, y0, x1, y1 = bbox
    X0, Y0, X1, Y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
    segs = []
    for d in drawings:
        if "s" not in d["type"] and d["type"] != "f":
            continue
        r = d["rect"]
        if r.x1 < X0 or r.x0 > X1 or r.y1 < Y0 or r.y0 > Y1:
            continue
        # segments that belong to a recognised marker are never ticks/axes
        mboxes = [(m[1] - m[3] / 2 - 0.05, m[2] - m[4] / 2 - 0.05, m[1] + m[3] / 2 + 0.05, m[2] + m[4] / 2 + 0.05)
                  for m in markers_of(d, marker_max) if max(m[3], m[4]) <= marker_max]
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                s = (a.x, a.y, b.x, b.y)
            elif it[0] == "re" and "s" in d["type"]:
                q = it[1]
                for s in ((q.x0, q.y0, q.x1, q.y0), (q.x1, q.y0, q.x1, q.y1),
                          (q.x0, q.y1, q.x1, q.y1), (q.x0, q.y0, q.x0, q.y1)):
                    if (_seg_in(s, (X0, Y0, X1, Y1)) and not _seg_excluded(s, exclude)
                            and not _seg_excluded(s, mboxes, pad=0.0)):
                        segs.append(s)
                continue
            else:
                continue
            if (_seg_in(s, (X0, Y0, X1, Y1)) and not _seg_excluded(s, exclude)
                    and not _seg_excluded(s, mboxes, pad=0.0)):
                segs.append(s)
    return segs


def _seg_in(s, b):
    return (b[0] <= min(s[0], s[2]) and max(s[0], s[2]) <= b[2]
            and b[1] <= min(s[1], s[3]) and max(s[1], s[3]) <= b[3])


def _seg_excluded(s, exclude, pad=4.0):
    for e in exclude:
        if _seg_in(s, (e[0] - pad, e[1] - pad, e[2] + pad, e[3] + pad)):
            return True
    return False


@dataclass
class AxisLine:
    orient: str        # "x" (horizontal line) or "y" (vertical line)
    coord: float       # y of a horizontal line / x of a vertical line
    lo: float          # extent along the line
    hi: float
    ticks: list[float] = field(default_factory=list)          # tick positions along the line
    tick_lengths: list[float] = field(default_factory=list)


def find_axis(segs: list[tuple], bbox: Sequence[float], orient: str, n_values: int,
              side: str | None = None, tick_max: float = 4.5, min_frac: float = 0.4) -> AxisLine:
    """Find the axis line with its attached short tick segments.

    ``orient='x'``: horizontal axis line, vertical ticks; tick position = x of the
    tick's middle. ``orient='y'``: vertical axis line, horizontal ticks.
    Among several candidate lines (bottom/top spine) the one with the most ticks
    wins, ``side`` breaks ties / forces the choice.
    """
    x0, y0, x1, y1 = bbox
    span = (x1 - x0) if orient == "x" else (y1 - y0)
    tol = 0.05
    lines = []
    shorts = []
    for s in segs:
        dx, dy = abs(s[2] - s[0]), abs(s[3] - s[1])
        length = max(dx, dy)
        # journal PDFs draw axes/ticks slightly slanted (Bastviken: up to 0.15 pt over a
        # 1.5 pt tick, 0.16 pt over a 124 pt axis), so the tolerance is relative
        horiz = dx > tol and dy < max(tol, 0.15 * dx)
        vert = dy > tol and dx < max(tol, 0.15 * dy)
        if orient == "x":
            if horiz and length >= min_frac * span:
                lines.append(AxisLine("x", (s[1] + s[3]) / 2, min(s[0], s[2]), max(s[0], s[2])))
            elif vert and length <= tick_max:
                shorts.append(((s[0] + s[2]) / 2, min(s[1], s[3]), max(s[1], s[3]), length))
        else:
            if vert and length >= min_frac * span:
                lines.append(AxisLine("y", (s[0] + s[2]) / 2, min(s[1], s[3]), max(s[1], s[3])))
            elif horiz and length <= tick_max:
                shorts.append(((s[1] + s[3]) / 2, min(s[0], s[2]), max(s[0], s[2]), length))
    # merge collinear pieces of the same line
    merged: list[AxisLine] = []
    for ln in sorted(lines, key=lambda l: (round(l.coord, 1), l.lo)):
        m = next((m for m in merged if abs(m.coord - ln.coord) < 0.3 and ln.lo <= m.hi + 1), None)
        if m:
            m.hi = max(m.hi, ln.hi)
            m.lo = min(m.lo, ln.lo)
        else:
            merged.append(ln)
    if not merged:
        raise AxisError(f"no {orient} axis line found in bbox {list(bbox)}")
    for ln in merged:
        pos = []
        for p, a, b, length in shorts:
            # tick must start/end on the line (in/out ticks) or be centred on it
            # (in-out ticks); arbitrary crossings (e.g. a marker edge) are ignored
            touches = (abs(a - ln.coord) < 0.3 or abs(b - ln.coord) < 0.3
                       or abs((a + b) / 2 - ln.coord) < 0.3)
            if touches and ln.lo - 0.5 <= p <= ln.hi + 0.5:
                if not any(abs(p - q) < 0.3 for q, _ in pos):
                    pos.append((p, length))
        pos.sort()
        ln.ticks = [p for p, _ in pos]
        ln.tick_lengths = [l for _, l in pos]
    if side:
        want_low = side in ("top", "left")  # smaller coordinate in PDF space
        merged.sort(key=lambda l: l.coord, reverse=not want_low)
        cands = [l for l in merged if len(l.ticks) >= 2] or merged
        best = cands[0]
    else:
        # most ticks; among equals prefer the one whose tick count matches the card
        best = max(merged, key=lambda l: (len(l.ticks) >= n_values, -abs(len(l.ticks) - n_values), len(l.ticks)))
    return best


class AxisError(RuntimeError):
    pass


def select_major_ticks(line: AxisLine, n: int) -> list[float]:
    """Pick the ``n`` major tick positions (minor ticks are shorter)."""
    t = list(line.ticks)
    if len(t) == n:
        return t
    if len(t) > n:
        lens = np.round(np.array(line.tick_lengths), 2)
        for L in sorted(set(lens), reverse=True):
            sel = [p for p, l in zip(t, lens) if l >= L - 0.05]
            if len(sel) == n:
                return sel
    raise AxisError(
        f"{line.orient} axis: found {len(t)} tick marks at {[round(v, 2) for v in t]}, "
        f"but the Figure Card lists {n} tick values. Give ticks as [position, value] pairs "
        f"in the card to override.")


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------

class Calibration:
    """Piecewise-linear mapping position -> value between ticks.

    Outside the tick range the end segments are extrapolated linearly. Log
    axes are interpolated in log10 space. No global fit.
    """

    def __init__(self, positions: Sequence[float], values: Sequence[float], scale: str = "linear"):
        p = np.asarray(positions, float)
        v = np.asarray(values, float)
        if len(p) < 2 or len(p) != len(v):
            raise AxisError("calibration needs >= 2 (position, value) pairs")
        o = np.argsort(p)
        self.positions = p[o]
        self.values = v[o]
        self.scale = scale
        self.log = scale == "log"
        if self.log and np.any(self.values <= 0):
            raise AxisError("log axis with non-positive tick value")
        self._v = np.log10(self.values) if self.log else self.values

    def _lin(self, x, p, v):
        x = np.asarray(x, float)
        y = np.interp(x, p, v)
        lo = x < p[0]
        hi = x > p[-1]
        if np.any(lo):
            y = np.where(lo, v[0] + (x - p[0]) * (v[1] - v[0]) / (p[1] - p[0]), y)
        if np.any(hi):
            y = np.where(hi, v[-1] + (x - p[-1]) * (v[-1] - v[-2]) / (p[-1] - p[-2]), y)
        return y

    def __call__(self, pos):
        y = self._lin(pos, self.positions, self._v)
        y = 10 ** y if self.log else y
        return float(y) if np.ndim(y) == 0 else y

    def inverse(self, value):
        v = np.log10(value) if self.log else np.asarray(value, float)
        o = np.argsort(self._v)
        y = self._lin(v, self._v[o], self.positions[o])
        return float(y) if np.ndim(y) == 0 else y

    def half_width(self, pos: float, dpos: float) -> float:
        """Half the value range covered by ``pos +- dpos`` (uncertainty)."""
        return abs(self(pos + dpos) - self(pos - dpos)) / 2

    def residual(self) -> float:
        """Max deviation (in position units) of ticks from a global linear fit;
        documents uneven tick spacing."""
        if len(self.positions) < 3:
            return 0.0
        A = np.vstack([self._v, np.ones_like(self._v)]).T
        coef, *_ = np.linalg.lstsq(A, self.positions, rcond=None)
        return float(np.max(np.abs(A @ coef - self.positions)))

    def to_dict(self):
        return {"positions": self.positions.tolist(), "values": self.values.tolist(), "scale": self.scale}

    @classmethod
    def from_dict(cls, d):
        return cls(d["positions"], d["values"], d.get("scale", "linear"))


def axis_tick_values(axis_card: dict) -> tuple[list[float], list[tuple[float, float]]]:
    """Split card ticks into value-only ticks and explicit (pos, value) overrides."""
    vals, pairs = [], []
    for t in axis_card["ticks"]:
        if isinstance(t, (list, tuple)):
            pairs.append((float(t[0]), float(t[1])))
        else:
            vals.append(float(t))
    return vals, pairs


def calibrate_axis(segs, bbox, axis_card: dict, orient: str, log=None, label="") -> tuple[Calibration, AxisLine | None]:
    vals, pairs = axis_tick_values(axis_card)
    scale = axis_card.get("scale", "linear")
    if pairs and not vals:
        cal = Calibration([p for p, _ in pairs], [v for _, v in pairs], scale)
        line = None
        try:
            line = find_axis(segs, bbox, orient, len(pairs), axis_card.get("side"))
        except AxisError:
            pass
        if log:
            log("vector", "calibration", panel=label, axis=orient, source="card positions",
                ticks=list(zip(cal.positions.tolist(), cal.values.tolist())), residual_pt=cal.residual())
        return cal, line
    line = find_axis(segs, bbox, orient, len(vals), axis_card.get("side"))
    pos = select_major_ticks(line, len(vals))
    # values ascending along the axis direction; y in PDF space grows downward
    inverted = bool(axis_card.get("inverted", False))
    ascending_with_pos = (not inverted) if orient == "x" else inverted
    v_sorted = sorted(vals) if ascending_with_pos else sorted(vals, reverse=True)
    cal = Calibration(sorted(pos), v_sorted, scale)
    if log:
        spacing = np.diff(cal.positions)
        log("vector", "calibration", panel=label, axis=orient, source="detected ticks",
            ticks=list(zip(cal.positions.tolist(), cal.values.tolist())),
            axis_line={"coord": line.coord, "lo": line.lo, "hi": line.hi},
            tick_spacing_pt=spacing.tolist(), residual_pt=cal.residual())
    return cal, line


# --------------------------------------------------------------------------
# Polylines and quantisation
# --------------------------------------------------------------------------

def polylines(drawings: Sequence[dict], bbox: Sequence[float], min_segments: int = 5,
              exclude: Sequence[Sequence[float]] = ()) -> list[np.ndarray]:
    """Stroked chains with >= ``min_segments`` connected segments (series lines)."""
    x0, y0, x1, y1 = bbox
    out = []
    for d in drawings:
        if "s" not in d["type"]:
            continue
        r = d["rect"]
        if not (r.x0 >= x0 - 3 and r.x1 <= x1 + 3 and r.y0 >= y0 - 3 and r.y1 <= y1 + 3):
            continue
        chain: list = []

        def flush():
            if len(chain) >= min_segments + 1:
                arr = np.array(chain)
                if not any(_seg_in((arr[:, 0].min(), arr[:, 1].min(), arr[:, 0].max(), arr[:, 1].max()),
                                   (e[0] - 1, e[1] - 1, e[2] + 1, e[3] + 1)) for e in exclude):
                    out.append(arr)

        for it in d["items"]:
            if it[0] != "l":
                flush()
                chain = []
                continue
            a, b = it[1], it[2]
            if chain and abs(chain[-1][0] - a.x) < 1e-2 and abs(chain[-1][1] - a.y) < 1e-2:
                chain.append((b.x, b.y))
            else:
                flush()
                chain = [(a.x, a.y), (b.x, b.y)]
        flush()
    return out


def quantisation_step(values: Sequence[float]) -> float:
    """Estimate the coordinate grid step of a PDF (often ~0.66 pt).

    Returns 0.0 when the coordinates look continuous.
    """
    u = np.unique(np.round(np.asarray(values, float), 4))
    if len(u) < 4:
        return 0.0
    d = np.diff(u)
    d = d[d > 1e-3]
    if len(d) < 3:
        return 0.0
    qmin = float(np.min(d))
    for div in range(1, 7):  # the smallest observed gap may be a multiple of the grid
        q = qmin / div
        if q <= 0.01:
            break
        k = d / q
        if (np.abs(k - np.round(k)) < 0.1).mean() >= 0.98:
            return q
    # Real journal PDFs (Bastviken 2008) show no clean grid in marker centres or
    # path vertices, so detection returns 0 there; the Figure Card can then set
    # ``coord_grid_pt`` per panel/inset.
    return 0.0


# --------------------------------------------------------------------------
# Panel extraction
# --------------------------------------------------------------------------

def _rgb_dist(a, b):
    if a is None or b is None:
        return 0.0
    return float(np.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))))


def series_signatures(panel_card: dict, legend_markers: list[dict] | None, log=None, label="") -> list[dict]:
    """Signature (shape, filled, colour, size) per series.

    With a legend bbox: legend markers top-to-bottom are mapped to the card's
    marker series in order. Otherwise the card's marker/filled/color are used.
    """
    series = [s for s in panel_card["series"] if s.get("marker", "x") != "none"]
    sigs = []
    if legend_markers:
        lm = sorted(legend_markers, key=lambda m: (round(m["y"], 1), m["x"]))
        if len(lm) != len(series):
            if log:
                log("vector", "warning_legend_count", panel=label, legend_markers=len(lm), series=len(series))
        for s, m in zip(series, lm):
            card_shape = s.get("marker")
            if card_shape and CARD_TO_SHORT.get(card_shape) != m["shape"] and log:
                log("vector", "warning_legend_shape", panel=label, series=s["label"],
                    card=card_shape, legend=SHAPE_NAMES.get(m["shape"]))
            sigs.append(dict(label=s["label"], shape=m["shape"], filled=m["filled"], color=m["color"],
                             size=max(m["w"], m["h"])))
    else:
        for s in series:
            if "marker" not in s:
                raise ValueError(f"series {s['label']!r}: need 'marker' in card or a legend bbox")
            sigs.append(dict(label=s["label"], shape=CARD_TO_SHORT[s["marker"]], filled=bool(s.get("filled", False)),
                             color=tuple(s["color"]) if s.get("color") else None, size=None))
    if log:
        log("vector", "legend", panel=label, mapping=[{k: v for k, v in g.items()} for g in sigs])
    return sigs


def assign_series(m: dict, sigs: list[dict]) -> str:
    cands = [s for s in sigs if s["shape"] == m["shape"] and s["filled"] == m["filled"]]
    if not cands:
        return UNASSIGNED
    if len(cands) == 1:
        return cands[0]["label"]
    return min(cands, key=lambda s: _rgb_dist(s["color"], m["color"]))["label"]


def size_range(card_range, sigs) -> tuple[float, float]:
    if card_range:
        return float(card_range[0]), float(card_range[1])
    sizes = [s["size"] for s in sigs if s.get("size")]
    if sizes:
        return 0.75 * min(sizes), 1.3 * max(sizes)
    return 1.0, 12.0


def extract_axes_block(drawings, bbox, axis_x, axis_y, sigs, size_rng, exclude=(), log=None,
                       label="", source="Hauptpanel", series_lines=None, max_size=None,
                       coord_grid_pt=None):
    """Extract all data markers of one axes block (main panel or inset)."""
    segs = stroke_segments(drawings, bbox, exclude=exclude)
    calx, linex = calibrate_axis(segs, bbox, axis_x, "x", log, label)
    caly, liney = calibrate_axis(segs, bbox, axis_y, "y", log, label)
    ms = max_size or max(size_rng[1] * 1.05, 5.0)
    raw = collect(drawings, bbox, max_size=ms)
    data = [m for m in raw if not any(e[0] - 1 <= m["x"] <= e[2] + 1 and e[1] - 1 <= m["y"] <= e[3] + 1
                                      for e in exclude)]
    lo, hi = size_range(None, []) if size_rng is None else size_rng
    kept = [m for m in data if lo <= max(m["w"], m["h"]) <= hi]
    rejected = len(data) - len(kept)
    # quantisation step from all coordinates of kept markers' drawings
    coords_x, coords_y = [], []
    for i in {m["draw_index"] for m in kept}:
        for it in drawings[i]["items"]:
            # end points only (Bezier control points are not on the grid)
            if it[0] == "l":
                pts = [it[1], it[2]]
            elif it[0] == "c":
                pts = [it[1], it[4]]
            elif it[0] == "re":
                pts = [it[1].tl, it[1].br]
            elif it[0] == "qu":
                pts = [it[1].ul, it[1].lr]
            else:
                pts = []
            for p in pts:
                coords_x.append(p.x)
                coords_y.append(p.y)
    # tick positions and axis lines are drawn on the same grid
    coords_x += list(calx.positions) + ([liney.coord] if liney else [])
    coords_y += list(caly.positions) + ([linex.coord] if linex else [])
    if coord_grid_pt:
        qx = qy = float(coord_grid_pt)  # from the Figure Card
    else:
        qx = quantisation_step(coords_x)
        qy = quantisation_step(coords_y)
    floor = 0.01  # pt, numerical floor when coordinates look continuous
    lines = polylines(drawings, bbox, exclude=exclude)
    verts = np.vstack(lines) if lines else np.zeros((0, 2))
    points = []
    for m in kept:
        ser = assign_series(m, sigs)
        vd = float(np.min(np.hypot(verts[:, 0] - m["x"], verts[:, 1] - m["y"]))) if len(verts) else None
        points.append(dict(
            series=ser, shape=SHAPE_NAMES[m["shape"]], filled=m["filled"],
            px=round(m["x"], 3), py=round(m["y"], 3), w=round(m["w"], 3), h=round(m["h"], 3),
            x_value=calx(m["x"]), y_value=caly(m["y"]),
            uncertainty_x=calx.half_width(m["x"], max(qx, floor) / 2),
            uncertainty_y=caly.half_width(m["y"], max(qy, floor) / 2),
            confidence="gut", source=source, vertex_dist=vd, draw_index=m["draw_index"],
        ))
    points.sort(key=lambda p: (p["series"], p["py"], p["px"]))
    if log:
        counts: dict[str, int] = {}
        for p in points:
            counts[p["series"]] = counts.get(p["series"], 0) + 1
        log("vector", "markers", panel=label, found=len(raw), in_block=len(data), kept=len(kept),
            size_filter_pt=[lo, hi], rejected_by_size=rejected, per_series=counts,
            polylines=len(lines))
        log("vector", "uncertainty", panel=label, quantisation_pt={"x": qx, "y": qy},
            median_uncertainty={"x": float(np.median([p["uncertainty_x"] for p in points])) if points else None,
                                "y": float(np.median([p["uncertainty_y"] for p in points])) if points else None})
    block = dict(
        label=label, source=source, bbox=list(bbox), points=points,
        calibration={"x": calx.to_dict(), "y": caly.to_dict()},
        axis_extent={"x": [linex.lo, linex.hi] if linex else [bbox[0], bbox[2]],
                     "y": [liney.lo, liney.hi] if liney else [bbox[1], bbox[3]]},
        axis_coord={"x": linex.coord if linex else None, "y": liney.coord if liney else None},
        quantisation_pt={"x": qx, "y": qy},
        marker_counts=_marker_counts(kept),
        polylines=[l.tolist() for l in lines],
    )
    return block


def _marker_counts(markers):
    c: dict[str, int] = {}
    for m in markers:
        k = f"{SHAPE_NAMES[m['shape']]}|{'filled' if m['filled'] else 'open'}|{m['color']}"
        c[k] = c.get(k, 0) + 1
    return c


def extract_panel(drawings: Sequence[dict], panel_card: dict, log=None) -> dict:
    """Extract one panel (with insets) from page drawings. Returns raw blocks;
    merging of inset and main values happens in :func:`merge_insets`."""
    pid = panel_card["id"]
    bbox = panel_card.get("bbox_pt")
    if not bbox:
        raise ValueError(f"panel {pid}: vector extraction needs bbox_pt (PDF points)")
    insets = panel_card.get("insets") or []
    inset_boxes = [i["bbox_pt"] for i in insets]
    legend_box = (panel_card.get("legend") or {}).get("bbox_pt")
    legend_markers = collect(drawings, legend_box, max_size=12.0) if legend_box else None
    if legend_markers is not None:
        # legend numerals are often glyph paths that parse as circles/plus signs;
        # the panel's marker size range filters them out
        lo, hi = panel_card.get("marker_size_pt") or (0.0, 12.0)
        legend_markers = [m for m in legend_markers if lo <= m["w"] <= hi and lo <= m["h"] <= hi]
    sigs = series_signatures(panel_card, legend_markers, log, pid)
    rng = size_range(panel_card.get("marker_size_pt"), sigs)
    exclude = list(inset_boxes) + ([legend_box] if legend_box else [])
    main = extract_axes_block(drawings, bbox, panel_card["x"], panel_card["y"], sigs, rng,
                              exclude=exclude, log=log, label=pid, source="Hauptpanel",
                              coord_grid_pt=panel_card.get("coord_grid_pt"))
    blocks = {"main": main}
    for ins in insets:
        iid = f"{pid}:{ins['id']}"
        isigs = series_signatures({"series": panel_card["series"]},
                                  None, None, iid) if not legend_markers else [dict(s) for s in sigs]
        if ins.get("legend", {}).get("bbox_pt"):
            lm = collect(drawings, ins["legend"]["bbox_pt"], max_size=12.0)
            isigs = series_signatures(panel_card, lm, log, iid)
        irng = size_range(ins.get("marker_size_pt"), [])  # inset markers are scaled differently
        if not ins.get("marker_size_pt") and rng:
            irng = (0.4 * rng[0], rng[1])
        iexcl = [legend_box] if legend_box else []
        blk = extract_axes_block(drawings, ins["bbox_pt"], ins["x"], ins["y"], isigs, irng,
                                 exclude=[e for e in iexcl if e], log=log, label=iid, source="Inset",
                                 coord_grid_pt=ins.get("coord_grid_pt", panel_card.get("coord_grid_pt")))
        blk["merge_on"] = ins.get("merge_on", "y")
        blk["merge_tol"] = float(ins.get("merge_tol", 0.2))
        blocks[f"inset:{ins['id']}"] = blk
    return {"id": pid, "blocks": blocks, "signatures": [_sig_json(s) for s in sigs]}


def _sig_json(s):
    return {"label": s["label"], "shape": SHAPE_NAMES.get(s["shape"], s["shape"]), "filled": s["filled"],
            "color": list(s["color"]) if s.get("color") else None, "size": s.get("size")}


def merge_insets(panel: dict, log=None) -> list[dict]:
    """Combine main-panel and inset points.

    Inset and main point of the same series within ``merge_tol`` on the merge
    axis are one point: the inset value is preferred, both raw values are kept.
    """
    main = [dict(p) for p in panel["blocks"]["main"]["points"]]
    for p in main:
        p.setdefault("x_raw_main", p["x_value"])
        p.setdefault("x_raw_inset", None)
    out = list(main)
    for key, blk in panel["blocks"].items():
        if not key.startswith("inset:"):
            continue
        on = blk.get("merge_on", "y")
        other = "x" if on == "y" else "y"
        tol = blk.get("merge_tol", 0.2)
        used = set()
        for ip in blk["points"]:
            best, bd = None, None
            for j, mp in enumerate(main):
                if j in used or mp["series"] != ip["series"]:
                    continue
                d = abs(mp[f"{on}_value"] - ip[f"{on}_value"])
                if d < tol and (bd is None or d < bd):
                    best, bd = j, d
            rec = dict(ip)
            rec["inset"] = key.split(":", 1)[1]
            rec[f"{other}_raw_inset"] = ip[f"{other}_value"]
            if best is None:
                rec[f"{other}_raw_main"] = None
                out.append(rec)
                continue
            used.add(best)
            mp = main[best]
            dev = abs(mp[f"{other}_value"] - ip[f"{other}_value"])
            allowed = 2 * (mp[f"uncertainty_{other}"] + ip[f"uncertainty_{other}"]) + 1e-6
            rec[f"{other}_raw_main"] = mp[f"{other}_value"]
            rec["main_px"], rec["main_py"] = mp["px"], mp["py"]
            rec["merge_deviation"] = dev
            rec["merge_ok"] = dev <= allowed
            out[out.index(mp)] = rec
            if log and dev > allowed:
                log("vector", "warning_inset_mismatch", panel=panel["id"], series=ip["series"],
                    main=mp[f"{other}_value"], inset=ip[f"{other}_value"], deviation=dev, allowed=allowed)
    return out


def page_drawings(pdf_path: str, page_number_1based: int):
    import pymupdf
    doc = pymupdf.open(pdf_path)
    page = doc[page_number_1based - 1]
    return page, page.get_drawings()


# --------------------------------------------------------------------------
# Set-up helpers (web interface): detection for a box the user has drawn
# --------------------------------------------------------------------------

def _major_guess(line: AxisLine) -> list[float]:
    """Ticks of the longest length class (major ticks); all ticks if uniform."""
    if not line.ticks:
        return []
    lens = np.round(np.array(line.tick_lengths), 2)
    L = float(lens.max())
    return [p for p, l in zip(line.ticks, lens) if l >= L - 0.05]


def detect_ticks(drawings: Sequence[dict], bbox: Sequence[float],
                 exclude: Sequence[Sequence[float]] = (), side: dict | None = None) -> dict:
    """Axis lines and tick positions inside a user-drawn panel box.

    Returns ``{"x": {...}, "y": {...}}``; each axis has ``coord``, ``lo``, ``hi``,
    ``ticks`` (all tick positions), ``tick_lengths`` and ``major`` (longest
    ticks), or ``error`` if no axis line was found.
    """
    segs = stroke_segments(drawings, bbox, exclude=exclude)
    out = detect_ticks_from_segments({"x": segs, "y": segs}, bbox, side)
    out["method"] = "vector"
    return out


def detect_ticks_from_segments(segs_by_axis: dict, bbox: Sequence[float], side: dict | None = None) -> dict:
    """``detect_ticks`` on given segments (shared with the raster path)."""
    side = side or {}
    out = {}
    for orient in ("x", "y"):
        segs = segs_by_axis[orient]
        try:
            ln = find_axis(segs, bbox, orient, 10 ** 6, side.get(orient))
            out[orient] = {"coord": ln.coord, "lo": ln.lo, "hi": ln.hi, "ticks": list(ln.ticks),
                           "tick_lengths": list(ln.tick_lengths), "major": _major_guess(ln)}
        except AxisError as e:
            out[orient] = {"error": str(e), "ticks": [], "major": []}
    return out


def detect_legend(drawings: Sequence[dict], bbox: Sequence[float], size_pt: Sequence[float] | None = None) -> list[dict]:
    """Legend markers in a user-drawn box, top to bottom (as series_signatures orders them)."""
    lo, hi = size_pt or (0.0, 12.0)
    ms = [m for m in collect(drawings, bbox, max_size=12.0) if lo <= m["w"] <= hi and lo <= m["h"] <= hi]
    ms.sort(key=lambda m: (round(m["y"], 1), m["x"]))
    return [{"marker": SHAPE_NAMES.get(m["shape"], m["shape"]), "filled": m["filled"],
             "color": list(m["color"]) if m["color"] else None, "x": m["x"], "y": m["y"],
             "size": max(m["w"], m["h"])} for m in ms]
