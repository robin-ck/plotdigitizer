// Hash router: #/ (upload), #/s/<token>, #/s/<token>/fig/<num>/setup, #/s/<token>/fig/<num>/review

import * as upload from "./upload.js";
import * as setup from "./setup.js";
import * as review from "./review.js";
import { h, clear } from "./ui.js";

let cleanup = null;

export function parse(hash) {
  const raw = (hash || "").replace(/^#/, "");
  const [path, qs] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const query = Object.fromEntries(new URLSearchParams(qs || ""));
  if (parts[0] === "s" && parts[1]) {
    const token = parts[1];
    if (parts[2] === "fig" && parts[3]) {
      const view = parts[4] === "review" ? "review" : "setup";
      return { view, token, num: parts[3], query };
    }
    return { view: "session", token, query };
  }
  return { view: "upload", query };
}

export function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

export const routes = {
  session: (t) => `#/s/${encodeURIComponent(t)}`,
  setup: (t, n, page) => `#/s/${encodeURIComponent(t)}/fig/${encodeURIComponent(n)}/setup${page ? `?page=${page}` : ""}`,
  review: (t, n, panel) => `#/s/${encodeURIComponent(t)}/fig/${encodeURIComponent(n)}/review${panel ? `?panel=${encodeURIComponent(panel)}` : ""}`,
};

async function route() {
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  const app = document.getElementById("app");
  clear(app);
  const r = parse(location.hash);
  document.body.dataset.view = r.view;
  try {
    if (r.view === "upload") cleanup = await upload.renderUpload(app, r);
    else if (r.view === "session") cleanup = await upload.renderSession(app, r);
    else if (r.view === "setup") cleanup = await setup.render(app, r);
    else if (r.view === "review") cleanup = await review.render(app, r);
  } catch (e) {
    console.error(e);
    clear(app);
    app.appendChild(h("section", { class: "page-msg" },
      h("h1", {}, e.status === 404 ? "Session not found" : "Something went wrong"),
      h("p", {}, e.message || String(e)),
      h("p", {}, h("a", { href: "#/" }, "Upload a PDF"))));
  }
  const focusTarget = app.querySelector("h1");
  if (focusTarget) { focusTarget.setAttribute("tabindex", "-1"); focusTarget.focus({ preventScroll: true }); }
}

window.addEventListener("hashchange", route);
route();
