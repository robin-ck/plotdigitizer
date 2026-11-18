// Marker symbols (circle, square, triangle, diamond, x, plus, star) as SVG
// elements, plus the series colour palette.

const NS = "http://www.w3.org/2000/svg";

export const SHAPES = ["circle", "square", "triangle", "diamond", "x", "plus", "star"];

// Colour-blind-safe palette (Okabe-Ito based, darkened for >= 4.5:1 on white).
export const PALETTE = ["#0b62a4", "#c2410c", "#0f766e", "#a21caf", "#8a5a00", "#4d7c0f", "#be123c", "#334155"];

export function seriesColor(i) {
  return PALETTE[((i % PALETTE.length) + PALETTE.length) % PALETTE.length];
}

function svgEl(tag, attrs = {}) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
  return e;
}

function star(cx, cy, r) {
  const pts = [];
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 === 0 ? r : r * 0.45;
    pts.push(`${(cx + rr * Math.cos(a)).toFixed(3)},${(cy + rr * Math.sin(a)).toFixed(3)}`);
  }
  return pts.join(" ");
}

/**
 * SVG element for a marker centred at (cx, cy) with half size r.
 * opts: {color, filled, strokeWidth}
 */
export function markerEl(shape, cx, cy, r, opts = {}) {
  const color = opts.color || "#111";
  const sw = opts.strokeWidth ?? r * 0.35;
  const lineOnly = shape === "x" || shape === "plus";
  const fill = lineOnly ? "none" : opts.filled ? color : "#fff";
  const common = { fill, stroke: color, "stroke-width": sw, "vector-effect": opts.nonScaling ? "non-scaling-stroke" : null };
  switch (shape) {
    case "square":
      return svgEl("rect", { x: cx - r * 0.85, y: cy - r * 0.85, width: r * 1.7, height: r * 1.7, ...common });
    case "triangle":
      return svgEl("polygon", { points: `${cx},${cy - r} ${cx + r * 0.95},${cy + r * 0.75} ${cx - r * 0.95},${cy + r * 0.75}`, ...common });
    case "diamond":
      return svgEl("polygon", { points: `${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}`, ...common });
    case "x":
      return svgEl("path", { d: `M${cx - r * 0.8},${cy - r * 0.8}L${cx + r * 0.8},${cy + r * 0.8}M${cx - r * 0.8},${cy + r * 0.8}L${cx + r * 0.8},${cy - r * 0.8}`, ...common, "stroke-width": sw * 1.4 });
    case "plus":
      return svgEl("path", { d: `M${cx - r},${cy}L${cx + r},${cy}M${cx},${cy - r}L${cx},${cy + r}`, ...common, "stroke-width": sw * 1.4 });
    case "star":
      return svgEl("polygon", { points: star(cx, cy, r * 1.15), ...common });
    case "circle":
    default:
      return svgEl("circle", { cx, cy, r: r * 0.9, ...common });
  }
}

/** Small standalone <svg> icon of a marker (for legends, lists, tables). */
export function markerIcon(shape, filled, color = "#1f2933", size = 16) {
  const s = svgEl("svg", { width: size, height: size, viewBox: "0 0 16 16", "aria-hidden": "true", focusable: "false", class: "marker-icon" });
  s.appendChild(markerEl(shape, 8, 8, 5.5, { color, filled, strokeWidth: 1.6 }));
  return s;
}
