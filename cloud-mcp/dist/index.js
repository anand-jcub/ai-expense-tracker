var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });

// src/mcp.js
var MCP_VERSION = "2025-03-26";
var SUPPORTED_VERSIONS = ["2025-11-25", "2025-03-26", "2024-11-05"];
var SNAPSHOT_KEY = "expense:v1:snapshot";
var MCP_CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Accept, Authorization, X-Sync-Key, Mcp-Session-Id, Last-Event-Id, MCP-Protocol-Version",
  "Access-Control-Expose-Headers": "Mcp-Session-Id, MCP-Protocol-Version",
  "Access-Control-Max-Age": "86400"
};
var TOOLS = [
  {
    name: "list_balances",
    description: "List khata (who-owes-whom) balances. net > 0 means they owe you; net < 0 means you owe them.",
    inputSchema: {
      type: "object",
      properties: {
        nonzero_only: {
          type: "boolean",
          description: "If true (default), only non-zero balances."
        }
      }
    }
  },
  {
    name: "get_balance_for_person",
    description: "Get khata balance for one person by name or contact id (e.g. Ranjima).",
    inputSchema: {
      type: "object",
      required: ["name_or_id"],
      properties: {
        name_or_id: {
          type: "string",
          description: "Contact name, alias, or numeric id."
        }
      }
    }
  },
  {
    name: "get_person_ledger",
    description: "Ledger history for a contact (newest first).",
    inputSchema: {
      type: "object",
      required: ["name_or_id"],
      properties: {
        name_or_id: { type: "string" },
        limit: { type: "number", description: "Max entries (default 20, max 40)." }
      }
    }
  },
  {
    name: "get_dashboard_summary",
    description: "Spend summary for a period (synced dashboard or derived from transactions).",
    inputSchema: {
      type: "object",
      properties: {
        start_date: { type: "string", description: "YYYY-MM-DD" },
        end_date: { type: "string", description: "YYYY-MM-DD" }
      }
    }
  },
  {
    name: "search_transactions",
    description: "Search bank transactions (merchant, description, category, notes). Prefer this over full export.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string" },
        start_date: { type: "string" },
        end_date: { type: "string" },
        limit: { type: "number", description: "Default 20, max 50." }
      }
    }
  },
  {
    name: "export_transactions",
    description: "Transaction export (same columns as dashboard download). Keep limit small (default 30).",
    inputSchema: {
      type: "object",
      properties: {
        start_date: { type: "string" },
        end_date: { type: "string" },
        query: { type: "string" },
        limit: { type: "number", description: "Default 30, max 100." },
        newest_first: { type: "boolean", description: "Default true." }
      }
    }
  },
  {
    name: "get_sync_status",
    description: "When data was last synced from the PC. If missing/stale, ask user to run sync-cloud.cmd.",
    inputSchema: { type: "object", properties: {} }
  }
];
function emptySnapshot() {
  return {
    username: null,
    syncedAt: null,
    balances: [],
    ledgers: {},
    transactions: [],
    dashboard: null
  };
}
__name(emptySnapshot, "emptySnapshot");
async function loadSnapshot(env) {
  if (!env.STORE) return emptySnapshot();
  const raw = await env.STORE.get(SNAPSHOT_KEY);
  if (!raw) return emptySnapshot();
  try {
    return { ...emptySnapshot(), ...JSON.parse(raw) };
  } catch {
    return emptySnapshot();
  }
}
__name(loadSnapshot, "loadSnapshot");
function extractKey(request) {
  const url = new URL(request.url);
  const headerKey = request.headers.get("X-Sync-Key") || "";
  const queryKey = url.searchParams.get("key") || "";
  const auth = request.headers.get("Authorization") || "";
  let bearer = "";
  if (auth.toLowerCase().startsWith("bearer ")) {
    bearer = auth.slice(7).trim();
  }
  return headerKey || queryKey || bearer || "";
}
__name(extractKey, "extractKey");
function checkAuth(request, env) {
  const key = extractKey(request);
  const expected = env.MCP_KEY || env.SYNC_KEY || "";
  if (!expected || key !== expected) {
    return jsonResponse(
      {
        jsonrpc: "2.0",
        id: null,
        error: {
          code: -32001,
          message: "Unauthorized. Pass ?key=YOUR_MCP_KEY, X-Sync-Key header, or Authorization: Bearer."
        }
      },
      401
    );
  }
  return null;
}
__name(checkAuth, "checkAuth");
function jsonResponse(obj, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...MCP_CORS,
      ...extraHeaders
    }
  });
}
__name(jsonResponse, "jsonResponse");
function rpcResponse(result, request, extraHeaders = {}) {
  if (result === null) {
    return new Response(null, { status: 202, headers: { ...MCP_CORS, ...extraHeaders } });
  }
  const accept = (request.headers.get("Accept") || "").toLowerCase();
  const preferSse = accept.includes("text/event-stream") && !accept.includes("application/json") ? true : accept.includes("text/event-stream");
  const first = accept.split(",")[0]?.trim() || "";
  const useSse = first.startsWith("text/event-stream") || request.headers.get("X-MCP-Response") === "sse";
  if (useSse || preferSse && !accept.includes("application/json")) {
    const payload = `event: message
data: ${JSON.stringify(result)}

`;
    return new Response(payload, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        ...MCP_CORS,
        ...extraHeaders
      }
    });
  }
  return jsonResponse(result, 200, extraHeaders);
}
__name(rpcResponse, "rpcResponse");
function newSessionId() {
  const a = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}
__name(newSessionId, "newSessionId");
function negotiateVersion(clientVersion) {
  const v = String(clientVersion || "").trim();
  if (SUPPORTED_VERSIONS.includes(v)) return v;
  return MCP_VERSION;
}
__name(negotiateVersion, "negotiateVersion");
function requireData(snap) {
  if (!snap.syncedAt) {
    return {
      error: "No data synced yet. On the PC run sync-cloud.cmd then retry."
    };
  }
  return null;
}
__name(requireData, "requireData");
function matchContact(snap, nameOrId) {
  const raw = String(nameOrId || "").trim();
  if (!raw) return null;
  if (/^\d+$/.test(raw)) {
    const id = Number(raw);
    const bal = (snap.balances || []).find((b) => Number(b.contact_id) === id);
    if (bal) return bal;
    const led = snap.ledgers?.[String(id)];
    if (led?.contact) {
      return {
        contact_id: led.contact.id,
        contact_name: led.contact.name,
        net: led.balance?.net,
        status: led.balance?.status
      };
    }
  }
  const q = raw.toLowerCase();
  const balances = snap.balances || [];
  let hit = balances.find((b) => String(b.contact_name || "").toLowerCase() === q);
  if (hit) return hit;
  hit = balances.find(
    (b) => String(b.contact_name || "").toLowerCase().includes(q)
  );
  if (hit) return hit;
  hit = balances.find(
    (b) => (b.aliases || []).some((a) => String(a).toLowerCase().includes(q))
  );
  return hit || null;
}
__name(matchContact, "matchContact");
function filterTxns(txns, { start_date, end_date, query, limit, newest_first }) {
  let rows = Array.isArray(txns) ? [...txns] : [];
  if (newest_first !== false) {
    rows.sort((a, b) => String(b.txn_date || "").localeCompare(String(a.txn_date || "")));
  }
  const start = (start_date || "").trim();
  const end = (end_date || "").trim();
  const q = (query || "").trim().toLowerCase();
  const out = [];
  const cap = Math.max(1, Math.min(Number(limit) || 30, 100));
  for (const row of rows) {
    const d = String(row.txn_date || "");
    if (start && d < start) continue;
    if (end && d > end) continue;
    if (q) {
      const blob = [
        row.merchant_display,
        row.description,
        row.category,
        row.expense_type,
        row.notes,
        row.reference
      ].map((x) => String(x || "")).join(" ").toLowerCase();
      if (!blob.includes(q)) continue;
    }
    out.push(row);
    if (out.length >= cap) break;
  }
  return out;
}
__name(filterTxns, "filterTxns");
function slimTxn(t) {
  return {
    id: t.id,
    date: t.txn_date,
    merchant: t.merchant_display,
    debit: Number(t.debit || 0),
    credit: Number(t.credit || 0),
    category: t.category,
    type: t.expense_type,
    notes: t.notes || void 0
  };
}
__name(slimTxn, "slimTxn");
function dispatchTool(name, args, snap) {
  const missing = requireData(snap);
  if (missing && name !== "get_sync_status") return missing;
  switch (name) {
    case "get_sync_status":
      return {
        username: snap.username,
        syncedAt: snap.syncedAt,
        balance_count: (snap.balances || []).length,
        transaction_count: (snap.transactions || []).length,
        ledger_contact_count: Object.keys(snap.ledgers || {}).length,
        has_data: Boolean(snap.syncedAt),
        note: snap.syncedAt ? "Cloud AI reads this snapshot. Re-run sync-cloud.cmd after new imports." : "No snapshot \u2014 run sync-cloud.cmd on the PC."
      };
    case "list_balances": {
      const nonzero = args.nonzero_only !== false;
      let items = snap.balances || [];
      if (nonzero) items = items.filter((b) => Number(b.net || 0) !== 0);
      items = [...items].sort((a, b) => Math.abs(Number(b.net || 0)) - Math.abs(Number(a.net || 0))).slice(0, 40).map((b) => ({
        contact_id: b.contact_id,
        contact_name: b.contact_name,
        net: b.net,
        status: b.status,
        they_owe_you: b.they_owe_you,
        you_owe_them: b.you_owe_them,
        entry_count: b.entry_count
      }));
      return { count: items.length, balances: items };
    }
    case "get_balance_for_person": {
      const hit = matchContact(snap, args.name_or_id);
      if (!hit) return { error: `No contact matching ${JSON.stringify(args.name_or_id)}` };
      const net = Number(hit.net || 0);
      const cname = hit.contact_name || "They";
      let answer;
      if (net > 0) answer = `${cname} owes you \u20B9${net.toLocaleString("en-IN")}.`;
      else if (net < 0) answer = `You owe ${cname} \u20B9${Math.abs(net).toLocaleString("en-IN")}.`;
      else answer = `${cname} is settled (\u20B90).`;
      return {
        contact_id: hit.contact_id,
        contact_name: hit.contact_name,
        net: hit.net,
        status: hit.status,
        they_owe_you: hit.they_owe_you,
        you_owe_them: hit.you_owe_them,
        entry_count: hit.entry_count,
        answer
      };
    }
    case "get_person_ledger": {
      const hit = matchContact(snap, args.name_or_id);
      if (!hit) return { error: `No contact matching ${JSON.stringify(args.name_or_id)}` };
      const id = String(hit.contact_id);
      const led = snap.ledgers?.[id] || {
        contact: { id: hit.contact_id, name: hit.contact_name },
        balance: { net: hit.net, status: hit.status },
        entries: []
      };
      const lim = Math.max(1, Math.min(Number(args.limit) || 20, 40));
      return {
        contact: led.contact,
        balance: led.balance,
        entries: (led.entries || []).slice(0, lim)
      };
    }
    case "get_dashboard_summary": {
      if (snap.dashboard && !args.start_date && !args.end_date) {
        return { ...snap.dashboard, username: snap.username, source: "synced_dashboard" };
      }
      const rows = filterTxns(snap.transactions || [], {
        start_date: args.start_date,
        end_date: args.end_date,
        limit: 5e3,
        newest_first: false
      });
      let debits = 0;
      let credits = 0;
      for (const t of rows) {
        debits += Number(t.debit || 0);
        credits += Number(t.credit || 0);
      }
      return {
        username: snap.username,
        start_date: args.start_date || null,
        end_date: args.end_date || null,
        period_debits: debits,
        period_credits: credits,
        transaction_count: rows.length,
        source: "derived_from_transactions"
      };
    }
    case "search_transactions": {
      const lim = Math.max(1, Math.min(Number(args.limit) || 20, 50));
      const rows = filterTxns(snap.transactions || [], {
        start_date: args.start_date,
        end_date: args.end_date,
        query: args.query || "",
        limit: lim,
        newest_first: true
      });
      return { count: rows.length, transactions: rows.map(slimTxn) };
    }
    case "export_transactions": {
      const lim = Math.max(1, Math.min(Number(args.limit) || 30, 100));
      const rows = filterTxns(snap.transactions || [], {
        start_date: args.start_date,
        end_date: args.end_date,
        query: args.query || "",
        limit: lim,
        newest_first: args.newest_first !== false
      });
      return {
        username: snap.username,
        count: rows.length,
        start_date: args.start_date || null,
        end_date: args.end_date || null,
        query: args.query || null,
        transactions: rows.map(slimTxn),
        note: "Slim export for cloud AI. Use start_date/end_date/query to focus."
      };
    }
    default:
      return { error: `Unknown tool: ${name}` };
  }
}
__name(dispatchTool, "dispatchTool");
async function handleJsonRpc(body, env) {
  const id = Object.prototype.hasOwnProperty.call(body, "id") ? body.id : null;
  const method = String(body.method || "");
  if (id === null && method && method.startsWith("notifications/")) {
    return null;
  }
  if (!Object.prototype.hasOwnProperty.call(body, "id") && method.startsWith("notifications/")) {
    return null;
  }
  try {
    switch (method) {
      case "initialize": {
        const clientVersion = body.params?.protocolVersion;
        const protocolVersion = negotiateVersion(clientVersion);
        return {
          jsonrpc: "2.0",
          id,
          result: {
            protocolVersion,
            capabilities: {
              tools: { listChanged: false },
              resources: { listChanged: false },
              prompts: { listChanged: false }
            },
            serverInfo: { name: "expense-tracker", version: "1.1.0" },
            instructions: "Personal expense + khata. net > 0 means they owe the user. Prefer list_balances, get_balance_for_person, search_transactions (small limits). Call get_sync_status if data looks stale."
          }
        };
      }
      case "notifications/initialized":
      case "notifications/cancelled":
      case "notifications/progress":
        return null;
      case "ping":
        return { jsonrpc: "2.0", id, result: {} };
      case "tools/list":
        return { jsonrpc: "2.0", id, result: { tools: TOOLS } };
      case "tools/call": {
        const toolName = body.params?.name;
        const toolArgs = body.params?.arguments || {};
        if (!toolName) throw new Error("params.name (tool name) is required");
        const snap = await loadSnapshot(env);
        const result = dispatchTool(toolName, toolArgs, snap);
        const text = JSON.stringify(result);
        return {
          jsonrpc: "2.0",
          id,
          result: {
            content: [{ type: "text", text }],
            isError: Boolean(result?.error)
          }
        };
      }
      case "resources/list":
        return {
          jsonrpc: "2.0",
          id,
          result: {
            resources: [
              {
                uri: "expense://balances",
                name: "Khata balances",
                mimeType: "application/json"
              },
              {
                uri: "expense://sync-status",
                name: "Sync status",
                mimeType: "application/json"
              }
            ]
          }
        };
      case "resources/read": {
        const uri = String(body.params?.uri || "");
        const snap = await loadSnapshot(env);
        let content;
        if (uri.includes("sync")) content = JSON.stringify(dispatchTool("get_sync_status", {}, snap));
        else content = JSON.stringify(dispatchTool("list_balances", {}, snap));
        return {
          jsonrpc: "2.0",
          id,
          result: { contents: [{ uri, mimeType: "application/json", text: content }] }
        };
      }
      case "prompts/list":
        return {
          jsonrpc: "2.0",
          id,
          result: {
            prompts: [
              {
                name: "money_briefing",
                description: "Who owes what + recent spend summary."
              }
            ]
          }
        };
      case "prompts/get": {
        if (body.params?.name === "money_briefing") {
          return {
            jsonrpc: "2.0",
            id,
            result: {
              description: "Money briefing",
              messages: [
                {
                  role: "user",
                  content: {
                    type: "text",
                    text: "Call get_sync_status, list_balances, and get_dashboard_summary. Summarise who owes money and recent spending."
                  }
                }
              ]
            }
          };
        }
        throw new Error(`Unknown prompt: ${body.params?.name}`);
      }
      default:
        return {
          jsonrpc: "2.0",
          id,
          error: { code: -32601, message: `Method not found: ${method}` }
        };
    }
  } catch (err) {
    return {
      jsonrpc: "2.0",
      id,
      error: { code: -32603, message: String(err.message || err) }
    };
  }
}
__name(handleJsonRpc, "handleJsonRpc");
async function handleMcp(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: MCP_CORS });
  }
  const denied = checkAuth(request, env);
  if (denied) return denied;
  const syncKey = extractKey(request);
  let sessionId = request.headers.get("Mcp-Session-Id") || "";
  if (request.method === "DELETE") {
    return new Response(null, { status: 200, headers: MCP_CORS });
  }
  if (request.method === "GET") {
    const accept = request.headers.get("Accept") || "";
    if (accept.includes("text/event-stream")) {
      const endpointUrl = `${url.origin}/mcp?key=${encodeURIComponent(syncKey)}`;
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(
            encoder.encode(
              `event: endpoint
data: ${JSON.stringify({ uri: endpointUrl })}

`
            )
          );
          controller.enqueue(encoder.encode(`: keepalive

`));
          controller.close();
        }
      });
      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
          ...MCP_CORS,
          ...sessionId ? { "Mcp-Session-Id": sessionId } : {}
        }
      });
    }
    const snap = await loadSnapshot(env);
    return jsonResponse({
      service: "expense-tracker-mcp",
      version: "1.1.0",
      protocol: MCP_VERSION,
      supportedProtocols: SUPPORTED_VERSIONS,
      transport: "Streamable HTTP (POST /mcp)",
      syncedAt: snap.syncedAt,
      username: snap.username,
      tools: TOOLS.map((t) => ({ name: t.name, description: t.description })),
      connect: `Gemini Spark \u2192 Connected Apps: ${url.origin}/mcp?key=YOUR_MCP_KEY`
    });
  }
  if (request.method === "POST") {
    let body;
    try {
      body = await request.json();
    } catch {
      return jsonResponse(
        { jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } },
        400
      );
    }
    const isInit = !Array.isArray(body) && String(body.method || "") === "initialize";
    if (isInit && !sessionId) {
      sessionId = newSessionId();
    }
    const extra = {};
    if (sessionId) extra["Mcp-Session-Id"] = sessionId;
    if (isInit) {
      const negotiated = negotiateVersion(body.params?.protocolVersion);
      extra["MCP-Protocol-Version"] = negotiated;
    }
    if (Array.isArray(body)) {
      const results = await Promise.all(body.map((req) => handleJsonRpc(req, env)));
      const responses = results.filter((r) => r !== null);
      if (responses.length === 0) {
        return new Response(null, { status: 202, headers: { ...MCP_CORS, ...extra } });
      }
      return rpcResponse(responses, request, extra);
    }
    const result = await handleJsonRpc(body, env);
    return rpcResponse(result, request, extra);
  }
  return jsonResponse({ error: "Method not allowed" }, 405);
}
__name(handleMcp, "handleMcp");
async function handleSync(request, env) {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: MCP_CORS });
  }
  const denied = checkAuth(request, env);
  if (denied) return denied;
  if (request.method !== "POST") {
    return jsonResponse({ error: "POST a snapshot JSON body" }, 405);
  }
  if (!env.STORE) {
    return jsonResponse({ error: "KV STORE binding missing" }, 500);
  }
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "Invalid JSON" }, 400);
  }
  const snap = {
    username: body.username || null,
    syncedAt: (/* @__PURE__ */ new Date()).toISOString(),
    balances: Array.isArray(body.balances) ? body.balances : [],
    ledgers: body.ledgers && typeof body.ledgers === "object" ? body.ledgers : {},
    transactions: Array.isArray(body.transactions) ? body.transactions.slice(0, 5e3) : [],
    dashboard: body.dashboard || null
  };
  await env.STORE.put(SNAPSHOT_KEY, JSON.stringify(snap));
  return jsonResponse({
    ok: true,
    syncedAt: snap.syncedAt,
    username: snap.username,
    balance_count: snap.balances.length,
    transaction_count: snap.transactions.length,
    ledger_contact_count: Object.keys(snap.ledgers).length
  });
}
__name(handleSync, "handleSync");

// src/index.js
var index_default = {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    if (path === "/health" || path === "/") {
      return new Response(
        JSON.stringify({
          ok: true,
          service: "expense-tracker-mcp-hub",
          build: "2026-08-13-v1.1.1",
          mcp: "/mcp?key=YOUR_MCP_KEY",
          sync: "POST /sync with X-Sync-Key or ?key="
        }),
        { headers: { "Content-Type": "application/json" } }
      );
    }
    if (path === "/mcp") {
      return handleMcp(request, env);
    }
    if (path === "/sync") {
      return handleSync(request, env);
    }
    return new Response(JSON.stringify({ error: "Not found", paths: ["/health", "/mcp", "/sync"] }), {
      status: 404,
      headers: { "Content-Type": "application/json" }
    });
  }
};
export {
  index_default as default
};
//# sourceMappingURL=index.js.map
