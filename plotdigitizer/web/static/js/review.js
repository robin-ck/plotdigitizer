// Screen 3: review extracted points next to the original, edit, validate.
// Values always come from the server; edits send positions (pt) or typed values.

import { api } from "./api.js";
import { h, clear, fmt, fmtDateTime, errorBox, setHeader, modal } from "./ui.js";
import { SvgView, svgEl, dragFrom, pageImage, zoomControls, inBox, normBox, isTyping, isSpaceDown } from "./svgview.js";
import { markerEl, markerIcon, seriesColor } from "./markers.js";
import { routes } from "./router.js";

const UNASSIGNED = "nicht zuordenbar";

// ---------------------------------------------------------------- check text

function where(d) {
  const parts = [];
  if (d.panel) parts.push(`Panel ${d.panel}`);
  const blk = d.block || d.inset;
  if (blk && blk !== "main") parts.push(String(blk).replace("inset:", "inset "));
  if (d.series) parts.push(`series “${d.series}”`);
  return parts.length ? `${parts.join(", ")}: ` : "";
}

export function checkText(c) {
  const d = c.detail || {};
  const w = where(d);
  switch (c.check) {
    case "marker_count":
      return `${w}${d.points} points extracted, but ${d.markers} markers found in the drawing.`;
    case "all_assigned":
      return `${w}${d.unassigned} point(s) could not be assigned to a series.`;
    case "expected_count":
      return `${w}expected ${d.expected} points, found ${d.got}.`;
    case "marker_on_polyline_vertex":
      return `${w}markers lie off the line vertices (median ${fmt(d.median_pt)} pt, max ${fmt(d.max_pt)} pt over ${d.n} points). Series may be mixed up.`;
    case "inset_main_agreement":
      return `${w}${(d.mismatches || []).length} of ${d.merged} inset points disagree with the main panel.`;
    case "within_axis_range": {
      const o = (d.outside || []).slice(0, 3).map((p) => `${p.series} (${fmt(p.x)}, ${fmt(p.y)})`).join("; ");
      return `${w}${(d.outside || []).length} point(s) outside the axis range${o ? `: ${o}` : ""}.`;
    }
    case "no_duplicates":
      return `${w}${(d.duplicates || []).length} duplicate point(s) at the same position.`;
    case "text_check":
      if (d.note === "no points selected") return `Text claim “${d.claim}”: no points match the claim's selection.`;
      return `Text claim “${d.claim}” not matched: observed ${fmt(d.observed?.[0])}–${fmt(d.observed?.[1])}, expected ${fmt(d.expected?.[0])}–${fmt(d.expected?.[1])}.`;
    default:
      return `${w}${c.check.replace(/_/g, " ")} ${JSON.stringify(d).slice(0, 200)}`;
  }
}

// ---------------------------------------------------------------- screen

export async function render(app, { token, num, query }) {
  const [session, first] = await Promise.all([api.session(token), api.review(token, num)]);
  const st = {
    rv: first,
    pid: query.panel && first.panels.some((p) => p.id === query.panel) ? query.panel : first.panels[0]?.id,
    sel: new Set(), primary: null, tool: "move", undo: [], busy: false, drag: null, box: null,
  };
  const pageSize = session.page_sizes[first.page_pdf - 1] || [612, 792];

  // ----- layout
  const tabs = h("div", { class: "panel-tabs", role: "tablist", "aria-label": "Panels" });
  const toolBtn = {};
  const mkTool = (t, label) => (toolBtn[t] = h("button", { type: "button", class: "btn", "aria-pressed": "false", onclick: () => setTool(t) }, label));
  const seriesSel = h("select", { class: "text", style: { width: "auto" }, "aria-label": "Series for new points", onchange: () => setTool("add") });
  const undoBtn = h("button", { type: "button", class: "btn", onclick: undo, title: "Undo (Ctrl+Z)" }, "Undo");
  const delBtn = mkTool("delete", "Delete point");
  const delSelBtn = h("button", { type: "button", class: "btn danger", onclick: () => deletePoints([...st.sel]), title: "Delete selected points (Del)" }, "Delete selected");
  const toolbar = h("div", { class: "toolbar", role: "toolbar", "aria-label": "Point tools" },
    mkTool("move", "Move"), mkTool("select", "Box select"), mkTool("add", "Add point"), seriesSel, delBtn, delSelBtn, undoBtn,
    h("span", { class: "spacer" }));
  const status = h("p", { class: "status", "aria-live": "polite" });
  const errSlot = h("div", { "aria-live": "assertive" });

  const svgL = svgEl("svg", { role: "img", "aria-label": "Original plot from the PDF (read-only)" });
  const svgR = svgEl("svg", { role: "img", "aria-label": "Extracted points re-plotted on the same axes (editable)" });
  const viewsEl = h("div", { class: "views" },
    h("div", { class: "view-card" }, h("div", { class: "view-head" }, h("h2", { class: "small", style: { fontSize: "13px" } }, "Original (PDF)"), h("span", { class: "tag" }, "read-only")), h("div", { class: "stage" }, svgL)),
    h("div", { class: "view-card" }, h("div", { class: "view-head" }, h("h2", { class: "small", style: { fontSize: "13px" } }, "Detected (re-plotted from extracted values)"), h("span", { class: "tag edit" }, "editable")), h("div", { class: "stage" }, svgR)));
  const legendRow = h("div", { class: "legend-row" });
  const side = h("aside", { class: "side narrow", "aria-label": "Checks and points" });

  app.appendChild(h("div", { class: "workspace" },
    h("section", { class: "canvas-col", "aria-label": "Plots" },
      h("h1", { class: "visually-hidden" }, `Review figure ${num}`),
      h("div", { class: "row" }, tabs, h("span", { class: "spacer" }), h("a", { href: routes.setup(token, num), class: "btn" }, "← Back to set-up")),
      toolbar, status, errSlot, viewsEl, legendRow),
    side));

  // ----- views
  const isBg = (e, svg) => e.target === svg || e.target.dataset.bg !== undefined;
  // background drag pans, except when adding or box-selecting (Box select tool, or Shift+drag)
  const boxMode = (e) => st.tool === "select" || (st.tool === "move" && e.shiftKey);
  const viewL = new SvgView(svgL, { bounds: [0, 0, pageSize[0], pageSize[1]], isPanTarget: (e) => st.tool !== "add" && !boxMode(e) && isBg(e, svgL) });
  const viewR = new SvgView(svgR, { bounds: [0, 0, pageSize[0], pageSize[1]], isPanTarget: (e) => st.tool !== "add" && !boxMode(e) && isBg(e, svgR) });
  viewL.link(viewR);
  svgEl("rect", { x: -5000, y: -5000, width: 10000, height: 10000, fill: "#fff", "data-bg": "" }, svgL);
  pageImage(svgL, viewL, (z) => api.pageUrl(token, first.page_pdf, z), pageSize);
  svgEl("rect", { x: -5000, y: -5000, width: 10000, height: 10000, fill: "#fff", "data-bg": "" }, svgR);
  const layer = {
    L: svgEl("g", {}, svgL), R: svgEl("g", {}, svgR),
    selL: svgEl("g", { style: "pointer-events:none" }, svgL), selR: svgEl("g", { style: "pointer-events:none" }, svgR),
  };
  toolbar.appendChild(zoomControls(viewL, () => fitPanel()));
  toolbar.appendChild(h("span", { class: "small muted" }, "Both views zoom and pan together"));
  let lastScale = 0;
  viewL.onChange(() => {
    const s = viewL.scale();
    if (Math.abs(s - lastScale) / (lastScale || 1) > 0.05) { lastScale = s; drawPoints(); }
    drawSelection();
  });

  const panel = () => st.rv.panels.find((p) => p.id === st.pid);
  function fitPanel() {
    const p = panel();
    if (p && p.clip) viewL.fit(p.clip, 14);
  }

  // series -> colour/shape
  function seriesInfo(p) {
    const labels = [];
    for (const s of p.series || []) if (!labels.includes(s.label)) labels.push(s.label);
    for (const s of p.signatures || []) if (!labels.includes(s.label)) labels.push(s.label);
    for (const b of Object.values(p.blocks)) for (const q of b.points) if (!labels.includes(q.series)) labels.push(q.series);
    const sig = Object.fromEntries((p.signatures || []).map((s) => [s.label, s]));
    const info = {};
    labels.forEach((l, i) => {
      info[l] = { color: l === UNASSIGNED ? "#52606d" : seriesColor(i), shape: sig[l]?.shape || "circle", filled: sig[l]?.filled ?? true, size: sig[l]?.size, index: i,
        meaning: (p.series || []).find((s) => s.label === l)?.meaning || "" };
    });
    return info;
  }

  function allPoints(p) {
    const out = [];
    for (const [key, b] of Object.entries(p.blocks)) for (const q of b.points) out.push({ ...q, block: key });
    return out;
  }
  const findPoint = (id) => { const p = panel(); return p ? allPoints(p).find((q) => q.id === id) : null; };

  // ----- re-plot (axes, ticks, grid)
  function drawReplot(p) {
    const g = svgEl("g", { "aria-hidden": "true" }, layer.R);
    for (const [key, b] of Object.entries(p.blocks)) {
      const main = key === "main";
      const fs = main ? 8 : 6;
      const tl = main ? 4 : 3;
      const ex = b.axis_extent?.x || [b.bbox[0], b.bbox[2]];
      const ey = b.axis_extent?.y || [b.bbox[1], b.bbox[3]];
      const ax = b.axis_coord?.x ?? Math.max(...ey);
      const ay = b.axis_coord?.y ?? Math.min(...ex);
      const cx = b.calibration.x, cy = b.calibration.y;
      const top = ax < (b.bbox[1] + b.bbox[3]) / 2;
      const right = ay > (b.bbox[0] + b.bbox[2]) / 2;
      if (!main) svgEl("rect", { x: b.bbox[0], y: b.bbox[1], width: b.bbox[2] - b.bbox[0], height: b.bbox[3] - b.bbox[1], fill: "#fbfcfd", stroke: "#e3e6ea", "vector-effect": "non-scaling-stroke" }, g);
      for (const x of cx.positions) svgEl("line", { class: "rp-grid", x1: x, x2: x, y1: ey[0], y2: ey[1] }, g);
      for (const y of cy.positions) svgEl("line", { class: "rp-grid", y1: y, y2: y, x1: ex[0], x2: ex[1] }, g);
      svgEl("line", { class: "rp-axis", x1: ex[0], x2: ex[1], y1: ax, y2: ax }, g);
      svgEl("line", { class: "rp-axis", y1: ey[0], y2: ey[1], x1: ay, x2: ay }, g);
      cx.positions.forEach((x, i) => {
        const d = top ? -tl : tl;
        svgEl("line", { class: "rp-axis", x1: x, x2: x, y1: ax, y2: ax + d }, g);
        const t = svgEl("text", { class: "rp-label", x, y: top ? ax - tl - 2 : ax + tl + fs, "font-size": fs, "text-anchor": "middle" }, g);
        t.textContent = fmt(cx.values[i]);
      });
      cy.positions.forEach((y, i) => {
        const d = right ? tl : -tl;
        svgEl("line", { class: "rp-axis", y1: y, y2: y, x1: ay, x2: ay + d }, g);
        const t = svgEl("text", { class: "rp-label", x: right ? ay + tl + 2 : ay - tl - 2, y: y + fs * 0.35, "font-size": fs, "text-anchor": right ? "start" : "end" }, g);
        t.textContent = fmt(cy.values[i]);
      });
      if (main) {
        const xt = [p.x?.title, p.x?.unit ? `(${p.x.unit})` : ""].filter(Boolean).join(" ");
        const yt = [p.y?.title, p.y?.unit ? `(${p.y.unit})` : ""].filter(Boolean).join(" ");
        const mx = (ex[0] + ex[1]) / 2, my = (ey[0] + ey[1]) / 2;
        if (xt) {
          const t = svgEl("text", { class: "rp-label", x: mx, y: top ? ax - tl - fs * 2.2 : ax + tl + fs * 2.6, "font-size": fs * 1.1, "text-anchor": "middle" }, g);
          t.textContent = xt;
        }
        if (yt) {
          const maxLen = Math.max(1, ...cy.values.map((v) => fmt(v).length));
          const off = tl + 2 + maxLen * fs * 0.6 + fs * 0.9;
          const tx = right ? ay + off : ay - off;
          const t = svgEl("text", { class: "rp-label", x: tx, y: my, "font-size": fs * 1.1, "text-anchor": "middle", transform: `rotate(-90 ${tx} ${my})` }, g);
          t.textContent = yt;
        }
      }
    }
  }

  // ----- points
  function markerR(q, info) {
    const s = info[q.series]?.size;
    const base = q.block === "main" ? 3 : 2.2;
    return s ? Math.max(base, Math.min(6, s / 2 * 1.4)) : base;
  }

  function drawPoints() {
    const p = panel();
    clear(layer.L); clear(layer.R);
    if (!p) return;
    drawReplot(p);
    const info = seriesInfo(p);
    const sc = viewL.scale() || 1;
    const hitR = 7 / sc; // >= 14px target diameter even when zoomed out
    const gR = svgEl("g", {}, layer.R);
    for (const q of allPoints(p)) {
      const inf = info[q.series] || { color: "#333", shape: "circle", filled: true };
      const r = markerR(q, info);
      const gr = svgEl("g", { class: "pt", "data-id": q.id }, gR);
      gr.appendChild(markerEl(q.shape || inf.shape, q.px, q.py, r, { color: inf.color, filled: q.filled ?? inf.filled, strokeWidth: r * 0.4 }));
      svgEl("circle", { class: "pt-hit", cx: q.px, cy: q.py, r: Math.max(r, hitR) }, gr);
      // left: invisible targets on the original markers
      const gl = svgEl("g", { class: "pt", "data-id": q.id }, layer.L);
      svgEl("circle", { class: "pt-hit", cx: q.px, cy: q.py, r: Math.max(r, hitR) }, gl);
      for (const [g, view] of [[gr, viewR], [gl, viewL]]) {
        const title = svgEl("title", {}, g);
        title.textContent = `${q.series}: ${fmt(q.x_value)}, ${fmt(q.y_value)}`;
        g.addEventListener("pointerdown", (e) => pointDown(e, q, view));
      }
    }
    drawSelection();
  }

  function drawSelection() {
    clear(layer.selL); clear(layer.selR);
    const p = panel();
    if (!p) return;
    const sc = viewL.scale() || 1;
    const info = seriesInfo(p);
    const off = st.drag ? st.drag.delta : [0, 0];
    // rings on every selected point
    for (const id of st.sel) {
      const q = findPoint(id);
      if (!q) continue;
      const pos = [q.px + off[0], q.py + off[1]];
      for (const g of [layer.selL, layer.selR]) svgEl("circle", { class: "sel-ring", cx: pos[0], cy: pos[1], r: 9 / sc }, g);
      if (st.drag) svgEl("circle", { cx: pos[0], cy: pos[1], r: markerR(q, info), fill: "none", stroke: info[q.series]?.color || "#333", "stroke-width": 2, "vector-effect": "non-scaling-stroke" }, layer.selR);
    }
    // crosshair + value label on the primary point
    const q = st.primary && st.sel.has(st.primary) && findPoint(st.primary);
    if (q) {
      const b = p.blocks[q.block];
      const pos = [q.px + off[0], q.py + off[1]];
      const ex = b.axis_extent?.x || [b.bbox[0], b.bbox[2]], ey = b.axis_extent?.y || [b.bbox[1], b.bbox[3]];
      for (const [g, isR] of [[layer.selL, false], [layer.selR, true]]) {
        svgEl("line", { class: "crosshair", x1: pos[0], x2: pos[0], y1: Math.min(...ey), y2: Math.max(...ey) }, g);
        svgEl("line", { class: "crosshair", y1: pos[1], y2: pos[1], x1: Math.min(...ex), x2: Math.max(...ex) }, g);
        if (isR && !st.drag && st.sel.size === 1) {
          const fs = 12 / sc;
          const txt = `${q.series} · ${fmt(q.x_value)}, ${fmt(q.y_value)}${p.y?.unit ? ` ${p.y.unit}` : ""}`;
          const w = txt.length * fs * 0.56 + 12 / sc;
          const x = pos[0] + 14 / sc, y = pos[1] - 30 / sc;
          svgEl("rect", { x, y, width: w, height: 22 / sc, rx: 4 / sc, fill: "#1f2933" }, g);
          const t = svgEl("text", { x: x + 6 / sc, y: y + 15 / sc, "font-size": fs, fill: "#fff", "font-family": "Inter, system-ui, sans-serif" }, g);
          t.textContent = txt;
        }
      }
    }
    // selection rectangle while box-selecting
    if (st.box) {
      const [x0, y0, x1, y1] = normBox(st.box[0], st.box[1]);
      for (const g of [layer.selL, layer.selR]) svgEl("rect", { class: "sel-box", x: x0, y: y0, width: x1 - x0, height: y1 - y0 }, g);
    }
  }

  /**
   * Change the selection. mode: "replace" (default), "toggle" or "add".
   * `ids` may be a single id, an array, or null (clear).
   */
  function select(ids, { mode = "replace", scroll = true, reveal = false } = {}) {
    const list = ids == null ? [] : Array.isArray(ids) ? ids : [ids];
    if (mode === "replace") st.sel = new Set(list);
    else for (const id of list) {
      if (mode === "toggle" && st.sel.has(id)) st.sel.delete(id);
      else st.sel.add(id);
    }
    const last = list[list.length - 1];
    st.primary = last && st.sel.has(last) ? last : st.sel.has(st.primary) ? st.primary : [...st.sel].pop() || null;
    drawSelection();
    side.querySelectorAll("tr[data-id]").forEach((tr) => {
      const on = st.sel.has(tr.dataset.id);
      tr.classList.toggle("selected", on);
      tr.setAttribute("aria-selected", String(on));
      if (scroll && tr.dataset.id === st.primary) tr.scrollIntoView({ block: "nearest" });
    });
    updateTools();
    if (reveal && st.primary) {
      const q = findPoint(st.primary);
      const vb = viewL.vb;
      if (q && !inBox([q.px, q.py], [vb.x, vb.y, vb.x + vb.w, vb.y + vb.h])) viewL.setViewBox({ ...vb, x: q.px - vb.w / 2, y: q.py - vb.h / 2 });
    }
  }
  const multiKey = (e) => e.shiftKey || e.ctrlKey || e.metaKey;

  function pointDown(e, q, view) {
    if (e.button !== 0 || e.defaultPrevented) return;
    if (st.tool === "add") return; // handled by the svg listener (adds at the click)
    e.preventDefault();
    e.stopPropagation();
    if (st.tool === "delete") {
      deletePoints([q.id]);
      return;
    }
    if (multiKey(e)) { select(q.id, { mode: "toggle" }); return; }
    // clicking a point that is already part of a multi-selection drags the whole group
    if (!st.sel.has(q.id)) select(q.id);
    else { st.primary = q.id; drawSelection(); }
    if (st.tool === "select") return;
    const ids = [...st.sel];
    dragFrom(e, view, (pt, s0) => {
      st.drag = { delta: [pt[0] - s0[0], pt[1] - s0[1]] };
      drawSelection();
    }, (pt, s0, moved) => {
      st.drag = null;
      if (!moved) { select(q.id); return; }
      const p = panel();
      const d = [pt[0] - s0[0], pt[1] - s0[1]];
      const pts = ids.map(findPoint).filter(Boolean);
      sendEdits(pts.map((r) => ({ op: "move", panel: p.id, id: r.id, pt: [round3(r.px + d[0]), round3(r.py + d[1])] })),
        pts.map((r) => ({ op: "move", panel: p.id, id: r.id, pt: [r.px, r.py] })), pts.length > 1 ? `Move ${pts.length} points` : "Move");
    });
  }

  function boxSelect(e, view) {
    const additive = multiKey(e);
    dragFrom(e, view, (pt, s0) => {
      st.box = [s0, pt];
      drawSelection();
    }, (pt, s0, moved) => {
      st.box = null;
      if (!moved) { if (!additive) select(null); else drawSelection(); return; }
      const b = normBox(s0, pt);
      const ids = allPoints(panel()).filter((q) => inBox([q.px, q.py], b)).map((q) => q.id);
      select(ids, { mode: additive ? "add" : "replace" });
      status.textContent = `${st.sel.size} point${st.sel.size === 1 ? "" : "s"} selected.`;
    });
  }

  for (const [svg, view] of [[svgL, viewL], [svgR, viewR]]) {
    svg.addEventListener("pointerdown", (e) => {
      if (e.defaultPrevented || e.button !== 0 || isSpaceDown()) return;
      if (st.tool === "add") dragFrom(e, view, null, (pt, s0, moved) => { if (!moved) addPoint(pt); });
      else if (boxMode(e) && isBg(e, svg)) boxSelect(e, view);
    });
  }

  // ----- edits
  const round3 = (v) => Math.round(v * 1000) / 1000;

  function blockAt(p, pt) {
    for (const [key, b] of Object.entries(p.blocks)) if (key !== "main" && inBox(pt, b.bbox)) return key;
    return "main";
  }

  function addPoint(pt) {
    const p = panel();
    const series = seriesSel.value;
    if (!series) { showError("Choose the series for the new point first."); return; }
    const block = blockAt(p, pt);
    sendEdits([{ op: "add", panel: p.id, block, series, pt: [round3(pt[0]), round3(pt[1])] }], null, "Add");
  }

  function deletePoints(ids) {
    const p = panel();
    const pts = ids.map(findPoint).filter(Boolean);
    if (!pts.length) return;
    sendEdits(pts.map((q) => ({ op: "delete", panel: p.id, id: q.id })),
      pts.map((q) => ({ op: "add", panel: p.id, block: q.block, series: q.series, pt: [q.px, q.py], _replaces: q.id })),
      pts.length > 1 ? `Delete ${pts.length} points` : "Delete");
  }

  function showError(msg) {
    clear(errSlot);
    if (msg) errSlot.appendChild(errorBox(msg));
  }

  /**
   * Send edits; `inverse` (list) is pushed to the undo stack. For an add,
   * the inverse (delete of the new id) is built from the response.
   */
  async function sendEdits(edits, inverse, label, { isUndo = false } = {}) {
    if (st.busy) return null;
    st.busy = true;
    showError("");
    status.textContent = `${label}…`;
    const wire = edits.map(({ _replaces, ...e }) => e);
    try {
      const res = await api.edits(token, num, wire);
      const applied = res.applied || [];
      if (!isUndo) {
        const inv = inverse ? inverse : applied.filter((a) => a.op === "add").map((a) => ({ op: "delete", panel: edits[0].panel, id: a.id }));
        st.undo.push({ label, ops: inv });
      }
      // re-added points get a new id: rewrite older undo entries
      edits.forEach((e, i) => {
        if (e.op === "add" && e._replaces && applied[i]) remapId(e._replaces, applied[i].id);
      });
      st.rv = res;
      const added = applied.filter((a) => a.op === "add").map((a) => a.id);
      if (added.length) st.sel = new Set(added);
      else st.sel = new Set([...st.sel].filter((id) => findPoint(id)));
      if (!st.sel.has(st.primary)) st.primary = [...st.sel].pop() || null;
      status.textContent = `${label} saved.${res.validation ? "" : wasValidated ? " Validation cleared by the edit." : ""}`;
      wasValidated = !!(res.validation && res.validation.validated);
      renderAll();
      return res;
    } catch (e) {
      status.textContent = "";
      showError(e.message);
      drawPoints();
      return null;
    } finally {
      st.busy = false;
      updateTools();
    }
  }

  function remapId(oldId, newId) {
    for (const entry of st.undo) for (const op of entry.ops) {
      if (op.id === oldId) op.id = newId;
      if (op._replaces === oldId) op._replaces = newId;
    }
    if (st.sel.has(oldId)) { st.sel.delete(oldId); st.sel.add(newId); }
    if (st.primary === oldId) st.primary = newId;
  }

  async function undo() {
    const entry = st.undo.pop();
    if (!entry) return;
    const res = await sendEdits(entry.ops, null, `Undo ${entry.label.toLowerCase()}`, { isUndo: true });
    if (!res) st.undo.push(entry);
    updateTools();
  }

  let wasValidated = !!(first.validation && first.validation.validated);

  // ----- tools
  function setTool(t) {
    st.tool = t;
    document.body.dataset.tool = t;
    for (const [k, b] of Object.entries(toolBtn)) b.setAttribute("aria-pressed", String(k === t));
    status.textContent = { move: "Move: drag a point (in either view) to its correct position. Shift/Ctrl+click adds to the selection, Shift+drag on empty space selects a box; dragging a selected point moves the whole selection.",
      select: "Box select: drag a box around points. Shift/Ctrl adds to the selection. Ctrl+A selects all, Del deletes the selection.",
      add: `Add point: click where a missing marker is (repeat for more). Series: ${seriesSel.value || "–"}.`,
      delete: "Delete: click a wrong point to remove it." }[t];
  }
  function updateTools() {
    undoBtn.disabled = !st.undo.length || st.busy;
    undoBtn.textContent = st.undo.length ? `Undo (${st.undo.length})` : "Undo";
    delSelBtn.disabled = !st.sel.size || st.busy;
    delSelBtn.textContent = st.sel.size ? `Delete selected (${st.sel.size})` : "Delete selected";
  }

  const onKey = (e) => {
    if (isTyping(e.target) || document.querySelector("dialog[open]")) return;
    if ((e.key === "Delete" || e.key === "Backspace") && st.sel.size) { e.preventDefault(); deletePoints([...st.sel]); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a" && panel()) { e.preventDefault(); select(allPoints(panel()).map((q) => q.id), { scroll: false }); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
    else if (e.key === "Escape") select(null);
  };
  document.addEventListener("keydown", onKey);

  // ----- panel tabs
  async function showPanel(pid, { fit = true } = {}) {
    st.pid = pid;
    st.sel = new Set(); st.primary = null;
    history.replaceState(null, "", routes.review(token, num, pid));
    renderTabs();
    const p = panel();
    clear(seriesSel);
    const info = seriesInfo(p);
    for (const l of Object.keys(info)) if (l !== UNASSIGNED) seriesSel.appendChild(h("option", { value: l }, l));
    if (fit) fitPanel();
    renderAll();
    setHeader({ step: 3, context: `${session.citekey} · Fig. ${num} · Panel ${pid}`, right: h("a", { href: routes.session(token) }, "All figures") });
    if (!st.rv.reviewed_panels.includes(pid)) {
      try {
        const r = await api.reviewed(token, num, pid);
        st.rv.reviewed_panels = r.reviewed_panels;
        renderSide();
      } catch (e) { showError(e.message); }
    }
  }

  function renderTabs() {
    clear(tabs);
    if (st.rv.panels.length < 2) { tabs.appendChild(h("span", { class: "small muted" }, `Panel ${st.pid}`)); return; }
    for (const p of st.rv.panels) {
      const on = p.id === st.pid;
      tabs.appendChild(h("button", { type: "button", role: "tab", "aria-selected": String(on), class: `btn pill ${on ? "current" : ""}`,
        onclick: () => showPanel(p.id) }, `Panel ${p.id}`, st.rv.reviewed_panels.includes(p.id) ? h("span", { "aria-label": " (reviewed)" }, " ✓") : null));
    }
  }

  // ----- side column
  function renderSide() {
    const active = document.activeElement;
    const activeKey = active && active.dataset && active.dataset.key;
    clear(side);
    const rv = st.rv;
    const p = panel();
    if (rv.validation && rv.validation.validated) {
      side.appendChild(h("div", { class: "banner-validated", role: "status" },
        h("strong", {}, "✓ Validated"), ` on ${fmtDateTime(rv.validation.at)}. Any edit clears the validation.`));
    }
    // checks
    const failing = rv.checks.filter((c) => !c.ok && (c.level === "warning" || c.level === "error"))
      .filter((c) => !c.detail?.panel || c.detail.panel === st.pid);
    const otherPanels = rv.checks.filter((c) => !c.ok && (c.level === "warning" || c.level === "error") && c.detail?.panel && c.detail.panel !== st.pid).length;
    const checksEl = h("section", { class: "checks", "aria-label": "Checks" },
      h("h2", { style: { fontSize: "17px" } }, failing.length ? `${failing.length} check${failing.length > 1 ? "s" : ""} need${failing.length > 1 ? "" : "s"} attention` : "All checks pass"),
      failing.map((c) => h("div", { class: `check-item ${c.level}` }, h("span", { class: "lvl" }, c.level === "error" ? "Error" : "Warning"), checkText(c))),
      otherPanels ? h("p", { class: "small muted" }, `${otherPanels} more in other panels.`) : null);
    side.appendChild(checksEl);

    // points table
    const pts = allPoints(p);
    const info = seriesInfo(p);
    pts.sort((a, b) => (info[a.series]?.index ?? 99) - (info[b.series]?.index ?? 99));
    const xName = p.x?.title || "x", yName = p.y?.title || "y";
    const tbody = h("tbody");
    for (const q of pts) {
      // raster matches: confidence from the template match score (gut / mittel / gering)
      const weak = { mittel: "extracted (fair match)", gering: "check: weak match" }[q.confidence];
      const st_ = q.edited || weak || "extracted";
      const xi = h("input", { value: fmt(q.x_value), "aria-label": `${xName} value of ${q.series} point ${q.id}`, inputmode: "decimal", "data-key": `${q.id}:x` });
      const yi = h("input", { value: fmt(q.y_value), "aria-label": `${yName} value of ${q.series} point ${q.id}`, inputmode: "decimal", "data-key": `${q.id}:y` });
      const commit = (e) => {
        if (e.key === "Escape") { xi.value = fmt(q.x_value); yi.value = fmt(q.y_value); e.target.blur(); return; }
        if (e.key !== "Enter") return;
        e.preventDefault();
        const xv = Number(xi.value.replace("−", "-")), yv = Number(yi.value.replace("−", "-"));
        if (!Number.isFinite(xv) || !Number.isFinite(yv)) { showError("Enter numbers for both values."); return; }
        if (!st.sel.has(q.id) || st.sel.size > 1) select(q.id, { scroll: false });
        sendEdits([{ op: "set", panel: p.id, id: q.id, value: [xv, yv] }], [{ op: "move", panel: p.id, id: q.id, pt: [q.px, q.py] }], "Edit value");
      };
      xi.addEventListener("keydown", commit);
      yi.addEventListener("keydown", commit);
      const focusSel = () => { if (!st.sel.has(q.id)) select(q.id, { scroll: false, reveal: true }); };
      xi.addEventListener("focus", focusSel);
      yi.addEventListener("focus", focusSel);
      const inf = info[q.series] || {};
      const on = st.sel.has(q.id);
      tbody.appendChild(h("tr", { "data-id": q.id, class: on ? "selected" : "", "aria-selected": String(on),
        onclick: (e) => {
          if (e.target.tagName === "INPUT") return;
          // Shift: range from the last selected row; Ctrl/Cmd: toggle one row
          if (e.shiftKey && st.primary) {
            const ids = pts.map((r) => r.id);
            const i0 = ids.indexOf(st.primary), i1 = ids.indexOf(q.id);
            if (i0 >= 0) { const r = ids.slice(Math.min(i0, i1), Math.max(i0, i1) + 1); if (i1 < i0) r.reverse(); select(r, { mode: "add", scroll: false }); return; }
          }
          select(q.id, { mode: e.ctrlKey || e.metaKey ? "toggle" : "replace", scroll: false, reveal: true });
        } },
        h("td", { title: inf.meaning || "" }, h("span", { class: "series-cell" }, markerIcon(q.shape || inf.shape, q.filled ?? inf.filled, inf.color, 14), q.series,
          q.block !== "main" ? h("span", { class: "muted" }, ` (${q.block.replace("inset:", "inset ")})`) : null)),
        h("td", { class: "num" }, xi), h("td", { class: "num" }, yi),
        h("td", { class: q.edited ? `st-${q.edited}` : weak ? `st-${q.confidence === "gering" ? "weak" : "fair"}` : "st-extracted" }, st_)));
    }
    side.appendChild(h("h2", { style: { fontSize: "17px" } }, `Points (${pts.length})`));
    side.appendChild(h("p", { class: "small muted" }, "Click a row to select the point; Shift+click selects a range, Ctrl+click adds single rows. Type a value and press Enter to move it."));
    side.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "points" },
      h("caption", { class: "visually-hidden" }, `Points of panel ${p.id}`),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Series"),
        h("th", { scope: "col" }, xName), h("th", { scope: "col" }, yName), h("th", { scope: "col" }, "Status"))),
      tbody)));

    // actions
    const allReviewed = rv.panels.every((x) => rv.reviewed_panels.includes(x.id));
    const valBtn = h("button", { type: "button", class: "btn success big", disabled: !allReviewed, onclick: () => validate() },
      rv.validation && rv.validation.validated ? "Validated ✓" : "Mark validated ✓");
    side.appendChild(h("div", { class: "actions-row" },
      h("a", { class: "btn big", href: api.csvUrl(token, num), download: "" }, "Download CSV"), valBtn));
    const missing = rv.panels.filter((x) => !rv.reviewed_panels.includes(x.id)).map((x) => x.id);
    side.appendChild(h("p", { class: "small muted" },
      missing.length ? `Open panel${missing.length > 1 ? "s" : ""} ${missing.join(", ")} before validating. ` : "",
      h("a", { href: api.csvUrl(token, num, true), download: "" }, "Spreadsheet CSV (one row per point)"),
      ` · ${rv.n_edits || 0} manual edit${rv.n_edits === 1 ? "" : "s"}`));
    if (activeKey) side.querySelector(`[data-key="${CSS.escape(activeKey)}"]`)?.focus();
  }

  async function validate(reasons) {
    showError("");
    try {
      const res = await api.validate(token, num, reasons);
      st.rv = res;
      wasValidated = true;
      status.textContent = "Figure validated.";
      renderAll();
    } catch (e) {
      if (e.status === 422 && Array.isArray(e.data.lacking)) {
        const r = await askReasons(e.data.lacking, reasons || {});
        if (r) validate(r);
      } else showError(e.message);
    }
  }

  function askReasons(lacking, prev) {
    const byId = Object.fromEntries(st.rv.checks.map((c) => [c.id, c]));
    const body = h("div", { style: { display: "flex", flexDirection: "column", gap: "14px" } },
      h("p", {}, "These checks fail. Give a short reason for each (it is stored with the validation)."));
    lacking.forEach((id, i) => {
      const c = byId[id];
      body.appendChild(h("div", { class: "field" },
        h("label", { for: `reason-${i}` }, c ? checkText(c) : id),
        h("textarea", { id: `reason-${i}`, name: id, rows: 2, required: true, value: prev[id] || "" })));
    });
    return modal("Reasons for failing checks", body, [
      { label: "Cancel", value: null },
      { label: "Validate", primary: true, submit: true, value: (form) => {
        const out = { ...prev };
        form.querySelectorAll("textarea").forEach((t) => (out[t.name] = t.value.trim()));
        return out;
      } },
    ]);
  }

  // ----- legend under the views
  function renderLegend() {
    clear(legendRow);
    const p = panel();
    const info = seriesInfo(p);
    const counts = {};
    for (const q of allPoints(p)) counts[q.series] = (counts[q.series] || 0) + 1;
    for (const [l, inf] of Object.entries(info)) {
      if (!counts[l] && l === UNASSIGNED) continue;
      legendRow.appendChild(h("span", { title: inf.meaning }, markerIcon(inf.shape, inf.filled, inf.color, 14), `${l} (${counts[l] || 0})`));
    }
    legendRow.appendChild(h("span", {}, "Selecting points on either side highlights them on both. Del removes the selection."));
  }

  function renderAll() {
    renderTabs();
    drawPoints();
    renderSide();
    renderLegend();
    updateTools();
  }

  setTool("move");
  requestAnimationFrame(() => showPanel(st.pid));

  return () => {
    document.removeEventListener("keydown", onKey);
    delete document.body.dataset.tool;
    viewL.destroy(); viewR.destroy();
  };
}
