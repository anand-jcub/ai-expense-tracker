/** Read-only Highnes ledger. Served from KV so it works when the laptop is off. */

const HIGHNES_KEY = 'expense:v1:highnes';

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function inr(n) {
  const v = Number(n) || 0;
  const sign = v < 0 ? '−' : '';
  return sign + '₹' + Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

const STATUS = {
  'Unpaid (Added to Balance)': 'Not repaid',
  Reimbursed: 'Repaid',
  'Covered in baseline': 'In the opening balance',
  'No statement debit yet': 'Not on the statement yet',
};

function lineLabel(e) {
  const kind = e.entry_type || '';
  const name = (e.loan_name || '').trim();
  if (kind === 'opening_balance') return 'Opening balance';
  if (kind === 'loan_debit') return name ? `Anand paid ${name}` : 'Anand paid a loan';
  if (kind === 'transfer_repaid' || kind === 'reimbursement') return 'You paid Anand';
  if (kind === 'money_lent') return 'Anand sent you money';
  return String(kind).replaceAll('_', ' ');
}

function remindersHtml(summary) {
  const sched = summary.upcoming_schedule || {};
  const loans = sched.loans_schedule || sched.loans || [];
  const notes = [];
  for (const loan of loans) {
    const rupees = inr(loan.amount);
    if (loan.status === 'overdue') notes.push(`${loan.name} ${rupees} is not repaid`);
    else if (loan.status === 'due_today') notes.push(`${loan.name} ${rupees} is due today`);
    else if (loan.status === 'due_soon') notes.push(`${loan.name} ${rupees} is due ${loan.due_date_short || 'soon'}`);
  }
  if (!notes.length) return '';
  return `<ul class="reminders">${notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>`;
}

function calendarHref(url) {
  const cal = new URL(url);
  cal.pathname = '/share/highnes/calendar.ics';
  return cal.pathname + cal.search;
}

function page(summary, url) {
  const owed = Number(summary.total_balance_owed) || 0;
  const loans = (summary.active_loans || [])
    .map((loan) => {
      const status = STATUS[loan.status] || loan.status || '';
      const when = loan.last_date ? ` · ${esc(loan.last_date)}` : '';
      return `<article class="loan"><strong>${esc(loan.name)}</strong><span>${inr(loan.monthly_emi)}</span><span class="muted">${esc(status)}${when}</span></article>`;
    })
    .join('');
  const lines = (summary.entries || [])
    .map((e) => {
      const amt = Number(e.amount) || 0;
      const cls = amt < 0 ? 'down' : 'up';
      return `<li><span>${esc(e.entry_date)}</span><span>${esc(lineLabel(e))}</span><span class="${cls}">${inr(amt)}</span><span class="muted">${inr(e.running_balance)}</span></li>`;
    })
    .join('');
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>What you owe Anand</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; background: #f6f4ef; color: #1c1915; }
    main { max-width: 640px; margin: 0 auto; padding: 28px 16px 48px; }
    .kicker { margin: 0; color: #6b645c; font-size: 14px; }
    .figure { margin: 4px 0 8px; font-size: 36px; font-weight: 650; letter-spacing: -0.03em; }
    .muted { color: #6b645c; font-size: 13px; }
    .reminders { margin: 8px 0 0; padding-left: 18px; }
    a.cal { display: inline-block; margin-top: 14px; color: #1c1915; }
    .loans { display: grid; gap: 8px; margin: 18px 0; }
    .loan { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; padding: 12px; background: #fff; border-radius: 12px; }
    .loan .muted { grid-column: 1 / -1; }
    ol { list-style: none; margin: 0; padding: 0; }
    li { display: grid; grid-template-columns: 92px 1fr auto auto; gap: 8px; padding: 12px 0; border-top: 1px solid #e6e1d8; font-size: 15px; }
    .down { color: #6b645c; }
    @media (max-width: 640px) {
      li { grid-template-columns: 1fr auto; }
      li span:nth-child(1), li span:nth-child(4) { color: #6b645c; font-size: 12px; }
    }
  </style>
</head>
<body>
  <main>
    <p class="kicker">You owe Anand</p>
    <p class="figure">${inr(owed)}</p>
    <p class="muted">Opening ${inr(summary.opening_balance)} on ${esc(summary.opening_date || '')}.</p>
    ${remindersHtml(summary)}
    <p><a class="cal" href="${esc(calendarHref(url))}">Add reminders to my phone calendar</a></p>
    <div class="loans">${loans}</div>
    <ol>${lines || '<li>No lines yet.</li>'}</ol>
  </main>
</body>
</html>`;
}

function authSync(request, env) {
  const url = new URL(request.url);
  const key =
    request.headers.get('X-Sync-Key') ||
    url.searchParams.get('key') ||
    '';
  const expected = env.MCP_KEY || env.SYNC_KEY || '';
  return expected && key === expected;
}

export async function handleHighnesSync(request, env) {
  if (request.method !== 'POST') {
    return new Response(JSON.stringify({ error: 'POST the ledger JSON' }), {
      status: 405,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  if (!authSync(request, env)) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  if (!env.STORE) {
    return new Response(JSON.stringify({ error: 'KV missing' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  let body;
  try {
    body = await request.json();
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid JSON' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  const summary = body.summary && typeof body.summary === 'object' ? body.summary : null;
  if (!summary) {
    return new Response(JSON.stringify({ error: 'summary required' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  const stored = {
    ...summary,
    share_key: String(body.share_key || '').trim(),
    syncedAt: new Date().toISOString(),
  };
  await env.STORE.put(HIGHNES_KEY, JSON.stringify(stored));
  return new Response(
    JSON.stringify({
      ok: true,
      syncedAt: stored.syncedAt,
      total_balance_owed: stored.total_balance_owed,
    }),
    { headers: { 'Content-Type': 'application/json' } },
  );
}

export async function handleHighnesShare(request, env, opts = {}) {
  const url = new URL(request.url);
  const key = url.searchParams.get('key') || '';
  if (!env.STORE) {
    return new Response('Ledger is not available.', { status: 500 });
  }
  const raw = await env.STORE.get(HIGHNES_KEY);
  if (!raw) {
    return new Response('Not synced yet. The laptop needs to be on once to publish the ledger.', {
      status: 404,
    });
  }
  let stored;
  try {
    stored = JSON.parse(raw);
  } catch {
    return new Response('Ledger is unreadable.', { status: 500 });
  }
  if (!stored.share_key || key !== stored.share_key) {
    return new Response('This link is not valid.', { status: 403 });
  }
  if (opts.calendar) {
    const ics = opts.ics();
    return new Response(ics, {
      headers: {
        'Content-Type': 'text/calendar; charset=utf-8',
        'Content-Disposition': 'attachment; filename="pay-anand.ics"',
      },
    });
  }
  return new Response(page(stored, url), {
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-cache' },
  });
}

export function highnesCalendarIcs() {
  const now = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  const event = (uid, day, summary, description) => `BEGIN:VEVENT
UID:${uid}
DTSTAMP:${now}
DTSTART;VALUE=DATE:202609${String(day).padStart(2, '0')}
RRULE:FREQ=MONTHLY;BYMONTHDAY=${day}
SUMMARY:${summary}
DESCRIPTION:${description}
BEGIN:VALARM
TRIGGER:-P1D
ACTION:DISPLAY
DESCRIPTION:${summary}
END:VALARM
END:VEVENT`;
  return `BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Expense Tracker//Highnes//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-CALNAME:Pay Anand
${event('highnes-branch@ledger', 1, 'Pay Anand: Branch ₹2,981', 'Branch EMI is due. Pay Anand.')}
${event('highnes-clix@ledger', 7, 'Pay Anand: Clix ₹5,695', 'Clix EMI is due. Pay Anand.')}
${event('highnes-sbi@ledger', 17, 'Pay Anand: SBI EMI ₹4,820', 'SBI EMI is due. Pay Anand.')}
END:VCALENDAR
`;
}
