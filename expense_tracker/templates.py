"""HTML rendering functions for the expense tracker dashboard."""

from __future__ import annotations

import html
import urllib.parse
from decimal import Decimal, InvalidOperation

from .services import (
    CATEGORIES,
    EXPENSE_TYPES,
    active_period_label,
    credit_debit_totals,
    credits_by_category,
    credits_by_merchant,
    date_bounds,
    debits_by_category,
    debits_by_merchant,
    expenses_by_category,
    dashboard_totals,
    filter_dashboard_rows,
    filter_editable_rows,
    filter_review_rows,
    filter_transactions_by_text,
    people_from_split_ratio,
    review_people_value,
    sort_review_rows,
    split_display,
    top_merchants_from_rows,
)


def login_page(message: str | None = None, error: str | None = None) -> bytes:
    """Render the login page."""
    msg_html = f'<div class="toast success">{esc(message)}</div>' if message else ""
    err_html = f'<div class="toast error">{esc(error)}</div>' if error else ""
    body = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Login — Expense Tracker</title>
<link rel="stylesheet" href="/style.css">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body class="auth-page">
  <div class="auth-card">
    <h1>Expense Tracker</h1>
    <p class="auth-subtitle">Sign in to your account</p>
    {msg_html}{err_html}
    <form method="post" action="/login" class="auth-form">
      <label>Username<input type="text" name="username" autofocus required autocomplete="username"></label>
      <label>Password<input type="password" name="password" required autocomplete="current-password"></label>
      <button type="submit">Sign in</button>
    </form>
    <p class="auth-link">No account? <a href="/register">Register</a></p>
  </div>
</body></html>"""
    return body.encode("utf-8")


def register_page(message: str | None = None, error: str | None = None) -> bytes:
    """Render the registration page."""
    msg_html = f'<div class="toast success">{esc(message)}</div>' if message else ""
    err_html = f'<div class="toast error">{esc(error)}</div>' if error else ""
    body = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Register — Expense Tracker</title>
<link rel="stylesheet" href="/style.css">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body class="auth-page">
  <div class="auth-card">
    <h1>Expense Tracker</h1>
    <p class="auth-subtitle">Create an account</p>
    {msg_html}{err_html}
    <form method="post" action="/register" class="auth-form">
      <label>Username<input type="text" name="username" autofocus required autocomplete="username"></label>
      <label>Password<input type="password" name="password" required autocomplete="new-password"></label>
      <label>Confirm password<input type="password" name="confirm_password" required autocomplete="new-password"></label>
      <button type="submit">Create account</button>
    </form>
    <p class="auth-link">Already registered? <a href="/login">Sign in</a></p>
  </div>
</body></html>"""
    return body.encode("utf-8")


def money(value) -> str:
    try:
        return f"₹{Decimal(str(value or 0)):,.2f}"
    except InvalidOperation:
        return "₹0.00"


def signed_amount(value) -> str:
    try:
        amount = Decimal(str(value or 0))
    except InvalidOperation:
        amount = Decimal("0")
    if amount > 0:
        return f'<span class="amount credit">+ {money(amount)}</span>'
    if amount < 0:
        return f'<span class="amount debit">− {money(abs(amount))}</span>'
    return '<span class="amount">₹0.00</span>'


def esc(value) -> str:
    return html.escape(str(value or ""))


def row_get(row, key: str, default=None):
    """Access a sqlite3.Row key with a fallback (Row does not support .get())."""
    return row[key] if key in row.keys() else default


def option_tags(options: list[str], selected: str | None) -> str:
    return "".join(
        f'<option value="{esc(option)}" {"selected" if option == selected else ""}>{esc(option)}</option>'
        for option in options
    )


def render_dashboard_filters(
    start_date: str,
    end_date: str,
    min_date: str,
    max_date: str,
    exclude_business: bool,
    use_my_share: bool = False,
) -> str:
    return f"""
    <section class="dashboard-controls">
      <div class="section-head">
        <h2>Dashboard period</h2>
      </div>
      <form method="get" action="/" class="period-form">
        <label>Start date <input type="date" name="start_date" value="{esc(start_date)}" min="{esc(min_date)}" max="{esc(max_date)}"></label>
        <label>End date <input type="date" name="end_date" value="{esc(end_date)}" min="{esc(min_date)}" max="{esc(max_date)}"></label>
        <label class="check"><input type="checkbox" name="exclude_business" value="1" {"checked" if exclude_business else ""}> Exclude business</label>
        <button type="submit">Apply</button>
        <a class="button subtle" href="/">Reset</a>
      </form>
    </section>
    """


def render_credit_debit_pie(totals: dict[str, Decimal]) -> str:
    credit = totals["credit"]
    debit = totals["debit"]
    net = totals["net"]
    if credit == 0 and debit == 0:
        return '<p class="empty">No credits or debits in this period.</p>'
    return f"""
    <div class="pie-layout">
      <div class="chart-container" style="position: relative; height: 180px; width: 180px; margin: 0 auto;">
        <canvas id="creditDebitChart" data-credit="{float(credit)}" data-debit="{float(debit)}"></canvas>
      </div>
      <div class="pie-legend">
        <div><span class="legend-dot credit-dot"></span><strong>Credits</strong><span>{money(credit)}</span></div>
        <div><span class="legend-dot debit-dot"></span><strong>Debits</strong><span>{money(debit)}</span></div>
        <div><span class="legend-dot net-dot"></span><strong>Net</strong><span>{signed_amount(net)}</span></div>
      </div>
    </div>
    """


def render_categories_chart(categories_dict: dict[str, list[tuple[str, Decimal]]]) -> str:
    import json
    data_attrs = []
    for key in ['expenses', 'debits', 'credits']:
        categories = categories_dict.get(key, [])
        labels = [c[0] for c in categories]
        values = [float(c[1]) for c in categories]
        data_attrs.append(f'data-labels-{key}="{esc(json.dumps(labels))}" data-values-{key}="{esc(json.dumps(values))}"')
    
    return f"""
    <div class="chart-container" style="position: relative; min-height: 200px; width: 100%;">
      <canvas id="categoriesChart" {' '.join(data_attrs)}></canvas>
    </div>
    """


def render_merchants_chart(merchants_dict: dict[str, list[tuple[str, Decimal]]]) -> str:
    import json
    data_attrs = []
    for key in ['expenses', 'debits', 'credits']:
        merchants = merchants_dict.get(key, [])
        labels = [m[0] for m in merchants]
        values = [float(m[1]) for m in merchants]
        data_attrs.append(f'data-labels-{key}="{esc(json.dumps(labels))}" data-values-{key}="{esc(json.dumps(values))}"')
    
    return f"""
    <div class="chart-container" style="position: relative; min-height: 260px; width: 100%;">
      <canvas id="merchantsChart" {' '.join(data_attrs)}></canvas>
    </div>
    """


def render_manual_transaction_form() -> str:
    return f"""
    <section id="manual-transaction">
      <h2>Add manual transaction</h2>
      <form class="manual" method="post" action="/manual">
        <label>Date <input type="date" name="txn_date" required></label>
        <label>Direction <select name="direction">
          <option value="debit">Debit</option>
          <option value="credit">Credit</option>
        </select></label>
        <label>Amount <input type="number" name="amount" min="0.01" step="0.01" required></label>
        <label>Description <input name="description" required placeholder="Merchant or payee"></label>
        <label>Category <select name="category" required>
          <option value="">Choose</option>
          {option_tags(CATEGORIES, None)}
        </select></label>
        <label>Type <select name="expense_type">
          {option_tags(EXPENSE_TYPES, "Personal")}
        </select></label>
        <label>People <input name="split_people" type="number" min="1" step="1" value="1" title="Number of people sharing this expense"></label>
        <label>Notes <input name="notes" placeholder="Optional"></label>
        <label class="check"><input type="checkbox" name="learn"> Learn</label>
        <button type="submit">Add transaction</button>
      </form>
    </section>
    """


def render_money_flows_view(transactions: list[dict]) -> str:
    # Filter for transfers and loans
    money_flows = [t for t in transactions if t['expense_type'] in ('Transfer', 'Loan')]
    
    if not money_flows:
        return '<p class="empty">No money flow data available (Transfers & Loans).</p>'
        
    items_html = []
    for f in money_flows[:40]:
        date_str = f["txn_date"]
        merchant = f["merchant_display"]
        amount = f["amount_signed"]
        desc = f["description"]
        category = f["category"]
        expense_type = f["expense_type"]
        
        flow_class = "credit-flow" if amount > 0 else "debit-flow"
        cat_badge_html = f'<span class="rel-row-badge rel-cat">{esc(category)}</span>' if category else ""
        
        items_html.append(
            f"""
            <div class="timeline-node {flow_class}" style="margin-bottom:12px; padding:12px; border-left:4px solid {'var(--success)' if amount > 0 else 'var(--error)'}; background:var(--surface-color); border-radius:4px;">
              <div class="node-date" style="font-size:12px; color:var(--muted);">{esc(date_str)}</div>
              <div class="node-content" style="display:flex; justify-content:space-between; align-items:center;">
                <div class="node-title">
                  <strong style="display:block; margin-top:4px;">{esc(merchant)}</strong>
                  <span style="font-size:12px; color:var(--muted);">{esc(desc)}</span>
                </div>
                <div class="node-amount" style="font-weight:600; color:{'var(--success)' if amount > 0 else 'var(--error)'};">
                  {money(amount)}
                </div>
              </div>
              <div class="node-meta" style="margin-top:8px;">
                {cat_badge_html} <span class="rel-row-badge rel-type" style="margin-left:8px; font-size:11px; background:var(--border-color); padding:2px 6px; border-radius:4px;">{esc(expense_type)}</span>
              </div>
            </div>
            """
        )
        
    return f'<div class="timeline" style="margin-top:16px;">{"".join(items_html)}</div>'


def _contact_option_tags(contacts: list[dict], selected_id=None) -> str:
    opts = ['<option value="">— Select contact —</option>']
    for item in contacts:
        c = item.get("contact") if isinstance(item, dict) and "contact" in item else item
        if not c:
            continue
        cid = c.get("id")
        name = c.get("name") or "?"
        sel = " selected" if selected_id and int(selected_id) == int(cid) else ""
        opts.append(f'<option value="{cid}"{sel}>{esc(name)}</option>')
    return "".join(opts)


def render_contacts_section(
    contacts: list[dict],
    passthrough_candidates: list[dict],
    partner_balances: list[dict] | None = None,
    merge_suggestions: list[dict] | None = None,
) -> str:
    # Compute aggregate metrics
    total_owes_you = Decimal("0")
    total_you_owe = Decimal("0")
    for item in contacts:
        bal = item["balance"]
        net = Decimal(str(bal["net_balance"]))
        if net > 0:
            total_owes_you += net
        elif net < 0:
            total_you_owe += abs(net)

    # Khata Summary Cards
    summary_cards_html = f"""
    <div class="grid metrics" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:16px; margin-bottom:20px;">
      <div class="metric" style="background:var(--surface-color); border:1px solid var(--border-color); border-radius:12px; padding:16px;">
        <span style="font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; font-weight:600;">Net Owed to You</span>
        <strong style="display:block; margin-top:4px; font-size:22px; color:var(--success);">{money(total_owes_you)}</strong>
      </div>
      <div class="metric" style="background:var(--surface-color); border:1px solid var(--border-color); border-radius:12px; padding:16px;">
        <span style="font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; font-weight:600;">Net You Owe</span>
        <strong style="display:block; margin-top:4px; font-size:22px; color:var(--error);">{money(total_you_owe)}</strong>
      </div>
      <div class="metric" style="background:var(--surface-color); border:1px solid var(--border-color); border-radius:12px; padding:16px;">
        <span style="font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; font-weight:600;">Active Contacts</span>
        <strong style="display:block; margin-top:4px; font-size:22px; color:var(--text-color);">{len(contacts)}</strong>
      </div>
    </div>
    """

    # Who owes whom (on People)
    people_settlement_html = render_home_settlement_strip(partner_balances or [], limit=8)

    # Contact select options (rolling, opening, PT pickers, manual merge)
    contact_opts = _contact_option_tags(contacts)

    # Merge suggestions
    merge_html = ""
    if merge_suggestions:
        cards = []
        for sug in merge_suggestions[:6]:
            losers = ", ".join(esc(n) for n in sug.get("loser_names") or [])
            loser_ids = ",".join(str(i) for i in sug.get("loser_ids") or [])
            cards.append(
                f"""
                <div class="merge-suggest-card">
                  <div class="merge-suggest-body">
                    <strong>Merge into {esc(sug.get('winner_name') or '?')}</strong>
                    <span class="merge-suggest-meta">Also: {losers}</span>
                    <span class="merge-suggest-reason">{esc(sug.get('reason') or '')}</span>
                  </div>
                  <form method="post" action="/contacts/merge" class="merge-suggest-form"
                        onsubmit="return confirm('Merge these contacts into {esc(sug.get('winner_name') or '')}? Ledger rows will be combined and duplicates cleaned.');">
                    <input type="hidden" name="winner_id" value="{sug.get('winner_id')}">
                    <input type="hidden" name="loser_ids" value="{loser_ids}">
                    <button type="submit" class="button">Merge</button>
                  </form>
                </div>
                """
            )
        merge_html = f"""
        <section class="home-strip merge-suggestions" aria-label="Merge suggestions">
          <div class="home-strip-header">
            <h2>Suggested merges</h2>
            <span class="home-chip muted" style="padding:4px 10px; font-size:11px;">{len(merge_suggestions)} cluster(s)</span>
          </div>
          <div class="merge-suggest-list">{"".join(cards)}</div>
          <p class="empty" style="margin:8px 0 0; font-size:12px;">Merging reassigns ledger rows to the winner and voids migrate/pass-through duplicates.</p>
        </section>
        """

    # Search & Filter Controls
    search_bar_html = """
    <div style="display:flex; flex-wrap:wrap; gap:12px; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <div style="flex:1; min-width:240px; max-width:400px; position:relative;">
        <input id="contact-search-input" onkeyup="filterContactCards()" placeholder="Search contact by name or handle..." style="width:100%; padding:10px 14px 10px 36px; border-radius:20px; border:1px solid var(--border-color); background:var(--surface-color); color:var(--text-color); font-size:14px;">
        <svg viewBox="0 0 24 24" style="position:absolute; left:12px; top:50%; transform:translateY(-50%); width:16px; height:16px; fill:var(--muted);"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
      </div>
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        <button class="button filter-pill active" data-filter="all" onclick="filterContactStatus('all', this)" style="padding:6px 14px; font-size:12px; border-radius:16px;">All</button>
        <button class="button subtle filter-pill" data-filter="owes_you" onclick="filterContactStatus('owes_you', this)" style="padding:6px 14px; font-size:12px; border-radius:16px;">Owes Me</button>
        <button class="button subtle filter-pill" data-filter="you_owe" onclick="filterContactStatus('you_owe', this)" style="padding:6px 14px; font-size:12px; border-radius:16px;">I Owe</button>
        <button class="button subtle filter-pill" data-filter="settled" onclick="filterContactStatus('settled', this)" style="padding:6px 14px; font-size:12px; border-radius:16px;">Settled</button>
        <button class="button" onclick="document.getElementById('modal-add-contact').style.display='flex'" style="padding:6px 16px; font-size:13px; border-radius:20px;">+ New Contact</button>
        <button class="button subtle" type="button" onclick="document.getElementById('modal-manual-merge').style.display='flex'" style="padding:6px 16px; font-size:13px; border-radius:20px;">Manual merge</button>
      </div>
    </div>
    """

    # Rolling mode + Opening balance (user's main real-world workflows)
    today = __import__("datetime").date.today().isoformat()
    workflow_html = f"""
    <div class="people-workflow-grid">
      <section class="home-strip rolling-panel" aria-label="Rolling mode">
        <div class="home-strip-header">
          <h2>Rolling mode</h2>
          <span class="home-chip accent" style="padding:4px 10px; font-size:11px;">A → you → B · nets stay 0</span>
        </div>
        <p class="empty" style="margin:0 0 12px; font-size:13px;">
          e.g. Ranjima sends you ₹20,000 → you send Highnes ₹20,000. Both legs pass-through (not personal debt).
        </p>
        <form method="post" action="/ledger/rolling" class="workflow-form"
              onsubmit="return confirm('Post rolling chain? Neither person\\'s debt net should change.');">
          <label>Money received from
            <select name="from_contact_id" required>{contact_opts}</select>
          </label>
          <label>Money sent to
            <select name="to_contact_id" required>{contact_opts}</select>
          </label>
          <label>Amount (₹)
            <input type="number" name="amount" step="0.01" min="0.01" required placeholder="20000">
          </label>
          <label>Date
            <input type="date" name="entry_date" value="{today}">
          </label>
          <label class="workflow-notes">Note (optional)
            <input type="text" name="notes" placeholder="e.g. Highnes needed 20k, Ranjima funded">
          </label>
          <button type="submit" class="button">Post rolling chain</button>
        </form>
      </section>

      <section class="home-strip opening-panel" aria-label="Opening balance">
        <div class="home-strip-header">
          <h2>Opening / stock balance</h2>
          <span class="home-chip muted" style="padding:4px 10px; font-size:11px;">one click</span>
        </div>
        <p class="empty" style="margin:0 0 12px; font-size:13px;">
          e.g. Highnes already owes you ₹50,000 before this month&apos;s bank lines.
        </p>
        <form method="post" action="/ledger/opening" class="workflow-form"
              onsubmit="return confirm('Set opening balance for this person?');">
          <label>Person
            <select name="contact_id" required>{contact_opts}</select>
          </label>
          <label>Direction
            <select name="direction">
              <option value="they_owe_you" selected>They owe me</option>
              <option value="you_owe_them">I owe them</option>
            </select>
          </label>
          <label>Amount (₹)
            <input type="number" name="amount" step="0.01" min="0.01" required placeholder="50000">
          </label>
          <label>Date
            <input type="date" name="entry_date" value="{today}">
          </label>
          <label class="workflow-notes">Note (optional)
            <input type="text" name="notes" placeholder="e.g. Prior balance before June">
          </label>
          <button type="submit" class="button">Set opening</button>
        </form>
      </section>
    </div>
    """

    # Pass-through banner with contact pickers when unlinked
    banner_html = ""
    if passthrough_candidates:
        candidate_items = []
        for cand in passthrough_candidates[:5]:
            amt = cand.get("credit_amount") or cand.get("amount") or 0
            from_name = cand.get("credit_contact") or cand.get("credit_merchant") or "Unknown"
            to_name = cand.get("debit_contact") or cand.get("debit_merchant") or "Unknown"
            dt = cand.get("credit_date") or cand.get("date") or ""
            credit_id = cand.get("credit_tx_id") or cand.get("credit_id") or 0
            debit_id = cand.get("debit_tx_id") or cand.get("debit_id") or 0
            from_contact_id = cand.get("from_contact_id") or 0
            to_contact_id = cand.get("to_contact_id") or 0
            needs_from = not from_contact_id
            needs_to = not to_contact_id
            from_field = (
                f'<label class="pt-pick">From (received)<select name="from_contact_id" required>{_contact_option_tags(contacts, from_contact_id or None)}</select></label>'
                if needs_from
                else f'<input type="hidden" name="from_contact_id" value="{from_contact_id}">'
            )
            to_field = (
                f'<label class="pt-pick">To (forwarded)<select name="to_contact_id" required>{_contact_option_tags(contacts, to_contact_id or None)}</select></label>'
                if needs_to
                else f'<input type="hidden" name="to_contact_id" value="{to_contact_id}">'
            )
            warn = ""
            if needs_from or needs_to:
                warn = '<div class="pt-warn">Link missing contact(s) before confirming.</div>'
            candidate_items.append(
                f"""
                <div class="passthrough-card">
                  <div class="passthrough-card-main">
                    <strong class="pt-title">⚡ Pass-through candidate</strong>
                    <div>Received <strong>{money(amt)}</strong> from <strong>{esc(from_name)}</strong>
                    → forwarded to <strong>{esc(to_name)}</strong> on {esc(dt)}</div>
                    {warn}
                  </div>
                  <form method="post" action="/ledger/passthrough/confirm" class="passthrough-form">
                    <input type="hidden" name="credit_id" value="{credit_id}">
                    <input type="hidden" name="debit_id" value="{debit_id}">
                    <input type="hidden" name="amount" value="{amt}">
                    <input type="hidden" name="entry_date" value="{dt}">
                    <div class="pt-pickers">{from_field}{to_field}</div>
                    <div class="pt-actions">
                      <button type="submit" name="action" value="confirm" class="button">Confirm pass-through</button>
                      <button type="submit" name="action" value="dismiss" class="button subtle" formnovalidate>Dismiss</button>
                    </div>
                  </form>
                </div>
                """
            )
        banner_html = f'<div class="passthrough-candidates-banner">{"".join(candidate_items)}</div>'

    # Contacts Cards Grid
    cards_html = []
    colors = ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#ec4899", "#06b6d4"]
    
    for idx, item in enumerate(contacts):
        contact = item["contact"]
        bal = item["balance"]
        cid = contact["id"]
        cname = contact["name"]
        aliases = contact.get("aliases", [])
        aliases_str = ", ".join(aliases) if aliases else ""
        net = bal["net_balance"]
        total_sent = bal["total_you_sent"]
        total_rec = bal["total_they_sent"]
        
        if net > 0:
            status_text = f"Owes you {money(net)}"
            status_code = "owes_you"
            badge_style = "background:rgba(16,185,129,0.12); color:#10b981; border:1px solid rgba(16,185,129,0.3);"
        elif net < 0:
            status_text = f"You owe {money(abs(net))}"
            status_code = "you_owe"
            badge_style = "background:rgba(239,68,68,0.12); color:#ef4444; border:1px solid rgba(239,68,68,0.3);"
        else:
            status_text = "Settled (₹0)"
            status_code = "settled"
            badge_style = "background:var(--border-color); color:var(--muted);"
            
        initial = cname[0].upper() if cname else "?"
        avatar_bg = colors[idx % len(colors)]
        
        cards_html.append(
            f"""
            <div class="contact-card" data-name="{esc(cname.lower())}" data-aliases="{esc(aliases_str.lower())}" data-status="{status_code}" style="background:var(--surface-color); border:1px solid var(--border-color); border-radius:14px; padding:18px; display:flex; flex-direction:column; justify-content:space-between; transition:all 0.25s ease;" onmouseover="this.style.transform='translateY(-4px)';this.style.boxShadow='0 8px 24px rgba(0,0,0,0.12)';" onmouseout="this.style.transform='none';this.style.boxShadow='none';">
              <div>
                <div style="display:flex; align-items:flex-start; justify-content:space-between; margin-bottom:14px;">
                  <div style="display:flex; align-items:center; gap:12px;">
                    <div style="width:42px; height:42px; border-radius:50%; background:{avatar_bg}; color:#fff; display:flex; align-items:center; justify-content:center; font-weight:bold; font-size:18px; box-shadow:0 2px 8px rgba(0,0,0,0.15);">{esc(initial)}</div>
                    <div>
                      <h3 style="margin:0; font-size:17px; font-weight:600;">{esc(cname)}</h3>
                      {f'<span style="font-size:11px; color:var(--muted); display:block; margin-top:2px;">{esc(aliases_str[:30])}</span>' if aliases_str else ''}
                    </div>
                  </div>
                  <span class="badge" style="font-size:12px; font-weight:600; padding:5px 10px; border-radius:12px; {badge_style}">{esc(status_text)}</span>
                </div>
                <div style="font-size:13px; color:var(--muted); background:var(--background-color); border-radius:8px; padding:10px; margin-bottom:16px; display:flex; justify-content:space-between;">
                  <div>You sent: <strong style="color:var(--text-color);">{money(total_sent)}</strong></div>
                  <div>They sent: <strong style="color:var(--text-color);">{money(total_rec)}</strong></div>
                </div>
              </div>
              <div style="display:flex; gap:10px;">
                <button class="button subtle" onclick="openLedgerDrawer({cid}, '{esc(cname)}')" style="flex:1; padding:8px 12px; font-size:13px; border-radius:8px;">View Ledger</button>
                <button class="button" onclick="openAddLedgerModal({cid}, '{esc(cname)}')" style="flex:1; padding:8px 12px; font-size:13px; border-radius:8px;">+ Entry</button>
              </div>
            </div>
            """
        )

    grid_html = f'<div id="contacts-grid" class="grid" style="grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:18px;">{"".join(cards_html) if cards_html else "<p class=\'empty\'>No contacts found.</p>"}</div>'

    add_contact_modal = """
    <div id="modal-add-contact" class="modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); backdrop-filter:blur(4px); align-items:center; justify-content:center; z-index:1000;">
      <div style="background:var(--surface-color); border:1px solid var(--border-color); padding:28px; border-radius:16px; width:100%; max-width:420px; box-shadow:0 20px 40px rgba(0,0,0,0.3);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
          <h3 style="margin:0; font-size:18px;">Add New Contact</h3>
          <button class="button subtle" onclick="document.getElementById('modal-add-contact').style.display='none'" style="padding:4px 8px;">✕</button>
        </div>
        <form method="post" action="/contacts/create">
          <label style="display:block; margin-bottom:14px; font-size:13px; font-weight:600;">Contact Name
            <input name="name" required placeholder="e.g. Highnes" style="width:100%; margin-top:6px; padding:10px 12px; border-radius:8px; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color);">
          </label>
          <label style="display:block; margin-bottom:14px; font-size:13px; font-weight:600;">UPI Handles / Phone Aliases
            <input name="aliases" placeholder="e.g. highnes.7@sibl, 8078866770" style="width:100%; margin-top:6px; padding:10px 12px; border-radius:8px; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color);">
          </label>
          <label style="display:block; margin-bottom:20px; font-size:13px; font-weight:600;">Notes
            <input name="notes" placeholder="Optional notes (e.g. roommate)" style="width:100%; margin-top:6px; padding:10px 12px; border-radius:8px; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color);">
          </label>
          <div style="display:flex; justify-content:flex-end; gap:10px;">
            <button type="button" class="button subtle" onclick="document.getElementById('modal-add-contact').style.display='none'" style="padding:8px 16px;">Cancel</button>
            <button type="submit" class="button" style="padding:8px 20px;">Create Contact</button>
          </div>
        </form>
      </div>
    </div>
    """

    add_entry_modal = """
    <div id="modal-add-ledger" class="modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); backdrop-filter:blur(4px); align-items:center; justify-content:center; z-index:1000;">
      <div style="background:var(--surface-color); border:1px solid var(--border-color); padding:28px; border-radius:16px; width:100%; max-width:460px; box-shadow:0 20px 40px rgba(0,0,0,0.3);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
          <h3 style="margin:0; font-size:18px;">Add Ledger Entry for <span id="ledger-modal-contact-name" style="color:var(--accent);"></span></h3>
          <button class="button subtle" onclick="document.getElementById('modal-add-ledger').style.display='none'" style="padding:4px 8px;">✕</button>
        </div>
        <form method="post" action="/ledger/add">
          <input type="hidden" id="ledger-modal-contact-id" name="contact_id">
          
          <label style="display:block; margin-bottom:14px; font-size:13px; font-weight:600;">Direction
            <select name="direction" style="width:100%; margin-top:6px; padding:10px 12px; border-radius:8px; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color);">
              <option value="you_sent">You Sent (They owe you)</option>
              <option value="they_sent">They Sent (You owe them)</option>
            </select>
          </label>
          
          <label style="display:block; margin-bottom:14px; font-size:13px; font-weight:600;">Amount (₹)
            <input type="number" step="0.01" min="0.01" name="amount" required placeholder="0.00" style="width:100%; margin-top:6px; padding:10px 12px; border-radius:8px; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color); font-size:16px; font-weight:bold;">
          </label>

          <label style="display:block; margin-bottom:14px; font-size:13px; font-weight:600;">Purpose
            <select name="purpose" style="width:100%; margin-top:6px; padding:10px 12px; border-radius:8px; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color);">
              <option value="loan">Loan / Borrowed</option>
              <option value="rolling">Rolling Money</option>
              <option value="food_split">Food Split</option>
              <option value="trip">Trip Expense</option>
              <option value="other" selected>Other</option>
            </select>
          </label>

          <label style="display:block; margin-bottom:14px; font-size:13px; font-weight:600;">Date
            <input type="date" name="entry_date" id="ledger-modal-date" style="width:100%; margin-top:6px; padding:10px 12px; border-radius:8px; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color);">
          </label>

          <label style="display:block; margin-bottom:14px; font-size:13px; font-weight:600;">Notes
            <input name="notes" placeholder="Optional details (e.g. Cash, GPay, Food bill)" style="width:100%; margin-top:6px; padding:10px 12px; border-radius:8px; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color);">
          </label>

          <label class="check" style="display:flex; align-items:center; gap:8px; margin-bottom:20px; font-size:13px; cursor:pointer;">
            <input type="checkbox" name="is_opening_balance"> Pre-July Opening Balance
          </label>

          <div style="display:flex; justify-content:flex-end; gap:10px;">
            <button type="button" class="button subtle" onclick="document.getElementById('modal-add-ledger').style.display='none'" style="padding:8px 16px;">Cancel</button>
            <button type="submit" class="button" style="padding:8px 20px;">Save Entry</button>
          </div>
        </form>
      </div>
    </div>
    """

    drawer_html = """
    <div id="ledger-drawer-backdrop" onclick="closeLedgerDrawer()" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); backdrop-filter:blur(3px); z-index:1099;"></div>
    <div id="ledger-drawer" style="display:none; position:fixed; top:0; right:0; width:100%; max-width:520px; height:100vh; background:var(--surface-color); border-left:1px solid var(--border-color); box-shadow:-8px 0 32px rgba(0,0,0,0.25); z-index:1100; flex-direction:column; padding:24px; overflow-y:auto; transition:transform 0.3s ease;">
      <div style="display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--border-color); padding-bottom:16px; margin-bottom:16px;">
        <h3 id="drawer-contact-name" style="margin:0; font-size:18px;">Ledger History</h3>
        <button class="button subtle" onclick="closeLedgerDrawer()" style="padding:6px 12px; font-size:14px; border-radius:8px;">✕ Close</button>
      </div>

      <div id="drawer-balance-summary" style="background:var(--background-color); border:1px solid var(--border-color); border-radius:12px; padding:16px; margin-bottom:16px;">
        <!-- Filled dynamically by JS -->
      </div>

      <div style="margin-bottom:12px; display:flex; gap:6px; flex-wrap:wrap;">
        <button class="button filter-pill active" onclick="filterDrawerEntries('all', this)" style="padding:4px 10px; font-size:11px; border-radius:12px;">All</button>
        <button class="button subtle filter-pill" onclick="filterDrawerEntries('you_sent', this)" style="padding:4px 10px; font-size:11px; border-radius:12px;">Given (+)</button>
        <button class="button subtle filter-pill" onclick="filterDrawerEntries('they_sent', this)" style="padding:4px 10px; font-size:11px; border-radius:12px;">Received (-)</button>
      </div>

      <form method="post" action="/ledger/settle" id="drawer-settle-form" class="drawer-settle-form">
        <input type="hidden" id="drawer-settle-contact-id" name="contact_id">
        <div class="drawer-settle-row">
          <label>Settle amount (₹)
            <input type="number" name="amount" id="drawer-settle-amount" step="0.01" min="0.01" placeholder="Full balance if empty">
          </label>
          <div class="drawer-settle-actions">
            <button type="button" class="button subtle" id="drawer-settle-full-btn" onclick="fillFullSettleAmount()">Use full</button>
            <button type="submit" class="button" onclick="return confirmSettle()">Settle</button>
          </div>
        </div>
        <p class="empty" style="margin:6px 0 0; font-size:11px;">Leave amount blank to settle the full USB net. Partial settle posts a compensating entry.</p>
      </form>

      <div id="drawer-entries-list" style="margin-top:16px;">
        <!-- Filled dynamically by JS -->
      </div>
    </div>
    """

    manual_merge_modal = f"""
    <div id="modal-manual-merge" class="modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); backdrop-filter:blur(4px); align-items:center; justify-content:center; z-index:1000;">
      <div style="background:var(--surface-color); border:1px solid var(--border-color); padding:28px; border-radius:16px; width:100%; max-width:460px; box-shadow:0 20px 40px rgba(0,0,0,0.3);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
          <h3 style="margin:0; font-size:18px;">Manual merge</h3>
          <button class="button subtle" type="button" onclick="document.getElementById('modal-manual-merge').style.display='none'">✕</button>
        </div>
        <form method="post" action="/contacts/merge" onsubmit="return confirm('Merge selected contacts?');">
          <label style="display:block; margin-bottom:12px; font-size:13px; font-weight:600;">Keep (winner)
            <select name="winner_id" required style="width:100%; margin-top:6px; padding:10px; border-radius:8px; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color);">
              {contact_opts}
            </select>
          </label>
          <label style="display:block; margin-bottom:16px; font-size:13px; font-weight:600;">Merge away (loser IDs, comma-separated)
            <input name="loser_ids" required placeholder="e.g. 12,15,18" style="width:100%; margin-top:6px; padding:10px; border-radius:8px; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color);">
          </label>
          <p class="empty" style="font-size:12px; margin:0 0 16px;">Tip: open a suggested merge card for one-click clusters, or use contact IDs from the cards.</p>
          <div style="display:flex; justify-content:flex-end; gap:10px;">
            <button type="button" class="button subtle" onclick="document.getElementById('modal-manual-merge').style.display='none'">Cancel</button>
            <button type="submit" class="button">Merge</button>
          </div>
        </form>
      </div>
    </div>
    """

    return f"""
    <section>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
        <h2>People (Khata)</h2>
      </div>
      {summary_cards_html}
      {people_settlement_html}
      {workflow_html}
      {merge_html}
      {search_bar_html}
      {banner_html}
      {grid_html}
      {add_contact_modal}
      {add_entry_modal}
      {manual_merge_modal}
      {drawer_html}
    </section>
    """


def collapsible_section(section_id: str, title: str, body: str, meta: str = "", open_section: bool = False) -> str:
    open_attr = " open" if open_section else ""
    meta_html = f'<span class="summary-meta">{esc(meta)}</span>' if meta else ""
    return f"""
    <details id="{esc(section_id)}" class="collapsible"{open_attr}>
      <summary><span>{esc(title)}</span>{meta_html}</summary>
      <div class="collapsible-body">
        {body}
      </div>
    </details>
    """


def review_sort_controls(direction: str, search_query: str = "") -> str:
    newest_class = "active" if direction != "oldest" else ""
    oldest_class = "active" if direction == "oldest" else ""
    search_param = f"&review_search={urllib.parse.quote(search_query)}" if search_query else ""
    return f"""
    <div class="section-tools">
      <span>Sort by date</span>
      <div class="segmented" aria-label="Review date sort">
        <a class="{newest_class}" href="/?review_sort=newest{search_param}#review">Newest first</a>
        <a class="{oldest_class}" href="/?review_sort=oldest{search_param}#review">Oldest first</a>
      </div>
    </div>
    """


def person_search_controls(search_query: str, result_count: int) -> str:
    clear_link = '<a class="button subtle" href="/#person-search">Clear</a>' if search_query.strip() else ""
    result_text = f"{result_count} matching transaction(s)" if search_query.strip() else "Type a name or text to search"
    return f"""
    <form method="get" action="/" class="person-search-form">
      <label>Search person or text <input name="person_search" value="{esc(search_query)}" placeholder="Example: highnes"></label>
      <button type="submit">Search</button>
      {clear_link}
      <span>{esc(result_text)}</span>
    </form>
    """


def render_credit_debit_graph(rows, query: str) -> str:
    if not query.strip():
        return '<p class="empty">Search a name or statement text to see matching credits and debits.</p>'
    if not rows:
        return '<p class="empty">No matching transactions found.</p>'

    credit_total, debit_total = credit_debit_totals(rows)
    max_total = max(credit_total, debit_total, Decimal("1"))
    credit_width = max(2, int((credit_total / max_total) * 100)) if credit_total else 2
    debit_width = max(2, int((debit_total / max_total) * 100)) if debit_total else 2
    net = credit_total - debit_total
    return f"""
    <div class="credit-debit-graph">
      <div class="summary-pair">
        <div><span>Total credits</span><strong class="credit-text">{money(credit_total)}</strong></div>
        <div><span>Total debits</span><strong class="debit-text">{money(debit_total)}</strong></div>
        <div><span>Net</span><strong>{signed_amount(net)}</strong></div>
      </div>
      <div class="bar-row">
        <div class="bar-label">Credits</div>
        <div class="bar-track"><div class="bar-fill credit-fill" style="width:{credit_width}%"></div></div>
        <div class="bar-value">{money(credit_total)}</div>
      </div>
      <div class="bar-row">
        <div class="bar-label">Debits</div>
        <div class="bar-track"><div class="bar-fill debit-fill" style="width:{debit_width}%"></div></div>
        <div class="bar-value">{money(debit_total)}</div>
      </div>
    </div>
    """


def category_badge(category: str) -> str:
    cat_lower = str(category or "").lower()
    style_class = "uncategorized"
    if "food" in cat_lower or "dining" in cat_lower or "groceries" in cat_lower:
        style_class = "cat-food"
    elif "personal" in cat_lower:
        style_class = "cat-personal"
    elif "business" in cat_lower:
        style_class = "cat-business"
    elif "health" in cat_lower:
        style_class = "cat-health"
    elif "transport" in cat_lower or "travel" in cat_lower:
        style_class = "cat-transport"
    elif "leisure" in cat_lower or "entertainment" in cat_lower:
        style_class = "cat-leisure"
    elif "family" in cat_lower:
        style_class = "cat-family"
    return f'<span class="cat-badge {style_class}">{esc(category or "Uncategorized")}</span>'


def render_person_transaction_rows(rows) -> str:
    if not rows:
        return '<tr><td colspan="6" class="empty">No transactions to show.</td></tr>'
    output = []
    for row in rows:
        output.append(
            f"""
            <tr>
              <td>{esc(row['txn_date'])}</td>
              <td><strong>{esc(row['merchant_display'])}</strong><span>{esc(row['description'])}</span></td>
              <td>{money(row['credit'])}</td>
              <td>{money(row['debit'])}</td>
              <td>{signed_amount(row['amount_signed'])}</td>
              <td>{category_badge(row['category'])}</td>
            </tr>
            """
        )
    return "".join(output)


def review_search_controls(search_query: str, review_sort: str, total_count: int, filtered_count: int) -> str:
    result_text = (
        f"{filtered_count} of {total_count} pending"
        if search_query.strip()
        else f"{total_count} pending"
    )
    clear_link = (
        f'<a class="button subtle" href="/?review_sort={esc(review_sort)}#review">Clear</a>'
        if search_query.strip()
        else ""
    )
    return f"""
    <form method="get" action="/" class="review-search">
      <input type="hidden" name="review_sort" value="{esc(review_sort)}">
      <label>Search review cases <input name="review_search" value="{esc(search_query)}" placeholder="Merchant, notes, amount"></label>
      <button type="submit">Search</button>
      {clear_link}
      <span>{esc(result_text)}</span>
    </form>
    """


def edit_search_controls(search_query: str, total_count: int, filtered_count: int, shown_count: int) -> str:
    if search_query.strip():
        result_text = f"{filtered_count} of {total_count} classified"
    else:
        result_text = f"Showing recent {shown_count} of {total_count} classified"
    clear_link = '<a class="button subtle" href="/#edit-classifications">Clear</a>' if search_query.strip() else ""
    return f"""
    <form method="get" action="/" class="review-search">
      <label>Search classified transactions <input name="edit_search" value="{esc(search_query)}" placeholder="Merchant, category, notes, amount"></label>
      <button type="submit">Search</button>
      {clear_link}
      <span>{esc(result_text)}</span>
    </form>
    """


def bar_list(items, max_value=None) -> str:
    if not items:
        return '<p class="empty">No data yet.</p>'
    maximum = Decimal(str(max_value or max((amount for _, amount in items), default=1) or 1))
    rows = []
    for label, amount in items:
        amount_dec = Decimal(str(amount or 0))
        width = max(2, int((amount_dec / maximum) * 100)) if maximum else 2
        rows.append(
            f"""
            <div class="bar-row">
              <div class="bar-label">{esc(label)}</div>
              <div class="bar-track"><div class="bar-fill" style="width:{width}%"></div></div>
              <div class="bar-value">{money(amount_dec)}</div>
            </div>
            """
        )
    return "".join(rows)


TYPE_CHIP_ORDER = ["Personal", "Shared", "Loan", "Transfer", "Business", "Other"]


def _type_chips_html(row_key: str, selected: str | None, select_name: str) -> str:
    selected = selected if selected in EXPENSE_TYPES else "Personal"
    chips = []
    for t in TYPE_CHIP_ORDER:
        active = " active" if t == selected else ""
        chips.append(
            f'<button type="button" class="type-chip{active}" data-type="{esc(t)}" '
            f'data-row="{esc(row_key)}" onclick="selectExpenseType(this)">{esc(t)}</button>'
        )
    return f"""
    <div class="type-chip-row" data-row="{esc(row_key)}">
      {''.join(chips)}
    </div>
    <select name="{esc(select_name)}" class="expense-type-select" data-row="{esc(row_key)}"
            onchange="toggleTypeFields(this)" style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0;" tabindex="-1" aria-hidden="true">
      {option_tags(EXPENSE_TYPES, selected)}
    </select>
    """


def render_review_rows(rows) -> str:
    if not rows:
        return '<tr><td colspan="8" class="empty">Nothing waiting for review.</td></tr>'
    output = []
    for row in rows:
        row_id = row["id"]
        et = row_get(row, "expense_type") or "Personal"
        status = row_get(row, "status") or "needs_review"
        shared_show = "display:none" if et != "Shared" else ""
        output.append(
            f"""
            <tr class="tx-row" data-status="{esc(status)}" data-expense-type="{esc(et)}" data-filter-bucket="needs_review">
              <td>{esc(row['txn_date'])}</td>
              <td>
                <strong>{esc(row['merchant_display'])}</strong>
                <span>{esc(row['description'])}</span>
                <span class="badge warn" style="margin-top:4px; display:inline-block;">needs review</span>
              </td>
              <td>{signed_amount(row['amount_signed'])}</td>
              <td colspan="5">
                <div class="review-form" data-row="{row_id}">
                  <input type="hidden" name="review_ids" value="{row_id}">
                  <div class="review-field type-field-block">
                    <span class="field-label">Type</span>
                    {_type_chips_html(str(row_id), et, f"expense_type_{row_id}")}
                  </div>
                  <label class="review-field"><span>Category</span><select name="category_{row_id}" class="category-select" data-row="{row_id}" onchange="updateStickyBatchCounts()">
                    <option value="">Choose</option>
                    {option_tags(CATEGORIES, row_get(row, 'category'))}
                  </select></label>
                  <label class="review-field shared-only-field" data-row="{row_id}" style="{shared_show}"><span>People</span><input name="split_people_{row_id}" type="number" min="1" step="1" value="{review_people_value(row)}" title="Number of people sharing this expense"></label>
                  <label class="review-field shared-only-field" data-row="{row_id}" style="{shared_show}"><span>Shared with</span><input name="shared_with_{row_id}" list="contact-partner-list" placeholder="Contact or username" title="Partner for shared expenses" value="{esc(row_get(row, 'shared_with', '') or '')}"></label>
                  <label class="review-field"><span>Notes</span><input name="notes_{row_id}" placeholder="Optional"></label>
                  <label class="check"><input type="checkbox" name="learn_{row_id}"> Learn</label>
                </div>
              </td>
            </tr>
            """
        )
    return "".join(output)


def render_edit_rows(rows) -> str:
    if not rows:
        return '<tr><td colspan="9" class="empty">No classified transactions found.</td></tr>'
    output = []
    for row in rows:
        row_id = row["id"]
        et = row["expense_type"] or "Personal"
        badge = "ok" if row["status"] != "needs_review" else "warn"
        shared_show = "display:none" if et != "Shared" else ""
        bucket = "needs_review" if row["status"] == "needs_review" else (
            "shared" if et == "Shared" else ("loan" if et == "Loan" else "classified")
        )
        output.append(
            f"""
            <tr class="tx-row" data-status="{esc(row['status'])}" data-expense-type="{esc(et)}" data-filter-bucket="{bucket}">
              <td>{esc(row['txn_date'])}</td>
              <td>
                <strong>{esc(row['merchant_display'])}</strong>
                <span>{esc(row['description'])}</span>
              </td>
              <td>{signed_amount(row['amount_signed'])}</td>
              <td><span class="badge {badge}">{esc(row['status'])}</span></td>
              <td colspan="5">
                <div class="review-form" data-row="edit_{row_id}">
                  <input type="hidden" name="edit_ids" value="{row_id}">
                  <div class="review-field type-field-block">
                    <span class="field-label">Type</span>
                    {_type_chips_html(f"edit_{row_id}", et, f"edit_expense_type_{row_id}")}
                  </div>
                  <label class="review-field"><span>Category</span><select name="edit_category_{row_id}" class="category-select" data-row="edit_{row_id}" onchange="updateStickyBatchCounts()">
                    <option value="">Choose</option>
                    {option_tags(CATEGORIES, row['category'])}
                  </select></label>
                  <label class="review-field shared-only-field" data-row="edit_{row_id}" style="{shared_show}"><span>People</span><input name="edit_split_people_{row_id}" type="number" min="1" step="1" value="{review_people_value(row)}" title="Number of people sharing this expense"></label>
                  <label class="review-field shared-only-field" data-row="edit_{row_id}" style="{shared_show}"><span>Shared with</span><input name="edit_shared_with_{row_id}" list="contact-partner-list" placeholder="Contact or username" value="{esc(row_get(row, 'shared_with', '') or '')}"></label>
                  <label class="review-field"><span>Notes</span><input name="edit_notes_{row_id}" value="{esc(row_get(row, 'notes', '') or '')}" placeholder="Optional"></label>
                  <label class="check"><input type="checkbox" name="edit_learn_{row_id}"> Learn</label>
                </div>
              </td>
            </tr>
            """
        )
    return "".join(output)


def render_loan_suggestions(suggestions: list[dict]) -> str:
    if not suggestions:
        return ""
    cards = []
    for s in suggestions[:6]:
        cards.append(
            f"""
            <div class="loan-suggest-card">
              <div>
                <strong>Post {money(s['amount'])} as loan to {esc(s['contact_name'])}?</strong>
                <div class="loan-suggest-meta">{esc(s['txn_date'])} · {esc(s['merchant_display'])}
                  · type {esc(s.get('expense_type') or '?')}</div>
                <div class="loan-suggest-note">Suggest only — will create a khata entry (you sent). Does not change the bank row.</div>
              </div>
              <form method="post" action="/ledger/add" class="loan-suggest-form"
                    onsubmit="return confirm('Post {money(s['amount'])} loan to {esc(s['contact_name'])}?');">
                <input type="hidden" name="contact_id" value="{s['contact_id']}">
                <input type="hidden" name="direction" value="you_sent">
                <input type="hidden" name="amount" value="{s['amount']}">
                <input type="hidden" name="purpose" value="loan">
                <input type="hidden" name="entry_date" value="{esc(s['txn_date'])}">
                <input type="hidden" name="transaction_id" value="{s['transaction_id']}">
                <input type="hidden" name="notes" value="Suggested from {esc(s['merchant_display'])}">
                <button type="submit" class="button">Post to khata</button>
              </form>
            </div>
            """
        )
    return f"""
    <section class="home-strip loan-suggestions" aria-label="Loan suggestions">
      <div class="home-strip-header">
        <h2>Suggested loans</h2>
        <span class="home-chip muted" style="padding:4px 10px; font-size:11px;">never auto-posts</span>
      </div>
      <div class="loan-suggest-list">{"".join(cards)}</div>
    </section>
    """


def render_unified_transactions_section(
    pending_rows: list,
    classified_rows: list,
    loan_suggestions: list[dict] | None = None,
    tx_filter: str = "needs_review",
    review_sort: str = "newest",
    review_search: str = "",
    edit_search: str = "",
) -> str:
    """P2: single workspace with filters for review + edit."""
    tx_filter = tx_filter if tx_filter in {
        "needs_review", "classified", "shared", "loan", "all"
    } else "needs_review"

    pending_count = len(pending_rows)
    classified_count = len(classified_rows)
    shared_count = sum(1 for r in classified_rows if (r["expense_type"] or "") == "Shared")
    loan_count = sum(1 for r in classified_rows if (r["expense_type"] or "") == "Loan")

    def pill(fid: str, label: str, count: int) -> str:
        active = " active" if tx_filter == fid else " subtle"
        href = f"/?tx_filter={fid}"
        if review_search:
            href += f"&review_search={urllib.parse.quote(review_search)}"
        if edit_search:
            href += f"&edit_search={urllib.parse.quote(edit_search)}"
        href += f"&review_sort={urllib.parse.quote(review_sort)}#review"
        return (
            f'<a class="button filter-pill{active}" href="{href}" '
            f'style="padding:6px 14px; font-size:12px; border-radius:16px; text-decoration:none;">'
            f'{esc(label)} <strong>{count}</strong></a>'
        )

    filters = f"""
    <div class="tx-filter-bar">
      {pill("needs_review", "Needs review", pending_count)}
      {pill("classified", "Classified", classified_count)}
      {pill("shared", "Shared", shared_count)}
      {pill("loan", "Loans", loan_count)}
      {pill("all", "All", pending_count + classified_count)}
    </div>
    """

    loan_html = render_loan_suggestions(loan_suggestions or [])

    # Body by filter
    if tx_filter == "needs_review":
        body = f"""
        {review_sort_controls(review_sort, review_search)}
        {review_search_controls(review_search, review_sort, pending_count, pending_count)}
        <form method="post" action="/review" class="review-batch-form" id="unified-review-form">
          <div style="overflow-x:auto;">
            <table class="tx-table">
              <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th colspan="5">Classify</th></tr></thead>
              <tbody>{render_review_rows(pending_rows) if pending_rows else '<tr><td colspan="8" class="empty">Nothing waiting for review.</td></tr>'}</tbody>
            </table>
          </div>
          {review_batch_actions(pending_rows)}
        </form>
        """
    elif tx_filter in {"classified", "shared", "loan"}:
        if tx_filter == "shared":
            rows = [r for r in classified_rows if (r["expense_type"] or "") == "Shared"]
        elif tx_filter == "loan":
            rows = [r for r in classified_rows if (r["expense_type"] or "") == "Loan"]
        else:
            rows = classified_rows
        body = f"""
        {edit_search_controls(edit_search, classified_count, len(rows), len(rows))}
        <form method="post" action="/edit-classifications" class="review-batch-form" id="unified-edit-form">
          <div style="overflow-x:auto;">
            <table class="tx-table">
              <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th>Status</th><th colspan="5">Correction</th></tr></thead>
              <tbody>{render_edit_rows(rows) if rows else '<tr><td colspan="9" class="empty">No matching classified rows.</td></tr>'}</tbody>
            </table>
          </div>
          {edit_batch_actions(rows)}
        </form>
        """
    else:  # all — show pending then classified (two forms)
        body = f"""
        <h3 class="tx-subhead">Needs review</h3>
        <form method="post" action="/review" class="review-batch-form">
          <div style="overflow-x:auto;">
            <table class="tx-table">
              <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th colspan="5">Classify</th></tr></thead>
              <tbody>{render_review_rows(pending_rows) if pending_rows else '<tr><td colspan="8" class="empty">None pending.</td></tr>'}</tbody>
            </table>
          </div>
          {review_batch_actions(pending_rows)}
        </form>
        <h3 class="tx-subhead" style="margin-top:24px;">Classified</h3>
        <form method="post" action="/edit-classifications" class="review-batch-form">
          <div style="overflow-x:auto;">
            <table class="tx-table">
              <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th>Status</th><th colspan="5">Correction</th></tr></thead>
              <tbody>{render_edit_rows(classified_rows[:40]) if classified_rows else '<tr><td colspan="9" class="empty">None classified.</td></tr>'}</tbody>
            </table>
          </div>
          {edit_batch_actions(classified_rows[:40])}
        </form>
        """

    return f"""
    <section class="unified-tx-section">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:12px;">
        <h2 style="margin:0;">Transactions</h2>
      </div>
      {filters}
      {loan_html}
      {body}
    </section>
    """


def render_suggestions(suggestions: list[dict]) -> str:
    if not suggestions:
        return '<p class="empty">No connection suggestions found. Normal payees/narration matching automatically starts once statements are uploaded.</p>'
    
    html_items = []
    for s in suggestions:
        html_items.append(
            f"""
            <div class="suggestion-card">
              <div class="suggestion-info">
                <div class="suggestion-reason">{esc(s['reason'])}</div>
                <div class="suggestion-pair">
                  <div class="suggestion-item debit">
                    <strong>Debit: {esc(s['debit_merchant'])}</strong>
                    <span>{esc(s['debit_desc'])}</span>
                    <span class="date">{esc(s['debit_date'])} (Remaining: {money(s['debit_remaining'])})</span>
                  </div>
                  <div class="suggestion-arrow">&rarr;</div>
                  <div class="suggestion-item credit">
                    <strong>Credit: {esc(s['credit_merchant'])}</strong>
                    <span>{esc(s['credit_desc'])}</span>
                    <span class="date">{esc(s['credit_date'])} (Remaining: {money(s['credit_remaining'])})</span>
                  </div>
                </div>
              </div>
              <form method="post" action="/connect" class="suggestion-action">
                <input type="hidden" name="debit_id" value="{s['debit_id']}">
                <input type="hidden" name="credit_id" value="{s['credit_id']}">
                <input type="hidden" name="amount" value="{s['suggested_amount']}">
                <button type="submit" class="button">Link {money(s['suggested_amount'])}</button>
              </form>
            </div>
            """
        )
    return '<div class="suggestions-list">' + "".join(html_items) + "</div>"


def render_active_connections(links: list[dict]) -> str:
    if not links:
        return '<p class="empty">No active connections. Debits and credits are currently computed independently.</p>'
    
    rows = []
    for l in links:
        rows.append(
            f"""
            <tr>
              <td>{esc(l['linked_at'].split('T')[0])}</td>
              <td><strong>{money(l['link_amount'])}</strong></td>
              <td>
                <div class="linked-pair-info">
                  <span class="tag debit">DR</span>
                  <strong>{esc(l['debit_merchant'])}</strong> ({esc(l['debit_date'])})
                </div>
              </td>
              <td>
                <div class="linked-pair-info">
                  <span class="tag credit">CR</span>
                  <strong>{esc(l['credit_merchant'])}</strong> ({esc(l['credit_date'])})
                </div>
              </td>
              <td>
                <form method="post" action="/disconnect">
                  <input type="hidden" name="link_id" value="{l['link_id']}">
                  <button type="submit" class="button danger subtle small">Unlink</button>
                </form>
              </td>
            </tr>
            """
        )
    return f"""
    <div style="overflow-x: auto;">
      <table>
        <thead>
          <tr>
            <th>Linked Date</th>
            <th>Offset Amount</th>
            <th>Debit Transaction</th>
            <th>Credit Transaction</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows)}
        </tbody>
      </table>
    </div>
    """


def render_manual_linker(linkable: dict) -> str:
    debits = linkable["debits"]
    credits = linkable["credits"]
    
    debit_options = "".join(
        f'<option value="{d["id"]}" data-remaining="{d["remaining"]}">{esc(d["txn_date"])} - {esc(d["merchant_display"])} (Rem: {money(d["remaining"])})</option>'
        for d in debits
    )
    credit_options = "".join(
        f'<option value="{c["id"]}" data-remaining="{c["remaining"]}">{esc(c["txn_date"])} - {esc(c["merchant_display"])} (Rem: {money(c["remaining"])})</option>'
        for c in credits
    )
    
    if not debits or not credits:
        return '<p class="empty">You need at least one unlinked debit and one unlinked credit to create a manual connection.</p>'
        
    return f"""
    <form method="post" action="/connect" class="manual-linker-form">
      <div class="grid three">
        <label>
          <span>Select Debit (DR)</span>
          <select name="debit_id" id="manual-debit-select" required>
            <option value="">-- Choose Debit --</option>
            {debit_options}
          </select>
        </label>
        <label>
          <span>Select Credit (CR)</span>
          <select name="credit_id" id="manual-credit-select" required>
            <option value="">-- Choose Credit --</option>
            {credit_options}
          </select>
        </label>
        <label>
          <span>Link Amount (₹)</span>
          <div class="input-with-button" style="display:flex; gap: 8px;">
            <input type="number" name="amount" step="0.01" min="0.01" placeholder="Enter amount" required id="manual-link-amount" style="flex:1;">
            <button type="submit" class="button">Link</button>
          </div>
        </label>
      </div>
    </form>
    """


def review_batch_actions(rows) -> str:
    if not rows:
        return ""
    return """
    <div class="review-actions sticky-batch-bar" data-sticky-bar>
      <span class="sticky-batch-meta"><span class="sticky-count">0</span> row(s) ready (category set)</span>
      <button type="submit" class="button sticky-batch-btn">Confirm changes</button>
    </div>
    """


def edit_batch_actions(rows) -> str:
    if not rows:
        return ""
    return """
    <div class="review-actions sticky-batch-bar" data-sticky-bar>
      <span class="sticky-batch-meta"><span class="sticky-count">0</span> row(s) with category</span>
      <button type="submit" class="button sticky-batch-btn">Save classification edits</button>
    </div>
    """


def render_recent_rows(rows) -> str:
    if not rows:
        return '<tr><td colspan="7" class="empty">Import a statement to see transactions.</td></tr>'
    output = []
    for row in rows:
        badge = "warn" if row["status"] == "needs_review" else "ok"
        output.append(
            f"""
            <tr>
              <td>{esc(row['txn_date'])}</td>
              <td><strong>{esc(row['merchant_display'])}</strong><span>{esc(row['description'])}</span></td>
              <td>{esc(row['category'] or 'Uncategorized')}</td>
              <td>{esc(row['expense_type'])}</td>
              <td>{signed_amount(row['amount_signed'])}</td>
              <td>{money(row['my_share'])}</td>
              <td><span class="badge {badge}">{esc(row['status'])}</span></td>
            </tr>
            """
        )
    return "".join(output)


def render_rules(rows) -> str:
    if not rows:
        return '<tr class="empty-row"><td colspan="6" class="empty">Merchant mappings will appear after confirmations.</td></tr>'
    return "".join(
        f"""
        <tr>
          <td><strong>{esc(row['merchant_display'])}</strong></td>
          <td>{category_badge(row['category'])}</td>
          <td><span class="type-tag {esc(str(row['expense_type']).lower())}">{esc(row['expense_type'])}</span></td>
          <td>{split_display(row['split_ratio'])}</td>
          <td><span class="match-count-pill">{esc(row['match_count'])}</span></td>
          <td>
            <form method="post" action="/delete-rule" style="margin:0; display:inline;" onsubmit="return confirm('Delete this matching rule?');">
              <input type="hidden" name="rule_id" value="{row['id']}">
              <button type="submit" class="button danger subtle small" style="min-height: 28px; padding: 4px 8px; font-size:11px;">Delete</button>
            </form>
          </td>
        </tr>
        """
        for row in rows
    )


def render_onboarding_checklist(onboarding: dict | None) -> str:
    """P3: first-run checklist on Home."""
    if not onboarding:
        return ""
    steps = onboarding.get("steps") or []
    if not steps:
        return ""
    if onboarding.get("complete"):
        return """
        <section class="home-strip onboarding-strip onboarding-done" aria-label="Setup complete">
          <div class="home-strip-header">
            <h2>Setup complete</h2>
            <a class="button subtle home-strip-link" href="/app/">Open React app →</a>
          </div>
          <p class="empty" style="margin:0;">You can keep using classic UI, or try the new Home &amp; People shell.</p>
        </section>
        """
    items = []
    done_n = 0
    for s in steps:
        done = bool(s.get("done"))
        if done:
            done_n += 1
        cls = "done" if done else ""
        mark = "✓" if done else ""
        items.append(
            f'<li class="onboard-item {cls}"><span class="onboard-check">{mark}</span>'
            f'<div><strong>{esc(s.get("label"))}</strong>'
            f'<div class="onboard-hint">{esc(s.get("hint") or "")}</div></div></li>'
        )
    return f"""
    <section class="home-strip onboarding-strip" aria-label="Getting started">
      <div class="home-strip-header">
        <h2>Getting started ({done_n}/{len(steps)})</h2>
        <a class="button subtle home-strip-link" href="/app/">React app →</a>
      </div>
      <ul class="onboard-list">{"".join(items)}</ul>
    </section>
    """


def render_home_nl_box() -> str:
    """P3: natural-language settlement question on Home (client → API)."""
    return """
    <section class="home-strip home-nl" aria-label="Ask about balances">
      <div class="home-strip-header">
        <h2>Ask: who owes whom?</h2>
      </div>
      <form id="home-nl-form" class="home-nl-form" onsubmit="return askSettlementQuestion(event)">
        <input id="home-nl-input" type="search" placeholder='e.g. How much does Highnes owe me?'
               autocomplete="off" aria-label="Settlement question">
        <button type="submit" class="button">Ask</button>
      </form>
      <div id="home-nl-answer" class="home-nl-answer" hidden></div>
      <p class="empty" style="margin:8px 0 0; font-size:12px;">Uses your People balances (khata + open shared). Never changes data.</p>
    </section>
    """


def render_mobile_bottom_nav(pending_badge_count: int = 0) -> str:
    """P3: primary nav for small screens."""
    badge = (
        f'<span class="mnav-badge">{pending_badge_count}</span>'
        if pending_badge_count > 0
        else ""
    )
    return f"""
    <nav class="mobile-bottom-nav" aria-label="Primary mobile navigation">
      <a href="#dashboard" class="mnav-item" data-tab-jump="dashboard" data-tab="dashboard">
        <span class="mnav-label">Home</span>
      </a>
      <a href="#review" class="mnav-item" data-tab-jump="review" data-tab="review">
        <span class="mnav-label">Txns</span>{badge}
      </a>
      <a href="#contacts" class="mnav-item" data-tab-jump="contacts" data-tab="contacts">
        <span class="mnav-label">People</span>
      </a>
      <a href="#import-add" class="mnav-item" data-tab-jump="import-add" data-tab="import-add">
        <span class="mnav-label">Import</span>
      </a>
      <a href="/app/" class="mnav-item mnav-app">
        <span class="mnav-label">App</span>
      </a>
    </nav>
    """


def render_home_attention_strip(
    review_count: int,
    passthrough_count: int,
    open_shared_null_partner: int = 0,
) -> str:
    """P0: needs-attention strip on Home dashboard."""
    chips = []
    if review_count > 0:
        chips.append(
            f'<a class="home-chip warn" href="#review" data-tab-jump="review">'
            f'<strong>{review_count}</strong> to review</a>'
        )
    if passthrough_count > 0:
        chips.append(
            f'<a class="home-chip accent" href="#contacts" data-tab-jump="contacts">'
            f'<strong>{passthrough_count}</strong> pass-through candidate'
            f'{"s" if passthrough_count != 1 else ""}</a>'
        )
    if open_shared_null_partner > 0:
        chips.append(
            f'<a class="home-chip muted" href="/?tx_filter=shared#review" data-tab-jump="review">'
            f'<strong>{open_shared_null_partner}</strong> shared missing partner</a>'
        )
    if not chips:
        chips.append(
            '<span class="home-chip ok"><strong>✓</strong> Nothing needs attention</span>'
        )
    return f"""
    <section class="home-strip home-attention" aria-label="Needs attention">
      <div class="home-strip-header">
        <h2>Needs attention</h2>
      </div>
      <div class="home-chip-row">{"".join(chips)}</div>
    </section>
    """


def render_home_settlement_strip(partner_balances: list[dict], limit: int = 5) -> str:
    """P0: top who-owes-whom nets on Home dashboard."""
    ranked = sorted(
        partner_balances or [],
        key=lambda b: abs(float(b.get("net") or 0)),
        reverse=True,
    )
    top = [b for b in ranked if float(b.get("net") or 0) != 0][:limit]

    if not top:
        body = (
            '<p class="empty" style="margin:0;">No open person balances yet. '
            'Use <a href="#contacts" data-tab-jump="contacts">People</a> for khata, '
            'or tag <strong>Shared with</strong> on review.</p>'
        )
    else:
        rows = []
        for b in top:
            name = str(b.get("username") or b.get("contact_name") or "?")
            net = float(b.get("net") or 0)
            if net > 0:
                label = f"owes you {money(net)}"
                cls = "credit"
            else:
                label = f"you owe {money(abs(net))}"
                cls = "debit"
            rows.append(
                f'<li class="home-settle-row">'
                f'<span class="home-settle-name">{esc(name)}</span>'
                f'<span class="amount {cls}">{esc(label)}</span>'
                f'</li>'
            )
        body = f'<ul class="home-settle-list">{"".join(rows)}</ul>'

    return f"""
    <section class="home-strip home-settlement" aria-label="Who owes whom">
      <div class="home-strip-header">
        <h2>Who owes whom</h2>
        <a class="button subtle home-strip-link" href="#contacts" data-tab-jump="contacts">Open People →</a>
      </div>
      {body}
    </section>
    """


def page(
    data: dict,
    message: str | None = None,
    error: str | None = None,
    review_sort: str = "newest",
    review_search: str = "",
    edit_search: str = "",
    person_search: str = "",
    start_date: str = "",
    end_date: str = "",
    exclude_business: bool = False,
    use_my_share: bool = False,
    current_user: str | None = None,
    all_users: list[str] | None = None,
    partner_balances: list[dict] | None = None,
    tx_filter: str = "needs_review",
) -> bytes:
    """Assemble the full dashboard HTML page from pre-fetched data."""
    all_users = all_users or []
    partner_balances = partner_balances or []
    review_sort = "oldest" if review_sort == "oldest" else "newest"
    review_search = review_search.strip()
    edit_search = edit_search.strip()
    person_search = person_search.strip()
    tx_filter = tx_filter if tx_filter in {
        "needs_review", "classified", "shared", "loan", "all"
    } else "needs_review"
    filtered_review = filter_review_rows(data["pending"], review_search)
    pending_review = sort_review_rows(filtered_review, review_sort)
    # Split review queue by debit/credit (legacy split still used for badge counts)
    debit_review = [r for r in pending_review if r["debit"] and float(r["debit"] or 0) > 0]
    credit_review = [r for r in pending_review if r["credit"] and float(r["credit"] or 0) > 0]
    # Filter by selected date period
    def _in_period(r):
        txn_date = str(r["txn_date"] or "")
        if start_date and txn_date < start_date:
            return False
        if end_date and txn_date > end_date:
            return False
        return True
    debit_review = [r for r in debit_review if _in_period(r)]
    credit_review = [r for r in credit_review if _in_period(r)]
    # Unified pending list (debits + credits) for Transactions workspace
    unified_pending = [r for r in pending_review if _in_period(r)]
    pending_badge_count = len(unified_pending)
    # Full queue size for Home attention (not period-filtered)
    attention_review_count = len(data.get("pending") or [])
    attention_pt_count = len(data.get("passthrough_candidates") or [])

    def _row_field(row, key, default=None):
        try:
            if hasattr(row, "keys") and key in row.keys():
                return row[key]
        except Exception:
            pass
        if isinstance(row, dict):
            return row.get(key, default)
        return default

    open_shared_null = sum(
        1
        for r in data.get("transactions") or []
        if (_row_field(r, "expense_type") or "") == "Shared"
        and not (_row_field(r, "shared_with") or _row_field(r, "shared_with_contact_id"))
        and float(_row_field(r, "debit") or 0) > 0
    )
    # Onboarding from live counts
    try:
        from .db import onboarding_status as _onboarding_status
        # page() has no conn — use data counts if present
        onboarding = data.get("onboarding")
    except Exception:
        onboarding = None
    home_onboarding_html = render_onboarding_checklist(onboarding)
    home_attention_html = render_home_attention_strip(
        attention_review_count, attention_pt_count, open_shared_null
    )
    home_nl_html = render_home_nl_box()
    home_settlement_html = render_home_settlement_strip(partner_balances)
    mobile_nav_html = render_mobile_bottom_nav(pending_badge_count)
    editable_all = [row for row in data["transactions"] if row["status"] != "needs_review"]
    filtered_edit = filter_editable_rows(data["transactions"], edit_search)
    # Show more rows in unified workspace
    editable_rows = filtered_edit if edit_search else filtered_edit[:50]
    unified_tx_html = render_unified_transactions_section(
        unified_pending,
        editable_rows,
        loan_suggestions=data.get("loan_suggestions") or [],
        tx_filter=tx_filter,
        review_sort=review_sort,
        review_search=review_search,
        edit_search=edit_search,
    )
    person_matches = sorted(
        filter_transactions_by_text(data["transactions"], person_search),
        key=lambda row: (row["txn_date"], row["id"]),
        reverse=True,
    )
    min_date, max_date = date_bounds(data["transactions"])
    start_date = start_date if start_date else min_date
    end_date = end_date if end_date else max_date
    period_rows = filter_dashboard_rows(data["transactions"], start_date, end_date, exclude_business)
    period_totals = dashboard_totals(period_rows, use_my_share)
    period_categories = {
        'expenses': expenses_by_category(period_rows, use_my_share=True),
        'debits': debits_by_category(period_rows),
        'credits': credits_by_category(period_rows)
    }
    period_merchants = {
        'expenses': top_merchants_from_rows(period_rows, use_my_share=True),
        'debits': debits_by_merchant(period_rows),
        'credits': credits_by_merchant(period_rows)
    }
    message_html = f'<div class="notice">{esc(message)}</div>' if message else ""
    error_html = f'<div class="notice error">{esc(error)}</div>' if error else ""
    person_section = collapsible_section(
        "person-search",
        "Credit / debit search",
        f"""
        {person_search_controls(person_search, len(person_matches))}
        {render_credit_debit_graph(person_matches, person_search)}
        <table>
          <thead><tr><th>Date</th><th>Merchant / text</th><th>Credit</th><th>Debit</th><th>Amount</th><th>Category</th></tr></thead>
          <tbody>{render_person_transaction_rows(person_matches)}</tbody>
        </table>
        """,
        f"{len(person_matches)} match(es)" if person_search else "Search people or statement text",
        bool(person_search),
    )
    review_section = collapsible_section(
        "review",
        "Transactions awaiting review",
        f"""
        {review_sort_controls(review_sort, review_search)}
        {review_search_controls(review_search, review_sort, len(data['pending']), len(filtered_review))}
        <form method="post" action="/review" class="review-batch-form">
          <table>
            <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th colspan="5">Confirmation</th></tr></thead>
            <tbody>{render_review_rows(pending_review)}</tbody>
          </table>
          {review_batch_actions(pending_review)}
        </form>
        """,
        f"{len(data['pending'])} pending",
        bool(review_search),
    )
    edit_section = collapsible_section(
        "edit-classifications",
        "Edit classifications",
        f"""
        {edit_search_controls(edit_search, len(editable_all), len(filtered_edit), len(editable_rows))}
        <form method="post" action="/edit-classifications" class="review-batch-form">
          <table>
            <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th>Status</th><th colspan="5">Correction</th></tr></thead>
            <tbody>{render_edit_rows(editable_rows)}</tbody>
          </table>
          {edit_batch_actions(editable_rows)}
        </form>
        """,
        f"{len(editable_all)} classified",
        bool(edit_search),
    )
    rules_section = collapsible_section(
        "merchant-rules",
        "Merchant knowledge base",
        f"""
        <table>
          <thead><tr><th>Merchant</th><th>Category</th><th>Type</th><th>Split</th><th>Uses</th></tr></thead>
          <tbody>{render_rules(data['rules'])}</tbody>
        </table>
        """,
        f"{len(data['rules'])} rule(s)",
    )
    shared_section = collapsible_section(
        "shared-expenses",
        "Shared expenses",
        f"""
        <table>
          <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Total</th><th>Split</th><th>My share</th></tr></thead>
          <tbody>{''.join(f"<tr><td>{esc(r['txn_date'])}</td><td>{esc(r['merchant_display'])}</td><td>{esc(r['category'])}</td><td>{money(r['debit'])}</td><td>{split_display(r['split_ratio'])}</td><td>{money(r['my_share'])}</td></tr>" for r in data['shared']) or '<tr><td colspan="6" class="empty">No shared expenses yet.</td></tr>'}</tbody>
        </table>
        """,
        f"{len(data['shared'])} shared",
    )
    # Contact datalist for shared-with picker
    contact_options = ""
    for item in data.get("contacts") or []:
        c = item.get("contact") if isinstance(item, dict) and "contact" in item else item
        if not c:
            continue
        if c.get("merged_into_id"):
            continue
        contact_options += f'<option value="{esc(c.get("name", ""))}">'
    partner_datalist = f'<datalist id="contact-partner-list">{contact_options}</datalist>'

    # Merge suggestions for People tab
    merge_suggestions: list[dict] = []
    try:
        from .settlement import suggest_merge_groups
        # Need a live connection — suggestions precomputed in page only if provided via data
        merge_suggestions = data.get("merge_suggestions") or []
    except Exception:
        merge_suggestions = []

    # User header badge
    user_badge = ""
    if current_user:
        user_badge = f'<div class="user-badge"><span class="avatar">{esc(current_user[0].upper())}</span><span>{esc(current_user.title())}</span><form method="post" action="/logout" style="margin:0;"><button type="submit" class="logout-btn">Logout</button></form></div>'

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Personal Expense Tracker</title>
  <link rel="stylesheet" href="/style.css?v=14">
  <script src="/chart.js?v=4"></script>
</head>
<body>
  <header>
    <div class="header-title">
      <h1>Personal Expense Tracker</h1>
      <p>Spend, review, and who-owes-whom — local SBI tracker</p>
    </div>
    <div class="header-right">
      <a class="button subtle" href="/app/" style="margin-right:8px; text-decoration:none; font-size:13px;">React app</a>
      {user_badge}
      <button id="theme-toggle" class="theme-toggle-btn" aria-label="Toggle theme">
        <svg class="sun-icon" viewBox="0 0 24 24" style="display:none;"><path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1zM5.99 4.58c-.39-.39-1.03-.39-1.41 0s-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41L5.99 4.58zm12.37 12.37c-.39-.39-1.03-.39-1.41 0s-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41l-1.06-1.06zm1.06-10.96c.39-.39.39-1.03 0-1.41s-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06zM7.05 18.36c.39-.39.39-1.03 0-1.41s-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06z"/></svg>
        <svg class="moon-icon" viewBox="0 0 24 24" style="display:none;"><path d="M12.3 22h-.1c-5.5 0-10-4.5-10-10 0-4.8 3.5-9 8.3-9.8.6-.1 1.2.3 1.3.9.1.6-.2 1.2-.8 1.4-3.4 1-5.8 4.1-5.8 7.6 0 4.4 3.6 8 8 8 3.5 0 6.6-2.4 7.6-5.8.2-.6.8-.9 1.4-.8.6.1 1 .7.9 1.3-.8 4.8-5 8.2-9.9 8.2z"/></svg>
      </button>
    </div>
  </header>
  
  <div class="app-container">
    <aside class="sidebar">
      <nav class="nav-tabs" aria-label="Main Navigation">
        <a href="#dashboard" class="tab-link active" data-tab="dashboard">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>
          <span>Home</span>
        </a>
        <a href="#review" class="tab-link" data-tab="review">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-2 10H7v-2h10v2zm0-4H7V7h10v2zm0 8H7v-2h10v2z"/></svg>
          <span>Transactions</span>
          {f'<span class="tab-badge warn" id="review-count-badge">{pending_badge_count}</span>' if pending_badge_count > 0 else ''}
        </a>
        <a href="#contacts" class="tab-link" data-tab="contacts">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
          <span>People</span>
        </a>
        <a href="#import-add" class="tab-link" data-tab="import-add">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
          <span>Import</span>
        </a>
        <details class="nav-more">
          <summary class="nav-more-summary">
            <svg class="nav-icon" viewBox="0 0 24 24"><path d="M6 10c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm12 0c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm-6 0c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>
            <span>More</span>
          </summary>
          <div class="nav-more-items">
            <a href="/?tx_filter=classified#review" class="tab-link" data-tab="review" data-tab-jump="review">
              <span>Classified (edit)</span>
            </a>
            <a href="#search" class="tab-link" data-tab="search">
              <span>Credit / debit search</span>
            </a>
            <a href="#rules" class="tab-link" data-tab="rules">
              <span>Rules &amp; shared</span>
            </a>
          </div>
        </details>
      </nav>
    </aside>

    <main class="main-content">
      <div id="toast-container" class="toast-container" data-message="{esc(message)}" data-error="{esc(error)}"></div>

      <!-- Tab 1: Dashboard -->
      <div id="pane-dashboard" class="tab-pane active">
        {home_onboarding_html}
        {home_attention_html}
        {home_nl_html}
        {home_settlement_html}

        {render_dashboard_filters(start_date, end_date, min_date, max_date, exclude_business, use_my_share)}
        
        <div class="grid metrics" style="grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));">
          <div id="card-credits" class="metric" onclick="switchDashboardTab('credits')" style="cursor:pointer;transition:transform 0.2s,box-shadow 0.2s;" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 4px 12px rgba(0,0,0,0.15)';" onmouseout="this.style.transform='none';this.style.boxShadow='none';">
            <span>Period credits</span><strong style="color:var(--success);">{money(period_totals['credit'])}</strong>
          </div>
          <div id="card-debits" class="metric" onclick="switchDashboardTab('debits')" style="cursor:pointer;transition:transform 0.2s,box-shadow 0.2s;" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 4px 12px rgba(0,0,0,0.15)';" onmouseout="this.style.transform='none';this.style.boxShadow='none';">
            <span>Period debits</span><strong style="color:var(--error);">{money(period_totals['debit'])}</strong>
          </div>
          <div id="card-expenses" class="metric active" onclick="switchDashboardTab('expenses')" style="cursor:pointer;transition:transform 0.2s,box-shadow 0.2s;" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 4px 12px rgba(0,0,0,0.15)';" onmouseout="this.style.transform='none';this.style.boxShadow='none';">
            <span>My expenses</span><strong style="color:var(--error);">{money(period_totals['expense_share'])}</strong>
          </div>
        </div>
        {f'''<div class="empty-state-panel" style="margin-top:16px;">
          <strong>No spend data in this period</strong>
          <p class="empty">Import a statement or widen the date range to see charts.</p>
          <a class="button" href="#import-add" data-tab-jump="import-add">Go to Import</a>
        </div>''' if float(period_totals.get('debit') or 0) == 0 and float(period_totals.get('credit') or 0) == 0 else ''}

        <div class="grid two" style="margin-top:24px;">
          <section>
            <h2>Total credits / debits</h2>
            {render_credit_debit_pie(period_totals)}
          </section>
          <section>
            <h2 id="chart-category-title">Expenses by category</h2>
            {render_categories_chart(period_categories)}
          </section>
        </div>

        <section style="margin-top:24px;">
          <h2 id="chart-merchant-title">Top merchants</h2>
          {render_merchants_chart(period_merchants)}
        </section>

        <section style="margin-top:24px;">
          <h2>Exports</h2>
          <div class="actions">
            <a class="button" href="/export.csv">Download CSV</a>
            <a class="button" href="/export.json">Download JSON</a>
          </div>
          <p class="empty">Original transactions stay immutable. Reviews and learned merchant mappings are stored separately.</p>
        </section>
      </div>

      <!-- Tab 2: Import & Add -->
      <div id="pane-import-add" class="tab-pane">
        <div class="grid two">
          <section>
            <h2>Import weekly SBI statement</h2>
            <form class="import" method="post" action="/import" enctype="multipart/form-data">
              <label>Statement PDF <input type="file" name="statement" accept="application/pdf" required></label>
              <label>Password <input type="password" name="password" autocomplete="off"></label>
              <button type="submit">Import</button>
            </form>
          </section>
          {render_manual_transaction_form()}
        </div>
        
        <section style="margin-top:24px;">
          <h2>Money Flow</h2>
          {render_money_flows_view(data['transactions'])}
        </section>
      </div>

      <!-- Tab 3: People (Khata) -->
      <div id="pane-contacts" class="tab-pane">
        {render_contacts_section(
            data.get('contacts', []),
            data.get('passthrough_candidates', []),
            partner_balances=partner_balances,
            merge_suggestions=data.get('merge_suggestions') or merge_suggestions,
        )}
      </div>

      <!-- Tab 4: Unified Transactions (review + edit) -->
      <div id="pane-review" class="tab-pane">
        {partner_datalist}
        {unified_tx_html}
      </div>

      <!-- Tab 5: legacy hash #transactions → same unified workspace -->
      <div id="pane-transactions" class="tab-pane">
        {partner_datalist}
        {render_unified_transactions_section(
            unified_pending,
            editable_rows,
            loan_suggestions=data.get("loan_suggestions") or [],
            tx_filter="classified" if tx_filter == "needs_review" else tx_filter,
            review_sort=review_sort,
            review_search=review_search,
            edit_search=edit_search,
        )}
      </div>

      <!-- Tab 6: Search -->
      <div id="pane-search" class="tab-pane">
        <section>
          <h2>Credit / debit search</h2>
          {person_search_controls(person_search, len(person_matches))}
          {render_credit_debit_graph(person_matches, person_search)}
          <div style="overflow-x: auto;">
            <table>
              <thead><tr><th>Date</th><th>Merchant / text</th><th>Credit</th><th>Debit</th><th>Amount</th><th>Category</th></tr></thead>
              <tbody>{render_person_transaction_rows(person_matches)}</tbody>
            </table>
          </div>
        </section>
      </div>

      <!-- Tab 7: Knowledge Base & Shared -->
      <div id="pane-rules" class="tab-pane">
        <div class="grid two">
          <section>
            <h2>Merchant knowledge base</h2>
            <div class="rules-search-wrapper" style="margin-bottom:12px;">
              <input type="text" id="rules-search-input" placeholder="Search rules..." oninput="filterRulesTable()" style="width:100%;">
            </div>
            <div style="overflow-x: auto;">
              <table>
                <thead><tr><th>Merchant</th><th>Category</th><th>Type</th><th>Split</th><th>Uses</th><th>Action</th></tr></thead>
                <tbody id="rules-table-body">{render_rules(data['rules'])}</tbody>
              </table>
            </div>
          </section>
          <section>
            <h2>Shared expenses</h2>
            <p class="empty" style="margin-top:0;">Person balances live under <a href="#contacts" data-tab-jump="contacts">People</a> and Home.</p>
            <div style="overflow-x: auto; margin-top:12px;">
              <table>
                <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Total</th><th>Split</th><th>My share</th><th>Partner</th></tr></thead>
                <tbody>{''.join(f"<tr><td>{esc(r['txn_date'])}</td><td>{esc(r['merchant_display'])}</td><td>{esc(r['category'])}</td><td>{money(r['debit'])}</td><td>{split_display(r['split_ratio'])}</td><td>{money(r['my_share'])}</td><td>{esc((r['shared_with'] if hasattr(r, 'keys') and 'shared_with' in r.keys() and r['shared_with'] else None) or '—')}</td></tr>" for r in data['shared']) or '<tr><td colspan="7" class="empty">No shared expenses yet.</td></tr>'}</tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    </main>
  </div>
  
  {mobile_nav_html}
  <script src="/app.js?v=14"></script>
</body>
</html>
"""
    return html_doc.encode("utf-8")
