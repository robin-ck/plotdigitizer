"""Browser smoke test (Node Playwright). Skipped when node/playwright is missing."""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
HERE = Path(__file__).parent


def _has_playwright():
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _has_playwright(), reason="node playwright not available")
def test_browser_smoke(journal, tmp_path):
    pdf, card, _ = journal
    (tmp_path / "card.json").write_text(json.dumps(card))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, PD_DATA_ROOT=str(tmp_path / "data"))
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "plotdigitizer.web.app:app", "--port", str(port)],
                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        r = subprocess.run(["node", str(HERE / "e2e" / "smoke.mjs"), base, str(pdf), str(tmp_path / "card.json"),
                            str(tmp_path)], capture_output=True, text=True, timeout=240)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "SMOKE OK" in r.stdout
    finally:
        srv.terminate()
        srv.wait(10)
