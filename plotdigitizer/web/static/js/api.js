// Thin wrapper around the HTTP API (see openspec/changes/add-web-interface/api.md).

export class ApiError extends Error {
  constructor(status, detail, data) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
    this.data = data || {};
  }
}

const STATUS_TEXT = {
  404: "This session has expired or the link is wrong.",
  413: "The file is too large.",
  429: "Too many requests. Please wait a moment and try again.",
  504: "The job took too long and was stopped. Please try again.",
  507: "The server is full right now. Please try again later.",
};

async function handle(res) {
  let data = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    try { data = await res.json(); } catch { data = null; }
  } else {
    try { data = { detail: (await res.text()).slice(0, 500) }; } catch { data = null; }
  }
  if (!res.ok) {
    let detail = data && data.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    if (!detail) detail = STATUS_TEXT[res.status] || `Request failed (${res.status})`;
    throw new ApiError(res.status, detail, data);
  }
  return data;
}

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new ApiError(0, "Could not reach the server. Check your connection and try again.");
  }
  return handle(res);
}

const enc = encodeURIComponent;

export const api = {
  createSession(file, citekey) {
    const fd = new FormData();
    fd.append("file", file);
    if (citekey) fd.append("citekey", citekey);
    return request("POST", "/api/sessions", fd);
  },
  session: (t) => request("GET", `/api/s/${enc(t)}`),
  pageUrl: (t, n, zoom = 2) => `/api/s/${enc(t)}/pages/${n}.png?zoom=${zoom}`,
  detect: (t, body) => request("POST", `/api/s/${enc(t)}/detect`, body),
  legend: (t, body) => request("POST", `/api/s/${enc(t)}/legend`, body),
  card: (t, num) => request("GET", `/api/s/${enc(t)}/figures/${enc(num)}/card`),
  extract: (t, num, card, confirmDiscard) =>
    request("POST", `/api/s/${enc(t)}/figures/${enc(num)}/extract`, confirmDiscard ? { card, confirm_discard: true } : { card }),
  review: (t, num) => request("GET", `/api/s/${enc(t)}/figures/${enc(num)}`),
  reviewed: (t, num, pid) => request("POST", `/api/s/${enc(t)}/figures/${enc(num)}/panels/${enc(pid)}/reviewed`),
  edits: (t, num, edits) => request("POST", `/api/s/${enc(t)}/figures/${enc(num)}/edits`, { edits }),
  validate: (t, num, reasons) =>
    request("POST", `/api/s/${enc(t)}/figures/${enc(num)}/validate`, reasons ? { reasons } : {}),
  csvUrl: (t, num, sheet = false) => `/api/s/${enc(t)}/figures/${enc(num)}/${sheet ? "points_sheet" : "points"}.csv`,
  allCsvUrl: (t) => `/api/s/${enc(t)}/all_points.csv`,
};
