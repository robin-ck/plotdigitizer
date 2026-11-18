// Small DOM helpers shared by the screens.

export function h(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (v === true) e.setAttribute(k, "");
    else if (k in e && typeof v !== "string") e[k] = v;
    else e.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

/** Number with 4 significant digits, no exponent for ordinary magnitudes. */
export function fmt(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e6 || a < 1e-4) return v.toExponential(3);
  return String(Number(v.toPrecision(4)));
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

export function fmtDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Status line for long requests; returns a function to finish it. */
export function busy(el, text) {
  el.textContent = text;
  el.classList.add("busy");
  el.hidden = false;
  return () => { el.classList.remove("busy"); el.textContent = ""; };
}

export function errorBox(msg) {
  return h("div", { class: "alert error", role: "alert" }, msg);
}

/** Modal dialog using <dialog>. Resolves with the value given to close(). */
export function modal(title, body, buttons) {
  return new Promise((resolve) => {
    const dlg = h("dialog", { class: "modal", "aria-labelledby": "modal-title" });
    const form = h("form", { method: "dialog" });
    const foot = h("div", { class: "modal-actions" });
    for (const b of buttons) {
      foot.appendChild(h("button", {
        type: b.submit ? "submit" : "button", class: `btn ${b.primary ? "primary" : ""} ${b.danger ? "danger" : ""}`,
        onclick: (e) => {
          if (b.submit && !form.reportValidity()) return;
          e.preventDefault();
          const v = typeof b.value === "function" ? b.value(form) : b.value;
          dlg.close();
          dlg.remove();
          resolve(v);
        },
      }, b.label));
    }
    form.append(h("h2", { id: "modal-title" }, title), body, foot);
    dlg.appendChild(form);
    dlg.addEventListener("cancel", () => { dlg.remove(); resolve(null); });
    document.body.appendChild(dlg);
    dlg.showModal();
  });
}

export function confirmDialog(title, text, okLabel = "Continue") {
  return modal(title, h("p", {}, text), [
    { label: "Cancel", value: false },
    { label: okLabel, value: true, primary: true },
  ]);
}

/** Header step indicator and context text. */
export function setHeader({ step = 1, context = "", right = "" } = {}) {
  const steps = document.querySelectorAll(".steps [data-step]");
  steps.forEach((s) => {
    const on = Number(s.dataset.step) === step;
    s.classList.toggle("current", on);
    if (on) s.setAttribute("aria-current", "step");
    else s.removeAttribute("aria-current");
  });
  document.getElementById("hdr-context").textContent = context ? ` · ${context}` : "";
  const r = document.getElementById("hdr-right");
  clear(r);
  if (right instanceof Node) r.appendChild(right);
  else r.textContent = right;
}
