// Screen 2: set up a figure (panel, legend and inset boxes; axis ticks; series)
// and build the Figure Card (schemas/figure_card.schema.json).

import { api } from "./api.js";
import { h, clear, busy, errorBox, setHeader, confirmDialog } from "./ui.js";
import { SvgView, svgEl, dragFrom, pageImage, zoomControls, normBox, round2 } from "./svgview.js";
import { markerIcon, SHAPES } from "./markers.js";
import { go, routes } from "./router.js";

const MIN_BOX = 4; // pt
const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

// ---------------------------------------------------------------- state helpers

function axisState(a = {}, orient) {
  const vals = (a.ticks || []).map((t) => (Array.isArray(t) ? t[1] : t));
  const text = vals.join(", ");
  return { title: a.title || "", unit: a.unit || "", ticks: text, ticksInit: text, log: a.scale === "log",
    inverted: !!a.inverted, orient, orig: a };
}

function seriesState(s = {}) {
  return { label: s.label || "", meaning: s.meaning || "", marker: s.marker || "circle", filled: !!s.filled,
    line: !!(s.line && s.line !== "none"), orig: s };
}

function panelState(p = {}) {
  return {
    id: p.id || "a",
    bbox: p.bbox_pt || null,
    legend: (p.legend && p.legend.bbox_pt) || null,
    insets: (p.insets || []).map((i) => ({ id: i.id, bbox: i.bbox_pt || null, x: axisState(i.x, "x"), y: axisState(i.y, "y"), det: null, orig: i })),
    x: axisState(p.x, "x"),
    y: axisState(p.y, "y"),
    series: (p.series || []).map(seriesState),
    det: null,
    detBusy: false,
    orig: p,
  };
}

function parseTicks(text) {
  const parts = text.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean);
  const vals = parts.map((s) => Number(s.replace("−", "-")));
  return { vals, bad: parts.filter((_, i) => !Number.isFinite(vals[i])) };
}

function axisCard(a, full) {
  const out = { ...a.orig };
  if (full) {
    if (a.title) out.title = a.title; else delete out.title;
    if (a.unit) out.unit = a.unit; else delete out.unit;
  }
  if (a.log) out.scale = "log";
  else if (full || out.scale) out.scale = "linear";
  if (a.inverted) out.inverted = true; else delete out.inverted;
  // keep [position, value] pairs from a saved card unless the text changed
  out.ticks = a.ticks === a.ticksInit && a.orig.ticks ? a.orig.ticks : parseTicks(a.ticks).vals;
  return out;
}

const r2 = (b) => b.map(round2);

function buildCard(st) {
  const base = st.origCard || {};
  const panels = st.panels.map((p) => {
    const out = { ...p.orig, id: p.id, bbox_pt: r2(p.bbox), x: axisCard(p.x, true), y: axisCard(p.y, true) };
    delete out.bbox_px;
    if (p.legend) out.legend = { ...(p.orig.legend || {}), bbox_pt: r2(p.legend) };
    else delete out.legend;
    if (p.insets.length) {
      out.insets = p.insets.map((i) => ({ ...i.orig, id: i.id, bbox_pt: r2(i.bbox), x: axisCard(i.x, false), y: axisCard(i.y, false) }));
    } else delete out.insets;
    out.series = p.series.map((s) => {
      const o = { ...s.orig, label: s.label.trim(), marker: s.marker, filled: s.filled, line: s.line ? (s.orig.line && s.orig.line !== "none" ? s.orig.line : "solid") : "none" };
      if (s.meaning.trim()) o.meaning = s.meaning.trim(); else delete o.meaning;
      return o;
    });
    return out;
  });
  return {
    ...base,
    paper: { ...(base.paper || {}), citekey: st.session.citekey },
    figure: { ...(base.figure || {}), number: String(st.num), page_pdf: st.page, kind: "vector" },
    panels,
  };
}

/** Problems that block extraction; each {key, msg}. */
function problems(st) {
  const out = [];
  if (!st.panels.length) out.push({ key: "none", msg: "Draw at least one panel box." });
  const ids = new Set();
  st.panels.forEach((p, pi) => {
    const P = `Panel ${p.id}`;
    if (!p.bbox) out.push({ key: `${pi}.box`, msg: `${P}: draw the panel box.` });
    const axes = [[p.x, p.det && p.det.x, `${P}, x axis`, `${pi}.x`], [p.y, p.det && p.det.y, `${P}, y axis`, `${pi}.y`]];
    p.insets.forEach((ins, k) => {
      axes.push([ins.x, ins.det && ins.det.x, `${P}, inset ${ins.id} x axis`, `${pi}.i${k}.x`]);
      axes.push([ins.y, ins.det && ins.det.y, `${P}, inset ${ins.id} y axis`, `${pi}.i${k}.y`]);
    });
    for (const [a, det, name, key] of axes) {
      const m = tickMismatch(a, det);
      if (m.block) out.push({ key, msg: `${name}: ${m.text}` });
    }
    if (!p.series.length) out.push({ key: `${pi}.series`, msg: `${P}: add at least one series (or draw the legend box).` });
    const labels = new Set();
    p.series.forEach((s, si) => {
      const l = s.label.trim();
      if (!l) out.push({ key: `${pi}.s${si}`, msg: `${P}: series ${si + 1} needs a name.` });
      else if (labels.has(l)) out.push({ key: `${pi}.s${si}`, msg: `${P}: series name “${l}” is used twice.` });
      labels.add(l);
    });
    if (ids.has(p.id)) out.push({ key: `${pi}.id`, msg: `Panel id ${p.id} is used twice.` });
    ids.add(p.id);
  });
  return out;
}

/** {text, cls, block} describing entered vs detected tick count for one axis. */
function tickMismatch(a, det) {
  const { vals, bad } = parseTicks(a.ticks);
  if (bad.length) return { text: `“${bad[0]}” is not a number.`, cls: "bad", block: true };
  if (vals.length < 2) return { text: "enter at least 2 tick values.", cls: "bad", block: true };
  if (a.log && vals.some((v) => v <= 0)) return { text: "log scale needs positive tick values.", cls: "bad", block: true };
  if (!det) return { text: `${vals.length} values entered; ticks not detected yet.`, cls: "", block: false };
  if (det.error) return { text: `${vals.length} values entered; no axis line found in the box (${det.error}).`, cls: "", block: false };
  const n = det.major.length;
  if (n !== vals.length) return { text: `${vals.length} values entered but ${n} major ticks found.`, cls: "bad", block: true };
  return { text: `${n} ticks found, ${vals.length} values entered.`, cls: "good", block: false };
}

function nextPanelId(st) {
  const used = new Set(st.panels.map((p) => p.id));
  for (const c of "abcdefghijklmnopqrstuvwxyz") if (!used.has(c)) return c;
  return `p${st.panels.length + 1}`;
}

function nextInsetId(p) {
  const used = new Set(p.insets.map((i) => i.id));
  for (let i = 1; ; i++) if (!used.has(`i${i}`)) return `i${i}`;
}

// ---------------------------------------------------------------- screen

export async function render(app, { token, num, query }) {
  const session = await api.session(token);
  let card = null;
  try { card = await api.card(token, num); } catch (e) { if (e.status !== 404) throw e; }
  const fig = (session.figures || []).find((f) => String(f.number) === String(num));
  let page = Number((card && card.figure && card.figure.page_pdf) || query.page || (fig && fig.page_pdf) || 1);
  page = Math.min(Math.max(1, page), session.n_pages || 1);

  const st = {
    token, num, page, session, origCard: card,
    panels: card ? card.panels.map(panelState) : [],
    cur: 0, tool: card ? "select" : "panel",
  };
  if (!st.panels.length) st.panels.push(panelState({ id: "a" }));

  setHeader({ step: 2, context: `${session.citekey} · Fig. ${num}`, right: card ? "Saved set-up loaded" : "" });

  // ----- layout
  const svg = svgEl("svg", { role: "img", "aria-label": `Page ${page} of the PDF with the drawn boxes` });
  const stage = h("div", { class: "stage" }, svg);
  const pageSel = h("select", { class: "text", id: "page-sel", style: { width: "auto" }, "aria-label": "Page" });
  for (let i = 1; i <= session.n_pages; i++) pageSel.appendChild(h("option", { value: i, selected: i === page }, `Page ${i}`));
  const toolBtns = {};
  const mkTool = (tool, label) => (toolBtns[tool] = h("button", { type: "button", class: "btn", "aria-pressed": "false", onclick: () => setTool(st.tool === tool ? "select" : tool) }, label));
  const scaleLabel = h("span", { class: "small muted" });
  const toolbar = h("div", { class: "toolbar", role: "toolbar", "aria-label": "Drawing tools" },
    h("a", { href: routes.session(token), class: "btn" }, "← Figures"),
    mkTool("panel", "Draw panel box"), mkTool("legend", "Draw legend box"), mkTool("inset", "Draw inset"),
    h("span", { class: "spacer" }),
    h("label", { for: "page-sel", class: "small muted" }, "Page"), pageSel, scaleLabel);
  const help = h("p", { class: "stage-help", "aria-live": "polite" });
  const side = h("aside", { class: "side", "aria-label": "Figure set-up form" });
  app.appendChild(h("div", { class: "workspace" },
    h("section", { class: "canvas-col", "aria-label": "Page" }, h("h1", { class: "visually-hidden" }, `Set up figure ${num}`), toolbar, stage, help),
    side));

  // ----- page view
  let pageSize = session.page_sizes[page - 1] || [612, 792];
  const view = new SvgView(svg, {
    bounds: [0, 0, pageSize[0], pageSize[1]],
    isPanTarget: (e) => st.tool === "select" && (e.target === svg || e.target.dataset.bg !== undefined),
  });
  const bgRect = svgEl("rect", { x: -5000, y: -5000, width: 10000, height: 10000, fill: "#d9dde2", "data-bg": "" }, svg);
  const pageRect = svgEl("rect", { x: 0, y: 0, width: pageSize[0], height: pageSize[1], fill: "#fff", "data-bg": "" }, svg);
  let img = pageImage(svg, view, (z) => api.pageUrl(token, st.page, z), pageSize);
  const ov = svgEl("g", { class: "overlay" }, svg);
  toolbar.insertBefore(zoomControls(view, fitView), scaleLabel);
  view.onChange(() => { scaleLabel.textContent = `${Math.round(view.scale() * 100)}%`; drawOverlay(); });

  function fitView() {
    const boxes = st.panels.filter((p) => p.bbox).flatMap((p) => [p.bbox, p.legend].filter(Boolean));
    if (boxes.length) {
      const b = [Math.min(...boxes.map((x) => x[0])), Math.min(...boxes.map((x) => x[1])), Math.max(...boxes.map((x) => x[2])), Math.max(...boxes.map((x) => x[3]))];
      view.fit(b, 30);
    } else if (fig && fig.bbox && fig.page_pdf === st.page) view.fit(fig.bbox, 20);
    else view.fit([0, 0, pageSize[0], pageSize[1]], 4);
  }

  pageSel.addEventListener("change", () => {
    st.page = Number(pageSel.value);
    pageSize = session.page_sizes[st.page - 1] || pageSize;
    view.bounds = [0, 0, pageSize[0], pageSize[1]];
    pageRect.setAttribute("width", pageSize[0]); pageRect.setAttribute("height", pageSize[1]);
    img.remove();
    img = pageImage(svg, view, (z) => api.pageUrl(token, st.page, z), pageSize);
    svg.insertBefore(img, ov);
    svg.setAttribute("aria-label", `Page ${st.page} of the PDF with the drawn boxes`);
    st.panels.forEach((p) => { p.det = null; p.insets.forEach((i) => (i.det = null)); });
    st.panels.forEach((p, i) => runDetect(i));
    fitView();
    renderSide();
  });

  // ----- tools
  function setTool(t) {
    st.tool = t;
    for (const [k, b] of Object.entries(toolBtns)) b.setAttribute("aria-pressed", String(k === t));
    svg.classList.toggle("tool-draw", t !== "select");
    ov.style.pointerEvents = t === "select" ? "" : "none";
    const p = st.panels[st.cur];
    help.textContent = {
      select: "Drag a box edge to move it, a handle to resize it. Drag the page (or hold Space) to pan, scroll to zoom. Teal dots: tick positions found in the PDF drawing.",
      panel: p && !p.bbox ? `Drag on the page to draw the box of panel ${p.id} (include the axes and tick labels).` : "Drag on the page to draw a new panel box.",
      legend: `Drag around the legend of panel ${p ? p.id : ""}.`,
      inset: `Drag around an inset plot inside panel ${p ? p.id : ""}.`,
    }[t];
  }

  svg.addEventListener("pointerdown", (e) => {
    if (e.defaultPrevented || st.tool === "select" || e.button !== 0) return;
    const draft = svgEl("rect", { class: "draft" }, ov);
    dragFrom(e, view, (pt, s0) => {
      const b = normBox(s0, pt);
      draft.setAttribute("x", b[0]); draft.setAttribute("y", b[1]);
      draft.setAttribute("width", b[2] - b[0]); draft.setAttribute("height", b[3] - b[1]);
    }, (pt, s0, moved) => {
      draft.remove();
      const b = normBox(s0, pt);
      if (!moved || b[2] - b[0] < MIN_BOX || b[3] - b[1] < MIN_BOX) return;
      boxDrawn(st.tool, b);
    });
  });

  function boxDrawn(tool, b) {
    let p = st.panels[st.cur];
    if (tool === "panel") {
      if (!p || p.bbox) {
        p = panelState({ id: nextPanelId(st) });
        st.panels.push(p);
        st.cur = st.panels.length - 1;
      }
      p.bbox = b;
      runDetect(st.cur);
    } else if (tool === "legend") {
      p.legend = b;
      runLegend(st.cur);
      runDetect(st.cur);
    } else if (tool === "inset") {
      const ins = { id: nextInsetId(p), bbox: b, x: axisState({}, "x"), y: axisState({ inverted: p.y.inverted }, "y"), det: null, orig: {} };
      p.insets.push(ins);
      runDetectInset(st.cur, p.insets.length - 1);
      runDetect(st.cur);
    }
    setTool("select");
    drawOverlay();
    renderSide();
  }

  // ----- overlay drawing
  function drawOverlay() {
    clear(ov);
    const s = view.scale() || 1;
    const hs = 10 / s; // handle size: 10 screen px
    st.panels.forEach((p, pi) => {
      const isCur = pi === st.cur;
      if (p.bbox) boxEl(p.bbox, `panel${isCur ? "" : " other"}`, `Panel ${p.id}`, isCur, hs, (nb) => { p.bbox = nb; }, () => runDetect(pi), pi);
      if (p.legend) boxEl(p.legend, "legend", `Legend ${p.id}`, isCur, hs, (nb) => { p.legend = nb; }, () => { runLegend(pi); runDetect(pi); }, pi);
      p.insets.forEach((ins, k) => {
        if (ins.bbox) boxEl(ins.bbox, "inset", `Inset ${p.id}.${ins.id}`, isCur, hs, (nb) => { ins.bbox = nb; }, () => { runDetectInset(pi, k); runDetect(pi); }, pi);
      });
      if (isCur) {
        drawTicks(p.det, 3.2 / s);
        p.insets.forEach((ins) => drawTicks(ins.det, 2.6 / s));
      }
    });
  }

  function drawTicks(det, r) {
    if (!det) return;
    const g = svgEl("g", { "aria-hidden": "true", style: "pointer-events:none" }, ov);
    const ax = det.x, ay = det.y;
    if (ax && !ax.error) {
      svgEl("line", { class: "ov-axis", x1: ax.lo, x2: ax.hi, y1: ax.coord, y2: ax.coord }, g);
      for (const x of ax.major) svgEl("circle", { class: "ov-tick", cx: x, cy: ax.coord, r }, g);
    }
    if (ay && !ay.error) {
      svgEl("line", { class: "ov-axis", y1: ay.lo, y2: ay.hi, x1: ay.coord, x2: ay.coord }, g);
      for (const y of ay.major) svgEl("circle", { class: "ov-tick", cx: ay.coord, cy: y, r }, g);
    }
  }

  function boxEl(b, cls, label, active, hs, set, done, pi) {
    const g = svgEl("g", {}, ov);
    const [x0, y0, x1, y1] = b;
    svgEl("rect", { class: `ov-box ${cls}`, x: x0, y: y0, width: x1 - x0, height: y1 - y0 }, g);
    const color = cls.startsWith("panel") ? "#1d4ed8" : cls === "legend" ? "#c2410c" : "#7c3aed";
    const fs = 12 / view.scale();
    const lab = svgEl("text", { x: x0, y: y0 - 4 / view.scale(), "font-size": fs, "font-family": "Inter, system-ui, sans-serif", "font-weight": 600, fill: color, style: "pointer-events:none" }, g);
    lab.textContent = label;
    const hit = svgEl("rect", { class: "ov-hit inner", x: x0, y: y0, width: x1 - x0, height: y1 - y0 }, g);
    hit.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (st.cur !== pi) { st.cur = pi; renderSide(); }
      const orig = [...b];
      dragFrom(e, view, (pt, s0) => {
        const dx = pt[0] - s0[0], dy = pt[1] - s0[1];
        set([orig[0] + dx, orig[1] + dy, orig[2] + dx, orig[3] + dy]);
        drawOverlay();
      }, (pt, s0, moved) => { drawOverlay(); if (moved) { done(); renderSide(); } });
    });
    if (!active) return;
    const pos = { nw: [x0, y0], n: [(x0 + x1) / 2, y0], ne: [x1, y0], e: [x1, (y0 + y1) / 2], se: [x1, y1], s: [(x0 + x1) / 2, y1], sw: [x0, y1], w: [x0, (y0 + y1) / 2] };
    for (const k of HANDLES) {
      const [hx, hy] = pos[k];
      const hd = svgEl("rect", { class: `ov-handle ${k}`, x: hx - hs / 2, y: hy - hs / 2, width: hs, height: hs, fill: color, stroke: "#fff", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, g);
      if (k === "n" || k === "s") hd.style.cursor = "ns-resize";
      if (k === "e" || k === "w") hd.style.cursor = "ew-resize";
      hd.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        const orig = [...b];
        dragFrom(e, view, (pt) => {
          const nb = [...orig];
          if (k.includes("w")) nb[0] = pt[0];
          if (k.includes("e")) nb[2] = pt[0];
          if (k.includes("n")) nb[1] = pt[1];
          if (k.includes("s")) nb[3] = pt[1];
          set(normBox([nb[0], nb[1]], [nb[2], nb[3]]));
          drawOverlay();
        }, (pt, s0, moved) => { drawOverlay(); if (moved) { done(); renderSide(); } });
      });
    }
  }

  // ----- server helpers
  const status = h("p", { class: "status", "aria-live": "polite" });
  let detectSeq = 0;
  async function runDetect(pi) {
    const p = st.panels[pi];
    if (!p || !p.bbox) return;
    const my = ++detectSeq;
    p.detSeq = my;
    const exclude = [p.legend, ...p.insets.map((i) => i.bbox)].filter(Boolean).map(r2);
    const done = busy(status, `Looking for axis ticks in panel ${p.id}…`);
    try {
      const det = await api.detect(token, { page: st.page, bbox: r2(p.bbox), exclude });
      if (p.detSeq !== my) return;
      p.det = det;
      p.detErr = null;
    } catch (e) {
      if (p.detSeq !== my) return;
      p.det = null;
      p.detErr = e.message;
    } finally { done(); }
    drawOverlay();
    renderSide();
  }

  async function runDetectInset(pi, k) {
    const p = st.panels[pi];
    const ins = p && p.insets[k];
    if (!ins || !ins.bbox) return;
    const my = ++detectSeq;
    ins.detSeq = my;
    try {
      const det = await api.detect(token, { page: st.page, bbox: r2(ins.bbox), exclude: p.legend ? [r2(p.legend)] : [] });
      if (ins.detSeq === my) ins.det = det;
    } catch (e) {
      if (ins.detSeq === my) ins.det = null;
    }
    drawOverlay();
    renderSide();
  }

  async function runLegend(pi) {
    const p = st.panels[pi];
    if (!p || !p.legend) return;
    const done = busy(status, `Reading the legend of panel ${p.id}…`);
    try {
      const ms = await api.legend(token, { page: st.page, bbox: r2(p.legend) });
      p.series = ms.map((m, i) => {
        const old = p.series[i];
        const s = old ? { ...old } : seriesState({});
        s.marker = SHAPES.includes(m.marker) ? m.marker : "circle";
        s.filled = !!m.filled;
        s.color = m.color;
        return s;
      });
      p.legendMsg = ms.length ? `${ms.length} legend markers found, top to bottom.` : "No markers found in the legend box. Add series by hand.";
    } catch (e) {
      p.legendMsg = `Legend could not be read: ${e.message}`;
    } finally { done(); }
    renderSide();
  }

  // ----- side form
  function bboxInput(id, label, b, onSet) {
    const inp = h("input", { id, value: b ? r2(b).join(", ") : "", placeholder: "x0, y0, x1, y1", inputmode: "decimal" });
    inp.addEventListener("change", () => {
      const v = inp.value.split(/[,\s]+/).filter(Boolean).map(Number);
      if (v.length === 4 && v.every(Number.isFinite)) onSet(normBox([v[0], v[1]], [v[2], v[3]]));
      else inp.setCustomValidity("Enter four numbers: x0, y0, x1, y1"), inp.reportValidity();
    });
    inp.addEventListener("input", () => inp.setCustomValidity(""));
    return h("div", { class: "field" }, h("label", { for: id }, label), inp);
  }

  function axisFields(prefix, a, det, key, full, invertedLabel) {
    const tid = `${prefix}-ticks`;
    const note = h("span", { class: "tick-note", "data-note": key, id: `${tid}-note` });
    const ticks = h("input", { id: tid, value: a.ticks, placeholder: "e.g. 0, 50, 100, 150", inputmode: "decimal", "aria-describedby": `${tid}-note` });
    ticks.addEventListener("input", () => { a.ticks = ticks.value; updateValidity(); });
    const nFound = det && det[a.orient] && !det[a.orient].error ? ` (${det[a.orient].major.length} ticks found)` : "";
    const rows = [];
    if (full) {
      const t = h("input", { id: `${prefix}-title`, value: a.title, oninput: (e) => (a.title = e.target.value) });
      const u = h("input", { id: `${prefix}-unit`, value: a.unit, oninput: (e) => (a.unit = e.target.value) });
      rows.push(h("div", { class: "grid2" },
        h("div", { class: "field" }, h("label", { for: `${prefix}-title` }, "Variable"), t),
        h("div", { class: "field" }, h("label", { for: `${prefix}-unit` }, "Unit"), u)));
    }
    rows.push(h("div", { class: "field", "data-field": key },
      h("label", { for: tid }, `Tick values${nFound}`), ticks, note));
    const logBox = h("input", { type: "checkbox", id: `${prefix}-log`, checked: a.log, onchange: (e) => { a.log = e.target.checked; updateValidity(); } });
    const invBox = h("input", { type: "checkbox", id: `${prefix}-inv`, checked: a.inverted, onchange: (e) => (a.inverted = e.target.checked) });
    rows.push(h("div", { class: "row" },
      h("label", { class: "check", for: `${prefix}-log` }, logBox, "Log scale"),
      h("label", { class: "check", for: `${prefix}-inv` }, invBox, invertedLabel)));
    return rows;
  }

  function seriesRows(p, pi) {
    const list = h("div", { class: "series-list" });
    p.series.forEach((s, si) => {
      const icon = h("span", { class: "marker-cell" }, markerIcon(s.marker, s.filled, "#1f2933", 18));
      const refreshIcon = () => { clear(icon); icon.appendChild(markerIcon(s.marker, s.filled, "#1f2933", 18)); };
      const name = h("input", { class: "text", id: `s-${pi}-${si}-name`, value: s.label, placeholder: "Name (label)", "aria-label": `Series ${si + 1} name`, "data-field": `${pi}.s${si}`,
        oninput: (e) => { s.label = e.target.value; updateValidity(); } });
      const meaning = h("input", { class: "text meaning", id: `s-${pi}-${si}-meaning`, value: s.meaning, placeholder: "Meaning (optional)", "aria-label": `Series ${si + 1} meaning`,
        oninput: (e) => (s.meaning = e.target.value) });
      const del = h("button", { type: "button", class: "btn icon", "aria-label": `Remove series ${si + 1}`, title: "Remove series",
        onclick: () => { p.series.splice(si, 1); renderSide(); } }, "×");
      const mSel = h("select", { "aria-label": `Series ${si + 1} marker`, onchange: (e) => { s.marker = e.target.value; refreshIcon(); } },
        SHAPES.map((m) => h("option", { value: m, selected: m === s.marker }, m)));
      const fid = `s-${pi}-${si}-filled`, lid = `s-${pi}-${si}-line`;
      list.appendChild(h("div", { class: "series-row" }, icon, name, meaning, del,
        h("div", { class: "series-extra" }, mSel,
          h("label", { class: "check", for: fid }, h("input", { type: "checkbox", id: fid, checked: s.filled, onchange: (e) => { s.filled = e.target.checked; refreshIcon(); } }), "Filled"),
          h("label", { class: "check", for: lid }, h("input", { type: "checkbox", id: lid, checked: s.line, onchange: (e) => (s.line = e.target.checked) }), "Joined by a line"))));
    });
    return list;
  }

  const extractErr = h("div", { "aria-live": "polite" });
  const probList = h("ul", { class: "small", style: { margin: 0, paddingLeft: "18px", color: "#b91c1c" } });
  const extractBtn = h("button", { type: "button", class: "btn primary big", onclick: () => doExtract(false) }, "Extract points →");

  function renderSide() {
    const active = document.activeElement && document.activeElement.id;
    clear(side);
    const p = st.panels[st.cur];
    const tabs = h("div", { class: "panel-tabs", role: "group", "aria-label": "Panels" },
      st.panels.map((q, i) => h("button", { type: "button", class: `btn pill ${i === st.cur ? "current" : ""}`, "aria-pressed": String(i === st.cur),
        onclick: () => { st.cur = i; drawOverlay(); renderSide(); setTool(st.tool); } }, `Panel ${q.id}`)),
      h("button", { type: "button", class: "btn pill", onclick: () => {
        st.panels.push(panelState({ id: nextPanelId(st) }));
        st.cur = st.panels.length - 1;
        setTool("panel"); drawOverlay(); renderSide();
      } }, "+ Panel"));
    side.appendChild(tabs);
    if (!p) return;

    const idIn = h("input", { id: "panel-id", value: p.id, maxlength: 8, style: { width: "80px" },
      onchange: (e) => { const v = e.target.value.trim(); if (v) { p.id = v; drawOverlay(); renderSide(); } } });
    const pdet = p.det;
    const detLine = !p.bbox ? "Draw the panel box on the page (include axes and tick labels)."
      : p.detErr ? `Tick detection failed: ${p.detErr}`
      : !pdet ? "Looking for ticks…"
      : `x axis: ${pdet.x.error ? "not found" : `${pdet.x.major.length} ticks found`} · y axis: ${pdet.y.error ? "not found" : `${pdet.y.major.length} ticks found`}`;
    side.appendChild(h("fieldset", { class: "box" }, h("legend", {}, `Panel ${p.id}`),
      h("div", { class: "row" },
        h("div", { class: "field" }, h("label", { for: "panel-id" }, "Panel id"), idIn),
        h("span", { class: "spacer" }),
        st.panels.length > 1 || p.bbox ? h("button", { type: "button", class: "btn danger small", onclick: () => {
          st.panels.splice(st.cur, 1);
          if (!st.panels.length) st.panels.push(panelState({ id: "a" }));
          st.cur = Math.max(0, st.cur - 1);
          drawOverlay(); renderSide();
        } }, "Remove panel") : null),
      h("p", { class: "small muted" }, detLine),
      h("details", {}, h("summary", { class: "small" }, "Box coordinates (PDF points)"),
        bboxInput("panel-bbox", "Panel box", p.bbox, (b) => { p.bbox = b; runDetect(st.cur); drawOverlay(); renderSide(); }))));

    side.appendChild(h("fieldset", { class: "box" }, h("legend", {}, "X axis"),
      axisFields("x", p.x, pdet, `${st.cur}.x`, true, "Inverted (values grow leftward)")));
    side.appendChild(h("fieldset", { class: "box" }, h("legend", {}, "Y axis"),
      axisFields("y", p.y, pdet, `${st.cur}.y`, true, "Inverted (values grow downward)")));

    // insets
    if (p.insets.length) {
      const fs = h("fieldset", { class: "box" }, h("legend", {}, "Insets"));
      p.insets.forEach((ins, k) => {
        fs.appendChild(h("div", { class: "inset-block" },
          h("div", { class: "row" }, h("strong", {}, `Inset ${ins.id}`), h("span", { class: "spacer" }),
            h("button", { type: "button", class: "btn danger small", onclick: () => { p.insets.splice(k, 1); runDetect(st.cur); drawOverlay(); renderSide(); } }, "Remove inset")),
          h("p", { class: "small muted" }, "Own axes; tick values of the inset only."),
          axisFields(`ins${k}x`, ins.x, ins.det, `${st.cur}.i${k}.x`, false, "Inverted x"),
          axisFields(`ins${k}y`, ins.y, ins.det, `${st.cur}.i${k}.y`, false, "Inverted y (values grow downward)"),
          h("details", {}, h("summary", { class: "small" }, "Box coordinates (PDF points)"),
            bboxInput(`ins${k}-bbox`, "Inset box", ins.bbox, (b) => { ins.bbox = b; runDetectInset(st.cur, k); runDetect(st.cur); drawOverlay(); renderSide(); }))));
      });
      side.appendChild(fs);
    }

    // series
    const seriesFs = h("fieldset", { class: "box" },
      h("legend", {}, p.legend ? "Series (from legend, top to bottom)" : "Series"),
      p.legend
        ? h("div", { class: "row small" }, h("span", { class: "muted" }, p.legendMsg || "Legend box drawn."), h("span", { class: "spacer" }),
            h("button", { type: "button", class: "btn small", onclick: () => { p.legend = null; p.legendMsg = ""; runDetect(st.cur); drawOverlay(); renderSide(); } }, "Remove legend box"))
        : h("p", { class: "small muted" }, "Draw the legend box to fill this list from the legend, or add series by hand and choose their marker."),
      h("details", {}, h("summary", { class: "small" }, "Legend box coordinates (PDF points)"),
        bboxInput("legend-bbox", "Legend box", p.legend, (b) => { p.legend = b; runLegend(st.cur); runDetect(st.cur); drawOverlay(); renderSide(); })),
      seriesRows(p, st.cur),
      h("button", { type: "button", class: "btn", onclick: () => { p.series.push(seriesState({ marker: "circle" })); renderSide(); side.querySelector(`[data-field="${st.cur}.s${p.series.length - 1}"]`)?.focus(); } }, "+ Add series"));
    side.appendChild(seriesFs);

    side.appendChild(h("div", { class: "extract-bar" }, status, probList, extractErr, extractBtn));
    updateValidity();
    if (active) { const el = document.getElementById(active); if (el) el.focus(); }
  }

  function updateValidity() {
    // per-axis notes for the visible panel
    side.querySelectorAll("[data-note]").forEach((note) => {
      const key = note.dataset.note;
      const [pi, a, b] = key.split(".");
      const p = st.panels[Number(pi)];
      let ax, det;
      if (b) { const ins = p.insets[Number(a.slice(1))]; ax = ins[b]; det = ins.det && ins.det[b]; }
      else { ax = p[a]; det = p.det && p.det[a]; }
      const m = tickMismatch(ax, det);
      note.textContent = m.text;
      note.className = `tick-note ${m.cls}`;
      const field = note.closest(".field");
      field.classList.toggle("bad", m.block);
      field.classList.toggle("good", m.cls === "good");
      const inp = field.querySelector("input");
      if (m.block) inp.setAttribute("aria-invalid", "true"); else inp.removeAttribute("aria-invalid");
    });
    const probs = problems(st);
    clear(probList);
    for (const pr of probs) probList.appendChild(h("li", {}, pr.msg));
    extractBtn.disabled = probs.length > 0;
    extractBtn.title = probs.length ? "Fix the items listed above first" : "";
  }

  async function doExtract(confirm) {
    const probs = problems(st);
    if (probs.length) return;
    clear(extractErr);
    const card = buildCard(st);
    extractBtn.disabled = true;
    const done = busy(status, "Extracting points… this can take a few seconds.");
    try {
      await api.extract(token, num, card, confirm);
      done();
      go(routes.review(token, num));
    } catch (e) {
      done();
      extractBtn.disabled = false;
      if (e.status === 409 && !confirm) {
        const n = e.data.edits ?? "the";
        const ok = await confirmDialog("Discard manual edits?", `This discards ${n} manual edits. Continue?`, "Discard and extract");
        if (ok) doExtract(true);
        return;
      }
      extractErr.appendChild(errorBox(e.message));
      if (e.status === 504) extractErr.appendChild(h("button", { type: "button", class: "btn", onclick: () => doExtract(confirm) }, "Retry"));
    }
  }

  // ----- go
  setTool(st.tool);
  renderSide();
  requestAnimationFrame(() => { fitView(); drawOverlay(); });
  st.panels.forEach((p, i) => { runDetect(i); p.insets.forEach((_, k) => runDetectInset(i, k)); });
  if (card) setHeader({ step: 2, context: `${session.citekey} · Fig. ${num}`, right: h("a", { href: routes.review(token, num) }, "Go to review →") });

  return () => view.destroy();
}
