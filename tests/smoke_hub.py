"""Surface smoke: local API + Worker REST + MCP. Run after every hub change.

    python tests/smoke_hub.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _cfg() -> dict:
    raw = (ROOT / "cloud-mcp" / ".deploy-config.json").read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    if not data.get("url") or not data.get("key"):
        raise SystemExit("deploy-config missing url/key")
    return data


def curl(args: list[str], timeout: int = 20, data: dict | None = None) -> tuple[int, str]:
    cmd = ["curl.exe", "-sS", "-w", "\n__HTTP__%{http_code}", "--max-time", str(timeout), *args]
    inp = json.dumps(data) if data is not None else None
    if data is not None:
        cmd[1:1] = []
    r = subprocess.run(cmd, input=inp, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    code = 0
    if "__HTTP__" in out:
        body, _, tail = out.rpartition("__HTTP__")
        out = body
        try:
            code = int(tail.strip()[:3])
        except ValueError:
            code = 0
    return code, out


def hub_get(cfg: dict, path: str, timeout: int = 15) -> tuple[int, str]:
    return curl(
        ["-H", f"X-Sync-Key: {cfg['key']}", f"{cfg['url'].rstrip('/')}{path}"],
        timeout,
    )


def hub_post(cfg: dict, path: str, payload: dict, timeout: int = 25) -> tuple[int, str]:
    return curl(
        [
            "-H",
            f"X-Sync-Key: {cfg['key']}",
            "-H",
            "Content-Type: application/json",
            "-H",
            "Accept: application/json, text/event-stream",
            "--data-binary",
            "@-",
            f"{cfg['url'].rstrip('/')}{path}",
        ],
        timeout,
        payload,
    )


def main() -> int:
    cfg = _cfg()
    fails: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(("OK  " if ok else "FAIL") + f" {name} {detail[:180]}")
        if not ok:
            fails.append(name)

    code, body = curl(["http://127.0.0.1:8765/api/health"], 8)
    check("local_health", code == 200 and "live" in body and "expense-tracker" in body, body)

    code, body = hub_get(cfg, "/health")
    check("hub_health", code == 200 and "expense-tracker-mcp-hub" in body, body)

    code, body = hub_get(cfg, "/api/health")
    check("hub_api_health", code == 200 and "writes" in body, body)

    code, body = hub_get(cfg, "/api/dashboard/summary")
    has_cat = "by_category" in body
    rupee_scale = "period_expense_share" in body
    check("hub_dashboard", code == 200 and has_cat and rupee_scale, body[:200])

    code, body = hub_get(cfg, "/api/settlement/summary")
    junk = any(x in body.lower() for x in ("utib", "yesb", "google utib"))
    check("hub_people_not_merchants", code == 200 and "contacts" in body and not junk, body[:240])

    code, body = hub_post(cfg, "/api/assistant/chat", {"message": "How much does Highnes owe me?"})
    check("ask_highnes", code == 200 and "Highnes" in body and ("157" in body or "owe" in body.lower()), body[:240])

    code, body = hub_post(
        cfg,
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        },
    )
    check("mcp_init", code == 200 and "expense-tracker" in body, body[:200])

    code, body = hub_post(
        cfg,
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_balance_for_person", "arguments": {"name_or_id": "Highnes"}},
        },
    )
    check("mcp_highnes", code == 200 and "Highnes" in body, body[:240])

    code, body = curl(
        [
            "-H",
            "Content-Type: application/json",
            "--data-binary",
            "@-",
            "http://127.0.0.1:8765/api/manual",
        ],
        8,
        {"amount": 1, "description": "smoke-no-date", "category": "Food"},
    )
    check("manual_no_date_not_isoformat", "isoformat" not in body.lower(), f"http={code} {body[:160]}")

    cfg2 = _cfg()
    check("deploy_config_has_url", bool(cfg2.get("url") and cfg2.get("key")))

    print("---")
    if fails:
        print("FAILED:", ", ".join(fails))
        return 1
    print("all smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
