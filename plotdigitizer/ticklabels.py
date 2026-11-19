"""Read axis tick VALUES without an LLM.

Tick POSITIONS come from ``vector.find_axis`` (drawing commands). This module
reads the numbers printed next to them and pairs each number with a tick:

1. PDF text layer (``page.get_text("rawdict")``): exact characters and boxes.
   Tokens are split on spaces and wide gaps, a smaller raised token after
   ``10`` is read as an exponent (``10`` + ``3`` -> 1000).
2. OCR fallback (Tesseract via ``pytesseract``, optional) when the region has
   no usable text, e.g. labels converted to outlines or embedded images.

Each label goes to the nearest major tick along the axis, closest to the axis
line. The values are then checked for consistency: on a linear axis they must
grow evenly with position, on a log axis their logarithms must. Ticks without
a label are filled in from that fit and marked as inferred. Everything is a
suggestion for the person setting up the figure; nothing here is final.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence

import numpy as np

MINUS = "−–‒‐﹣－"   # minus sign and dash look-alikes
_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


@dataclass
class Token:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    source: str = "pdf_text"      # "pdf_text" | "ocr"
    conf: float | None = None     # OCR confidence 0..100

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def parse_number(text: str) -> float | None:
    """Parse a tick label; ``None`` if it is not a plain number.

    Handles the Unicode minus, a decimal comma (``0,5``), thousands separators
    (``1,000``, ``1 000`` is already split upstream) and ``1e3``.
    """
    t = text.strip()
    for ch in MINUS:
        t = t.replace(ch, "-")
    t = t.replace(" ", "").replace(" ", "")
    if "," in t and "." not in t:
        if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+", t):
            t = t.replace(",", "")
        elif t.count(",") == 1:
            t = t.replace(",", ".")
    elif "," in t:  # 1,000.5
        t = t.replace(",", "")
    if not _NUM.match(t):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


# --------------------------------------------------------------------------
# Tokens from the PDF text layer
# --------------------------------------------------------------------------

def _in_box(t: Token, box, pad: float = 0.0) -> bool:
    return box[0] - pad <= t.cx <= box[2] + pad and box[1] - pad <= t.cy <= box[3] + pad


def pdf_tokens(page, region: Sequence[float]) -> list[Token]:
    """Character runs inside ``region`` (PDF pt, top-left origin), split at
    spaces and at gaps wider than 0.3 x font size."""
    import pymupdf
    raw = page.get_text("rawdict", clip=pymupdf.Rect(*region))
    out: list[Token] = []
    for b in raw.get("blocks", []):
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                size = float(span.get("size", 0)) or 1.0
                cur: list = []

                def flush():
                    if cur:
                        txt = "".join(c["c"] for c in cur)
                        xs = [c["bbox"] for c in cur]
                        out.append(Token(txt, min(r[0] for r in xs), min(r[1] for r in xs),
                                         max(r[2] for r in xs), max(r[3] for r in xs), size))
                        cur.clear()

                for ch in span.get("chars", []):
                    c = ch["c"]
                    if c.isspace():
                        flush()
                        continue
                    if cur and ch["bbox"][0] - cur[-1]["bbox"][2] > 0.3 * size:
                        flush()
                    cur.append(ch)
                flush()
    return merge_exponents(out)


def merge_exponents(tokens: list[Token]) -> list[Token]:
    """``10`` followed by a smaller, raised number -> one token ``1e<exp>``.

    Also joins a lone minus sign with the number right after it (some PDFs
    draw the minus in another font, so it ends up in its own span)."""
    toks = sorted(tokens, key=lambda t: (round(t.cy), t.x0))
    used = set()
    out: list[Token] = []
    for i, a in enumerate(toks):
        if i in used:
            continue
        merged = None
        for j, b in enumerate(toks):
            if j == i or j in used:
                continue
            gap = b.x0 - a.x1
            if not (-0.5 * a.size < gap < 0.35 * a.size):
                continue
            base = a.text.replace("×", "").replace("x", "")
            exp = parse_number(b.text)
            if (base == "10" and exp is not None and float(exp).is_integer()
                    and b.size < 0.9 * a.size and b.cy < a.cy - 0.1 * a.size):
                merged = Token(f"1e{int(exp)}", a.x0, min(a.y0, b.y0), b.x1, a.y1, a.size, a.source,
                               _minconf(a, b))
            elif a.text.strip() in ("-",) + tuple(MINUS) and parse_number(b.text) is not None \
                    and abs(a.cy - b.cy) < 0.4 * a.size:
                merged = Token("-" + b.text, a.x0, min(a.y0, b.y0), b.x1, max(a.y1, b.y1), b.size,
                               a.source, _minconf(a, b))
            if merged:
                used.add(j)
                break
        out.append(merged or a)
    return out


def _minconf(a: Token, b: Token):
    cs = [c for c in (a.conf, b.conf) if c is not None]
    return min(cs) if cs else None


# --------------------------------------------------------------------------
# OCR fallback
# --------------------------------------------------------------------------

def ocr_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001  missing module or binary
        return False


def _runs(mask_1d, max_gap: int) -> list[tuple[int, int]]:
    """Index runs of True, joining runs separated by at most ``max_gap``."""
    idx = np.flatnonzero(mask_1d)
    if not len(idx):
        return []
    out = [[idx[0], idx[0]]]
    for i in idx[1:]:
        if i - out[-1][1] - 1 <= max_gap:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [(a, b) for a, b in out]


def _drop_strokes(ink: np.ndarray) -> np.ndarray:
    """Remove thin lines spanning >= 80% of the window height (vertical) or
    width (horizontal); glyphs are never that long and thin."""
    ink = ink.copy()
    H, W = ink.shape
    for axis, n, length in ((0, W, H), (1, H, W)):
        full = ink.sum(axis=axis) >= 0.8 * length
        for a, b in _runs(full, 0):
            if b - a + 1 <= max(2, 0.03 * n):
                a, b = max(0, a - 1), min(n - 1, b + 1)   # anti-aliased edges
                if axis == 0:
                    ink[:, a:b + 1] = False
                else:
                    ink[a:b + 1, :] = False
    return ink


def _isolate(ink: np.ndarray, orient: str, near: str) -> tuple[int, int, int, int] | None:
    """Box (r0, r1, c0, c1) of the label ink nearest the axis inside a window.

    Text further out (an axis title, a neighbouring label) is cut off at the
    first clear gap. Long thin strokes across the window (a frame line, an
    inward tick, a grid line) are removed first."""
    ink = _drop_strokes(ink)
    rows = _runs(ink.any(axis=1), 0)
    if not rows:
        return None
    h = max(b - a + 1 for a, b in rows)
    if orient == "x":   # label rows nearest the axis, then the central column run
        rr = _runs(ink.any(axis=1), max(1, h // 4))
        r0, r1 = rr[0] if near == "top" else rr[-1]
        cr = _runs(ink[r0:r1 + 1].any(axis=0), max(2, int(0.45 * (r1 - r0 + 1))))
        mid = ink.shape[1] / 2
        c0, c1 = min(cr, key=lambda r: 0 if r[0] <= mid <= r[1] else min(abs(r[0] - mid), abs(r[1] - mid)))
    else:               # label columns nearest the axis, then the central row run
        cr = _runs(ink.any(axis=0), max(2, int(0.45 * h)))
        c0, c1 = cr[-1] if near == "right" else cr[0]
        rr = _runs(ink[:, c0:c1 + 1].any(axis=1), max(1, h // 4))
        mid = ink.shape[0] / 2
        r0, r1 = min(rr, key=lambda r: 0 if r[0] <= mid <= r[1] else min(abs(r[0] - mid), abs(r[1] - mid)))
    return r0, r1, c0, c1


def _render(page, rect, zoom: float) -> np.ndarray:
    import pymupdf

    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect, alpha=False, colorspace=pymupdf.csGRAY)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)


def _clipped(box, shape, near: str) -> bool:
    """True if a label box (taller/wider than a stray pixel row) touches the
    window edge facing the axis, i.e. the window cut into the glyphs."""
    r0, r1, c0, c1 = box
    if near in ("top", "bottom"):
        return r1 - r0 >= 3 and (r0 == 0 if near == "top" else r1 == shape[0] - 1)
    return c1 - c0 >= 3 and (c0 == 0 if near == "left" else c1 == shape[1] - 1)


def _ocr_crop(page, rect, zoom: float, orient: str, near: str, grow: float = 0.0):
    """OCR the label nearest the axis in one page window; returns (text, conf).

    Windows start a tick length beyond the axis so outward ticks stay out.
    With inward ticks the labels can sit closer than that: if the label is
    cut by the axis-side edge, the window is moved ``grow`` pt toward the
    axis and read again."""
    arr = _render(page, rect, zoom)
    box = _isolate(arr < 140, orient, near)
    if box is not None and grow > 0 and _clipped(box, arr.shape, near):
        import pymupdf

        r = pymupdf.Rect(rect)
        if near == "top":
            r.y0 -= grow
        elif near == "bottom":
            r.y1 += grow
        elif near == "left":
            r.x0 -= grow
        else:
            r.x1 += grow
        arr = _render(page, r & page.rect, zoom)
        box = _isolate(arr < 140, orient, near)
    if box is None:
        return "", 0.0
    r0, r1, c0, c1 = box
    sub = arr[r0:r1 + 1, c0:c1 + 1]
    split = _superscript_split(sub < 140)
    if split is not None:   # 10 with a raised exponent: read both parts
        base, bconf = _ocr_img(sub[:, :split])
        exp, econf = _ocr_img(sub[:, split:])
        if base == "10" and re.fullmatch(r"-?\d+", exp or ""):
            return f"1e{exp}", min(bconf, econf)
    return _ocr_img(sub)


def _superscript_split(ink: np.ndarray) -> int | None:
    """Column where a raised, smaller trailing part starts (an exponent), or None."""
    H = ink.shape[0]
    cols = _runs(ink.any(axis=0), 0)
    if len(cols) < 2:
        return None
    def extent(a, b):
        r = np.flatnonzero(ink[:, a:b + 1].any(axis=1))
        return r[0], r[-1]
    for k in range(1, len(cols)):
        tail = [extent(a, b) for a, b in cols[k:]]
        head = [extent(a, b) for a, b in cols[:k]]
        t_top, t_bot = min(t for t, _ in tail), max(b for _, b in tail)
        h_top, h_bot = min(t for t, _ in head), max(b for _, b in head)
        if t_bot < h_bot - 0.3 * (h_bot - h_top) and (t_bot - t_top) < 0.85 * (h_bot - h_top) and h_bot >= 0.8 * H:
            return cols[k][0]
    return None


# (glyph height px, binarize, page segmentation mode). Single short numbers
# are fragile in Tesseract (a lone "0" or "5" comes out empty or as another
# digit depending on size and version), so several renderings vote.
_OCR_VARIANTS = [(32, False, 7), (32, False, 10), (24, True, 7), (40, False, 7), (32, True, 10), (24, False, 10),
                 (40, True, 10), (28, False, 7), (36, True, 7), (28, True, 10), (36, False, 10), (24, False, 7)]


def _ocr_once(sub: np.ndarray, height: int, binarize: bool, psm: int) -> tuple[str, float]:
    import pytesseract
    from PIL import Image, ImageOps

    if binarize:
        sub = np.where(sub < 140, 0, 255).astype(np.uint8)
    img = Image.fromarray(np.ascontiguousarray(sub))
    img = img.resize((max(1, round(img.width * height / img.height)), height), Image.LANCZOS)
    img = ImageOps.expand(img, border=height // 2, fill=255)
    wl = "-c tessedit_char_whitelist=0123456789.,-"
    d = pytesseract.image_to_data(img, config=f"--psm {psm} {wl}", output_type=pytesseract.Output.DICT)
    words = [(w.strip(), float(c)) for w, c in zip(d["text"], d["conf"]) if (w or "").strip() and float(c) >= 0]
    if not words:
        return "", 0.0
    return "".join(w for w, _ in words), min(c for _, c in words)


def _ocr_img(sub: np.ndarray) -> tuple[str, float]:
    """Read one number by majority vote over ``_OCR_VARIANTS``.

    Stops early once one value has 3 votes and no rival, or when the first 4
    renderings give no number at all (not a label). The confidence is the
    best agreeing confidence scaled by the share of votes."""
    r = np.flatnonzero((sub < 140).any(axis=1))
    c = np.flatnonzero((sub < 140).any(axis=0))
    if not len(r) or not len(c):
        return "", 0.0
    sub = sub[r[0]:r[-1] + 1, c[0]:c[-1] + 1]
    votes: dict[float, list[tuple[str, float]]] = {}
    for k, var in enumerate(_OCR_VARIANTS):
        txt, conf = _ocr_once(sub, *var)
        v = parse_number(txt)
        if v is not None:
            votes.setdefault(v, []).append((txt, conf))
        if not votes and k >= 3:
            break
        if len(votes) == 1 and len(next(iter(votes.values()))) >= 3:
            break
    if not votes:
        return "", 0.0
    n = sum(len(x) for x in votes.values())
    top = max(votes.values(), key=lambda x: (len(x), max(c for _, c in x)))
    txt, conf = max(top, key=lambda t: t[1])
    return txt, conf * len(top) / n


def ocr_tokens(page, axes: dict, zoom: float = 6.0, reach: float = 28.0) -> list[Token]:
    """OCR a window next to every major tick, on both sides of the axis line.

    Targeted windows work far better than OCR of the whole figure: Tesseract
    reads isolated short numbers poorly without a layout to anchor them.
    Windows start beyond the tick marks so tick and axis strokes stay out."""
    import pymupdf

    out = []
    for o in ("x", "y"):
        ax = axes.get(o) or {}
        major = sorted(ax.get("major") or [])
        if ax.get("error") or not major:
            continue
        spacing = float(np.min(np.diff(major))) if len(major) > 1 else 30.0
        tl = max(ax.get("tick_lengths") or [3.0])
        c = ax["coord"]
        sides = {-1: [], 1: []}
        for p in major:
            for sgn in (-1, 1):
                near, far = c + sgn * (tl + 0.8), c + sgn * (tl + 0.8 + reach)
                lo_p, hi_p = sorted((near, far))
                if o == "x":
                    half = min(0.48 * spacing, 22.0)
                    r = pymupdf.Rect(p - half, lo_p, p + half, hi_p)
                else:
                    half = min(0.48 * spacing, 7.0)
                    r = pymupdf.Rect(lo_p, p - half, hi_p, p + half)
                r = r & page.rect
                if r.is_empty or r.width < 2 or r.height < 2:
                    continue
                if o == "x":
                    near = "top" if sgn > 0 else "bottom"
                else:
                    near = "left" if sgn > 0 else "right"
                txt, conf = _ocr_crop(page, r, zoom, o, near, grow=tl)
                if parse_number(txt) is None:
                    continue
                # place the token in the window, centred on the tick
                if o == "x":
                    sides[sgn].append(Token(txt, p - 1, r.y0, p + 1, r.y1, 8.0, "ocr", conf))
                else:
                    sides[sgn].append(Token(txt, r.x0, p - 1, r.x1, p + 1, 8.0, "ocr", conf))
        # labels sit on one side; the other side holds data or nothing
        best = max(sides.values(), key=lambda ts: (len(ts), sum(t.conf or 0 for t in ts)))
        out.extend(best)
    return out


def _powers_of_ten(texts: list[str]) -> list[float] | None:
    """OCR flattens 10^3 into "103": if every label is 10 followed by a
    consecutive exponent, read them as powers of ten."""
    m = [re.fullmatch(r"10(-?\d)", t) for t in texts]
    if len(m) < 2 or not all(m):
        return None
    e = [int(x.group(1)) for x in m]
    d = np.diff(e)
    if len(set(d.tolist())) == 1 and abs(d[0]) == 1:
        return [10.0 ** k for k in e]
    return None


# --------------------------------------------------------------------------
# Pairing labels with ticks and checking them
# --------------------------------------------------------------------------

def _pair(tokens: list[Token], orient: str, coord: float, major: Sequence[float]) -> list[Token | None]:
    """Best label for each major tick (or ``None``)."""
    if not major:
        return []
    spacing = float(np.min(np.diff(sorted(major)))) if len(major) > 1 else 20.0
    along_tol = min(0.45 * spacing, 14.0)
    cands = []
    for t in tokens:
        if parse_number(t.text) is None:
            continue
        a = t.cx if orient == "x" else t.cy
        # distance from the axis line to the near edge of the label
        if orient == "x":
            perp = max(t.y0 - coord, coord - t.y1, 0.0)
        else:
            perp = max(t.x0 - coord, coord - t.x1, 0.0)
        if perp > 2.5 * t.size + 4:
            continue
        for k, p in enumerate(major):
            d = abs(a - p)
            if d <= along_tol:
                cands.append((perp + d, k, t))
    cands.sort(key=lambda c: c[0])
    got: list[Token | None] = [None] * len(major)
    used: set[int] = set()
    side = None  # all labels of one axis sit on one side of the line
    for _, k, t in cands:
        if got[k] is not None or id(t) in used:
            continue
        s = (t.cy > coord) if orient == "x" else (t.cx > coord)
        if side is None:
            side = s
        elif s != side:
            continue
        got[k] = t
        used.add(id(t))
    return got


def _fit(pos, vals):
    """Max deviation from a straight line, as a fraction of the median step."""
    p, v = np.asarray(pos, float), np.asarray(vals, float)
    A = np.vstack([p, np.ones_like(p)]).T
    coef, *_ = np.linalg.lstsq(A, v, rcond=None)
    step = np.median(np.abs(np.diff(v))) if len(v) > 1 else 1.0
    if step == 0:
        return math.inf, coef
    return float(np.max(np.abs(A @ coef - v)) / step), coef


def _round_like(v: float, examples: Sequence[float]) -> float:
    dec = 0
    for e in examples:
        s = repr(float(e))
        if "e" not in s and "." in s:
            dec = max(dec, len(s.split(".")[1].rstrip("0")))
    return round(v, dec)


def check_values(major: Sequence[float], values: Sequence[float | None], tol: float = 0.06) -> dict:
    """Consistency of the read values with the tick positions.

    Returns ``scale`` ("linear"/"log"/None), ``ok``, ``message`` and
    ``suggested`` (a value for every major tick, gaps filled from the fit, or
    ``None`` when the values do not fit a linear or log axis)."""
    idx = [k for k, v in enumerate(values) if v is not None]
    n = len(major)
    res = {"scale": None, "ok": False, "suggested": None, "inferred": [], "message": ""}
    if len(idx) < 2:
        res["message"] = f"{len(idx)} of {n} tick labels read; enter the values by hand."
        return res
    p = [major[k] for k in idx]
    v = [float(values[k]) for k in idx]
    if len(set(v)) < len(v):
        res["message"] = "the same value was read twice; check the labels."
        return res
    lin_err, lin = _fit(p, v)
    log_err, lg = (math.inf, None)
    if all(x > 0 for x in v):
        log_err, lg = _fit(p, np.log10(v))
    if len(idx) == 2 and n == 2:
        res.update(scale="linear", ok=True, suggested=v,
                   message="2 labels read; spacing cannot be checked with 2 ticks.")
        return res
    if len(idx) == 2:
        # two labels: linear unless they differ by a power of ten that suggests log
        ratio = max(v) / min(v) if min(v) > 0 else 0
        scale = "log" if ratio >= 10 and math.isclose(math.log10(ratio) % 1, 0, abs_tol=1e-6) and min(v) > 0 else "linear"
        coef, err = (lg, log_err) if scale == "log" else (lin, lin_err)
        note = "only 2 labels read, the other ticks are inferred; check them."
    elif lin_err <= tol and lin_err <= log_err:
        scale, coef, err, note = "linear", lin, lin_err, ""
    elif log_err <= tol:
        scale, coef, err, note = "log", lg, log_err, ""
    else:
        res["message"] = ("the values are not evenly spaced on a linear or log axis "
                          "(misread label or broken axis?); check them.")
        return res
    sugg, inferred = [], []
    for k, pos in enumerate(major):
        if values[k] is not None:
            sugg.append(float(values[k]))
            continue
        y = coef[0] * pos + coef[1]
        y = 10 ** y if scale == "log" else y
        sugg.append(_round_like(y, v) if scale == "linear" else float(f"{y:.3g}"))
        inferred.append(k)
    res.update(scale=scale, ok=not inferred and len(idx) > 2, suggested=sugg, inferred=inferred)
    if not note and inferred:
        note = f"{len(inferred)} unlabelled tick(s) filled in from the spacing; check them."
    res["message"] = note or f"{len(idx)} labels read, evenly spaced on a {scale} axis."
    return res


def read_axis_labels(tokens: list[Token], orient: str, coord: float, major: Sequence[float]) -> dict:
    """Pair tokens with ``major`` ticks and check them; see ``check_values``."""
    got = _pair(tokens, orient, coord, list(major))
    values = [parse_number(t.text) if t else None for t in got]
    pow10 = None
    if any(t and t.source == "ocr" for t in got):
        pow10 = _powers_of_ten([t.text for t in got if t])
        if pow10:
            it = iter(pow10)
            values = [next(it) if t else None for t in got]
    res = check_values(list(major), values)
    dropped = None
    if res["suggested"] is None and any(t and t.source == "ocr" for t in got) \
            and sum(v is not None for v in values) >= 4:
        # one misread label breaks the check: drop each in turn, keep a drop that fits
        for k in sorted((k for k, v in enumerate(values) if v is not None),
                        key=lambda k: got[k].conf if got[k].conf is not None else 100):
            trial = list(values)
            trial[k] = None
            r = check_values(list(major), trial)
            if r["suggested"] is not None:
                res, dropped = r, k
                res["message"] = (f"the label at tick {k + 1} was read as \u201c{got[k].text}\u201d, which does not "
                                  f"fit the others; replaced from the spacing. " + r["message"])
                break
    sugg = res["suggested"]
    inverted = None
    if sugg and len(sugg) >= 2:
        increasing = sugg[-1] > sugg[0]   # along PDF coordinates (x right, y down)
        inverted = (not increasing) if orient == "x" else increasing
    srcs = {t.source for t in got if t}
    confs = [t.conf for t in got if t and t.conf is not None]
    res.update(
        values=values,
        inverted=inverted,
        source="ocr" if "ocr" in srcs else ("pdf_text" if srcs else None),
        rejected=dropped,
        min_confidence=min(confs) if confs else None,
        labels=[None if t is None else {"text": t.text, "value": parse_number(t.text),
                                        "bbox": [round(t.x0, 2), round(t.y0, 2), round(t.x1, 2), round(t.y1, 2)]}
                for t in got],
    )
    if res["source"] == "ocr":
        res["ok"] = False
        if pow10:
            res["message"] = "labels look like powers of ten (10\u00b9, 10\u00b2, ...); " + res["message"]
        res["message"] = "read by OCR, check every value. " + res["message"]
    for key in ("suggested", "values"):
        if res.get(key) is not None:
            res[key] = [None if v is None else float(v) + 0.0 for v in res[key]]
    return res


def read_tick_labels(page, bbox: Sequence[float], axes: dict, exclude: Sequence[Sequence[float]] = (),
                     margin: float = 24.0, ocr: str = "auto") -> dict:
    """Tick values for the axes found by ``vector.detect_ticks``.

    ``axes`` is ``{"x": {"coord", "major", ...}, "y": {...}}``. ``ocr``:
    "auto" (only when the text layer gives nothing usable), "never", "always".
    Returns ``{"x": {...}, "y": {...}}`` as in ``read_axis_labels`` (or an
    ``error`` entry for an axis without ticks)."""
    region = [bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin]

    def keep(toks):
        return [t for t in toks if not any(_in_box(t, e) for e in exclude)]

    def n_read(r):
        return sum(v is not None for v in r.get("values", []))

    def coords(o):
        """The detected axis line first, then the opposite frame line: with
        ticks mirrored on all four sides the labelled one may be either."""
        ax, other = axes[o], axes["y" if o == "x" else "x"]
        cs = [ax["coord"]]
        if not other.get("error") and other.get("lo") is not None:
            cs += [c for c in (other["lo"], other["hi"]) if abs(c - ax["coord"]) > 2]
        return cs

    def best(results):
        return max(results, key=lambda r: (n_read(r), r.get("suggested") is not None))

    text = keep(pdf_tokens(page, region)) if ocr != "always" else []
    res = {}
    for o in ("x", "y"):
        ax = axes.get(o) or {}
        if ax.get("error") or not ax.get("major"):
            res[o] = {"error": "no ticks to label", "suggested": None, "values": []}
            continue
        r = best([dict(read_axis_labels(text, o, c, ax["major"]), label_coord=c) for c in coords(o)])
        if ocr == "always" or (ocr == "auto" and n_read(r) < 2):
            if ocr_available():
                cands = []
                for c in coords(o):
                    toks = keep(ocr_tokens(page, {o: dict(ax, coord=c)}))
                    cands.append(dict(read_axis_labels(toks, o, c, ax["major"]), label_coord=c))
                    if n_read(cands[-1]) == len(ax["major"]) and cands[-1].get("suggested") is not None:
                        break
                # misreads inside the plot can outnumber the real labels: an
                # evenly spaced reading wins over a longer inconsistent one
                r2 = max(cands, key=lambda r: (r.get("suggested") is not None, n_read(r)))
                if ocr == "always" or n_read(r2) > n_read(r):
                    r = r2
            elif r.get("suggested") is None:
                r["message"] += " (No text in the PDF here and OCR is not installed.)"
        res[o] = r
    return res
