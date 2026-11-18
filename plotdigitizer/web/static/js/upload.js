// Screen 1: upload a PDF, and the session view listing its figures and results.

import { api } from "./api.js";
import { h, clear, fmtDate, busy, errorBox, setHeader } from "./ui.js";
import { svgEl } from "./svgview.js";
import { go, routes } from "./router.js";

const LAST_KEY = "plotdigitizer:last-session";
function remember(token) { try { localStorage.setItem(LAST_KEY, token); } catch { /* storage unavailable */ } }
function recall() { try { return localStorage.getItem(LAST_KEY); } catch { return null; } }

function uploadForm(onDone) {
  let file = null;
  const status = h("p", { class: "status", "aria-live": "polite" });
  const errSlot = h("div");
  const fileInput = h("input", { type: "file", accept: "application/pdf,.pdf", class: "visually-hidden", id: "pdf-file" });
  const fileName = h("div", { class: "file-name", "aria-live": "polite" });
  const citekey = h("input", { id: "citekey", name: "citekey", placeholder: "e.g. Bastviken2008", autocomplete: "off" });
  const submit = h("button", { type: "submit", class: "btn primary big", disabled: true }, "Upload and find figures");

  const setFile = (f) => {
    clear(errSlot);
    if (!f) return;
    if (!/\.pdf$/i.test(f.name) && f.type !== "application/pdf") {
      errSlot.appendChild(errorBox("Please choose a PDF file."));
      return;
    }
    file = f;
    fileName.textContent = `${f.name} (${(f.size / 1048576).toFixed(1)} MB)`;
    if (!citekey.value) citekey.value = f.name.replace(/\.pdf$/i, "").replace(/[^\w.-]+/g, "_");
    submit.disabled = false;
  };
  fileInput.addEventListener("change", () => setFile(fileInput.files[0]));

  const drop = h("div", { class: "dropzone" },
    svgIcon(),
    h("div", { style: { fontSize: "15px" } }, "Drop a PDF here"),
    h("label", { for: "pdf-file", class: "btn outline-primary", tabindex: "0", role: "button",
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } } }, "Choose file"),
    fileInput, fileName,
    h("div", { class: "small" }, "PDF only · the whole session is deleted after 7 days"));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));

  const form = h("form", { class: "col-left", onsubmit: async (e) => {
    e.preventDefault();
    if (!file) return;
    clear(errSlot);
    submit.disabled = true;
    const done = busy(status, "Uploading and looking for figures…");
    try {
      const s = await api.createSession(file, citekey.value.trim());
      done();
      remember(s.token);
      onDone(s);
    } catch (err) {
      done();
      errSlot.appendChild(errorBox(err.message));
      submit.disabled = false;
    }
  } },
    h("h1", {}, "Upload a paper"), drop,
    h("div", { class: "field" }, h("label", { for: "citekey" }, "Citekey"), citekey,
      h("span", { class: "hint" }, "Used in the CSV to trace every value back to the paper.")),
    submit, status, errSlot);
  return form;
}

function svgIcon() {
  const s = svgEl("svg", { width: 40, height: 40, viewBox: "0 0 24 24", fill: "none", stroke: "#52606d", "stroke-width": 1.5, "aria-hidden": "true" });
  svgEl("path", { d: "M12 16V4m0 0l-4 4m4-4l4 4M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" }, s);
  return s;
}

export async function renderUpload(app) {
  setHeader({ step: 1, right: "Private session link · deleted after 7 days" });
  const last = recall();
  const right = h("section", { class: "col-right" },
    h("h2", {}, "How it works"),
    h("ol", { class: "muted", style: { margin: 0, paddingLeft: "20px", display: "flex", flexDirection: "column", gap: "6px" } },
      h("li", {}, "Upload a PDF. The figures in it are listed with their page."),
      h("li", {}, "Set up a figure: draw a box around each plot panel and its legend, and type the axis tick values."),
      h("li", {}, "Review the extracted points next to the original, correct them, validate, and download the CSV.")),
    h("p", { class: "muted" }, "Each upload gets a private link. Nothing is shared between sessions, and everything is deleted after 7 days."),
    last ? h("p", {}, h("a", { href: routes.session(last) }, "Return to your last session")) : null);
  app.appendChild(h("div", { class: "upload-layout" }, uploadForm((s) => go(routes.session(s.token))), right));
}

function figThumb(token, fig, size) {
  const b = fig.bbox && fig.bbox.length === 4 ? fig.bbox : [0, 0, size[0], size[1]];
  const pad = 6;
  const vb = [b[0] - pad, b[1] - pad, b[2] - b[0] + 2 * pad, b[3] - b[1] + 2 * pad];
  const s = svgEl("svg", { class: "thumb", viewBox: vb.join(" "), preserveAspectRatio: "xMidYMid meet", role: "img",
    "aria-label": `Page ${fig.page_pdf} thumbnail of figure ${fig.number}` });
  svgEl("rect", { x: vb[0], y: vb[1], width: vb[2], height: vb[3], fill: "#fff" }, s);
  svgEl("image", { href: api.pageUrl(token, fig.page_pdf, 2), x: 0, y: 0, width: size[0], height: size[1], preserveAspectRatio: "none" }, s);
  return s;
}

export async function renderSession(app, { token }) {
  const s = await api.session(token);
  remember(token);
  const expires = fmtDate(s.expires_at);
  setHeader({ step: 1, context: s.citekey, right: `Private session link · expires ${expires}` });
  const results = new Map((s.results || []).map((r) => [String(r.number), r]));
  const link = location.href.split("#")[0] + routes.session(token);

  // left column: session info and results
  const linkInput = h("input", { class: "text", id: "session-link", readOnly: true, value: link });
  const copyBtn = h("button", { type: "button", class: "btn", onclick: async () => {
    try { await navigator.clipboard.writeText(link); copyBtn.textContent = "Copied"; }
    catch { linkInput.select(); }
  } }, "Copy");
  const resList = h("ul", { class: "results-list" });
  for (const r of s.results || []) {
    resList.appendChild(h("li", {},
      h("strong", {}, `Fig. ${r.number}`),
      h("span", { class: "muted small" }, `${r.n_points} points`),
      r.validated ? h("span", { class: "badge ok" }, "✓ Validated") : h("span", { class: "badge warn" }, "Not validated"),
      h("span", { class: "spacer" }),
      h("a", { href: routes.review(token, r.number) }, "Review"),
      h("a", { href: api.csvUrl(token, r.number), download: "" }, "CSV")));
  }
  const left = h("section", { class: "col-left" },
    h("h1", {}, s.citekey),
    h("div", { class: "panel-card" },
      h("div", { class: "field" }, h("label", { for: "session-link" }, "Your private session link"),
        h("div", { class: "session-link" }, linkInput, copyBtn),
        h("span", { class: "hint" }, "Bookmark it: this link is the only way back to your work.")),
      h("div", { class: "alert warn" }, `Download your CSVs before ${expires}; everything is deleted then.`)),
    h("div", { class: "panel-card" },
      h("h2", {}, "Results"),
      (s.results || []).length ? resList : h("p", { class: "muted small" }, "No figure processed yet."),
      (s.results || []).length ? h("a", { class: "btn primary", href: api.allCsvUrl(token), download: "" }, "Download all (CSV)") : null),
    h("p", {}, h("a", { href: "#/" }, "Upload another PDF")));

  // right column: figures
  const grid = h("div", { class: "fig-grid" });
  const sizes = s.page_sizes || [];
  for (const f of s.figures || []) {
    const size = sizes[f.page_pdf - 1] || [612, 792];
    const r = results.get(String(f.number));
    const kind = f.kind === "raster" ? "Raster image" : f.mixed ? "Vector, with raster parts" : "Vector";
    const inner = [
      figThumb(token, f, size),
      h("div", { class: "title" }, `Fig. ${f.number} · p. ${f.page_pdf}`),
      h("div", { class: "meta" }, kind),
      f.caption ? h("div", { class: "caption", title: f.caption }, f.caption) : null,
    ];
    if (!f.supported) {
      inner.push(h("div", { class: "reason" }, f.reason || "Not supported"));
      grid.appendChild(h("div", { class: "fig-card unsupported", "aria-disabled": "true" }, inner));
    } else {
      if (r) inner.push(h("div", {}, r.validated ? h("span", { class: "badge ok" }, "✓ Validated") : h("span", { class: "badge" }, `${r.n_points} points extracted`)));
      inner.push(h("div", { class: "links" },
        h("a", { class: "btn primary small", href: routes.setup(token, f.number, f.page_pdf), "aria-label": `Set up figure ${f.number}` }, r ? "Set-up" : "Set up →"),
        r ? h("a", { class: "btn small", href: routes.review(token, f.number), "aria-label": `Review figure ${f.number}` }, "Review") : null));
      grid.appendChild(h("div", { class: "fig-card" }, inner));
    }
  }

  // manual set-up
  const numIn = h("input", { id: "man-num", required: true, placeholder: "e.g. 3", autocomplete: "off" });
  const pageSel = h("select", { id: "man-page" });
  for (let i = 1; i <= (s.n_pages || sizes.length); i++) pageSel.appendChild(h("option", { value: i }, `Page ${i}`));
  const manual = h("form", { class: "panel-card", onsubmit: (e) => {
    e.preventDefault();
    const n = numIn.value.trim();
    if (n) go(routes.setup(token, n, pageSel.value));
  } },
    h("h3", {}, "Set up a figure manually"),
    h("p", { class: "muted small" }, "Detection can miss figures. Give the figure number and the page it is on."),
    h("div", { class: "row" },
      h("div", { class: "field", style: { flex: "1 1 120px" } }, h("label", { for: "man-num" }, "Figure number"), numIn),
      h("div", { class: "field", style: { flex: "1 1 120px" } }, h("label", { for: "man-page" }, "Page"), pageSel),
      h("button", { type: "submit", class: "btn outline-primary", style: { alignSelf: "flex-end" } }, "Set up")));

  const right = h("section", { class: "col-right" },
    h("div", { class: "section-head" }, h("h2", {}, "Figures found"), h("span", { class: "small muted" }, "Detected from captions and drawings")),
    (s.figures || []).length ? grid : h("p", { class: "muted" }, "No figures were detected. Set one up manually below."),
    manual);
  app.appendChild(h("div", { class: "upload-layout" }, left, right));
}
