"""Stage 1 (light, no LLM): find figures via captions and graphics clusters.

1. Caption blocks: text blocks starting with ``Fig.``/``Figure``/``Abb.`` + number.
2. Graphics objects: vector drawings and images, clustered by spatial proximity.
3. Each cluster belongs to the caption directly below it (same column).
4. Kind: cluster without image = vector, with image = raster (image plus
   vector axes = raster, flagged ``mixed``).

The LLM check (P1) is not wired in; the user checks the list by eye.
"""

from __future__ import annotations

import re
from typing import Any

# number must be followed by a caption delimiter, not ")" or "," as in body text
# ("Figure 2) were at the high end", Bastviken 2008 p. 8)
CAPTION_RE = re.compile(r"^\s*(Fig\.?|Figure|Abb\.?|Abbildung)\s*(\d+)(?=[a-z]?\s*[.:|]|\s+[A-Z(])", re.IGNORECASE)


def find_captions(page) -> list[dict]:
    caps = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        text = " ".join("".join(s["text"] for s in ln["spans"]) for ln in b["lines"]).strip()
        m = CAPTION_RE.match(text)
        if m:
            caps.append({"number": m.group(2), "bbox": list(b["bbox"]), "text": text})
    return caps


def _merge_rects(rects: list[list[float]], gap: float) -> list[list[float]]:
    rects = [list(r) for r in rects]
    changed = True
    while changed:
        changed = False
        out: list[list[float]] = []
        for r in rects:
            for o in out:
                if r[0] <= o[2] + gap and o[0] <= r[2] + gap and r[1] <= o[3] + gap and o[1] <= r[3] + gap:
                    o[0], o[1] = min(o[0], r[0]), min(o[1], r[1])
                    o[2], o[3] = max(o[2], r[2]), max(o[3], r[3])
                    changed = True
                    break
            else:
                out.append(r)
        rects = out
    return rects


def graphics_clusters(page, gap: float = 12.0, min_area: float = 400.0) -> list[dict]:
    pw, ph = page.rect.width, page.rect.height
    items = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.width > 0.95 * pw and r.height > 0.95 * ph:
            continue  # page background
        items.append(("vector", [r.x0, r.y0, r.x1, r.y1]))
    for im in page.get_image_info(xrefs=True):
        items.append(("image", list(im["bbox"]), im.get("xref")))
    rects = _merge_rects([it[1] for it in items], gap)
    clusters = []
    for r in rects:
        if (r[2] - r[0]) * (r[3] - r[1]) < min_area:
            continue
        inside = [it for it in items if it[1][0] >= r[0] - 0.5 and it[1][2] <= r[2] + 0.5
                  and it[1][1] >= r[1] - 0.5 and it[1][3] <= r[3] + 0.5]
        has_img = any(it[0] == "image" for it in inside)
        n_vec = sum(1 for it in inside if it[0] == "vector")
        clusters.append({"bbox": r, "has_image": has_img, "n_vector": n_vec,
                         "xrefs": [it[2] for it in inside if it[0] == "image"]})
    return clusters


def find_figures(pdf_path: str, log=None) -> list[dict]:
    import pymupdf
    doc = pymupdf.open(pdf_path)
    figures = []
    for pno, page in enumerate(doc, start=1):
        caps = find_captions(page)
        if not caps:
            continue
        clusters = graphics_clusters(page)
        assigned: dict[int, list[dict]] = {i: [] for i in range(len(caps))}
        for c in clusters:
            b = c["bbox"]
            best, bd = None, None
            for i, cap in enumerate(caps):
                cb = cap["bbox"]
                same_col = b[0] < cb[2] and cb[0] < b[2]
                below = cb[1] >= b[3] - 5
                if same_col and below:
                    d = cb[1] - b[3]
                    if bd is None or d < bd:
                        best, bd = i, d
            if best is not None:
                assigned[best].append(c)
        for i, cap in enumerate(caps):
            cs = assigned[i]
            if not cs:
                continue
            bb = [min(c["bbox"][0] for c in cs), min(c["bbox"][1] for c in cs),
                  max(c["bbox"][2] for c in cs), max(c["bbox"][3] for c in cs)]
            has_img = any(c["has_image"] for c in cs)
            n_vec = sum(c["n_vector"] for c in cs)
            kind = "raster" if has_img else "vector"
            fig = {"number": cap["number"], "page_pdf": pno, "bbox": [round(v, 2) for v in bb],
                   "kind": kind, "mixed": has_img and n_vec > 20, "caption": cap["text"],
                   "caption_bbox": [round(v, 2) for v in cap["bbox"]],
                   "image_xrefs": [x for c in cs for x in c["xrefs"]]}
            figures.append(fig)
            if log:
                log("find_figures", "figure_found", **fig)
                if fig["mixed"]:
                    log("find_figures", "warning_mixed_figure", number=fig["number"], page=pno,
                        note="raster image plus vector axes; treated as raster")
    return figures
