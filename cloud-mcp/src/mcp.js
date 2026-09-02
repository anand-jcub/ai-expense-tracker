/**
 * Expense Tracker — Streamable HTTP MCP (Gemini Spark compatible).
 *
 * Spec: MCP Streamable HTTP (2025-03-26+)
 * Auth: ?key= | X-Sync-Key | Authorization: Bearer
 * Data: KV snapshot from PC (POST /sync)
 */

const MCP_VERSION = '2025-03-26';
const SUPPORTED_VERSIONS = ['2025-11-25', '2025-03-26', '2024-11-05'];
const SNAPSHOT_KEY = 'expense:v1:snapshot';
const GLANCE_KEY = 'expense:v1:glance';
const LIVE_KEY = 'expense:v1:live';

const MCP_CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
  'Access-Control-Allow-Headers':
    'Content-Type, Accept, Authorization, X-Sync-Key, Mcp-Session-Id, Last-Event-Id, MCP-Protocol-Version',
  'Access-Control-Expose-Headers': 'Mcp-Session-Id, MCP-Protocol-Version',
  'Access-Control-Max-Age': '86400',
};

const TOOLS = [
  {
    name: 'list_balances',
    description:
      'List khata (who-owes-whom) balances. net > 0 means they owe you; net < 0 means you owe them.',
    inputSchema: {
      type: 'object',
      properties: {
        nonzero_only: {
          type: 'boolean',
          description: 'If true (default), only non-zero balances.',
        },
      },
    },
  },
  {
    name: 'get_balance_for_person',
    description: 'Get khata balance for one person by name or contact id (e.g. Ranjima).',
    inputSchema: {
      type: 'object',
      required: ['name_or_id'],
      properties: {
        name_or_id: {
          type: 'string',
          description: 'Contact name, alias, or numeric id.',
        },
      },
    },
  },
  {
    name: 'get_person_ledger',
    description: 'Ledger history for a contact (newest first).',
    inputSchema: {
      type: 'object',
      required: ['name_or_id'],
      properties: {
        name_or_id: { type: 'string' },
        limit: { type: 'number', description: 'Max entries (default 20, max 40).' },
      },
    },
  },
  {
    name: 'get_dashboard_summary',
    description: 'Spend summary for a period (synced dashboard or derived from transactions).',
    inputSchema: {
      type: 'object',
      properties: {
        start_date: { type: 'string', description: 'YYYY-MM-DD' },
        end_date: { type: 'string', description: 'YYYY-MM-DD' },
      },
    },
  },
  {
    name: 'search_transactions',
    description:
      'Search bank transactions (merchant, description, category, notes). Prefer this over full export.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string' },
        start_date: { type: 'string' },
        end_date: { type: 'string' },
        limit: { type: 'number', description: 'Default 20, max 50.' },
      },
    },
  },
  {
    name: 'export_transactions',
    description:
      'Transaction export (same columns as dashboard download). Keep limit small (default 30).',
    inputSchema: {
      type: 'object',
      properties: {
        start_date: { type: 'string' },
        end_date: { type: 'string' },
        query: { type: 'string' },
        limit: { type: 'number', description: 'Default 30, max 100.' },
        newest_first: { type: 'boolean', description: 'Default true.' },
      },
    },
  },
  {
    name: 'get_sync_status',
    description:
      'When data was last synced from the PC. If missing/stale, ask user to run sync-cloud.cmd.',
    inputSchema: { type: 'object', properties: {} },
  },
];

function emptySnapshot() {
  return {
    username: null,
    syncedAt: null,
    balances: [],
    ledgers: {},
    transactions: [],
    dashboard: null,
  };
}

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

export { SNAPSHOT_KEY, GLANCE_KEY, LIVE_KEY, MCP_CORS, extractKey, checkAuth, jsonResponse };

function extractKey(request) {
  const url = new URL(request.url);
  const headerKey = request.headers.get('X-Sync-Key') || '';
  const queryKey = url.searchParams.get('key') || '';
  const auth = request.headers.get('Authorization') || '';
  let bearer = '';
  if (auth.toLowerCase().startsWith('bearer ')) {
    bearer = auth.slice(7).trim();
  }
  return headerKey || queryKey || bearer || '';
}

function checkAuth(request, env) {
  const key = extractKey(request);
  const expected = env.MCP_KEY || env.SYNC_KEY || '';
  if (!expected || key !== expected) {
    return jsonResponse(
      {
        jsonrpc: '2.0',
        id: null,
        error: {
          code: -32001,
          message:
            'Unauthorized. Pass ?key=YOUR_MCP_KEY, X-Sync-Key header, or Authorization: Bearer.',
        },
      },
      401
    );
  }
  return null;
}

function jsonResponse(obj, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...MCP_CORS,
      ...extraHeaders,
    },
  });
}

/** Streamable HTTP: when client Accept includes event-stream, return SSE message event. */
function rpcResponse(result, request, extraHeaders = {}) {
  if (result === null) {
    return new Response(null, { status: 202, headers: { ...MCP_CORS, ...extraHeaders } });
  }
  const accept = (request.headers.get('Accept') || '').toLowerCase();
  const preferSse =
    accept.includes('text/event-stream') && !accept.includes('application/json')
      ? true
      : accept.includes('text/event-stream');

  // Gemini often sends Accept: application/json, text/event-stream — prefer JSON
  // unless only event-stream is listed first without json... Spec allows either.
  // Use JSON by default for reliability; use SSE if Accept is ONLY event-stream
  // OR if X-Prefer-Sse is set. Actually Gemini Spark may require SSE for streamable HTTP.
  // Compromise: if Accept includes event-stream AND method was tools/call, use SSE.
  // Safer: always support both; use SSE when Accept lists event-stream as primary.
  const first = accept.split(',')[0]?.trim() || '';
  const useSse = first.startsWith('text/event-stream') || request.headers.get('X-MCP-Response') === 'sse';

  if (useSse || (preferSse && !accept.includes('application/json'))) {
    const payload = `event: message\ndata: ${JSON.stringify(result)}\n\n`;
    return new Response(payload, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
        ...MCP_CORS,
        ...extraHeaders,
      },
    });
  }

  return jsonResponse(result, 200, extraHeaders);
}

function newSessionId() {
  const a = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(a, (b) => b.toString(16).padStart(2, '0')).join('');
}

function negotiateVersion(clientVersion) {
  const v = String(clientVersion || '').trim();
  if (SUPPORTED_VERSIONS.includes(v)) return v;
  return MCP_VERSION;
}

function requireData(snap) {
  if (!snap.syncedAt) {
    return {
      error:
        'No data synced yet. On the PC run sync-cloud.cmd then retry.',
    };
  }
  return null;
}

function matchContact(snap, nameOrId) {
  const raw = String(nameOrId || '').trim();
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
        status: led.balance?.status,
      };
    }
  }
  const q = raw.toLowerCase();
  const balances = snap.balances || [];
  let hit = balances.find((b) => String(b.contact_name || '').toLowerCase() === q);
  if (hit) return hit;
  hit = balances.find((b) =>
    String(b.contact_name || '')
      .toLowerCase()
      .includes(q)
  );
  if (hit) return hit;
  hit = balances.find((b) =>
    (b.aliases || []).some((a) => String(a).toLowerCase().includes(q))
  );
  return hit || null;
}

function filterTxns(txns, { start_date, end_date, query, limit, newest_first }) {
  let rows = Array.isArray(txns) ? [...txns] : [];
  if (newest_first !== false) {
    rows.sort((a, b) => String(b.txn_date || '').localeCompare(String(a.txn_date || '')));
  }
  const start = (start_date || '').trim();
  const end = (end_date || '').trim();
  const q = (query || '').trim().toLowerCase();
  const out = [];
  const cap = Math.max(1, Math.min(Number(limit) || 30, 100));
  for (const row of rows) {
    const d = String(row.txn_date || '');
    if (start && d < start) continue;
    if (end && d > end) continue;
    if (q) {
      const blob = [
        row.merchant_display,
        row.description,
        row.category,
        row.expense_type,
        row.notes,
        row.reference,
      ]
        .map((x) => String(x || ''))
        .join(' ')
        .toLowerCase();
      if (!blob.includes(q)) continue;
    }
    out.push(row);
    if (out.length >= cap) break;
  }
  return out;
}

function slimTxn(t) {
  return {
    id: t.id,
    date: t.txn_date,
    merchant: t.merchant_display,
    debit: Number(t.debit || 0),
    credit: Number(t.credit || 0),
    category: t.category,
    type: t.expense_type,
    notes: t.notes || undefined,
  };
}

function dispatchTool(name, args, snap) {
  const missing = requireData(snap);
  if (missing && name !== 'get_sync_status') return missing;

  switch (name) {
    case 'get_sync_status':
      return {
        username: snap.username,
        syncedAt: snap.syncedAt,
        balance_count: (snap.balances || []).length,
        transaction_count: (snap.transactions || []).length,
        ledger_contact_count: Object.keys(snap.ledgers || {}).length,
        has_data: Boolean(snap.syncedAt),
        note: snap.syncedAt
          ? 'Cloud AI reads this snapshot. Re-run sync-cloud.cmd after new imports.'
          : 'No snapshot — run sync-cloud.cmd on the PC.',
      };

    case 'list_balances': {
      const nonzero = args.nonzero_only !== false;
      let items = snap.balances || [];
      if (nonzero) items = items.filter((b) => Number(b.net || 0) !== 0);
      items = [...items]
        .sort((a, b) => Math.abs(Number(b.net || 0)) - Math.abs(Number(a.net || 0)))
        .slice(0, 40)
        .map((b) => ({
          contact_id: b.contact_id,
          contact_name: b.contact_name,
          net: b.net,
          status: b.status,
          they_owe_you: b.they_owe_you,
          you_owe_them: b.you_owe_them,
          entry_count: b.entry_count,
        }));
      return { count: items.length, balances: items };
    }

    case 'get_balance_for_person': {
      const hit = matchContact(snap, args.name_or_id);
      if (!hit) return { error: `No contact matching ${JSON.stringify(args.name_or_id)}` };
      const net = Number(hit.net || 0);
      const cname = hit.contact_name || 'They';
      let answer;
      if (net > 0) answer = `${cname} owes you ₹${net.toLocaleString('en-IN')}.`;
      else if (net < 0) answer = `You owe ${cname} ₹${Math.abs(net).toLocaleString('en-IN')}.`;
      else answer = `${cname} is settled (₹0).`;
      return {
        contact_id: hit.contact_id,
        contact_name: hit.contact_name,
        net: hit.net,
        status: hit.status,
        they_owe_you: hit.they_owe_you,
        you_owe_them: hit.you_owe_them,
        entry_count: hit.entry_count,
        answer,
      };
    }

    case 'get_person_ledger': {
      const hit = matchContact(snap, args.name_or_id);
      if (!hit) return { error: `No contact matching ${JSON.stringify(args.name_or_id)}` };
      const id = String(hit.contact_id);
      const led = snap.ledgers?.[id] || {
        contact: { id: hit.contact_id, name: hit.contact_name },
        balance: { net: hit.net, status: hit.status },
        entries: [],
      };
      const lim = Math.max(1, Math.min(Number(args.limit) || 20, 40));
      return {
        contact: led.contact,
        balance: led.balance,
        entries: (led.entries || []).slice(0, lim),
      };
    }

    case 'get_dashboard_summary': {
      if (snap.dashboard && !args.start_date && !args.end_date) {
        return { ...snap.dashboard, username: snap.username, source: 'synced_dashboard' };
      }
      const rows = filterTxns(snap.transactions || [], {
        start_date: args.start_date,
        end_date: args.end_date,
        limit: 5000,
        newest_first: false,
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
        source: 'derived_from_transactions',
      };
    }

    case 'search_transactions': {
      const lim = Math.max(1, Math.min(Number(args.limit) || 20, 50));
      const rows = filterTxns(snap.transactions || [], {
        start_date: args.start_date,
        end_date: args.end_date,
        query: args.query || '',
        limit: lim,
        newest_first: true,
      });
      return { count: rows.length, transactions: rows.map(slimTxn) };
    }

    case 'export_transactions': {
      const lim = Math.max(1, Math.min(Number(args.limit) || 30, 100));
      const rows = filterTxns(snap.transactions || [], {
        start_date: args.start_date,
        end_date: args.end_date,
        query: args.query || '',
        limit: lim,
        newest_first: args.newest_first !== false,
      });
      return {
        username: snap.username,
        count: rows.length,
        start_date: args.start_date || null,
        end_date: args.end_date || null,
        query: args.query || null,
        transactions: rows.map(slimTxn),
        note: 'Slim export for cloud AI. Use start_date/end_date/query to focus.',
      };
    }

    default:
      return { error: `Unknown tool: ${name}` };
  }
}

async function handleJsonRpc(body, env) {
  const id = Object.prototype.hasOwnProperty.call(body, 'id') ? body.id : null;
  const method = String(body.method || '');

  // Notifications (no id) → no JSON-RPC response body (HTTP 202)
  if (id === null && method && method.startsWith('notifications/')) {
    return null;
  }
  // Some clients send notifications without id field at all
  if (!Object.prototype.hasOwnProperty.call(body, 'id') && method.startsWith('notifications/')) {
    return null;
  }

  try {
    switch (method) {
      case 'initialize': {
        const clientVersion = body.params?.protocolVersion;
        const protocolVersion = negotiateVersion(clientVersion);
        return {
          jsonrpc: '2.0',
          id,
          result: {
            protocolVersion,
            capabilities: {
              tools: { listChanged: false },
              resources: { listChanged: false },
              prompts: { listChanged: false },
            },
            serverInfo: { name: 'expense-tracker', version: '1.1.0' },
            instructions:
              'Personal expense + khata. net > 0 means they owe the user. Prefer list_balances, get_balance_for_person, search_transactions (small limits). Call get_sync_status if data looks stale.',
          },
        };
      }

      case 'notifications/initialized':
      case 'notifications/cancelled':
      case 'notifications/progress':
        return null;

      case 'ping':
        return { jsonrpc: '2.0', id, result: {} };

      case 'tools/list':
        return { jsonrpc: '2.0', id, result: { tools: TOOLS } };

      case 'tools/call': {
        const toolName = body.params?.name;
        const toolArgs = body.params?.arguments || {};
        if (!toolName) throw new Error('params.name (tool name) is required');
        const snap = await loadSnapshot(env);
        const result = dispatchTool(toolName, toolArgs, snap);
        // Compact JSON — large pretty-print payloads break Gemini Spark mid-session
        const text = JSON.stringify(result);
        return {
          jsonrpc: '2.0',
          id,
          result: {
            content: [{ type: 'text', text }],
            isError: Boolean(result?.error),
          },
        };
      }

      case 'resources/list':
        return {
          jsonrpc: '2.0',
          id,
          result: {
            resources: [
              {
                uri: 'expense://balances',
                name: 'Khata balances',
                mimeType: 'application/json',
              },
              {
                uri: 'expense://sync-status',
                name: 'Sync status',
                mimeType: 'application/json',
              },
            ],
          },
        };

      case 'resources/read': {
        const uri = String(body.params?.uri || '');
        const snap = await loadSnapshot(env);
        let content;
        if (uri.includes('sync')) content = JSON.stringify(dispatchTool('get_sync_status', {}, snap));
        else content = JSON.stringify(dispatchTool('list_balances', {}, snap));
        return {
          jsonrpc: '2.0',
          id,
          result: { contents: [{ uri, mimeType: 'application/json', text: content }] },
        };
      }

      case 'prompts/list':
        return {
          jsonrpc: '2.0',
          id,
          result: {
            prompts: [
              {
                name: 'money_briefing',
                description: 'Who owes what + recent spend summary.',
              },
            ],
          },
        };

      case 'prompts/get': {
        if (body.params?.name === 'money_briefing') {
          return {
            jsonrpc: '2.0',
            id,
            result: {
              description: 'Money briefing',
              messages: [
                {
                  role: 'user',
                  content: {
                    type: 'text',
                    text: 'Call get_sync_status, list_balances, and get_dashboard_summary. Summarise who owes money and recent spending.',
                  },
                },
              ],
            },
          };
        }
        throw new Error(`Unknown prompt: ${body.params?.name}`);
      }

      default:
        return {
          jsonrpc: '2.0',
          id,
          error: { code: -32601, message: `Method not found: ${method}` },
        };
    }
  } catch (err) {
    return {
      jsonrpc: '2.0',
      id,
      error: { code: -32603, message: String(err.message || err) },
    };
  }
}

export async function handleMcp(request, env) {
  const url = new URL(request.url);

  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: MCP_CORS });
  }

  const denied = checkAuth(request, env);
  if (denied) return denied;

  const syncKey = extractKey(request);
  let sessionId = request.headers.get('Mcp-Session-Id') || '';

  // DELETE — session terminate (optional)
  if (request.method === 'DELETE') {
    return new Response(null, { status: 200, headers: MCP_CORS });
  }

  // GET — SSE stream or info
  if (request.method === 'GET') {
    const accept = request.headers.get('Accept') || '';
    if (accept.includes('text/event-stream')) {
      // Keep stream open briefly with endpoint event (Streamable HTTP / legacy hybrid)
      const endpointUrl = `${url.origin}/mcp?key=${encodeURIComponent(syncKey)}`;
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(
            encoder.encode(
              `event: endpoint\ndata: ${JSON.stringify({ uri: endpointUrl })}\n\n`
            )
          );
          // Keep-alive comment so clients don't treat stream as instantly dead
          controller.enqueue(encoder.encode(`: keepalive\n\n`));
          // Close after open — stateless; client uses POST for work
          controller.close();
        },
      });
      return new Response(stream, {
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
          ...MCP_CORS,
          ...(sessionId ? { 'Mcp-Session-Id': sessionId } : {}),
        },
      });
    }
    const snap = await loadSnapshot(env);
    return jsonResponse({
      service: 'expense-tracker-mcp',
      version: '1.1.0',
      protocol: MCP_VERSION,
      supportedProtocols: SUPPORTED_VERSIONS,
      transport: 'Streamable HTTP (POST /mcp)',
      syncedAt: snap.syncedAt,
      username: snap.username,
      tools: TOOLS.map((t) => ({ name: t.name, description: t.description })),
      connect: `Gemini Spark → Connected Apps: ${url.origin}/mcp?key=YOUR_MCP_KEY`,
    });
  }

  // POST — JSON-RPC
  if (request.method === 'POST') {
    let body;
    try {
      body = await request.json();
    } catch {
      return jsonResponse(
        { jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } },
        400
      );
    }

    // Issue session on initialize
    const isInit =
      !Array.isArray(body) && String(body.method || '') === 'initialize';
    if (isInit && !sessionId) {
      sessionId = newSessionId();
    }
    const extra = {};
    if (sessionId) extra['Mcp-Session-Id'] = sessionId;
    if (isInit) {
      const negotiated = negotiateVersion(body.params?.protocolVersion);
      extra['MCP-Protocol-Version'] = negotiated;
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

  return jsonResponse({ error: 'Method not allowed' }, 405);
}

export async function handleSync(request, env) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: MCP_CORS });
  }

  const denied = checkAuth(request, env);
  if (denied) return denied;

  if (request.method !== 'POST') {
    return jsonResponse({ error: 'POST a snapshot JSON body' }, 405);
  }

  if (!env.STORE) {
    return jsonResponse({ error: 'KV STORE binding missing' }, 500);
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: 'Invalid JSON' }, 400);
  }

  const snap = {
    username: body.username || null,
    syncedAt: new Date().toISOString(),
    balances: Array.isArray(body.balances) ? body.balances : [],
    ledgers: body.ledgers && typeof body.ledgers === 'object' ? body.ledgers : {},
    transactions: Array.isArray(body.transactions) ? body.transactions.slice(0, 5000) : [],
    dashboard: body.dashboard || null,
  };

  const glance = {
    username: snap.username,
    syncedAt: snap.syncedAt,
    dashboard: snap.dashboard,
    balances: snap.balances,
    books: body.books && typeof body.books === 'object' ? body.books : { bank: [], khata: [] },
    people: Array.isArray(body.people) ? body.people : snap.balances,
    categories: Array.isArray(body.categories) ? body.categories : [],
    expense_types: Array.isArray(body.expense_types) ? body.expense_types : [],
  };

  await env.STORE.put(SNAPSHOT_KEY, JSON.stringify(snap));
  await env.STORE.put(GLANCE_KEY, JSON.stringify(glance));

  const pendingKey = 'expense:v1:pending_manual';
  let pendingManual = [];
  if (env.STORE) {
    const rawPending = await env.STORE.get(pendingKey);
    if (rawPending) {
      try {
        pendingManual = JSON.parse(rawPending);
      } catch {
        pendingManual = [];
      }
    }
    if (body.ack_pending && Array.isArray(body.ack_pending) && pendingManual.length > 0) {
      const ackSet = new Set(body.ack_pending);
      pendingManual = pendingManual.filter((item) => !ackSet.has(item.id));
      await env.STORE.put(pendingKey, JSON.stringify(pendingManual));
    }
  }

  const live = body.live && typeof body.live === 'object' ? body.live : null;
  const liveUrl = live && String(live.url || '').startsWith('https://') ? String(live.url).replace(/\/+$/, '') : '';
  const liveToken = live && String(live.token || '').trim();
  let liveOn = false;
  if (liveUrl && liveToken) {
    await env.STORE.put(
      LIVE_KEY,
      JSON.stringify({ url: liveUrl, token: liveToken, updatedAt: snap.syncedAt }),
    );
    liveOn = true;
  }

  return jsonResponse({
    ok: true,
    syncedAt: snap.syncedAt,
    username: snap.username,
    balance_count: snap.balances.length,
    transaction_count: snap.transactions.length,
    ledger_contact_count: Object.keys(snap.ledgers).length,
    glance: true,
    live: liveOn,
    pending_manual: pendingManual,
  });
}

export async function handleLiveRegister(request, env) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: MCP_CORS });
  }
  const denied = checkAuth(request, env);
  if (denied) return denied;
  if (request.method !== 'POST') {
    return jsonResponse({ error: 'POST {url, token}' }, 405);
  }
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: 'Invalid JSON' }, 400);
  }
  const liveUrl = String(body.url || '').replace(/\/+$/, '');
  const liveToken = String(body.token || '').trim();
  if (!liveUrl.startsWith('https://') || !liveToken) {
    return jsonResponse({ error: 'url and token required' }, 400);
  }
  const prev = await env.STORE.get(LIVE_KEY);
  let keepToken = liveToken;
  if (prev) {
    try {
      const old = JSON.parse(prev);
      if (old.token && !liveToken) keepToken = old.token;
    } catch {
      /* ignore */
    }
  }
  await env.STORE.put(
    LIVE_KEY,
    JSON.stringify({ url: liveUrl, token: keepToken, updatedAt: new Date().toISOString() }),
  );
  return jsonResponse({ ok: true, live: true, url: liveUrl });
}
