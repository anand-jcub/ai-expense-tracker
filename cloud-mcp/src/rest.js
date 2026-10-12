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

  if (path.startsWith('/api/push/')) {
    let body;
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      try {
        body = await request.json();
      } catch {
        body = {};
      }
    }
    const liveResp = await tryLive(request, env, path, body);
    if (liveResp) return liveResp;
    return json({ error: 'Desktop app not reachable to sync push notifications. Ensure your PC is running.' }, 503);
  }

  if (path === '/api/dashboard/summary' && request.method === 'GET') {
    const liveResp = await tryLive(request, env, path);
    if (liveResp) return liveResp;
    if (!glance) return json({ error: 'No snapshot yet. Run sync-cloud.cmd on the PC.' }, 404);

    const startDate = (url.searchParams.get('start_date') || url.searchParams.get('start') || '').trim();
    const endDate = (url.searchParams.get('end_date') || url.searchParams.get('end') || '').trim();
    const excludeBusiness = url.searchParams.get('exclude_business') !== '0';

    const defaultDash = glance.dashboard || {};
    if ((!startDate && !endDate) || (startDate === defaultDash.start_date && endDate === defaultDash.end_date)) {
      return json({
        ...defaultDash,
        mode: 'snapshot',
        syncedAt: glance.syncedAt,
      });
    }

    const txns = glance.transactions || [];
    const filtered = txns.filter((t) => {
      const d = String(t.txn_date || '').slice(0, 10);
      if (startDate && d < startDate) return false;
      if (endDate && d > endDate) return false;
      const rowCat = String(t.category || '').trim().toLowerCase();
      const rowType = String(t.expense_type || '').trim().toLowerCase();
      if (excludeBusiness && (rowCat === 'business' || rowType === 'business')) return false;
      return true;
    });

    let periodDebits = 0;
    let periodCredits = 0;
    let periodExpenseShare = 0;
    const catMap = {};

    for (const t of filtered) {
      const debit = Number(t.debit) || 0;
      const credit = Number(t.credit) || 0;
      periodDebits += debit;
      periodCredits += credit;
      if (debit > 0) {
        const expType = String(t.expense_type || '').trim().toLowerCase();
        if (expType === 'transfer' || expType === 'loan') continue;
        const myShare = t.my_share !== null && t.my_share !== undefined ? Number(t.my_share) : debit;
        const amt = Math.min(myShare, debit);
        periodExpenseShare += amt;
        const cat = t.category || 'Uncategorized';
        catMap[cat] = (catMap[cat] || 0) + amt;
      }
    }

    const byCategory = Object.entries(catMap)
      .map(([category, amount]) => ({ category, amount: Math.round(amount * 100) / 100 }))
      .sort((a, b) => b.amount - a.amount);

    return json({
      start_date: startDate || null,
      end_date: endDate || null,
      exclude_business: excludeBusiness,
      period_credits: Math.round(periodCredits * 100) / 100,
      period_debits: Math.round(periodDebits * 100) / 100,
      period_expense_share: Math.round(periodExpenseShare * 100) / 100,
      transaction_count: filtered.length,
      needs_review_count: filtered.filter((t) => t.status !== 'reviewed').length,
      by_category: byCategory,
      mode: 'snapshot',
      syncedAt: glance.syncedAt,
    });
  }

  if (path === '/api/transactions' && request.method === 'GET') {
    const liveResp = await tryLive(request, env, path);
    if (liveResp) return liveResp;
    if (!glance) return json({ error: 'No snapshot yet. Run sync-cloud.cmd on the PC.' }, 404);

    const startDate = (url.searchParams.get('start_date') || url.searchParams.get('start') || '').trim();
    const endDate = (url.searchParams.get('end_date') || url.searchParams.get('end') || '').trim();
    const category = (url.searchParams.get('category') || '').trim();
    const excludeBusiness = url.searchParams.get('exclude_business') !== '0';
    const q = (url.searchParams.get('q') || url.searchParams.get('query') || '').trim().toLowerCase();
    const limitRaw = (url.searchParams.get('limit') || '').trim().toLowerCase();

    let limit = null;
    if (limitRaw === 'all' || limitRaw === '0' || limitRaw === 'none') {
      limit = null;
    } else if (/^\d+$/.test(limitRaw)) {
      limit = Math.max(1, Math.min(parseInt(limitRaw, 10), 5000));
    } else if (category) {
      limit = null;
    } else {
      limit = 50;
    }

    const txns = [...(glance.transactions || [])].reverse();
    const filtered = [];

    for (const t of txns) {
      const d = String(t.txn_date || '').slice(0, 10);
      if (startDate && d < startDate) continue;
      if (endDate && d > endDate) continue;
      const rowCat = String(t.category || '').trim();
      const rowType = String(t.expense_type || '').trim();
      if (excludeBusiness && (rowCat.toLowerCase() === 'business' || rowType.toLowerCase() === 'business')) {
        continue;
      }
      if (category) {
        if (category.toLowerCase() === 'uncategorized') {
          const status = String(t.status || '').toLowerCase();
          if (rowCat && rowCat.toLowerCase() !== 'uncategorized' && status !== 'needs_review') {
            continue;
          }
        } else if (rowCat.toLowerCase() !== category.toLowerCase()) {
          continue;
        }
        const debit = Number(t.debit) || 0;
        if (debit <= 0) continue;
      }
      if (q) {
        const blob = [
          t.merchant_display,
          t.description,
          t.category,
          t.expense_type,
          t.notes,
          t.reference,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        if (!blob.includes(q)) continue;
      }
      filtered.push(t);
      if (limit !== null && filtered.length >= limit) break;
    }

    return json({
      username: glance.username,
      count: filtered.length,
      start_date: startDate || null,
      end_date: endDate || null,
      category: category || null,
      query: q || null,
      transactions: filtered,
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
        const isBiz = String(category || '').trim().toLowerCase() === 'business' || String(body.expense_type || '').trim().toLowerCase() === 'business';
        if (!isBiz) {
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
    return { reply: 'The ledger and contact balances system has been decommissioned.', cards: [], source: 'snapshot', matched: true, model: 'local' };
  }

  const spend = text.match(
    /(?:what (?:did|have) i spend|how much (?:did|have) i spend|spent?)\s+(?:on\s+)?([a-z ]+?)(?:\s+this month)?\??$/i,
  );
  if (spend) {
    const dash = glance.dashboard || {};
    const dashAll = glance.dashboard_all || dash;
    const cat = String(spend[1] || '')
      .replace(/\bthis month\b/i, '')
      .trim();
    const cats = (dashAll.by_category && dashAll.by_category.length) ? dashAll.by_category : (dash.by_category || []);
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
    return { reply: 'No open person balances. The ledger system has been decommissioned.', cards: [], source: 'snapshot', matched: true };
  }

  const dateHit = parseTargetDate(text);
  if (dateHit) {
    const txns = glance.transactions || glance.books?.bank || [];
    const dateRows = txns.filter((t) => {
      const d = String(t.txn_date || t.date || '').slice(0, 10);
      return d === dateHit || d.endsWith(dateHit.slice(4));
    });
    if (dateRows.length > 0) {
      let totalDebit = 0;
      let totalCredit = 0;
      const bits = dateRows.map((t) => {
        const d = Number(t.debit || 0);
        const c = Number(t.credit || 0);
        totalDebit += d;
        totalCredit += c;
        const merch = t.merchant_display || t.merchant || t.description || 'Transaction';
        const typeStr = d > 0 ? `₹${fmt(d)} (debit)` : `₹${fmt(c)} (credit)`;
        return `• ${merch}: ${typeStr} [${t.category || 'Other'}]`;
      });
      return {
        reply: `On ${dateHit}, you have ${dateRows.length} transaction(s):\n${bits.join('\n')}\nTotal debits: ₹${fmt(totalDebit)}, credits: ₹${fmt(totalCredit)}.`,
        cards: [],
        source: 'snapshot',
        matched: true,
        model: 'local',
      };
    } else {
      return {
        reply: `No transactions found for ${dateHit} in your synced records.`,
        cards: [],
        source: 'snapshot',
        matched: true,
        model: 'local',
      };
    }
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

const MONTH_MAP = {
  jan: '01', feb: '02', mar: '03', apr: '04', may: '05', jun: '06',
  jul: '07', aug: '08', sep: '09', oct: '10', nov: '11', dec: '12',
};

function parseTargetDate(text) {
  if (!text) return null;
  const low = String(text).toLowerCase();

  // Relative dates
  if (/\btoday\b/i.test(low)) {
    return new Date().toISOString().slice(0, 10);
  }
  if (/\byesterday\b/i.test(low)) {
    const y = new Date(Date.now() - 86400000);
    return y.toISOString().slice(0, 10);
  }

  // 1. YYYY-MM-DD
  const isoMatch = low.match(/\b(20\d{2})-(\d{2})-(\d{2})\b/);
  if (isoMatch) return `${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]}`;

  // 2. Month Name + Day: "august 31", "aug 31", "august 31st", "on august 31"
  const m1 = low.match(/\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(20\d{2}))?\b/i);
  if (m1) {
    const m = MONTH_MAP[m1[1].slice(0, 3).toLowerCase()];
    const d = String(m1[2]).padStart(2, '0');
    const y = m1[3] || '2026';
    return `${y}-${m}-${d}`;
  }

  // 3. Day + Month Name: "31 august", "31st august", "31st of august"
  const m2 = low.match(/\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s*,?\s*(20\d{2}))?\b/i);
  if (m2) {
    const d = String(m2[1]).padStart(2, '0');
    const m = MONTH_MAP[m2[2].slice(0, 3).toLowerCase()];
    const y = m2[3] || '2026';
    return `${y}-${m}-${d}`;
  }

  // 4. DD-MM-YYYY or DD/MM/YYYY
  const m3 = low.match(/\b(\d{1,2})[-/](\d{1,2})(?:[-/](20\d{2}))?\b/);
  if (m3 && Number(m3[1]) <= 31 && Number(m3[2]) <= 12) {
    const d = String(m3[1]).padStart(2, '0');
    const m = String(m3[2]).padStart(2, '0');
    const y = m3[3] || '2026';
    return `${y}-${m}-${d}`;
  }

  return null;
}

function findRelevantTransactions(allTxns, message, history = []) {
  if (!Array.isArray(allTxns) || !allTxns.length) return { targetDate: null, matching: [] };
  const userHistory = Array.isArray(history)
    ? history.filter((h) => h.role === 'user' || h.role === 'User').slice(-3).map((h) => String(h.text || ''))
    : [];
  const combined = [message, ...userHistory].join(' ').toLowerCase();

  const targetDate = parseTargetDate(message) || parseTargetDate(combined);

  let minAmount = 0;
  const minMatch = combined.match(/(?:more than|greater than|above|>|over|at least)\s*(?:rs\.?|inr|₹)?\s*([\d,]+)/i);
  if (minMatch) {
    minAmount = Number(minMatch[1].replace(/,/g, '')) || 0;
  }

  let maxAmount = Infinity;
  const maxMatch = combined.match(/(?:less than|under|below|<|up to)\s*(?:rs\.?|inr|₹)?\s*([\d,]+)/i);
  if (maxMatch) {
    maxAmount = Number(maxMatch[1].replace(/,/g, '')) || Infinity;
  }

  const hasDebit = /\b(debits?|spent|paid|withdrawal|outgoing)\b/i.test(combined);
  const hasCredit = /\b(credits?|received|incoming|got|deposit)\b/i.test(combined);
  const isBusiness = /\bbusiness\b/i.test(combined);

  const monthWord = combined.match(/\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b/i);
  const targetMonth = monthWord ? `-${MONTH_MAP[monthWord[1].slice(0, 3).toLowerCase()]}-` : null;

  const words = combined.split(/[^a-z0-9]/).filter((w) => w.length >= 2);

  const scored = allTxns.map((t) => {
    let score = 0;
    const cat = String(t.category || '').toLowerCase();
    const type = String(t.type || t.expense_type || '').toLowerCase();
    const desc = String(t.description || t.merchant || t.merchant_display || '').toLowerCase();
    const date = String(t.txn_date || t.date || '').slice(0, 10);
    const debit = Number(t.debit || 0);
    const credit = Number(t.credit || 0);
    const amt = debit || credit;

    // Exact date match gets top priority
    if (targetDate && (date === targetDate || date.endsWith(targetDate.slice(4)))) {
      score += 200;
    } else if (targetDate) {
      // Non-matching dates penalized when user specified an exact date
      score -= 50;
    }

    if (isBusiness) {
      if (cat === 'business' || type === 'business' || desc.includes('business')) {
        score += 35;
      }
    }

    if (minAmount > 0) {
      if (hasDebit && debit >= minAmount) score += 25;
      else if (hasCredit && credit >= minAmount) score += 25;
      else if (!hasDebit && !hasCredit && amt >= minAmount) score += 20;
      else return { t, score: -100 };
    }

    if (maxAmount < Infinity) {
      if (amt <= maxAmount) score += 10;
      else return { t, score: -100 };
    }

    if (hasDebit && debit > 0) score += 10;
    if (hasCredit && credit > 0) score += 10;

    if (targetMonth && date.includes(targetMonth)) {
      score += 20;
    }

    for (const w of words) {
      if (['debit', 'debits', 'credit', 'credits', 'more', 'than', 'rupees', 'category', 'money', 'this', 'month', 'show', 'me', 'in', 'on', 'transactions', 'again'].includes(w)) continue;
      if (desc.includes(w)) score += 15;
      if (cat.includes(w)) score += 15;
    }

    return { t, score };
  });

  const matching = scored
    .filter((x) => x.score > 0)
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      // Tie-breaker: sort descending by date so most recent transactions come first
      return String(b.t.txn_date || b.t.date || '').localeCompare(String(a.t.txn_date || a.t.date || ''));
    })
    .map((x) => x.t)
    .slice(0, 75);

  return { targetDate, matching };
}

async function callGeminiCloud(env, glance, message, history = []) {
  if (!env.GEMINI_API_KEY) return null;
  const apiKey = env.GEMINI_API_KEY;
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10);
  const dash = glance?.dashboard || {};
  const dashAll = glance?.dashboard_all || dash;
  const balances = glance?.balances || [];
  const people = glance?.people || [];
  const allTxns = (glance?.transactions && glance.transactions.length)
    ? glance.transactions
    : (glance?.books?.bank || []);

  const { targetDate, matching: relevantTxns } = findRelevantTransactions(allTxns, message, history);

  // Sort descending so the recent sample is truly the most recent transactions
  const sortedDesc = [...allTxns].sort((a, b) =>
    String(b.txn_date || b.date || '').localeCompare(String(a.txn_date || a.date || ''))
  );
  const recentSample = sortedDesc.slice(0, 25);
  const latestDate = sortedDesc[0]?.txn_date || sortedDesc[0]?.date || 'Unknown';
  const earliestDate = sortedDesc[sortedDesc.length - 1]?.txn_date || sortedDesc[sortedDesc.length - 1]?.date || 'Unknown';

  const contextPrompt = `You are the personal AI financial assistant for Anand.
Current Date: ${dateStr}
Current Active Dashboard Period: ${dash.start_date || '2026-08-01'} to ${dash.end_date || '2026-08-31'}
Total Expense Share for Active Period (Personal): ₹${fmt(dash.period_expense_share || 0)} (Total Debits: ₹${fmt(dash.period_debits || 0)}, Total Credits: ₹${fmt(dash.period_credits || 0)})
Database Transaction Records Span: from ${earliestDate} up to ${latestDate}.
${targetDate ? `Date Filter Target: ${targetDate} (${relevantTxns.length} matching transaction(s) found in records on this date).` : ''}

Category Breakdown This Month (Including Business):
${((dashAll.by_category && dashAll.by_category.length) ? dashAll.by_category : (dash.by_category || [])).map((c) => `- ${c.category}: ₹${fmt(c.amount)}`).join('\n') || 'None'}

All Valid Categories in System: Food, Groceries, Business, Rent, Health, Shopping, Entertainment, Utilities, Transport, Subscription, Personal Care, Family, Other, Flat, Travel, Transfer, Loan
All Valid Expense Types: Personal, Business, Shared, Transfer, Loan, Other

${relevantTxns.length ? `Relevant Transactions Matching Query Intent:
${relevantTxns.map((t) => `- ${t.txn_date || t.date}: ${t.merchant_display || t.merchant || t.description} | ₹${fmt(t.debit || t.credit || t.amount || 0)} (${t.debit ? 'debit' : 'credit'}) | Category: ${t.category || 'Other'} | Type: ${t.type || t.expense_type || 'Personal'}`).join('\n')}` : 'No specific matching transactions found.'}

Most Recent Transactions Sample:
${recentSample.map((t) => `- ${t.txn_date || t.date}: ${t.merchant_display || t.merchant || t.description} | ₹${fmt(t.debit || t.credit || t.amount || 0)} (${t.debit ? 'debit' : 'credit'}) | Category: ${t.category || 'Other'} | Type: ${t.type || t.expense_type || 'Personal'}`).join('\n')}

CRITICAL DOMAIN INSTRUCTIONS:
1. When the user asks for transactions on a specific date (e.g. August 31, 2026), look at "Relevant Transactions Matching Query Intent" first. List ALL matching transactions found on that date with Date, Recipient/Merchant, Amount (with ₹), and Category. NEVER claim there are no records if transactions appear in Relevant Transactions or records span to that date.
2. "Business" IS a fully valid, active category and expense type in Anand's tracker. Anand has business transactions and categories in his records. NEVER say that Anand does not have a "business" category or business expenses.
3. If the user asks for debits more than an amount (e.g. > 2000) in Business (or any category), list all matching transactions from the Relevant Transactions above with Date, Recipient/Merchant, Amount (with ₹), and Category/Type, and state the total.
4. Follow-up handling: If the user provides a short response like "Check again" or "In business", understand it in context of the conversation history.
5. Use the Indian Rupee symbol (₹). Be direct, friendly, and concise.`;

  const contents = [];
  if (Array.isArray(history) && history.length > 0) {
    for (const h of history.slice(-6)) {
      const role = (h.role === 'model' || h.role === 'assistant') ? 'model' : 'user';
      const text = String(h.text || '').trim();
      if (text) {
        if (!contents.length || contents[contents.length - 1].role !== role) {
          contents.push({ role, parts: [{ text }] });
        }
      }
    }
  }
  if (contents.length > 0 && contents[contents.length - 1].role === 'user') {
    contents.pop();
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
