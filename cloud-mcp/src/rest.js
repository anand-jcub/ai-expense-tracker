/**
 * Phone REST: try the live PC (tunnel) first, else the small glance snapshot.
 * Glance path does not parse the 5,000-row transaction blob.
 */
import { GLANCE_KEY, LIVE_KEY, extractKey, jsonResponse } from './mcp.js';

const SNAPSHOT_ADD = 'Desktop not reachable. Keep the PC tunnel on to add.';

export async function handleRest(request, env) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders() });
  }

  const denied = restAuth(request, env);
  if (denied) return denied;

  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '') || '/';
  const glance = await loadJson(env, GLANCE_KEY);

  if (path === '/api/health') {
    const writes = await liveReachable(env);
    return json({
      ok: Boolean(glance),
      service: 'expense-tracker-mcp-hub',
      mode: writes ? 'live' : 'snapshot',
      writes,
      syncedAt: glance?.syncedAt || null,
      username: glance?.username || null,
    });
  }

  if (path === '/api/dashboard/summary' && request.method === 'GET') {
    const liveResp = await tryLive(request, env, path);
    if (liveResp) return liveResp;
    if (!glance) return json({ error: 'No snapshot yet. Run sync-cloud.cmd on the PC.' }, 404);
    return json({
      ...(glance.dashboard || {}),
      mode: 'snapshot',
      syncedAt: glance.syncedAt,
    });
  }

  if (path === '/api/settlement/summary' && request.method === 'GET') {
    const liveResp = await tryLive(request, env, path);
    if (liveResp) return liveResp;
    if (!glance) return json({ error: 'No snapshot yet. Run sync-cloud.cmd on the PC.' }, 404);
    const rows = glance.people || glance.balances || [];
    const contacts = rows
      .filter((b) => Number(b.net) !== 0)
      .map((b) => ({
        contact_id: b.contact_id,
        contact_name: b.contact_name,
        net: b.net,
        status: b.status,
      }));
    return json({ contacts, mode: 'snapshot', syncedAt: glance.syncedAt });
  }

  if (path === '/api/meta' && request.method === 'GET') {
    const liveResp = await tryLive(request, env, path);
    if (liveResp) return liveResp;
    return json({
      categories: (glance && glance.categories) || [],
      expense_types: (glance && glance.expense_types) || ['Personal'],
      mode: 'snapshot',
    });
  }

  if (path === '/api/assistant/chat' && request.method === 'POST') {
    let body = {};
    try {
      body = await request.json();
    } catch {
      body = {};
    }
    const rawMsg = String(body.message || body.q || '');
    const liveResp = await tryLive(request, env, path, body);
    if (liveResp) return liveResp;

    // 1. Try Gemini Cloud AI if GEMINI_API_KEY is set in Worker secrets
    if (env.GEMINI_API_KEY && glance) {
      const geminiRes = await callGeminiCloud(env, glance, rawMsg, body.history);
      if (geminiRes) return json(geminiRes);
    }

    // 2. Fallback to local snapshot answer engine
    const local = glance ? answerAsk(glance, stitchFollowup(rawMsg, body.history)) : null;
    if (local && local.matched) return json(local);

    return json({
      reply: local?.reply || 'I can answer balances, transactions, and category spend from your synced bank data.',
      cards: [],
      source: 'snapshot',
      model: 'local',
    });
  }

  if (path === '/api/manual' && request.method === 'POST') {
    let body = {};
    try {
      body = await request.json();
    } catch {
      body = {};
    }
    const liveResp = await tryLive(request, env, path, body);
    if (liveResp) return liveResp;

    const amt = Number(body.amount) || 0;
    if (!amt || !body.description) {
      return json({ error: 'Amount and what it was for are required.', ok: false }, 400);
    }

    const txnId = `cloud-${Date.now()}`;
    const nowIso = new Date().toISOString();
    const dateStr = body.txn_date || nowIso.slice(0, 10);
    const category = body.category || 'Other';
    const desc = String(body.description || '').trim();

    // 1. Queue to KV for desktop SQLite merge
    const pendingKey = 'expense:v1:pending_manual';
    const pendingList = (await loadJson(env, pendingKey)) || [];
    const manualEntry = {
      id: txnId,
      txn_date: dateStr,
      amount: amt,
      description: desc,
      category: category,
      expense_type: body.expense_type || 'Personal',
      direction: body.direction || 'debit',
      created_at: nowIso,
    };
    pendingList.push(manualEntry);
    if (env.STORE) {
      await env.STORE.put(pendingKey, JSON.stringify(pendingList));
    }

    // 2. Optimistically update glance so phone UI updates immediately
    if (glance && env.STORE) {
      if (body.direction !== 'credit') {
        glance.dashboard = glance.dashboard || {};
        glance.dashboard.period_expense_share = (Number(glance.dashboard.period_expense_share) || 0) + amt;
        glance.dashboard.period_debits = (Number(glance.dashboard.period_debits) || 0) + amt;
        glance.dashboard.transaction_count = (Number(glance.dashboard.transaction_count) || 0) + 1;

        const cats = glance.dashboard.by_category || [];
        const existingCat = cats.find((c) => String(c.category || '').toLowerCase() === category.toLowerCase());
        if (existingCat) {
          existingCat.amount = (Number(existingCat.amount) || 0) + amt;
        } else {
          cats.push({ category, amount: amt });
        }
        glance.dashboard.by_category = cats.sort((a, b) => b.amount - a.amount);
      }

      glance.transactions = glance.transactions || [];
      glance.transactions.unshift({
        id: txnId,
        txn_date: dateStr,
        debit: body.direction !== 'credit' ? amt : 0,
        credit: body.direction === 'credit' ? amt : 0,
        description: desc,
        merchant_display: desc,
        category: category,
        expense_type: body.expense_type || 'Personal',
        source: 'manual',
      });

      await env.STORE.put(GLANCE_KEY, JSON.stringify(glance));
    }

    return json({
      ok: true,
      transaction_id: txnId,
      queued: true,
      message: 'Saved to cloud. Syncs with desktop when online.',
    });
  }

  if (path === '/api/assistant/confirm' && request.method === 'POST') {
    let body = {};
    try {
      body = await request.json();
    } catch {
      body = {};
    }
    const liveResp = await tryLive(request, env, path, body);
    if (liveResp) return liveResp;
    return json({ error: SNAPSHOT_ADD, reply: SNAPSHOT_ADD, ok: false }, 409);
  }

  return json({ error: 'Not found' }, 404);
}

async function liveReachable(env) {
  const live = await loadJson(env, LIVE_KEY);
  if (!live || !String(live.url || '').startsWith('https://') || !live.token) return false;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    const resp = await fetch(`${String(live.url).replace(/\/+$/, '')}/api/health`, {
      headers: { Authorization: `Bearer ${live.token}`, Accept: 'application/json' },
      signal: ctrl.signal,
    });
    clearTimeout(timer);
    return resp.ok;
  } catch {
    return false;
  }
}

async function tryLive(request, env, path, parsedBody) {
  if (!path.startsWith('/api')) return null;
  const live = await loadJson(env, LIVE_KEY);
  if (!live || !String(live.url || '').startsWith('https://') || !live.token) return null;
  const src = new URL(request.url);
  const dest = `${String(live.url).replace(/\/+$/, '')}${src.pathname}${src.search}`;
  try {
    const headers = {
      Accept: 'application/json',
      Authorization: `Bearer ${live.token}`,
      'Content-Type': 'application/json',
    };
    const init = { method: request.method, headers, redirect: 'manual' };
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      init.body =
        parsedBody !== undefined
          ? JSON.stringify(parsedBody)
          : await request.clone().arrayBuffer();
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 25000);
    init.signal = ctrl.signal;
    const resp = await fetch(dest, init);
    clearTimeout(timer);
    if (!resp.ok && (resp.status >= 500 || resp.status === 401 || resp.status === 404)) return null;
    const outHeaders = corsHeaders();
    outHeaders['Content-Type'] = resp.headers.get('Content-Type') || 'application/json';
    return new Response(resp.body, { status: resp.status, headers: outHeaders });
  } catch {
    return null;
  }
}

function restAuth(request, env) {
  const key = extractKey(request);
  const expected = env.MCP_KEY || env.SYNC_KEY || '';
  if (!expected || key !== expected) {
    return json(
      { error: 'Unauthorized', hint: 'Open the /app/?key=… pairing link from the PC.' },
      401,
    );
  }
  return null;
}

async function loadJson(env, kvKey) {
  if (!env.STORE) return null;
  const raw = await env.STORE.get(kvKey);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function stitchFollowup(message, history) {
  const t = String(message || '').trim();
  const follow =
    /^(and |what about|how about|also |last (month|week)|that|those)\b/i.test(t) ||
    t.split(/\s+/).filter(Boolean).length <= 8;
  if (!follow || !Array.isArray(history)) return t;
  const prev = [...history]
    .reverse()
    .find((h) => (h.role === 'user' || h.role === 'User') && h.text);
  if (!prev || prev.text === t) return t;
  return `${prev.text} — ${t}`;
}

function answerAsk(glance, message) {
  const text = (message || '').trim();
  if (!text) {
    return { reply: 'Ask about a person or this month’s spend.', cards: [], source: 'snapshot', matched: false };
  }

  const owe = text.match(
    /(?:how much (?:does|do)\s+)?(.+?)\s+(?:owe me|owes me)\??$/i,
  );
  const oweAlt =
    /owe|balance|khata/i.test(text) &&
    text.match(/(?:balance|khata|owe[sd]?)\s+(?:for|with|to)?\s*(.+?)\??$/i);
  const nameHit = owe || oweAlt;
  if (nameHit) {
    let name = String(nameHit[1] || '')
      .replace(/^(does|do|for|with|to)\s+/i, '')
      .trim()
      .replace(/[?.]$/, '');
    if (name && !/^(me|i|who)$/i.test(name)) {
      const row = findBalance(glance.balances || [], name);
      if (!row) {
        return { reply: `No contact matching “${name}”.`, cards: [], source: 'snapshot', matched: true };
      }
      return { reply: formatNet(row), cards: [], source: 'snapshot', matched: true, model: 'local' };
    }
  }

  const spend = text.match(
    /(?:what (?:did|have) i spend|how much (?:did|have) i spend|spent?)\s+(?:on\s+)?([a-z ]+?)(?:\s+this month)?\??$/i,
  );
  if (spend) {
    const dash = glance.dashboard || {};
    const cat = String(spend[1] || '')
      .replace(/\bthis month\b/i, '')
      .trim();
    const cats = dash.by_category || [];
    const match = cat
      ? cats.find((c) => String(c.category || '').toLowerCase() === cat.toLowerCase())
      : null;
    if (match) {
      return {
        reply: `You spent ₹${fmt(match.amount)} on ${match.category} from ${dash.start_date} to ${dash.end_date} (last sync).`,
        cards: [],
        source: 'snapshot',
        matched: true,
      };
    }
    return {
      reply: `This month (last sync): ₹${fmt(dash.period_expense_share)} personal spend (${dash.start_date}–${dash.end_date}).`,
      cards: [],
      source: 'snapshot',
      matched: true,
    };
  }

  if (/who owes|who do i owe|balances?\b/i.test(text)) {
    const rows = (glance.people || glance.balances || []).filter((b) => Number(b.net) !== 0);
    if (!rows.length) return { reply: 'No open person balances.', cards: [], source: 'snapshot', matched: true };
    const bits = rows.slice(0, 8).map((r) => {
      const net = Number(r.net) || 0;
      return net > 0
        ? `${r.contact_name} owes you ₹${fmt(net)}`
        : `you owe ${r.contact_name} ₹${fmt(Math.abs(net))}`;
    });
    return { reply: `${bits.join('; ')}.`, cards: [], source: 'snapshot', matched: true };
  }

  const booksHit = queryGlanceBooks(glance, text);
  if (booksHit) return booksHit;

  return {
    reply: 'Desktop not reachable for full Ask. I can still answer balances and this month’s spend from the last sync.',
    cards: [],
    source: 'snapshot',
    matched: false,
    model: 'local',
  };
}

function queryGlanceBooks(glance, text) {
  const books = glance.books || {};
  const low = text.toLowerCase();

  // Check incoming: "how much did Highnes send me" or "Highnes sent me"
  let incoming = false;
  let personName = '';
  const inMatch = text.match(/(?:how much did\s+|did\s+)?([A-Za-z]{2,40})\s+(?:send|sent|gave|give|paid?)\s+me\b/i);
  if (inMatch && !/^(did|how|what|who|i|you|when)$/i.test(inMatch[1])) {
    incoming = true;
    personName = inMatch[1];
  } else {
    // Outgoing: "did I send Highnes" or "paid Highnes 50k"
    const outMatch = text.match(/(?:send|sent|gave|give|paid?)\s+([A-Za-z]{2,40})/i);
    if (outMatch && !/^(me|i|who|to|for|us|them|him|her)$/i.test(outMatch[1])) {
      incoming = false;
      personName = outMatch[1];
    }
  }

  if (personName) {
    const rawAmt = (text.match(/([\d,.]+\s*(?:k\b|lakh?s?|lacs?)\b|[1-9][\d,.]{3,})/i) || [])[1] || '';
    let amt = 0;
    const kMatch = rawAmt.match(/([\d.]+)\s*k\b/i);
    if (kMatch) {
      amt = Number(kMatch[1]) * 1000;
    } else {
      amt = Number(String(rawAmt).replace(/,/g, '')) || 0;
    }
    if (/lak/i.test(rawAmt) && amt > 0 && amt < 1000) amt *= 100000;
    const isThreshold = /greater than|more than|over|above/i.test(text);
    const nameLow = personName.toLowerCase();

    // Check optional month filter (e.g. "on July" or "in July")
    const monthMatch = text.match(/\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b/i);
    const monthStr = monthMatch ? monthMatch[1].slice(0, 3).toLowerCase() : null;

    // --- Bank pass ---
    const txns = glance.transactions || [];
    const bankHits = txns.filter((t) => {
      const val = Number(incoming ? t.credit || 0 : t.debit || 0);
      if (val <= 0) return false;
      const blob = ((t.merchant_display || '') + ' ' + (t.description || '')).toLowerCase();
      if (!blob.includes(nameLow)) return false;
      if (monthStr) {
        const d = String(t.txn_date || '');
        // e.g. 2026-07-20 -> month 07 -> jul
        const mNames = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
        const mIdx = parseInt(d.split('-')[1], 10) - 1;
        if (mNames[mIdx] !== monthStr) return false;
      }
      if (amt) {
        if (isThreshold) return val >= amt;
        const tol = Math.max(amt * 0.05, 50);
        return val >= amt - tol && val <= amt + tol;
      }
      return true;
    }).sort((a, b) => String(b.txn_date || '').localeCompare(String(a.txn_date || '')));

    // --- Khata pass ---
    const targetDir = incoming ? 'they_sent' : 'you_sent';
    const khataHits = (books.khata || []).filter((e) => {
      if (String(e.direction) !== targetDir) return false;
      if (!String(e.contact_name || '').toLowerCase().includes(nameLow)) return false;
      const eAmt = Number(e.amount || 0);
      if (amt) {
        if (isThreshold) return eAmt >= amt;
        const tol = Math.max(amt * 0.05, 50);
        return eAmt >= amt - tol && eAmt <= amt + tol;
      }
      return true;
    });

    const allHits = [...bankHits.slice(0, 10), ...khataHits.slice(0, 10)]
      .sort((a, b) => String(b.txn_date || b.date || '').localeCompare(String(a.txn_date || a.date || '')));

    const thresh = amt ? (isThreshold ? ` of ₹${fmt(amt)}+` : ` of ~₹${fmt(amt)}`) : '';
    const verb = incoming ? `${personName} sent you` : `You sent ${personName}`;
    if (!allHits.length) {
      return {
        reply: `No bank transactions or synced khata entries found for ${personName}${thresh}.`,
        cards: [],
        source: 'snapshot',
        matched: true,
        model: 'local',
      };
    }
    const srcLabel = (bankHits.length && khataHits.length) ? ' (bank + khata)' : (bankHits.length ? ' (bank)' : ' (khata)');
    const bits = allHits.slice(0, 6).map((h) => {
      const d = h.txn_date || h.date || '';
      const a = Number(incoming ? h.credit || h.amount || 0 : h.debit || h.amount || 0);
      const src = h.direction ? ' (khata)' : '';
      return `₹${fmt(a)} on ${d}${src}`;
    });
    return {
      reply: `${verb}${thresh}${srcLabel}: ${bits.join('; ')}.`,
      cards: [],
      source: 'snapshot',
      matched: true,
      model: 'local',
    };
  }
  const bank = books.bank || [];
  if (!bank.length) return null;
  let q = low.replace(/\b(when|did|do|i|me|my|the|a|an|on|in|at|to|for|what|how|much|spend|spent|total|this|last|month|week)\b/g, ' ');
  q = q.replace(/\s+/g, ' ').trim();
  if (q.length < 3 && !/food|swiggy|zomato|top|biggest/i.test(low)) return null;
  const hits = bank.filter((t) => {
    const blob = `${t.merchant || ''} ${t.category || ''}`.toLowerCase();
    if (q && q.length >= 3 && !blob.includes(q.split(' ')[0])) return false;
    if (/food/i.test(low) && String(t.category || '').toLowerCase() !== 'food') return false;
    return true;
  });
  if (!hits.length) return null;
  const total = hits.reduce((s, t) => s + Number(t.debit || 0), 0);
  const bits = hits.slice(0, 6).map((t) => `${t.date} ${t.merchant || ''} ₹${fmt(t.debit || t.credit)}`);
  return {
    reply: `Last sync: ₹${fmt(total)} across ${hits.length} rows. ${bits.join('; ')}.`,
    cards: [],
    source: 'snapshot',
    matched: true,
    model: 'local',
  };
}

function findBalance(rows, name) {
  const q = name.toLowerCase();
  return (
    rows.find((r) => String(r.contact_name || '').toLowerCase() === q) ||
    rows.find((r) => (r.aliases || []).some((a) => String(a).toLowerCase() === q)) ||
    rows.find((r) => String(r.contact_name || '').toLowerCase().includes(q)) ||
    rows.find((r) => String(r.contact_id) === name)
  );
}

function formatNet(row) {
  const net = Number(row.net) || 0;
  const name = row.contact_name || 'They';
  if (net > 0) return `${name} owes you ₹${fmt(net)}.`;
  if (net < 0) return `You owe ${name} ₹${fmt(Math.abs(net))}.`;
  return `${name} is settled (₹0).`;
}

function fmt(n) {
  return Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Sync-Key',
  };
}

async function callGeminiCloud(env, glance, message, history = []) {
  if (!env.GEMINI_API_KEY) return null;
  const apiKey = env.GEMINI_API_KEY;
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10);
  const dash = glance?.dashboard || {};
  const balances = glance?.balances || [];
  const people = glance?.people || [];
  const txns = (glance?.transactions || []).slice(0, 40);

  const contextPrompt = `You are the personal AI financial assistant for Anand.
Current Date: ${dateStr}
Current Month: ${dash.start_date || '2026-08-01'} to ${dash.end_date || '2026-08-31'}
Total Expense Share This Month: ₹${fmt(dash.period_expense_share || 0)} (Total Debits: ₹${fmt(dash.period_debits || 0)}, Total Credits: ₹${fmt(dash.period_credits || 0)})

Category Breakdown This Month:
${(dash.by_category || []).map((c) => `- ${c.category}: ₹${fmt(c.amount)}`).join('\n') || 'None'}

Contact / Person Balances (Khata):
${(people.length ? people : balances).map((b) => {
  const net = Number(b.net) || 0;
  if (net > 0) return `- ${b.contact_name}: owes Anand ₹${fmt(net)}`;
  if (net < 0) return `- ${b.contact_name}: Anand owes ₹${fmt(Math.abs(net))}`;
  return `- ${b.contact_name}: Settled (₹0)`;
}).join('\n') || 'No balances'}

Recent Transactions Sample:
${txns.slice(0, 25).map((t) => `- ${t.txn_date}: ${t.merchant_display || t.description} | ₹${fmt(t.debit || t.credit || t.amount || 0)} (${t.debit ? 'debit' : 'credit'}) | Category: ${t.category || 'Other'}`).join('\n')}

Instructions:
1. Answer the user's question clearly, concisely, and accurately based on the financial and bank statement context provided above.
2. Use Indian Rupee symbol (₹) for currency amounts.
3. Be friendly, direct, and concise.`;

  const contents = [];
  if (Array.isArray(history) && history.length > 0) {
    for (const h of history.slice(-4)) {
      contents.push({
        role: h.role === 'model' || h.role === 'assistant' ? 'model' : 'user',
        parts: [{ text: String(h.text || '') }],
      });
    }
  }
  contents.push({
    role: 'user',
    parts: [{ text: `${contextPrompt}\n\nUser Question: ${message}` }],
  });

  const models = ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-3.6-flash'];
  for (const model of models) {
    try {
      const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 12000);
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents,
          generationConfig: {
            temperature: 0.2,
            maxOutputTokens: 800,
          },
        }),
        signal: ctrl.signal,
      });
      clearTimeout(timer);
      if (res.ok) {
        const data = await res.json();
        const text = data?.candidates?.[0]?.content?.parts?.[0]?.text;
        if (text) {
          return {
            reply: text.trim(),
            cards: [],
            source: 'gemini-cloud',
            model: model,
          };
        }
      }
    } catch {
      // try next model or fallback
    }
  }
  return null;
}

function json(obj, status = 200) {
  return jsonResponse(obj, status, corsHeaders());
}
