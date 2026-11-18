"""Run worker functions in a child process with a hard timeout.

No external queue: an asyncio semaphore caps concurrent jobs, excess requests
wait. Each job is one child from a forkserver (heavy imports preloaded), killed
when the timeout expires. Single instance only.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import traceback

from . import worker

_ctx = None


def _context():
    global _ctx
    if _ctx is None:
        try:
            _ctx = mp.get_context("forkserver")
            _ctx.set_forkserver_preload(["plotdigitizer.web.worker", "pymupdf", "numpy", "matplotlib"])
        except ValueError:  # pragma: no cover  (platforms without forkserver)
            _ctx = mp.get_context("spawn")
    return _ctx


class JobTimeout(Exception):
    pass


class JobFailed(Exception):
    pass


def _entry(conn, name, args):
    try:
        conn.send(("ok", getattr(worker, name)(*args)))
    except BaseException as e:  # noqa: BLE001
        conn.send(("err", f"{e.__class__.__name__}: {e}", traceback.format_exc()))
    finally:
        conn.close()


def run_sync(name: str, args: tuple, timeout: float):
    ctx = _context()
    parent, child = ctx.Pipe(duplex=False)
    p = ctx.Process(target=_entry, args=(child, name, args), daemon=True)
    p.start()
    child.close()
    try:
        if not parent.poll(timeout):
            raise JobTimeout(f"{name} took longer than {timeout:.0f} s")
        try:
            msg = parent.recv()
        except EOFError:
            raise JobFailed(f"{name}: worker exited unexpectedly") from None
    finally:
        if p.is_alive():
            p.kill()
        p.join(5)
        parent.close()
    if msg[0] == "err":
        raise JobFailed(msg[1])
    return msg[1]


class JobManager:
    def __init__(self, max_jobs: int, timeout: float):
        self.timeout = timeout
        self._sem = asyncio.Semaphore(max_jobs)

    async def run(self, name: str, *args, timeout: float | None = None):
        async with self._sem:
            return await asyncio.to_thread(run_sync, name, args, timeout or self.timeout)
