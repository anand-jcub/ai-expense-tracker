"""Push local SQLite snapshot to Cloudflare expense MCP hub.

Usage (from repo root):
  set EXPENSE_MCP_URL=https://expense-tracker-mcp-hub.<subdomain>.workers.dev
  set EXPENSE_MCP_KEY=your-secret
  set EXPENSE_MCP_USER=anand
  .\\venv\\Scripts\\python.exe -m expense_tracker.cloud_sync

Or: sync-cloud.cmd
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from expense_tracker.auth import issue_local_api_token, verify_api_token
from expense_tracker.contacts import get_all_balances, get_ledger
from expense_tracker.db import connect, export_rows
from expense_tracker.services import CATEGORIES, EXPENSE_TYPES, dashboard_summary_payload


def _data_dir() -> Path:
    raw = (os.environ.get("DATA_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_ROOT / "data").resolve()


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def _month_bounds() -> tuple[str, str]:
    today = date.today()
    start = today.replace(day=1).isoformat()
    if today.month == 12:
        from datetime import timedelta

        end = (today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)).isoformat()
    else:
        from datetime import timedelta

        end = (today.replace(month=today.month + 1, day=1) - timedelta(days=1)).isoformat()
    return start, end


def build_snapshot(username: str) -> dict[str, Any]:
    db_path = _data_dir() / f"expenses_{username.lower()}.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"No database for user '{username}' at {db_path}")

    with connect(db_path) as conn:
        bal_items = get_all_balances(conn)
        balances = []
        ledgers: dict[str, Any] = {}
        for item in bal_items:
            c = item.get("contact") or {}
            bal = item.get("balance") or {}
            cid = c.get("id")
            row = {
                "contact_id": cid,
                "contact_name": c.get("name"),
                "net": _jsonable(bal.get("net")),
                "status": bal.get("status"),
                "they_owe_you": _jsonable(bal.get("they_owe_you")),
                "you_owe_them": _jsonable(bal.get("you_owe_them")),
                "entry_count": bal.get("entry_count"),
                "aliases": c.get("aliases") or [],
            }
            balances.append(row)
            if cid is not None:
                try:
                    led = get_ledger(conn, int(cid))
                    entries = list(reversed(led.get("entries") or []))[:80]
                    slim = []
                    for e in entries:
                        slim.append(
                            {
                                "date": e.get("entry_date"),
                                "direction": e.get("direction"),
                                "amount": _jsonable(e.get("amount")),
                                "purpose": e.get("purpose"),
                                "is_passthrough": bool(e.get("is_passthrough")),
                                "notes": e.get("notes"),
                                "running_balance": _jsonable(e.get("running_balance")),
                            }
                        )
                    b2 = led.get("balance") or {}
                    ledgers[str(cid)] = {
                        "contact": {
                            "id": (led.get("contact") or {}).get("id"),
                            "name": (led.get("contact") or {}).get("name"),
                        },
                        "balance": {
                            "net": _jsonable(b2.get("net")),
                            "status": b2.get("status"),
                        },
                        "entries": slim,
                    }
                except Exception:
                    pass

        txns = [_jsonable(dict(r)) for r in export_rows(conn)]
        # Cap for KV size
        if len(txns) > 5000:
            txns = txns[-5000:]

        dashboard = dashboard_summary_payload(conn, exclude_business=True)
        books = _slim_books(txns, ledgers)

    people = [b for b in balances if _looks_like_person(b.get("contact_name"))]
    return {
        "username": username.lower(),
        "balances": balances,
        "people": people,
        "ledgers": ledgers,
        "transactions": txns,
        "dashboard": dashboard,
        "books": books,
        "categories": list(CATEGORIES),
        "expense_types": list(EXPENSE_TYPES),
    }


_MERCHANT_RE = re.compile(
    r"utib|yesb|hdfc|sbin|payme|google|innovati|one97|branch|poweracces|chalokeral",
    re.I,
)


def _slim_books(txns: list, ledgers: dict) -> dict[str, Any]:
    from datetime import date, timedelta

    cut = (date.today() - timedelta(days=90)).isoformat()
    bank = []
    for t in reversed(list(txns or [])):
        d = str((t or {}).get("txn_date") or "")
        if d < cut:
            continue
        bank.append(
            {
                "date": d,
                "merchant": t.get("merchant_display") or t.get("description"),
                "debit": t.get("debit") or 0,
                "credit": t.get("credit") or 0,
                "category": t.get("category"),
            }
        )
        if len(bank) >= 800:
            break
    khata = []
    for led in (ledgers or {}).values():
        name = ((led.get("contact") or {}).get("name")) or ""
        for e in led.get("entries") or []:
            if e.get("is_passthrough"):
                continue
            khata.append(
                {
                    "contact_name": name,
                    "date": e.get("date") or e.get("entry_date"),
                    "direction": e.get("direction"),
                    "amount": e.get("amount") or 0,
                    "purpose": e.get("purpose"),
                }
            )
            if len(khata) >= 400:
                break
        if len(khata) >= 400:
            break
    return {"bank": bank, "khata": khata}


def _looks_like_person(name: str | None) -> bool:
    n = (name or "").strip()
    if not n or n.lower() == "branch":
        return False
    return _MERCHANT_RE.search(n) is None


def push_snapshot(
    snapshot: dict[str, Any],
    base_url: str,
    key: str,
    timeout: int = 120,
) -> dict[str, Any]:
    base = base_url.rstrip("/")
    url = f"{base}/sync?key={urllib.parse.quote(key)}"
    live = _live_bridge(snapshot.get("username") or "anand")
    if live:
        snapshot = {**snapshot, "live": live}
    body = json.dumps(snapshot).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Sync-Key": key,
            "Accept": "application/json",
            # Avoid CF Error 1010 (Python-urllib UA sometimes banned)
            "User-Agent": "expense-tracker-cloud-sync/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Sync HTTP {exc.code}: {err_body}") from exc


def sync_and_merge_pending(
    user: str,
    base: str,
    key: str,
    timeout: int = 120,
) -> dict[str, Any]:
    snap = build_snapshot(user)
    result = push_snapshot(snap, base, key, timeout=timeout)
    pending = result.get("pending_manual") or []
    if pending:
        from expense_tracker.db import add_manual_transaction

        db_path = _data_dir() / f"expenses_{user}.db"
        acked = []
        with connect(db_path) as conn:
            for item in pending:
                try:
                    add_manual_transaction(
                        conn,
                        txn_date=item.get("txn_date") or date.today().isoformat(),
                        description=item.get("description") or "Manual",
                        amount=Decimal(str(item.get("amount") or 0)),
                        direction=item.get("direction") or "debit",
                        category=item.get("category") or "Other",
                        expense_type=item.get("expense_type") or "Personal",
                        uploaded_by=user,
                    )
                    conn.commit()
                    acked.append(item.get("id"))
                except Exception as exc:
                    print(f"Error merging cloud manual entry: {exc}", file=sys.stderr)
        if acked:
            fresh_snap = build_snapshot(user)
            fresh_snap["ack_pending"] = acked
            result = push_snapshot(fresh_snap, base, key, timeout=timeout)
    return result


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    user = (
        (os.environ.get("EXPENSE_MCP_USER") or os.environ.get("EXPENSE_SYNC_USER") or "anand")
        .strip()
        .lower()
    )
    base = (os.environ.get("EXPENSE_MCP_URL") or "").strip()
    key = (os.environ.get("EXPENSE_MCP_KEY") or os.environ.get("MCP_KEY") or "").strip()

    # Optional: load from cloud-mcp/.env.local style file next to scripts
    cfg = _read_deploy_cfg()
    base = _good_hub(base or (cfg.get("url") or ""))
    key = key or (cfg.get("key") or "").strip()
    user = user or (cfg.get("username") or "anand")

    if argv and argv[0] in {"--register-live", "register-live"}:
        return register_live(user, base, key)

    if not base.startswith("https://"):
        print(
            "EXPENSE_MCP_URL must be the Worker HTTPS origin, e.g.\n"
            "  https://expense-tracker-mcp-hub.anandjcub-sb.workers.dev\n"
            f"Got: {base[:80]!r}\n"
            "Fix cloud-mcp/.deploy-config.json  url  (not the KV id).",
            file=sys.stderr,
        )
        return 2
    if not key:
        print("Set EXPENSE_MCP_KEY (same secret as Worker MCP_KEY).", file=sys.stderr)
        return 2

    print(f"Building snapshot for user={user} from {_data_dir()} ...")
    result = sync_and_merge_pending(user, base, key)
    print(json.dumps(result, indent=2))
    print("OK — cloud MCP can now read this snapshot.")
    print(f"Phone: {base.rstrip('/')}/app/?key={key}")
    return 0


HUB_DEFAULT = "https://expense-tracker-mcp-hub.anandjcub-sb.workers.dev"


def _good_hub(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("https://") and "workers.dev" in u:
        return u.rstrip("/")
    return HUB_DEFAULT


def _read_deploy_cfg() -> dict[str, Any]:
    path = _ROOT / "cloud-mcp" / ".deploy-config.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            return {}
        data["url"] = _good_hub(str(data.get("url") or ""))
        return data
    except Exception:
        return {}


def _merge_deploy_cfg(updates: dict[str, Any]) -> None:
    path = _ROOT / "cloud-mcp" / ".deploy-config.json"
    cfg = _read_deploy_cfg()
    cfg.update({k: v for k, v in updates.items() if v})
    cfg["url"] = _good_hub(str(cfg.get("url") or ""))
    if not cfg.get("key"):
        raise RuntimeError("Refusing to write deploy-config without key")
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def register_live(username: str, base: str, key: str) -> int:
    """Update Worker live URL after a new trycloudflare tunnel (no full snapshot)."""
    live = _live_bridge(username)
    if not live:
        print("No tunnel.url yet.", file=sys.stderr)
        return 2
    if not base.startswith("https://") or not key:
        print("Hub url/key missing in deploy-config.", file=sys.stderr)
        return 2
    url = f"{base.rstrip('/')}/sync/live?key={urllib.parse.quote(key)}"
    body = json.dumps({"url": live["url"], "token": live["token"]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Sync-Key": key,
            "User-Agent": "expense-tracker-cloud-sync/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
        print(raw or "OK")
        print(f"Live URL registered: {live['url']}")
        return 0
    except urllib.error.HTTPError as exc:
        print(f"register-live HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        return 1


def _live_bridge(username: str) -> dict[str, str] | None:
    """Public PC URL + Bearer so the Worker can use this machine when it is on."""
    url_file = _ROOT / "tunnel.url"
    live_url = (os.environ.get("EXPENSE_LIVE_URL") or "").strip()
    if url_file.is_file():
        live_url = live_url or url_file.read_text(encoding="utf-8").strip()
    if not live_url.startswith("https://"):
        return None
    cfg_path = _ROOT / "cloud-mcp" / ".deploy-config.json"
    token = ""
    cfg: dict[str, Any] = {}
    cfg = _read_deploy_cfg()
    token = str(cfg.get("live_token") or "").strip()
    if token and not verify_api_token(token):
        token = ""
    if not token:
        token = issue_local_api_token(username, label="cloud-hub", days_valid=365) or ""
        if token:
            _merge_deploy_cfg({"live_token": token})
    if not token:
        return None
    return {"url": live_url.rstrip("/"), "token": token}


def sync_user_safe(username: str) -> bool:
    try:
        user = (username or "anand").strip().lower()
        cfg = _read_deploy_cfg()
        base = _good_hub(os.environ.get("EXPENSE_MCP_URL") or cfg.get("url") or "")
        key = (os.environ.get("EXPENSE_MCP_KEY") or cfg.get("key") or "").strip()
        if not base.startswith("https://") or not key:
            return False
        sync_and_merge_pending(user, base, key, timeout=20)
        return True
    except Exception:
        return False


def trigger_cloud_sync_bg(username: str) -> None:
    import threading

    threading.Thread(target=sync_user_safe, args=(username,), daemon=True).start()


if __name__ == "__main__":
    raise SystemExit(main())

