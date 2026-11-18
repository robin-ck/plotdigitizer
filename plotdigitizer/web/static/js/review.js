// Screen 3: review extracted points next to the original, edit, validate.
// Values always come from the server; edits send positions (pt) or typed values.

import { api } from "./api.js";
import { h, clear, fmt, fmtDateTime, errorBox, setHeader, modal } from "./ui.js";
import { SvgView, svgEl, dragFrom, pageImage, zoomControls, inBox, isTyping } from "./svgview.js";
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
    sel: null, tool: "move", undo: [], busy: false, drag: null,
  };
  const pageSize = session.page_sizes[first.page_pdf - 1] || [612, 792];

  // ----- layout
  const tabs = h("div", { class: "panel-tabs", role: "tablist", "aria-label": "Panels" });
  const toolBtn = {};
  const mkTool = (t, label) => (toolBtn[t] = h("button", { type: "button", class: "btn", "aria-pressed": "false", onclick: () => setTool(t) }, label));
  const seriesSel = h("select", { class: "text", style: { width: "auto" }, "aria-label": "Series for new points", onchange: () => setTool("add") });
  const undoBtn = h("button", { type: "button", class: "btn", onclick: undo, title: "Undo (Ctrl+Z)" }, "Undo");
  const delBtn = mkTool("delete", "Delete");
  const toolbar = h("div", { class: "toolbar", role: "toolbar", "aria-label": "Point tools" },
    mkTool("move", "Move"), mkTool("add", "Add point"), seriesSel, delBtn, undoBtn,
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
  const viewL = new SvgView(svgL, { bounds: [0, 0, pageSize[0], pageSize[1]], isPanTarget: (e) => st.tool !== "add" && isBg(e, svgL) });
  const viewR = new SvgView(svgR, { bounds: [0, 0, pageSize[0], pageSize[1]], isPanTarget: (e) => st.tool !== "add" && isBg(e, svgR) });
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
    if (p && p.clip) viewL.fit(p.clip, 0);
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
          const tx = right ? ay + tl + fs * 3.6 : ay - tl - fs * 3.2;
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
    return s ? Math.max(base * 0.8, Math.min(6, s / 2 * 1.15)) : base;
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
    const q = st.sel && findPoint(st.sel);
    if (!p || !q) return;
    const b = p.blocks[q.block];
    const pos = st.drag && st.drag.id === q.id ? st.drag.pt : [q.px, q.py];
    const ex = b.axis_extent?.x || [b.bbox[0], b.bbox[2]], ey = b.axis_extent?.y || [b.bbox[1], b.bbox[3]];
    const sc = viewL.scale() || 1;
    const info = seriesInfo(p);
    for (const [g, isR] of [[layer.selL, false], [layer.selR, true]]) {
      svgEl("line", { class: "crosshair", x1: pos[0], x2: pos[0], y1: Math.min(...ey), y2: Math.max(...ey) }, g);
      svgEl("line", { class: "crosshair", y1: pos[1], y2: pos[1], x1: Math.min(...ex), x2: Math.max(...ex) }, g);
      svgEl("circle", { class: "sel-ring", cx: pos[0], cy: pos[1], r: 9 / sc }, g);
      if (isR && !st.drag) {
        const fs = 12 / sc;
        const txt = `${q.series} · ${fmt(q.x_value)}, ${fmt(q.y_value)}${p.y?.unit ? ` ${p.y.unit}` : ""}`;
        const w = txt.length * fs * 0.56 + 12 / sc;
        const x = pos[0] + 14 / sc, y = pos[1] - 30 / sc;
        svgEl("rect", { x, y, width: w, height: 22 / sc, rx: 4 / sc, fill: "#1f2933" }, g);
        const t = svgEl("text", { x: x + 6 / sc, y: y + 15 / sc, "font-size": fs, fill: "#fff", "font-family": "Inter, system-ui, sans-serif" }, g);
        t.textContent = txt;
      }
    }
    // keep the dragged marker under the pointer
    if (st.drag) {
      svgEl("circle", { cx: pos[0], cy: pos[1], r: markerR(q, info), fill: "none", stroke: info[q.series]?.color || "#333", "stroke-width": 2, "vector-effect": "non-scaling-stroke" }, layer.selR);
    }
  }

  function select(id, { scroll = true, reveal = false } = {}) {
    st.sel = id;
    drawSelection();
    side.querySelectorAll("tr[data-id]").forEach((tr) => {
      const on = tr.dataset.id === id;
      tr.classList.toggle("selected", on);
      tr.setAttribute("aria-selected", String(on));
      if (on && scroll) tr.scrollIntoView({ block: "nearest" });
    });
    if (reveal && id) {
      const q = findPoint(id);
      const vb = viewL.vb;
      if (q && !inBox([q.px, q.py], [vb.x, vb.y, vb.x + vb.w, vb.y + vb.h])) viewL.setViewBox({ ...vb, x: q.px - vb.w / 2, y: q.py - vb.h / 2 });
    }
  }

  function pointDown(e, q, view) {
    if (e.button !== 0 || e.defaultPrevented) return;
    if (st.tool === "add") return; // handled by the svg listener (adds at the click)
    e.preventDefault();
    e.stopPropagation();
    if (st.tool === "delete") {
      select(q.id);
      deletePoint(q.id);
      return;
    }
    select(q.id);
    dragFrom(e, view, (pt) => {
      st.drag = { id: q.id, pt };
      drawSelection();
    }, (pt, s0, moved) => {
      st.drag = null;
      if (moved) {
        const p = panel();
        sendEdits([{ op: "move", panel: p.id, id: q.id, pt: [round3(pt[0]), round3(pt[1])] }],
          [{ op: "move", panel: p.id, id: q.id, pt: [q.px, q.py] }], "Move");
      } else drawSelection();
    });
  }

  for (const [svg, view] of [[svgL, viewL], [svgR, viewR]]) {
    svg.addEventListener("pointerdown", (e) => {
      if (e.defaultPrevented || e.button !== 0) return;
      if (st.tool !== "add") return;
      dragFrom(e, view, null, (pt, s0, moved) => { if (!moved) addPoint(pt); });
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

  function deletePoint(id) {
    const p = panel();
    const q = findPoint(id);
    if (!q) return;
    sendEdits([{ op: "delete", panel: p.id, id }], [{ op: "add", panel: p.id, block: q.block, series: q.series, pt: [q.px, q.py], _replaces: id }], "Delete");
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
      const added = applied.find((a) => a.op === "add");
      if (added) st.sel = added.id;
      else if (st.sel && !findPoint(st.sel)) st.sel = null;
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
    if (st.sel === oldId) st.sel = newId;
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
    status.textContent = { move: "Move: drag a point (in either view) to its correct position. Click to select.",
      add: `Add point: click where the missing marker is. Series: ${seriesSel.value || "–"}.`,
      delete: "Delete: click a point to remove it." }[t];
  }
  function updateTools() {
    undoBtn.disabled = !st.undo.length || st.busy;
    undoBtn.textContent = st.undo.length ? `Undo (${st.undo.length})` : "Undo";
  }

  const onKey = (e) => {
    if (isTyping(e.target) || document.querySelector("dialog[open]")) return;
    if ((e.key === "Delete" || e.key === "Backspace") && st.sel) { e.preventDefault(); deletePoint(st.sel); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
    else if (e.key === "Escape") select(null);
  };
  document.addEventListener("keydown", onKey);

  // ----- panel tabs
  async function showPanel(pid, { fit = true } = {}) {
    st.pid = pid;
    st.sel = null;
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
      const st_ = q.edited || "extracted";
      const xi = h("input", { value: fmt(q.x_value), "aria-label": `${xName} value of ${q.series} point ${q.id}`, inputmode: "decimal", "data-key": `${q.id}:x` });
      const yi = h("input", { value: fmt(q.y_value), "aria-label": `${yName} value of ${q.series} point ${q.id}`, inputmode: "decimal", "data-key": `${q.id}:y` });
      const commit = (e) => {
        if (e.key === "Escape") { xi.value = fmt(q.x_value); yi.value = fmt(q.y_value); e.target.blur(); return; }
        if (e.key !== "Enter") return;
        e.preventDefault();
        const xv = Number(xi.value.replace("−", "-")), yv = Number(yi.value.replace("−", "-"));
        if (!Number.isFinite(xv) || !Number.isFinite(yv)) { showError("Enter numbers for both values."); return; }
        select(q.id, { scroll: false });
        sendEdits([{ op: "set", panel: p.id, id: q.id, value: [xv, yv] }], [{ op: "move", panel: p.id, id: q.id, pt: [q.px, q.py] }], "Edit value");
      };
      xi.addEventListener("keydown", commit);
      yi.addEventListener("keydown", commit);
      const focusSel = () => { if (st.sel !== q.id) select(q.id, { scroll: false, reveal: true }); };
      xi.addEventListener("focus", focusSel);
      yi.addEventListener("focus", focusSel);
      const inf = info[q.series] || {};
      tbody.appendChild(h("tr", { "data-id": q.id, class: q.id === st.sel ? "selected" : "", "aria-selected": String(q.id === st.sel),
        onclick: (e) => { if (e.target.tagName !== "INPUT") select(q.id, { scroll: false, reveal: true }); } },
        h("td", { title: inf.meaning || "" }, h("span", { class: "series-cell" }, markerIcon(q.shape || inf.shape, q.filled ?? inf.filled, inf.color, 14), q.series,
          q.block !== "main" ? h("span", { class: "muted" }, ` (${q.block.replace("inset:", "inset ")})`) : null)),
        h("td", { class: "num" }, xi), h("td", { class: "num" }, yi),
        h("td", { class: `st-${st_}` }, st_)));
    }
    side.appendChild(h("h2", { style: { fontSize: "17px" } }, `Points (${pts.length})`));
    side.appendChild(h("p", { class: "small muted" }, "Click a row to select the point. Type a value and press Enter to move it."));
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
    legendRow.appendChild(h("span", {}, "Selecting a point on either side shows the crosshair on both."));
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
