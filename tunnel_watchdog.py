"""Hidden 2-minute keeper: local app + quick tunnel. Run with pythonw (no window)."""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
CREATE_NO_WINDOW = 0x08000000
LOG = ROOT / "tunnel-watchdog.log"
URL_FILE = ROOT / "tunnel.url"
PID_FILE = ROOT / "tunnel.pid"
TUNNEL_LOG = ROOT / "tunnel.log"
LOCAL = "http://127.0.0.1:8765/api/health"


def log(msg: str) -> None:
    line = datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n"
    try:
        LOG.open("a", encoding="utf-8").write(line)
    except OSError:
        pass


def url_ok(url: str, timeout: int = 8) -> bool:
    if not url:
        return False
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def cloudflared_path() -> Path | None:
    cands = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "cloudflared" / "cloudflared.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "cloudflared" / "cloudflared.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "cloudflared" / "cloudflared.exe",
    ]
    for p in cands:
        if p.is_file():
            return p
    return None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    return False


def ensure_local() -> bool:
    if url_ok(LOCAL, 3):
        return True
    log("local down; start pythonw run_forever")
    pyw = ROOT / "venv" / "Scripts" / "pythonw.exe"
    target = ROOT / "run_forever.py"
    if not pyw.is_file() or not target.is_file():
        return False
    subprocess.Popen(
        [str(pyw), str(target)],
        cwd=str(ROOT),
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )
    for _ in range(20):
        time.sleep(0.5)
        if url_ok(LOCAL, 2):
            return True
    return url_ok(LOCAL, 3)


def public_url() -> str:
    if not URL_FILE.is_file():
        return ""
    return URL_FILE.read_text(encoding="utf-8", errors="replace").strip()


def ensure_tunnel() -> None:
    pub = public_url()
    pid = 0
    if PID_FILE.is_file():
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            pid = 0
    alive = pid_alive(pid)
    pub_ok = bool(pub) and url_ok(pub.rstrip("/") + "/api/health", 8)
    if alive and pub_ok:
        return
    log(f"restart tunnel alive={alive} pub_ok={pub_ok}")
    exe = cloudflared_path()
    if not exe:
        log("cloudflared missing")
        return
    if pid and pid_alive(pid):
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=CREATE_NO_WINDOW)
        except Exception:
            pass
    if TUNNEL_LOG.is_file():
        try:
            TUNNEL_LOG.unlink()
        except OSError:
            pass
    proc = subprocess.Popen(
        [str(exe), "tunnel", "--url", "http://127.0.0.1:8765", "--logfile", str(TUNNEL_LOG), "--no-autoupdate"],
        cwd=str(ROOT),
        creationflags=CREATE_NO_WINDOW | 0x00000200,  # CREATE_NEW_PROCESS_GROUP
        close_fds=True,
    )
    PID_FILE.write_text(str(proc.pid), encoding="ascii")
    found = ""
    for _ in range(45):
        time.sleep(1)
        if TUNNEL_LOG.is_file():
            try:
                text = TUNNEL_LOG.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            import re

            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
            if m:
                found = m.group(0)
                break
        if proc.poll() is not None:
            log("cloudflared exited early")
            return
    if not found:
        log("no trycloudflare URL")
        return
    URL_FILE.write_text(found + "\n", encoding="ascii")
    try:
        from expense_tracker.cloud_sync import _read_deploy_cfg, register_live

        cfg = _read_deploy_cfg()
        register_live(cfg.get("username") or "anand", cfg.get("url") or "", cfg.get("key") or "")
        log("registered " + found)
    except Exception as exc:
        log("register-live failed: " + str(exc))


def main() -> int:
    if not ensure_local():
        log("local still down")
        return 1
    ensure_tunnel()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
