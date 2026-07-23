#!/usr/bin/env python3
"""Keep the expense tracker alive on :8765 (single instance, no console spam).

Restarts the server automatically if it exits or crashes.
Prefer starting via start.ps1 (uses pythonw — no terminal window).
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def _pick_python() -> Path:
    # pythonw = no console window on Windows
    for name in ("pythonw.exe", "python.exe"):
        p = ROOT / "venv" / "Scripts" / name
        if p.is_file():
            return p
    # Fallback: same interpreter family as this process
    here = Path(sys.executable)
    if here.name.lower() == "python.exe":
        pw = here.with_name("pythonw.exe")
        if pw.is_file():
            return pw
    return here


PYTHON = _pick_python()
APP = ROOT / "app.py"
ERR_LOG = ROOT / "run_err.log"
OUT_LOG = ROOT / "run_out.log"
PID_FILE = ROOT / "server.pid"
WATCHDOG_PID = ROOT / "watchdog.pid"
LOCK_FILE = ROOT / "watchdog.lock"
PORT = int(os.environ.get("EXPENSE_PORT", "8765"))
RESTART_DELAY = float(os.environ.get("EXPENSE_RESTART_DELAY", "1.5"))

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

_lock_sock = None


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [watchdog] {msg}"
    # Prefer file only when running under pythonw (no console)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with ERR_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def write_pid(path: Path, pid: int) -> None:
    try:
        path.write_text(str(pid), encoding="utf-8")
    except OSError:
        pass


def acquire_single_instance() -> bool:
    """Return False if another watchdog is already running.

    Bind a dedicated localhost port as a lock — atomic and reliable on Windows.
    """
    global _lock_sock
    import socket

    lock_port = int(os.environ.get("EXPENSE_WATCHDOG_LOCK_PORT", "18765"))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Exclusive bind: only one process can own this port
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("127.0.0.1", lock_port))
        sock.listen(1)
        _lock_sock = sock
        try:
            LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass
        return True
    except OSError:
        try:
            sock.close()
        except OSError:
            pass
        _lock_sock = None
        return False


def release_lock() -> None:
    global _lock_sock
    if _lock_sock is not None:
        try:
            _lock_sock.close()
        except OSError:
            pass
        _lock_sock = None


def main() -> int:
    os.chdir(ROOT)
    if not acquire_single_instance():
        # Another watchdog is already running — do not open more terminals/processes
        try:
            with ERR_LOG.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"{datetime.now():%Y-%m-%d %H:%M:%S} [watchdog] "
                    f"Already running; exit pid={os.getpid()}\n"
                )
        except OSError:
            pass
        return 0

    atexit.register(release_lock)
    write_pid(WATCHDOG_PID, os.getpid())
    log(f"Watchdog starting (pid={os.getpid()})")
    log(f"Python: {PYTHON}")
    log(f"App: {APP}")
    log(f"URL: http://127.0.0.1:{PORT}")

    while True:
        proc = None
        try:
            with OUT_LOG.open("ab") as out, ERR_LOG.open("ab") as err:
                stamp = f"\n----- server start {datetime.now():%Y-%m-%d %H:%M:%S} -----\n".encode()
                err.write(stamp)
                err.flush()
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                kwargs: dict = {
                    "args": [str(PYTHON), str(APP)],
                    "cwd": str(ROOT),
                    "stdout": out,
                    "stderr": err,
                    "env": env,
                }
                if os.name == "nt":
                    # No console window for the app child
                    kwargs["creationflags"] = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
                proc = subprocess.Popen(**kwargs)
                write_pid(PID_FILE, proc.pid)
                log(f"Server started pid={proc.pid}")
                code = proc.wait()
                log(f"Server exited code={code}; restart in {RESTART_DELAY}s")
        except KeyboardInterrupt:
            log("Watchdog stopped by user")
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            return 0
        except Exception as exc:
            log(f"Watchdog error: {exc!r}; retry in {RESTART_DELAY}s")
        time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    raise SystemExit(main())
