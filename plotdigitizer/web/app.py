"""FastAPI app for the web interface. API contract:
``openspec/changes/add-web-interface/api.md``.

Run: ``plotdigitizer serve`` or ``uvicorn plotdigitizer.web.app:app``.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Config
from .jobs import JobFailed, JobManager, JobTimeout
from .ratelimit import RateLimiter, client_ip
from .sessions import Store, safe_name

STATIC = Path(__file__).parent / "static"
NUM_RE = re.compile(r"^[A-Za-z0-9._-]{1,20}$")
PID_RE = re.compile(r"^[A-Za-z0-9._-]{1,20}$")
ZOOMS = (1, 2, 4)


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config()
    store = Store(cfg.data_root, cfg.retention_days)
    jobs = JobManager(cfg.max_jobs, cfg.job_timeout_s)
    upload_rl = RateLimiter(*cfg.upload_rate)
    job_rl = RateLimiter(*cfg.job_rate)
    locks: dict[str, asyncio.Lock] = {}

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async def loop():
            while True:
                await asyncio.to_thread(store.cleanup)
                await asyncio.sleep(3600)
        task = asyncio.create_task(loop())
        yield
        task.cancel()

    app = FastAPI(title="plotdigitizer", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg, app.state.store = cfg, store

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    # ------------------------------------------------------------ helpers
    def limit(request: Request, rl: RateLimiter):
        if not rl.allow(client_ip(request, cfg.trusted_proxy)):
            raise HTTPException(429, "too many requests, please wait a moment")

    def sdir(token: str) -> Path:
        d = store.dir(token)
        if d is None:
            raise HTTPException(404, "expired or unknown session")
        return d

    def lock(token: str) -> asyncio.Lock:
        return locks.setdefault(token, asyncio.Lock())

    async def job(name: str, *args):
        try:
            res = await jobs.run(name, *args)
        except JobTimeout as e:
            raise HTTPException(504, f"{e}. Try again, or try a smaller box.")
        except JobFailed as e:
            raise HTTPException(500, f"processing failed: {e}")
        if isinstance(res, dict) and "_error" in res:
            extra = {k: v for k, v in res.items() if not k.startswith("_")}
            raise HTTPException(res["_status"], {"message": res["_error"], **extra} if extra else res["_error"])
        return res

    def figdir(d: Path, num: str) -> Path:
        if not NUM_RE.match(num):
            raise HTTPException(400, "bad figure number")
        return d / "out" / store.meta(d)["citekey"] / f"fig{num}"

    def check_page(d: Path, page: Any) -> int:
        try:
            page = int(page)
        except (TypeError, ValueError):
            raise HTTPException(400, "page must be an integer")
        if not 1 <= page <= store.meta(d)["n_pages"]:
            raise HTTPException(400, "page out of range")
        return page

    def check_bbox(b: Any) -> list[float]:
        try:
            b = [float(v) for v in b]
        except (TypeError, ValueError):
            raise HTTPException(400, "bbox must be 4 numbers")
        if len(b) != 4:
            raise HTTPException(400, "bbox must be 4 numbers")
        x0, y0, x1, y1 = min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])
        if x1 - x0 < 2 or y1 - y0 < 2:
            raise HTTPException(400, "box too small")
        return [x0, y0, x1, y1]

    def n_edits(fd: Path) -> int:
        logp = fd / "log.jsonl"
        if not logp.exists():
            return 0
        n = 0
        for line in logp.read_text(encoding="utf-8").splitlines():
            ev = json.loads(line)["event"]
            if ev == "run_start":
                n = 0
            elif ev.startswith("manual_"):
                n += 1
        return n

    def review_payload(fd: Path) -> dict:
        from ..wpd import panel_clip
        sp = fd / "state.json"
        if not sp.exists():
            raise HTTPException(404, "figure not extracted yet")
        st = json.loads(sp.read_text(encoding="utf-8"))
        card = st["card"]
        by_card = {p["id"]: p for p in card["panels"]}
        panels = []
        for p in st["panels"]:
            pc = by_card[p["id"]]
            blocks = {}
            for k, b in p["blocks"].items():
                blocks[k] = {kk: b[kk] for kk in ("bbox", "calibration", "axis_extent", "axis_coord")}
                blocks[k]["points"] = [{kk: q.get(kk) for kk in (
                    "id", "series", "shape", "filled", "px", "py", "x_value", "y_value", "uncertainty_x",
                    "uncertainty_y", "confidence", "source", "edited")} for q in b["points"]]
            panels.append({
                "id": p["id"], "clip": panel_clip(p, pc), "signatures": p.get("signatures", []),
                "series": [{"label": s["label"], "meaning": s.get("meaning", "")} for s in pc["series"]],
                "x": {k: pc["x"].get(k) for k in ("title", "unit", "scale", "inverted")},
                "y": {k: pc["y"].get(k) for k in ("title", "unit", "scale", "inverted")},
                "blocks": blocks})
        cp = fd / "checks.json"
        checks = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else []
        return {"number": card["figure"]["number"], "page_pdf": card["figure"]["page_pdf"], "card": card,
                "panels": panels, "checks": checks, "validation": st.get("validation"),
                "reviewed_panels": st.get("reviewed_panels", []), "n_edits": n_edits(fd)}

    def session_payload(d: Path) -> dict:
        m = store.meta(d)
        results = []
        out = d / "out" / m["citekey"]
        if out.exists():
            for sp in sorted(out.glob("fig*/state.json")):
                st = json.loads(sp.read_text(encoding="utf-8"))
                results.append({"number": st["card"]["figure"]["number"],
                                "validated": bool(st.get("validation")),
                                "n_points": sum(len(b["points"]) for p in st["panels"] for b in p["blocks"].values())})
        return {k: m[k] for k in ("token", "citekey", "created_at", "expires_at", "n_pages", "page_sizes", "figures")} \
            | {"results": results}

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "invalid JSON body")
        if not isinstance(data, dict):
            raise HTTPException(400, "JSON object expected")
        return data

    # ------------------------------------------------------------ session
    @app.post("/api/sessions", status_code=201)
    async def create_session(request: Request, file: UploadFile = File(...), citekey: str = Form("")):
        limit(request, upload_rl)
        if await asyncio.to_thread(store.disk_usage) > cfg.disk_cap_gb * 1e9:
            raise HTTPException(507, "the server is full right now, please try again later")
        max_bytes = int(cfg.max_upload_mb * 1024 * 1024)
        head = await file.read(5)
        if head != b"%PDF-":
            raise HTTPException(400, "please upload a PDF file")
        token, d = store.create(citekey or Path(file.filename or "").stem)
        try:
            size = len(head)
            with open(d / "paper.pdf", "wb") as f:
                f.write(head)
                while chunk := await file.read(1 << 20):
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(413, f"file larger than {cfg.max_upload_mb:g} MB")
                    f.write(chunk)
            info = await job("inspect_pdf", str(d / "paper.pdf"), cfg.max_pages)
        except BaseException:
            store.delete(token)
            raise
        m = store.meta(d) | info
        store.write_meta(d, m)
        return session_payload(d)

    @app.get("/api/s/{token}")
    async def get_session(token: str):
        return session_payload(sdir(token))

    # ------------------------------------------------------------ pages
    @app.get("/api/s/{token}/pages/{page}.png")
    async def page_png(request: Request, token: str, page: int, zoom: int = 2):
        d = sdir(token)
        page = check_page(d, page)
        if zoom not in ZOOMS:
            raise HTTPException(400, f"zoom must be one of {ZOOMS}")
        out = d / "pages" / f"{page}@{zoom}.png"
        if not out.exists():
            limit(request, job_rl)
            await job("render_page", str(d / "paper.pdf"), page, zoom, str(out))
        return FileResponse(out, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

    # ------------------------------------------------------------ set-up helpers
    @app.post("/api/s/{token}/detect")
    async def detect(request: Request, token: str):
        d = sdir(token)
        limit(request, job_rl)
        data = await body(request)
        page = check_page(d, data.get("page"))
        bbox = check_bbox(data.get("bbox"))
        exclude = [check_bbox(b) for b in (data.get("exclude") or [])]
        side = data.get("side") or {}
        side = {k: v for k, v in side.items() if k in ("x", "y") and v in ("top", "bottom", "left", "right")}
        return await job("detect", str(d / "paper.pdf"), page, bbox, exclude, side)

    @app.post("/api/s/{token}/legend")
    async def legend(request: Request, token: str):
        d = sdir(token)
        limit(request, job_rl)
        data = await body(request)
        return await job("legend", str(d / "paper.pdf"), check_page(d, data.get("page")), check_bbox(data.get("bbox")))

    # ------------------------------------------------------------ figures
    @app.get("/api/s/{token}/figures/{num}/card")
    async def get_card(token: str, num: str):
        p = figdir(sdir(token), num) / "figure_card.json"
        if not p.exists():
            raise HTTPException(404, "no card saved for this figure")
        return json.loads(p.read_text(encoding="utf-8"))

    @app.post("/api/s/{token}/figures/{num}/extract")
    async def extract(request: Request, token: str, num: str):
        d = sdir(token)
        limit(request, job_rl)
        fd = figdir(d, num)
        data = await body(request)
        card = data.get("card")
        if not isinstance(card, dict):
            raise HTTPException(400, "card missing")
        card = copy.deepcopy(card)
        card["paper"] = {"citekey": store.meta(d)["citekey"]}
        card.setdefault("figure", {})
        if not isinstance(card["figure"], dict):
            raise HTTPException(400, "card.figure must be an object")
        card["figure"]["number"] = num
        card["figure"]["kind"] = "vector"
        check_page(d, card["figure"].get("page_pdf"))
        for pc in card.get("panels") or []:
            if not isinstance(pc, dict) or not PID_RE.match(str(pc.get("id", ""))):
                raise HTTPException(400, "each panel needs an id (letters, digits, . _ -)")
        async with lock(token):
            edits = n_edits(fd) if (fd / "state.json").exists() else 0
            if edits and not data.get("confirm_discard"):
                return JSONResponse({"detail": f"re-extracting discards {edits} manual edits", "edits": edits},
                                    status_code=409)
            await job("extract", str(d / "paper.pdf"), card, str(d / "out"))
            return review_payload(fd)

    @app.get("/api/s/{token}/figures/{num}")
    async def get_review(token: str, num: str):
        return review_payload(figdir(sdir(token), num))

    @app.post("/api/s/{token}/figures/{num}/panels/{pid}/reviewed")
    async def reviewed(token: str, num: str, pid: str):
        from ..review import EditError, mark_reviewed
        fd = figdir(sdir(token), num)
        if not (fd / "state.json").exists():
            raise HTTPException(404, "figure not extracted yet")
        async with lock(token):
            try:
                return {"reviewed_panels": mark_reviewed(fd, pid)}
            except EditError as e:
                raise HTTPException(400, str(e))

    @app.post("/api/s/{token}/figures/{num}/edits")
    async def edits(request: Request, token: str, num: str):
        d = sdir(token)
        limit(request, job_rl)
        fd = figdir(d, num)
        if not (fd / "state.json").exists():
            raise HTTPException(404, "figure not extracted yet")
        ops = (await body(request)).get("edits")
        if not isinstance(ops, list) or not ops or not all(isinstance(o, dict) for o in ops) or len(ops) > 500:
            raise HTTPException(400, "edits must be a non-empty list of objects (max 500)")
        async with lock(token):
            res = await job("edits", str(fd), ops)
            return review_payload(fd) | {"applied": res["applied"]}

    @app.post("/api/s/{token}/figures/{num}/validate")
    async def validate(request: Request, token: str, num: str):
        d = sdir(token)
        limit(request, job_rl)
        fd = figdir(d, num)
        if not (fd / "state.json").exists():
            raise HTTPException(404, "figure not extracted yet")
        reasons = (await body(request)).get("reasons") or {}
        if not isinstance(reasons, dict):
            raise HTTPException(400, "reasons must be an object")
        reasons = {str(k): str(v)[:1000] for k, v in reasons.items()}
        async with lock(token):
            try:
                await job("validate", str(fd), reasons)
            except HTTPException as e:
                if e.status_code == 422 and isinstance(e.detail, dict):
                    return JSONResponse({"detail": e.detail["message"], "lacking": e.detail["lacking"]},
                                        status_code=422)
                raise
            return review_payload(fd)

    @app.get("/api/s/{token}/figures/{num}/{name}")
    async def csv_file(token: str, num: str, name: str):
        if name not in ("points.csv", "points_sheet.csv"):
            raise HTTPException(404, "not found")
        d = sdir(token)
        p = figdir(d, num) / name
        if not p.exists():
            raise HTTPException(404, "figure not extracted yet")
        fn = f"{store.meta(d)['citekey']}_fig{num}_{name}"
        return FileResponse(p, media_type="text/csv", filename=fn)

    @app.get("/api/s/{token}/all_points.csv")
    async def all_points(token: str):
        from ..export import collect_csv
        d = sdir(token)
        out = d / "out"
        out.mkdir(exist_ok=True)
        p = await asyncio.to_thread(collect_csv, out, d / "all_points.csv")
        return FileResponse(p, media_type="text/csv", filename=f"{store.meta(d)['citekey']}_all_points.csv")

    # ------------------------------------------------------------ front end
    STATIC.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        idx = STATIC / "index.html"
        if not idx.exists():
            raise HTTPException(404, "front end not built")
        return FileResponse(idx, headers={"Cache-Control": "no-cache"})

    return app


class _LazyApp:
    """``uvicorn plotdigitizer.web.app:app`` builds the app on first use, so
    importing this module (e.g. in tests) has no side effects."""

    _app = None

    async def __call__(self, scope, receive, send):
        if _LazyApp._app is None:
            _LazyApp._app = create_app()
        await _LazyApp._app(scope, receive, send)


app = _LazyApp()
