// Shared zoom/pan for an <svg> whose viewBox is in PDF points, plus helpers.

export const NS = "http://www.w3.org/2000/svg";

export function svgEl(tag, attrs = {}, parent = null) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

let spaceDown = false;
window.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !isTyping(e.target)) {
    spaceDown = true;
    if (e.target === document.body || e.target.closest?.("svg")) e.preventDefault();
    document.body.classList.add("space-pan");
  }
});
window.addEventListener("keyup", (e) => {
  if (e.code === "Space") { spaceDown = false; document.body.classList.remove("space-pan"); }
});
window.addEventListener("blur", () => { spaceDown = false; document.body.classList.remove("space-pan"); });

export function isTyping(t) {
  return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}
export const isSpaceDown = () => spaceDown;

export function normBox(a, b) {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}
export const inBox = (p, b) => b && p[0] >= b[0] && p[0] <= b[2] && p[1] >= b[1] && p[1] <= b[3];
export const round2 = (v) => Math.round(v * 100) / 100;

/**
 * Zoom/pan controller. `bounds` = [x0, y0, x1, y1] limits panning (page area).
 * Options: isPanTarget(event) -> bool decides whether a plain drag pans.
 */
export class SvgView {
  constructor(svg, { bounds, isPanTarget, minWidth = 8 } = {}) {
    this.svg = svg;
    this.bounds = bounds;
    this.minWidth = minWidth;
    this.isPanTarget = isPanTarget || ((e) => e.target === svg || e.target.dataset?.bg !== undefined);
    this.listeners = [];
    this.links = [];
    this.vb = { x: 0, y: 0, w: 100, h: 100 };
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.style.touchAction = "none";
    svg.addEventListener("wheel", (e) => this._wheel(e), { passive: false });
    svg.addEventListener("pointerdown", (e) => this._down(e));
    this._ro = new ResizeObserver(() => this._emit());
    this._ro.observe(svg);
  }

  onChange(fn) { this.listeners.push(fn); }

  _emit(fromLink) {
    for (const fn of this.listeners) fn(this.vb);
    if (!fromLink) for (const o of this.links) o.setViewBox(this.vb, true);
  }

  link(other) {
    this.links.push(other);
    other.links.push(this);
  }

  setViewBox(vb, fromLink = false) {
    this.vb = { ...vb };
    this.svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
    this._emit(fromLink);
  }

  fit(box, pad = 0) {
    const [x0, y0, x1, y1] = box;
    this.setViewBox({ x: x0 - pad, y: y0 - pad, w: x1 - x0 + 2 * pad, h: y1 - y0 + 2 * pad });
  }

  /** Screen pixels per PDF point. */
  scale() {
    const r = this.svg.getBoundingClientRect();
    if (!r.width || !r.height) return 1;
    return Math.min(r.width / this.vb.w, r.height / this.vb.h);
  }

  toPt(clientX, clientY) {
    const m = this.svg.getScreenCTM();
    if (!m) return [0, 0];
    const p = new DOMPoint(clientX, clientY).matrixTransform(m.inverse());
    return [p.x, p.y];
  }

  zoomBy(f, center) {
    const vb = this.vb;
    const c = center || [vb.x + vb.w / 2, vb.y + vb.h / 2];
    let w = vb.w * f;
    if (w < this.minWidth) f = this.minWidth / vb.w;
    if (this.bounds) {
      const bw = (this.bounds[2] - this.bounds[0]) * 1.5;
      if (vb.w * f > bw) f = bw / vb.w;
    }
    this.setViewBox({ x: c[0] - (c[0] - vb.x) * f, y: c[1] - (c[1] - vb.y) * f, w: vb.w * f, h: vb.h * f });
  }

  _wheel(e) {
    e.preventDefault();
    const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
    const f = Math.exp(Math.max(-0.5, Math.min(0.5, dy * 0.0015)));
    this.zoomBy(f, this.toPt(e.clientX, e.clientY));
  }

  _down(e) {
    const pan = e.button === 1 || (e.button === 0 && (spaceDown || this.isPanTarget(e)));
    if (!pan) return;
    e.preventDefault();
    e.stopPropagation();
    const s = this.scale();
    const start = { cx: e.clientX, cy: e.clientY, vb: { ...this.vb } };
    this.svg.setPointerCapture(e.pointerId);
    this.svg.classList.add("panning");
    const move = (ev) => {
      const dx = (ev.clientX - start.cx) / s, dy = (ev.clientY - start.cy) / s;
      this.setViewBox({ ...start.vb, x: start.vb.x - dx, y: start.vb.y - dy });
    };
    const up = () => {
      this.svg.removeEventListener("pointermove", move);
      this.svg.removeEventListener("pointerup", up);
      this.svg.removeEventListener("pointercancel", up);
      this.svg.classList.remove("panning");
    };
    this.svg.addEventListener("pointermove", move);
    this.svg.addEventListener("pointerup", up);
    this.svg.addEventListener("pointercancel", up);
    this._panned = true;
  }

  destroy() { this._ro.disconnect(); }
}

/**
 * Track a drag that started with pointer event `e` on an overlay element.
 * onMove(pt, startPt) during the drag, onEnd(pt, startPt, moved) on release.
 */
export function dragFrom(e, view, onMove, onEnd) {
  e.preventDefault();
  e.stopPropagation();
  const svg = view.svg;
  const start = view.toPt(e.clientX, e.clientY);
  const c0 = [e.clientX, e.clientY];
  let moved = false;
  svg.setPointerCapture(e.pointerId);
  const move = (ev) => {
    if (!moved && Math.hypot(ev.clientX - c0[0], ev.clientY - c0[1]) < 3) return;
    moved = true;
    onMove && onMove(view.toPt(ev.clientX, ev.clientY), start);
  };
  const up = (ev) => {
    svg.removeEventListener("pointermove", move);
    svg.removeEventListener("pointerup", up);
    svg.removeEventListener("pointercancel", up);
    onEnd && onEnd(view.toPt(ev.clientX, ev.clientY), start, moved && ev.type === "pointerup");
  };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerup", up);
  svg.addEventListener("pointercancel", up);
}

/** Page <image> whose resolution follows the view scale (zoom 2, or 4 when zoomed in). */
export function pageImage(parent, view, urlFor, size, attrs = {}) {
  const img = svgEl("image", { x: 0, y: 0, width: size[0], height: size[1], preserveAspectRatio: "none", "data-bg": "", ...attrs }, parent);
  let cur = 0;
  const update = () => {
    const z = view.scale() * (window.devicePixelRatio || 1) > 2.2 ? 4 : 2;
    if (z !== cur) {
      cur = z;
      img.setAttribute("href", urlFor(z));
    }
  };
  view.onChange(update);
  update();
  return img;
}

/** Zoom controls (−, +, fit) for a view. */
export function zoomControls(view, fitFn) {
  const wrap = document.createElement("div");
  wrap.className = "zoom-controls";
  const mk = (label, aria, fn) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn icon";
    b.textContent = label;
    b.setAttribute("aria-label", aria);
    b.title = aria;
    b.addEventListener("click", fn);
    wrap.appendChild(b);
  };
  mk("−", "Zoom out", () => view.zoomBy(1.25));
  mk("+", "Zoom in", () => view.zoomBy(0.8));
  mk("⤢", "Fit to view", fitFn);
  return wrap;
}
