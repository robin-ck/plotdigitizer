"""Read series NAMES from the legend text without an LLM.

Legend marker positions come from ``vector.detect_legend`` /
``raster.detect_legend``. Each entry's name is the text on the marker's row,
right of the marker (left of it when nothing is on the right):

1. PDF text layer (``page.get_text("words")``): exact.
2. OCR fallback (Tesseract, optional) for rows without text in the layer
   (outlined glyphs, embedded images). Always marked for checking.

Results are suggestions; the user (or Figure Card) stays the authority.
"""

from __future__ import annotations

import re
from typing import Sequence

import numpy as np

from .ticklabels import ocr_available


def _row_half_heights(markers: Sequence[dict], bbox) -> list[float]:
    """Half the vertical room of each row: half the gap to the nearest other
    row, capped by the marker size (single-row legends get the box height)."""
    ys = [m["y"] for m in markers]
    out = []
    for i, m in enumerate(markers):
        gaps = [abs(y - m["y"]) for j, y in enumerate(ys) if j != i and abs(y - m["y"]) > 1.0]
        size = max(float(m.get("size") or 4.0), 4.0)
        h = 0.5 * min(gaps) if gaps else 0.5 * (bbox[3] - bbox[1])
        out.append(max(2.0, min(h, 1.5 * size)))
    return out


def _clean(text: str) -> str:
    # legend lines/markers OCR'd as dashes, bars, bullets, etc. at either end
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^[\W_]+(?=\w)|(?<=[\w)\]%])[^\w)\]%]+$", "", text).strip()


def _side_words(words, m, hh):
    """Words on the marker's row, right of it, else left of it."""
    half = 0.5 * float(m.get("size") or 0.0)
    row = [w for w in words if abs(0.5 * (w[1] + w[3]) - m["y"]) <= hh]
    right = [w for w in row if w[0] >= m["x"] + half - 0.5]
    left = [w for w in row if w[2] <= m["x"] - half + 0.5]
    return sorted(right or left, key=lambda w: w[0])


def pdf_labels(page, bbox, markers: Sequence[dict]) -> list[str | None]:
    import pymupdf
    words = page.get_text("words", clip=pymupdf.Rect(*bbox))
    words = [w for w in words if (w[4] or "").strip()]
    hh = _row_half_heights(markers, bbox)
    out = []
    for m, h in zip(markers, hh):
        ws = _side_words(words, m, h)
        # multi-column legend: stop at the next marker on the same row
        nxt = [o["x"] for o in markers if o["x"] > m["x"] + 2.0 and abs(o["y"] - m["y"]) <= h]
        if nxt:
            ws = [w for w in ws if w[0] < min(nxt)]
        txt = _clean(" ".join(w[4] for w in ws))
        out.append(txt or None)
    return out


def _ocr_line(gray: np.ndarray) -> tuple[str, float]:
    import pytesseract
    from PIL import Image, ImageOps

    ink = gray < 140
    r = np.flatnonzero(ink.any(axis=1))
    c = np.flatnonzero(ink.any(axis=0))
    if not len(r) or not len(c):
        return "", 0.0
    sub = gray[r[0]:r[-1] + 1, c[0]:c[-1] + 1]
    img = Image.fromarray(np.ascontiguousarray(sub))
    if img.height < 30:
        f = 40 / img.height
        img = img.resize((max(1, int(img.width * f)), 40), Image.LANCZOS)
    img = ImageOps.expand(img, border=max(10, img.height // 2), fill=255)
    d = pytesseract.image_to_data(img, config="--psm 7", output_type=pytesseract.Output.DICT)
    words = [(w.strip(), float(cf)) for w, cf in zip(d["text"], d["conf"]) if (w or "").strip() and float(cf) >= 0]
    if not words:
        return "", 0.0
    return " ".join(w for w, _ in words), min(cf for _, cf in words)


def _text_start(gray: np.ndarray, start: int) -> int | None:
    """First ink column after the marker (and any line glued to it) that
    touches ``start``; a detached dashed line is left to Tesseract and
    ``_clean``."""
    cols = (gray < 140).any(axis=0)
    c = start
    while c < len(cols) and cols[c]:
        c += 1
    ink = np.flatnonzero(cols[c:])
    return int(c + ink[0]) if len(ink) else None


def ocr_labels(page, bbox, markers: Sequence[dict], todo: Sequence[int], zoom: float = 6.0) -> dict[int, tuple[str, float]]:
    import pymupdf
    hh = _row_half_heights(markers, bbox)
    out = {}
    for i in todo:
        m, h = markers[i], hh[i]
        half = 0.5 * float(m.get("size") or 4.0)
        # multi-column legend: stop before the next marker on the same row
        nxt = [o["x"] - 0.5 * float(o.get("size") or 4.0) for o in markers
               if o["x"] > m["x"] + 2.0 and abs(o["y"] - m["y"]) <= h]
        right = min(nxt + [bbox[2]])
        rect = pymupdf.Rect(m["x"] - half, m["y"] - h, right, m["y"] + h) & pymupdf.Rect(*bbox)
        if rect.is_empty or rect.width < 2:
            continue
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect, colorspace=pymupdf.csGRAY, alpha=False)
        gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
        # start just right of the marker centre, skip marker + attached line
        span = _text_start(gray, int(half * zoom))
        if not span:
            continue
        txt, conf = _ocr_line(gray[:, max(0, span - 2):])
        txt = _clean(txt)
        if txt:
            out[i] = (txt, conf)
    return out


def read_legend_labels(page, bbox: Sequence[float], markers: Sequence[dict], use_ocr: bool = True) -> list[dict]:
    """One ``{"label", "source", "confidence"}`` per marker (same order).

    ``source`` is ``"pdf"``, ``"ocr"`` or ``None`` (nothing read)."""
    if not markers:
        return []
    labels = pdf_labels(page, bbox, markers)
    res = [{"label": t, "source": "pdf" if t else None, "confidence": 100.0 if t else None} for t in labels]
    todo = [i for i, t in enumerate(labels) if not t]
    if todo and use_ocr and ocr_available():
        for i, (t, c) in ocr_labels(page, bbox, markers, todo).items():
            res[i] = {"label": t, "source": "ocr", "confidence": round(c, 1)}
    return res
