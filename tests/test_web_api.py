"""API tests for the web interface (FastAPI TestClient, synthetic PDFs)."""

import copy
import datetime as dt
import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from plotdigitizer.web.app import create_app  # noqa: E402
from plotdigitizer.web.config import Config  # noqa: E402


def make_client(tmp_path, **kw):
    cfg = Config(data_root=tmp_path / "data", **kw)
    return TestClient(create_app(cfg)), cfg


@pytest.fixture()
def client(tmp_path):
    with make_client(tmp_path)[0] as c:
        yield c


def upload(c, pdf, citekey="Synth2026"):
    with open(pdf, "rb") as f:
        return c.post("/api/sessions", files={"file": ("j.pdf", f, "application/pdf")}, data={"citekey": citekey})


def web_card(card):
    c = copy.deepcopy(card)
    c.pop("paper", None)
    return c


@pytest.fixture()
def session(client, journal):
    pdf, card, exp = journal
    r = upload(client, pdf)
    assert r.status_code == 201, r.text
    return client, r.json(), card


@pytest.fixture()
def extracted(session):
    c, s, card = session
    r = c.post(f"/api/s/{s['token']}/figures/2/extract", json={"card": web_card(card)})
    assert r.status_code == 200, r.text
    return c, s, r.json()


def test_upload_and_session(session):
    c, s, _ = session
    assert len(s["token"]) == 32 and s["n_pages"] == 1 and s["citekey"] == "Synth2026"
    assert s["page_sizes"][0][0] > 100 and s["results"] == []
    assert c.get(f"/api/s/{s['token']}").json()["token"] == s["token"]
    exp = dt.datetime.fromisoformat(s["expires_at"]) - dt.datetime.fromisoformat(s["created_at"])
    assert exp == dt.timedelta(days=7)


def test_upload_rejects(client, tmp_path):
    r = client.post("/api/sessions", files={"file": ("x.pdf", b"hello world", "application/pdf")})
    assert r.status_code == 400
    r = client.post("/api/sessions", files={"file": ("x.pdf", b"%PDF-1.4 broken", "application/pdf")})
    assert r.status_code == 400
    assert list((tmp_path / "data").iterdir()) == []  # nothing stored


def test_upload_too_large(tmp_path, journal):
    c, _ = make_client(tmp_path, max_upload_mb=0.001)
    with c:
        assert upload(c, journal[0]).status_code == 413
        assert list((tmp_path / "data").iterdir()) == []


def test_unknown_and_isolated(session):
    c, s, _ = session
    assert c.get("/api/s/" + "A" * 32).status_code == 404
    assert c.get("/api/s/../../etc").status_code == 404
    assert c.get("/api/s/" + "A" * 32 + "/pages/1.png").status_code == 404


def test_page_png(session):
    c, s, _ = session
    r = c.get(f"/api/s/{s['token']}/pages/1.png?zoom=1")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert c.get(f"/api/s/{s['token']}/pages/2.png").status_code == 400
    assert c.get(f"/api/s/{s['token']}/pages/1.png?zoom=3").status_code == 400


def test_detect_and_legend(session):
    c, s, card = session
    pc = card["panels"][0]
    r = c.post(f"/api/s/{s['token']}/detect", json={"page": 1, "bbox": pc["bbox_pt"], "exclude": [pc["legend"]["bbox_pt"]]})
    assert r.status_code == 200, r.text
    assert len(r.json()["x"]["major"]) == 5 and len(r.json()["y"]["major"]) == 5
    assert "labels" in r.json()["x"] and "labels" in r.json()["y"]   # journal PDF: no label text
    r = c.post(f"/api/s/{s['token']}/legend", json={"page": 1, "bbox": pc["legend"]["bbox_pt"]})
    assert [m["marker"] for m in r.json()] == [x["marker"] for x in pc["series"]]
    assert all("label" in m and "label_source" in m for m in r.json())   # no legend text here
    assert c.post(f"/api/s/{s['token']}/detect", json={"page": 1, "bbox": [1, 2]}).status_code == 400


def test_extract_review_edit_validate_csv(extracted):
    c, s, rv = extracted
    t = s["token"]
    assert rv["number"] == "2" and rv["validation"] is None and rv["n_edits"] == 0
    pts = rv["panels"][0]["blocks"]["main"]["points"]
    assert len(pts) == 38 and all("id" in p for p in pts)
    assert rv["panels"][0]["x"]["title"] == "CH4" and len(rv["panels"][0]["clip"]) == 4
    assert all("id" in ch for ch in rv["checks"])
    p0 = pts[0]
    r = c.post(f"/api/s/{t}/figures/2/edits",
               json={"edits": [{"op": "move", "panel": "a", "id": p0["id"], "pt": [p0["px"] + 1, p0["py"]]}]})
    assert r.status_code == 200, r.text
    assert r.json()["n_edits"] == 1 and r.json()["applied"][0]["id"] == p0["id"]
    bad = c.post(f"/api/s/{t}/figures/2/edits", json={"edits": [{"op": "delete", "panel": "a", "id": "nope"}]})
    assert bad.status_code == 400
    # validation needs reviewed panels
    assert c.post(f"/api/s/{t}/figures/2/validate", json={}).status_code == 409
    assert c.post(f"/api/s/{t}/figures/2/panels/a/reviewed").json() == {"reviewed_panels": ["a"]}
    r = c.post(f"/api/s/{t}/figures/2/validate", json={})
    assert r.status_code == 200, r.text
    assert r.json()["validation"]["validated"] is True
    csv_ = c.get(f"/api/s/{t}/figures/2/points.csv")
    assert csv_.status_code == 200 and "manuell geprüft" in csv_.text
    assert c.get(f"/api/s/{t}/figures/2/points_sheet.csv").status_code == 200
    assert c.get(f"/api/s/{t}/all_points.csv").text.count("\n") == 39
    sess = c.get(f"/api/s/{t}").json()
    assert sess["results"] == [{"number": "2", "validated": True, "n_points": 38}]
    assert c.get(f"/api/s/{t}/figures/2/card").json()["panels"][0]["id"] == "a"


def test_validate_needs_reasons(session):
    c, s, card = session
    t = s["token"]
    card = web_card(card)
    card["panels"][0]["series"][0]["expected_count"] = 99
    assert c.post(f"/api/s/{t}/figures/2/extract", json={"card": card}).status_code == 200
    c.post(f"/api/s/{t}/figures/2/panels/a/reviewed")
    r = c.post(f"/api/s/{t}/figures/2/validate", json={})
    assert r.status_code == 422 and r.json()["lacking"] == ["expected_count:a::155"]
    r = c.post(f"/api/s/{t}/figures/2/validate", json={"reasons": {"expected_count:a::155": "guess"}})
    assert r.status_code == 200 and r.json()["validation"]["reasons"] == {"expected_count:a::155": "guess"}


def test_reextract_conflict(extracted):
    c, s, rv = extracted
    t = s["token"]
    card = rv["card"]
    c.post(f"/api/s/{t}/figures/2/edits", json={"edits": [{"op": "delete", "panel": "a", "id": "main#0"}]})
    r = c.post(f"/api/s/{t}/figures/2/extract", json={"card": card})
    assert r.status_code == 409 and r.json()["edits"] == 1
    r = c.post(f"/api/s/{t}/figures/2/extract", json={"card": card, "confirm_discard": True})
    assert r.status_code == 200 and r.json()["n_edits"] == 0
    assert len(r.json()["panels"][0]["blocks"]["main"]["points"]) == 38


def test_extract_bad_card(session):
    c, s, card = session
    t = s["token"]
    bad = web_card(card)
    bad["panels"][0]["x"]["ticks"] = [0, 50, 100]  # 3 values, 5 ticks on the axis
    r = c.post(f"/api/s/{t}/figures/2/extract", json={"card": bad})
    assert r.status_code == 400 and "tick" in r.json()["detail"]
    r = c.post(f"/api/s/{t}/figures/2/extract", json={"card": {"figure": {"page_pdf": 1}, "panels": []}})
    assert r.status_code == 400
    assert c.post(f"/api/s/{t}/figures/..%2F..%2Fx/extract", json={"card": web_card(card)}).status_code in (400, 404)


def test_expiry_and_cleanup(session, tmp_path):
    c, s, _ = session
    store = c.app.state.store
    d = store.root / s["token"]
    m = json.loads((d / "meta.json").read_text())
    m["expires_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()
    (d / "meta.json").write_text(json.dumps(m))
    assert c.get(f"/api/s/{s['token']}").status_code == 404
    assert not d.exists()


def test_cleanup_spares_session_being_created(tmp_path):
    """The cleanup loop starts with the app and may run while an upload's
    folder exists without meta.json yet; it must not delete that folder."""
    import os
    import time
    from plotdigitizer.web.sessions import Store
    store = Store(tmp_path / "data", 7)
    fresh, old = store.root / ("A" * 32), store.root / ("B" * 32)
    fresh.mkdir()
    old.mkdir()
    t = time.time() - 2 * 3600
    os.utime(old, (t, t))
    store.cleanup()
    assert fresh.exists() and not old.exists()


def test_rate_limit(tmp_path, journal):
    c, _ = make_client(tmp_path, upload_rate=(1, 3600))
    with c:
        r = upload(c, journal[0])
        assert r.status_code == 201, r.text
        assert upload(c, journal[0]).status_code == 429


def test_disk_cap(tmp_path, journal):
    c, _ = make_client(tmp_path, disk_cap_gb=0.0)
    with c:
        (tmp_path / "data").mkdir(exist_ok=True)
        (tmp_path / "data" / "filler").write_bytes(b"x")
        assert upload(c, journal[0]).status_code == 507


def test_job_timeout_kills_worker():
    import time
    from plotdigitizer.web.jobs import JobFailed, JobTimeout, run_sync
    t0 = time.monotonic()
    with pytest.raises(JobTimeout):
        run_sync("_sleep", (30,), timeout=1.0)
    assert time.monotonic() - t0 < 10
    assert run_sync("_sleep", (0,), timeout=20) == {"ok": True}
    with pytest.raises(JobFailed):
        run_sync("render_page", ("/nonexistent.pdf", 1, 1, "/tmp/x.png"), timeout=20)


def test_raster_figure_end_to_end(client, rasterfig):
    pdf, card, _ = rasterfig
    r = upload(client, pdf, "Raster2026")
    assert r.status_code == 201, r.text
    s = r.json()
    t = s["token"]
    pc = card["panels"][1]
    r = client.post(f"/api/s/{t}/detect", json={"page": 1, "bbox": pc["bbox_pt"]})
    assert r.status_code == 200, r.text
    assert r.json()["method"] == "raster" and len(r.json()["y"]["major"]) == 6
    leg = client.post(f"/api/s/{t}/legend", json={"page": 1, "bbox": card["panels"][0]["legend"]["bbox_pt"]}).json()
    assert [m["marker"] for m in leg] == ["circle", "circle", "triangle"]
    wc = web_card(card)
    wc["figure"]["kind"] = "vector"            # the server decides per panel
    r = client.post(f"/api/s/{t}/figures/4/extract", json={"card": wc})
    assert r.status_code == 200, r.text
