"""HTML rendering functions for the expense tracker dashboard."""

from __future__ import annotations

import html
import urllib.parse
from datetime import date, timedelta
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
    monthly_trends_dict,
    people_from_split_ratio,
    review_people_value,
    sort_review_rows,
    split_display,
    top_merchants_from_rows,
)


def login_page(message: str | None = None, error: str | None = None, next_path: str = "") -> bytes:
    """Render the login page."""
    msg_html = f'<div class="toast success">{esc(message)}</div>' if message else ""
    err_html = f'<div class="toast error">{esc(error)}</div>' if error else ""
    next_html = (
        f'<input type="hidden" name="next" value="{esc(next_path)}">' if next_path else ""
    )
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
      {next_html}
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


def bank_amount_html(row) -> str:
    """Full bank debit/credit — same as Last statement. Share is a note only."""
    html_amt = signed_amount(row["amount_signed"])
    et = row_get(row, "expense_type") or ""
    share = row_get(row, "my_share")
    if et == "Shared" and share is not None:
        html_amt += (
            f'<div style="font-size:11px;color:var(--muted);margin-top:2px;">'
            f"your share {money(share)}</div>"
        )
    return html_amt


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


def render_monthly_trend_chart(trends_dict: dict[str, list[tuple[str, Decimal]]]) -> str:
    import json
    data_attrs = []
    for key in ['expenses', 'debits', 'credits']:
        trend = trends_dict.get(key, [])
        labels = [t[0] for t in trend]
        values = [float(t[1]) for t in trend]
        data_attrs.append(f'data-labels-{key}="{esc(json.dumps(labels))}" data-values-{key}="{esc(json.dumps(values))}"')
    
    return f"""
    <div class="chart-container" style="position: relative; min-height: 200px; width: 100%;">
      <canvas id="monthlyTrendChart" {' '.join(data_attrs)}></canvas>
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


def render_recent_imports_view(recent_imports: list) -> str:
    if not recent_imports:
        return """
        <div style="padding:30px; text-align:center; background:var(--surface-color); border:1px solid var(--border-color); border-radius:12px;">
            <p class="empty" style="margin:0;">No statements uploaded yet.</p>
        </div>
        """
    
    rows_html = []
    for imp in recent_imports:
        fname = esc(imp["source_filename"] or "Statement")
        raw_date = str(imp["imported_at"] or "")
        dt_display = raw_date.split("T")[0] if "T" in raw_date else raw_date[:10]
        time_display = raw_date.split("T")[1][:5] if "T" in raw_date and len(raw_date.split("T")[1]) >= 5 else ""
        date_str = f"{dt_display} {time_display}".strip()
        count = imp["transaction_count"] or 0
        badge_class = "success" if count > 0 else "muted"
        rows_html.append(
            f"""
            <div class="log-row">
              <div>
                  <strong>{fname}</strong>
                  <span class="muted-line">{esc(date_str)}</span>
              </div>
              <span class="badge {badge_class}">{count}</span>
            </div>
            """
        )
        
    return f"""
    <div class="import-recent">
      {"".join(rows_html)}
    </div>
    """


def render_import_statement_section(
    last_import: dict | None,
    gmail_on: bool,
    gmail_address: str | None,
    pdf_password_saved: bool,
) -> str:
    """Quiet import: auto-import status first; PDF upload hidden until needed."""
    last_line = ""
    if last_import and last_import.get("filename"):
        fn = esc(last_import.get("filename") or "")
        span = ""
        if last_import.get("start") and last_import.get("end"):
            span = f" · {esc(str(last_import['start'])[:10])}–{esc(str(last_import['end'])[:10])}"
        n = last_import.get("inserted")
        extra = f" · {n} new" if n else ""
        last_line = (
            f'<p class="import-last">Last: {fn}{span}{extra} '
            f'<a href="/?tx_filter=last_statement#review">Review</a></p>'
        )

    pwd_field = ""
    if not pdf_password_saved:
        pwd_field = (
            '<label>PDF password <input type="password" name="password" '
            'autocomplete="off" placeholder="SBI: last 5 mobile + DOB ddmmyy"></label>'
        )
    upload = f"""
    <details class="import-more">
      <summary>Upload a PDF</summary>
      <form class="import import-upload" method="post" action="/import" enctype="multipart/form-data">
        <label>Statement PDF <input type="file" name="statement" accept="application/pdf" required></label>
        {pwd_field}
        <button type="submit">Import</button>
      </form>
    </details>
    """

    if gmail_on:
        addr = esc(gmail_address or "Gmail")
        primary = f"""
        <div class="import-status">
          <strong>Auto-import on</strong>
          <span>{addr}</span>
        </div>
        <form method="post" action="/import/mail-now" class="import-now">
          <button type="submit" class="button subtle">Check mail now</button>
        </form>
        {last_line}
        """
    else:
        extra_pw = ""
        if not pdf_password_saved:
            extra_pw = (
                '<label>PDF password <input type="password" name="statement_password" '
                'autocomplete="off" placeholder="SBI: last 5 mobile + DOB ddmmyy" required></label>'
            )
        primary = f"""
        <form class="import import-gmail" method="post" action="/gmail/connect">
          <p class="empty">One-time: Google Account → Security → App passwords. Then WhatsApp SBI PDFs import on this PC.</p>
          <label>Gmail <input type="email" name="gmail_address" value="anandjcub@gmail.com" required></label>
          <label>App password <input type="password" name="gmail_app_password" autocomplete="off" required></label>
          {extra_pw}
          <button type="submit">Turn on auto-import</button>
        </form>
        {last_line}
        """

    return f"""
    <section class="import-statement">
      <h2>Import</h2>
      {primary}
      {upload}
    </section>
    """


def render_money_flows_view(transactions: list[dict]) -> str:
    # Show all transactions as a complete connected cash flow timeline
    flow_txns = sorted(
        transactions,
        key=lambda r: (str(row_get(r, "txn_date") or ""), row_get(r, "id") or 0),
        reverse=True,
    )
    
    if not flow_txns:
        return """
        <div style="padding:32px; text-align:center; background:var(--surface-color); border:1px solid var(--border-color); border-radius:12px; margin-bottom:16px;">
            <div style="font-size:32px; margin-bottom:8px;">💸</div>
            <h4 style="margin:0 0 4px 0; color:var(--text);">No Money Flow Data</h4>
            <p class="empty" style="margin:0; font-size:13px;">No transactions found in this period.</p>
        </div>
        """
        
    total_inflow = sum(
        (Decimal(str(dict(f).get("credit") or 0)) for f in flow_txns if Decimal(str(dict(f).get("credit") or 0)) > 0),
        Decimal("0"),
    )
    total_outflow = sum(
        (Decimal(str(dict(f).get("debit") or 0)) for f in flow_txns if Decimal(str(dict(f).get("debit") or 0)) > 0),
        Decimal("0"),
    )
    net_transfer = total_inflow - total_outflow
    net_color = "var(--success)" if net_transfer >= 0 else "var(--error)"

    summary_bar = f"""
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:14px; margin-bottom:24px;">
      <div style="background:rgba(16, 185, 129, 0.05); padding:14px 18px; border-radius:12px; border:1px solid rgba(16, 185, 129, 0.2); backdrop-filter:blur(6px);">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700; letter-spacing:0.5px;">Total Inflow</span>
          <span style="font-size:14px; color:var(--success);">↙</span>
        </div>
        <div style="font-size:20px; font-weight:800; color:var(--success); margin-top:6px; font-family:monospace;">+{money(total_inflow)}</div>
      </div>
      <div style="background:rgba(239, 68, 68, 0.05); padding:14px 18px; border-radius:12px; border:1px solid rgba(239, 68, 68, 0.2); backdrop-filter:blur(6px);">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700; letter-spacing:0.5px;">Total Outflow</span>
          <span style="font-size:14px; color:var(--error);">↗</span>
        </div>
        <div style="font-size:20px; font-weight:800; color:var(--error); margin-top:6px; font-family:monospace;">-{money(total_outflow)}</div>
      </div>
      <div style="background:rgba(255, 255, 255, 0.03); padding:14px 18px; border-radius:12px; border:1px solid var(--border-color); backdrop-filter:blur(6px);">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700; letter-spacing:0.5px;">Net Flow</span>
          <span style="font-size:14px; color:{net_color};">⇄</span>
        </div>
        <div style="font-size:20px; font-weight:800; color:{net_color}; margin-top:6px; font-family:monospace;">{money(net_transfer)}</div>
      </div>
    </div>
    """

    timeline_items = []
    for idx, f in enumerate(flow_txns):
        date_str = f["txn_date"]
        merchant = f["merchant_display"] or "Unknown"
        amount = Decimal(str(f["amount_signed"] or 0))
        debit = Decimal(str(f["debit"] or 0))
        credit = Decimal(str(f["credit"] or 0))
        desc = f["description"] or ""
        category = dict(f).get("category") or ""
        expense_type = dict(f).get("expense_type") or "Personal"
            
        is_inflow = credit > 0 or amount > 0
        flow_color = "#10b981" if is_inflow else "#ef4444"
        display_amount = f"+{money(credit)}" if is_inflow else f"-{money(debit)}"
        side_class = "timeline-left" if is_inflow else "timeline-right"
        dot_icon = "↙" if is_inflow else "↗"
        
        cat_badge = f'<span style="font-size:10px; padding:2px 8px; border-radius:10px; background:rgba(255,255,255,0.06); color:var(--text); border:1px solid rgba(255,255,255,0.1);">{esc(category)}</span>' if category else ""
        type_badge = f'<span style="font-size:10px; padding:2px 8px; border-radius:10px; background:rgba(255,255,255,0.03); color:var(--muted); border:1px solid rgba(255,255,255,0.05);">{esc(expense_type)}</span>'
        desc_html = f'<div style="font-size:11px; color:var(--muted); margin-top:4px; opacity:0.85; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{esc(desc)}</div>' if desc and desc.lower() != merchant.lower() else ""

        timeline_items.append(f"""
        <div class="timeline-item {side_class}">
          <div class="timeline-node" style="background:{flow_color}; box-shadow:0 0 10px {flow_color}80;">
            <span style="font-size:10px; color:#000; font-weight:bold;">{dot_icon}</span>
          </div>
          <div class="timeline-card" style="border-left: 3px solid {flow_color};">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
              <div style="min-width:0; flex:1;">
                <div style="font-size:11px; font-weight:700; color:var(--muted); font-family:monospace; margin-bottom:3px;">{esc(date_str)}</div>
                <div style="font-size:14px; font-weight:700; color:var(--text); line-height:1.2;">{esc(merchant)}</div>
                {desc_html}
              </div>
              <div style="text-align:right; flex-shrink:0;">
                <div style="font-size:15px; font-weight:800; color:{flow_color}; font-family:monospace;">{display_amount}</div>
              </div>
            </div>
            <div style="display:flex; gap:6px; margin-top:8px; align-items:center; flex-wrap:wrap;">
              {cat_badge}
              {type_badge}
            </div>
          </div>
        </div>
        """)

    timeline_css = """
    <style>
      .timeline-container {
        position: relative;
        padding: 20px 0;
        margin: 0 auto;
        width: 100%;
      }
      .timeline-container::before {
        content: '';
        position: absolute;
        top: 0;
        bottom: 0;
        left: 50%;
        width: 2px;
        background: linear-gradient(180deg, rgba(16,185,129,0.3) 0%, rgba(255,255,255,0.1) 50%, rgba(239,68,68,0.3) 100%);
        transform: translateX(-50%);
        z-index: 1;
      }
      .timeline-item {
        position: relative;
        margin-bottom: 20px;
        width: 100%;
        display: flex;
        align-items: center;
      }
      .timeline-item.timeline-left {
        justify-content: flex-start;
      }
      .timeline-item.timeline-right {
        justify-content: flex-end;
      }
      .timeline-item.timeline-left .timeline-card {
        margin-right: calc(50% + 24px);
        width: calc(50% - 24px);
      }
      .timeline-item.timeline-right .timeline-card {
        margin-left: calc(50% + 24px);
        width: calc(50% - 24px);
      }
      .timeline-node {
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        width: 20px;
        height: 20px;
        border-radius: 50%;
        z-index: 2;
        display: flex;
        align-items: center;
        justify-content: center;
        border: 2px solid var(--bg-color, #0f172a);
        transition: transform 0.2s ease;
      }
      .timeline-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        padding: 12px 14px;
        backdrop-filter: blur(10px);
        transition: all 0.2s ease;
        box-shadow: 0 4px 14px rgba(0,0,0,0.15);
        box-sizing: border-box;
      }
      .timeline-card:hover {
        transform: translateY(-2px);
        background: rgba(255, 255, 255, 0.05);
        border-color: rgba(255, 255, 255, 0.18);
        box-shadow: 0 8px 24px rgba(0,0,0,0.25);
      }
      @media (max-width: 768px) {
        .timeline-container::before {
          left: 16px;
        }
        .timeline-node {
          left: 16px;
        }
        .timeline-item.timeline-left .timeline-card,
        .timeline-item.timeline-right .timeline-card {
          margin-left: 36px;
          margin-right: 0;
          width: calc(100% - 36px);
        }
      }
    </style>
    """

    return f'''
    {timeline_css}
    {summary_bar}
    <div class="timeline-container">
      {"".join(timeline_items)}
    </div>
    '''


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


def _render_contact_card(item: dict, *, quiet: bool = False) -> str:
    contact = item["contact"]
    bal = item["balance"]
    cid = contact["id"]
    cname = contact["name"] or "?"
    aliases = contact.get("aliases") or []
    aliases_str = ", ".join(aliases)
    notes = contact.get("notes") or ""
    net = Decimal(str(bal.get("net_balance", bal.get("net", 0))))
    entries = int(bal.get("entry_count") or 0)

    if net > 0:
        status_code = "owes_you"
        line = f"Owes you {money(net)}"
        amount_cls = "people-amt people-amt-pos"
        amount_txt = money(net)
    elif net < 0:
        status_code = "you_owe"
        line = f"You owe {money(abs(net))}"
        amount_cls = "people-amt people-amt-neg"
        amount_txt = money(abs(net))
    else:
        status_code = "settled"
        line = "Settled"
        amount_cls = "people-amt people-amt-zero"
        amount_txt = "₹0"

    meta = f"{entries} entr{'y' if entries == 1 else 'ies'}"
    if aliases_str:
        meta += f" · {esc(aliases_str[:40])}"

    return f"""
    <div class="people-row contact-card" data-name="{esc(cname.lower())}" data-aliases="{esc(aliases_str.lower())}" data-status="{status_code}" data-quiet="{'1' if quiet else '0'}" data-contact-id="{cid}" data-contact-name="{esc(cname)}" data-aliases-raw="{esc(aliases_str)}" data-notes="{esc(notes)}">
      <button type="button" class="people-row-main" data-action="open-drawer" data-contact-id="{cid}" data-contact-name="{esc(cname)}">
        <span class="people-avatar" aria-hidden="true">{esc(cname[0].upper())}</span>
        <span class="people-row-text">
          <span class="people-name">{esc(cname)}</span>
          <span class="people-meta">{line} · {meta}</span>
        </span>
        <span class="{amount_cls}">{amount_txt}</span>
      </button>
      <div class="people-row-actions">
        <button type="button" class="button subtle" title="Rename / edit aliases"
                data-action="edit-contact" data-contact-id="{cid}" data-contact-name="{esc(cname)}" data-aliases="{esc(aliases_str)}" data-notes="{esc(notes)}">Edit</button>
        <button type="button" class="button" data-action="add-ledger" data-contact-id="{cid}" data-contact-name="{esc(cname)}">+ Money</button>
        <button type="button" class="button subtle" data-action="open-drawer" data-contact-id="{cid}" data-contact-name="{esc(cname)}">History</button>
      </div>
    </div>
    """


def _render_people_toolbar() -> str:
    return """
    <div class="people-toolbar">
      <input id="contact-search-input" class="people-search" type="search" placeholder="Search name…" data-action="search-contacts" autocomplete="off">
      <div class="people-filters" role="group" aria-label="Filter">
        <button type="button" class="people-filter active" data-action="filter-status" data-filter="active">Balances</button>
        <button type="button" class="people-filter" data-action="filter-status" data-filter="owes_you">Owes me</button>
        <button type="button" class="people-filter" data-action="filter-status" data-filter="you_owe">I owe</button>
        <button type="button" class="people-filter" data-action="filter-status" data-filter="all">Everyone</button>
      </div>
      <button type="button" class="button" data-action="open-modal" data-modal-id="modal-add-contact">+ Person</button>
    </div>
    """


def _render_passthrough_suggestions(passthrough_candidates: list[dict], contacts: list[dict]) -> str:
    if not passthrough_candidates:
        return ""
    pt_items = []
    for cand in passthrough_candidates[:4]:
        amt = cand.get("credit_amount") or cand.get("amount") or 0
        from_name = cand.get("credit_contact") or cand.get("credit_merchant") or "Unknown"
        to_name = cand.get("debit_contact") or cand.get("debit_merchant") or "Unknown"
        dt = cand.get("credit_date") or cand.get("date") or ""
        credit_id = cand.get("credit_tx_id") or cand.get("credit_id") or 0
        debit_id = cand.get("debit_tx_id") or cand.get("debit_id") or 0
        from_contact_id = cand.get("from_contact_id") or 0
        to_contact_id = cand.get("to_contact_id") or 0
        from_field = (
            f'<label>From<select name="from_contact_id" required>{_contact_option_tags(contacts, from_contact_id or None)}</select></label>'
            if not from_contact_id
            else f'<input type="hidden" name="from_contact_id" value="{from_contact_id}">'
        )
        to_field = (
            f'<label>To<select name="to_contact_id" required>{_contact_option_tags(contacts, to_contact_id or None)}</select></label>'
            if not to_contact_id
            else f'<input type="hidden" name="to_contact_id" value="{to_contact_id}">'
        )
        pt_items.append(
            f"""
            <div class="people-pt-item">
              <div class="people-pt-copy">
                <strong>{money(amt)}</strong>
                <span>{esc(from_name)} → you → {esc(to_name)}</span>
                <span class="people-meta">{esc(dt)}</span>
              </div>
              <form method="post" action="/ledger/passthrough/confirm" class="people-pt-form">
                <input type="hidden" name="credit_id" value="{credit_id}">
                <input type="hidden" name="debit_id" value="{debit_id}">
                <input type="hidden" name="amount" value="{amt}">
                <input type="hidden" name="entry_date" value="{dt}">
                {from_field}{to_field}
                <div class="people-pt-actions">
                  <button type="submit" name="action" value="confirm" class="button">Mark as rolling</button>
                  <button type="submit" name="action" value="dismiss" class="button subtle" formnovalidate>Skip</button>
                </div>
              </form>
            </div>
            """
        )
    return f"""
    <details class="people-tools">
      <summary>Possible rolling money <span class="people-chip">{len(passthrough_candidates[:4])}</span></summary>
      <p class="empty people-hint">Bank pairs that look like A → you → B. Confirm only if you were just a middle person (does not change who owes whom).</p>
      <div class="people-pt-list">{"".join(pt_items)}</div>
    </details>
    """


def _render_people_tools(contacts: list[dict], today: str) -> str:
    contact_opts = _contact_option_tags(contacts)
    return f"""
    <details class="people-tools">
      <summary>More actions</summary>
      <div class="people-tools-grid">
        <div class="people-tool-card">
          <h3>Rolling money</h3>
          <p class="empty people-hint">Someone sent you money to pass on. Neither person&apos;s balance changes.</p>
          <form method="post" action="/ledger/rolling" class="people-simple-form"
                onsubmit="return confirm('Log rolling money? Balances stay the same.');">
            <label>Received from
              <select name="from_contact_id" required>{contact_opts}</select>
            </label>
            <label>Sent to
              <select name="to_contact_id" required>{contact_opts}</select>
            </label>
            <label>Amount (₹)
              <input type="number" name="amount" step="0.01" min="0.01" required placeholder="20000">
            </label>
            <label>Date
              <input type="date" name="entry_date" value="{today}">
            </label>
            <label class="people-span">Note
              <input type="text" name="notes" placeholder="Optional">
            </label>
            <button type="submit" class="button">Save rolling</button>
          </form>
        </div>
        <div class="people-tool-card">
          <h3>Starting balance</h3>
          <p class="empty people-hint">Money already owed before these bank statements.</p>
          <form method="post" action="/ledger/opening" class="people-simple-form"
                onsubmit="return confirm('Set starting balance?');">
            <label>Person
              <select name="contact_id" required>{contact_opts}</select>
            </label>
            <label>Who owes
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
            <label class="people-span">Note
              <input type="text" name="notes" placeholder="Optional">
            </label>
            <button type="submit" class="button">Save starting balance</button>
          </form>
        </div>
      </div>
    </details>
    """


def _render_add_contact_modal() -> str:
    return """
    <div id="modal-add-contact" class="people-modal" hidden>
      <div class="people-modal-card" role="dialog" aria-labelledby="add-contact-title">
        <div class="people-modal-head">
          <h3 id="add-contact-title">New person</h3>
          <button type="button" class="button subtle people-modal-close" data-action="close-modal" data-modal-id="modal-add-contact">✕</button>
        </div>
        <form method="post" action="/contacts/create" class="people-simple-form people-modal-form">
          <label class="people-span">Name
            <input name="name" required placeholder="e.g. Highnes" autofocus>
          </label>
          <label class="people-span">UPI / phone (optional)
            <input name="aliases" placeholder="highnes@upi, 98xxxxxxxx">
          </label>
          <label class="people-span">Note (optional)
            <input name="notes" placeholder="Friend, roommate…">
          </label>
          <div class="people-modal-actions">
            <button type="button" class="button subtle" data-action="close-modal" data-modal-id="modal-add-contact">Cancel</button>
            <button type="submit" class="button">Save person</button>
          </div>
        </form>
      </div>
    </div>
    """


def _render_edit_contact_modal() -> str:
    return """
    <div id="modal-edit-contact" class="people-modal" hidden>
      <div class="people-modal-card" role="dialog" aria-labelledby="edit-contact-title">
        <div class="people-modal-head">
          <h3 id="edit-contact-title">Edit person</h3>
          <button type="button" class="button subtle people-modal-close" data-action="close-modal" data-modal-id="modal-edit-contact">✕</button>
        </div>
        <form method="post" action="/contacts/edit" class="people-simple-form people-modal-form">
          <input type="hidden" id="edit-contact-id" name="contact_id">
          <label class="people-span">Readable name
            <input name="name" id="edit-contact-name" required placeholder="e.g. Ananthu (friend)">
          </label>
          <label class="people-span">Also known as (bank / UPI / phone)
            <input name="aliases" id="edit-contact-aliases" placeholder="anandu, 98xxxxxxxx, ms ranji">
          </label>
          <p class="empty people-hint" style="grid-column:1/-1;margin:0;">
            Keep bank fragments in “Also known as” so statements still match after you rename.
          </p>
          <label class="people-span">Note (optional)
            <input name="notes" id="edit-contact-notes" placeholder="Friend, roommate…">
          </label>
          <div class="people-modal-actions">
            <button type="button" class="button subtle" data-action="close-modal" data-modal-id="modal-edit-contact">Cancel</button>
            <button type="submit" class="button">Save name</button>
          </div>
        </form>
      </div>
    </div>
    """


def _render_add_ledger_modal() -> str:
    return """
    <div id="modal-add-ledger" class="people-modal" hidden>
      <div class="people-modal-card" role="dialog" aria-labelledby="add-entry-title">
        <div class="people-modal-head">
          <h3 id="add-entry-title">Add money with <span id="ledger-modal-contact-name"></span></h3>
          <button type="button" class="button subtle people-modal-close" data-action="close-modal" data-modal-id="modal-add-ledger">✕</button>
        </div>
        <form method="post" action="/ledger/add" class="people-simple-form people-modal-form">
          <input type="hidden" id="ledger-modal-contact-id" name="contact_id">

          <fieldset class="people-choice">
            <legend>What happened?</legend>
            <label class="people-choice-opt">
              <input type="radio" name="direction" value="you_sent" checked>
              <span><strong>I paid them</strong><small>Loan, food, trip — they owe me</small></span>
            </label>
            <label class="people-choice-opt">
              <input type="radio" name="direction" value="they_sent">
              <span><strong>They paid me</strong><small>Repayment or money I received</small></span>
            </label>
          </fieldset>

          <label class="people-span">Amount (₹)
            <input type="number" step="0.01" min="0.01" name="amount" required placeholder="1500" class="people-amount-input">
          </label>

          <label class="people-span">Why
            <select name="purpose">
              <option value="loan" selected>Loan</option>
              <option value="food_split">Food split</option>
              <option value="trip">Trip</option>
              <option value="opening_balance">Starting balance</option>
              <option value="other">Other</option>
            </select>
          </label>

          <label class="people-span">Date
            <input type="date" name="entry_date" id="ledger-modal-date">
          </label>

          <label class="people-span">Note (optional)
            <input name="notes" placeholder="Cash, GPay, lunch…">
          </label>

          <div class="people-modal-actions">
            <button type="button" class="button subtle" data-action="close-modal" data-modal-id="modal-add-ledger">Cancel</button>
            <button type="submit" class="button">Save</button>
          </div>
        </form>
      </div>
    </div>
    """


def _render_ledger_drawer() -> str:
    return """
    <div id="ledger-drawer-backdrop" class="people-drawer-backdrop" data-action="close-drawer" hidden></div>
    <aside id="ledger-drawer" class="people-drawer" hidden aria-label="Person history">
      <div class="people-drawer-head">
        <div>
          <h3 id="drawer-contact-name">History</h3>
          <p id="drawer-balance-summary" class="people-drawer-summary"></p>
        </div>
        <button type="button" class="button subtle" data-action="close-drawer">Close</button>
      </div>

      <div class="people-drawer-actions">
        <button type="button" class="button subtle" id="drawer-edit-btn">Edit name</button>
        <button type="button" class="button" id="drawer-add-money-btn">+ Money</button>
        <form method="post" action="/ledger/settle" id="drawer-settle-form" class="people-settle">
          <input type="hidden" id="drawer-settle-contact-id" name="contact_id">
          <input type="number" name="amount" id="drawer-settle-amount" step="0.01" min="0.01" placeholder="Full amount" class="people-settle-input">
          <button type="submit" class="button subtle" onclick="return confirmSettle()">Mark settled</button>
        </form>
      </div>

      <div id="drawer-entries-list" class="people-history"></div>
    </aside>
    """


def render_contacts_section(
    contacts: list[dict],
    passthrough_candidates: list[dict],
    partner_balances: list[dict] | None = None,
    merge_suggestions: list[dict] | None = None,
) -> str:
    """Simple People (khata) UX: list first, tools secondary."""
    _ = merge_suggestions, partner_balances
    from datetime import date as _date

    today = _date.today().isoformat()

    total_owes_you = Decimal("0")
    total_you_owe = Decimal("0")
    active_items: list[dict] = []
    quiet_items: list[dict] = []

    for item in contacts:
        bal = item["balance"]
        net = Decimal(str(bal.get("net_balance", bal.get("net", 0))))
        if net > 0:
            total_owes_you += net
            active_items.append(item)
        elif net < 0:
            total_you_owe += abs(net)
            active_items.append(item)
        else:
            quiet_items.append(item)

    active_items.sort(
        key=lambda it: abs(Decimal(str(it["balance"].get("net_balance", it["balance"].get("net", 0))))),
        reverse=True,
    )
    quiet_items.sort(key=lambda it: (it["contact"].get("name") or "").lower())

    active_html = "".join(_render_contact_card(i) for i in active_items) or (
        '<p class="empty people-empty">Nobody owes money right now. Add a person or log a loan.</p>'
    )
    quiet_html = "".join(_render_contact_card(i, quiet=True) for i in quiet_items)
    quiet_count = len(quiet_items)

    pt_html = _render_passthrough_suggestions(passthrough_candidates, contacts)
    tools_html = _render_people_tools(contacts, today)

    quiet_block = ""
    if quiet_count:
        quiet_block = f"""
        <details class="people-tools people-quiet" id="people-quiet-panel">
          <summary>Settled / no balance <span class="people-chip">{quiet_count}</span></summary>
          <div id="contacts-grid-quiet" class="people-list">{quiet_html}</div>
        </details>
        """

    return f"""
    <div class="people-page" aria-label="People balances">
      <div class="people-header">
        <div>
          <h2>People</h2>
          <p class="people-subtitle">Who owes whom — loans, food splits, and handoffs</p>
        </div>
        <div class="people-totals">
          <div class="people-total pos">
            <span>They owe you</span>
            <strong>{money(total_owes_you)}</strong>
          </div>
          <div class="people-total neg">
            <span>You owe</span>
            <strong>{money(total_you_owe)}</strong>
          </div>
        </div>
      </div>

      {_render_people_toolbar()}

      {pt_html}

      <div id="contacts-grid" class="people-list">
        {active_html}
      </div>

      {quiet_block}
      {tools_html}

      {_render_add_contact_modal()}
      {_render_edit_contact_modal()}
      {_render_add_ledger_modal()}
      {_render_ledger_drawer()}
    </div>
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


def review_sort_controls(
    direction: str,
    search_query: str = "",
    tx_filter: str = "needs_review",
    exclude_credits: bool = False,
    start_date: str = "",
    end_date: str = "",
    edit_search: str = "",
) -> str:
    newest_class = "active" if direction != "oldest" else ""
    oldest_class = "active" if direction == "oldest" else ""

    def _sort_href(sort_dir: str) -> str:
        p = [f"review_sort={sort_dir}"]
        if tx_filter and tx_filter != "needs_review":
            p.append(f"tx_filter={urllib.parse.quote(tx_filter)}")
        if exclude_credits:
            p.append("exclude_credits=1")
        if search_query:
            p.append(f"review_search={urllib.parse.quote(search_query)}")
        if edit_search:
            p.append(f"edit_search={urllib.parse.quote(edit_search)}")
        if start_date:
            p.append(f"start_date={urllib.parse.quote(start_date)}")
        if end_date:
            p.append(f"end_date={urllib.parse.quote(end_date)}")
        return f"/?{'&'.join(p)}#review"

    return f"""
    <div class="section-tools">
      <span>Sort by date</span>
      <div class="segmented" aria-label="Review date sort">
        <a class="{newest_class}" href="{_sort_href('newest')}">Newest first</a>
        <a class="{oldest_class}" href="{_sort_href('oldest')}">Oldest first</a>
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


def review_search_controls(
    search_query: str,
    review_sort: str,
    total_count: int,
    filtered_count: int,
    tx_filter: str = "needs_review",
    exclude_credits: bool = False,
    start_date: str = "",
    end_date: str = "",
) -> str:
    result_text = (
        f"{filtered_count} of {total_count} pending"
        if search_query.strip()
        else f"{total_count} pending"
    )
    clear_params = []
    if tx_filter and tx_filter != "needs_review":
        clear_params.append(f"tx_filter={urllib.parse.quote(tx_filter)}")
    if review_sort and review_sort != "newest":
        clear_params.append(f"review_sort={esc(review_sort)}")
    if exclude_credits:
        clear_params.append("exclude_credits=1")
    if start_date:
        clear_params.append(f"start_date={urllib.parse.quote(start_date)}")
    if end_date:
        clear_params.append(f"end_date={urllib.parse.quote(end_date)}")
    clear_qs = f"?{'&'.join(clear_params)}" if clear_params else "/"
    clear_link = (
        f'<a class="button subtle" href="{clear_qs}#review">Clear</a>'
        if search_query.strip()
        else ""
    )
    hidden_inputs = []
    if tx_filter:
        hidden_inputs.append(f'<input type="hidden" name="tx_filter" value="{esc(tx_filter)}">')
    if review_sort:
        hidden_inputs.append(f'<input type="hidden" name="review_sort" value="{esc(review_sort)}">')
    if exclude_credits:
        hidden_inputs.append('<input type="hidden" name="exclude_credits" value="1">')
    if start_date:
        hidden_inputs.append(f'<input type="hidden" name="start_date" value="{esc(start_date)}">')
    if end_date:
        hidden_inputs.append(f'<input type="hidden" name="end_date" value="{esc(end_date)}">')

    return f"""
    <form method="get" action="/" class="review-search">
      {''.join(hidden_inputs)}
      <label>Search review cases <input name="review_search" value="{esc(search_query)}" placeholder="Merchant, notes, amount"></label>
      <button type="submit">Search</button>
      {clear_link}
      <span>{esc(result_text)}</span>
    </form>
    """


def edit_search_controls(
    search_query: str,
    total_count: int,
    filtered_count: int,
    shown_count: int,
    tx_filter: str = "classified",
    review_sort: str = "newest",
    exclude_credits: bool = False,
    start_date: str = "",
    end_date: str = "",
) -> str:
    label_plural = "shared expenses" if tx_filter == "shared" else ("loans" if tx_filter == "loan" else "classified")
    if search_query.strip():
        result_text = f"{filtered_count} of {total_count} {label_plural}"
    else:
        result_text = f"Showing {shown_count} {label_plural}"
    clear_params = []
    if tx_filter:
        clear_params.append(f"tx_filter={urllib.parse.quote(tx_filter)}")
    if review_sort and review_sort != "newest":
        clear_params.append(f"review_sort={esc(review_sort)}")
    if exclude_credits:
        clear_params.append("exclude_credits=1")
    if start_date:
        clear_params.append(f"start_date={urllib.parse.quote(start_date)}")
    if end_date:
        clear_params.append(f"end_date={urllib.parse.quote(end_date)}")
    clear_qs = f"?{'&'.join(clear_params)}" if clear_params else "/"
    clear_link = (
        f'<a class="button subtle" href="{clear_qs}#review">Clear</a>'
        if search_query.strip()
        else ""
    )
    hidden_inputs = []
    if tx_filter:
        hidden_inputs.append(f'<input type="hidden" name="tx_filter" value="{esc(tx_filter)}">')
    if review_sort:
        hidden_inputs.append(f'<input type="hidden" name="review_sort" value="{esc(review_sort)}">')
    if exclude_credits:
        hidden_inputs.append('<input type="hidden" name="exclude_credits" value="1">')
    if start_date:
        hidden_inputs.append(f'<input type="hidden" name="start_date" value="{esc(start_date)}">')
    if end_date:
        hidden_inputs.append(f'<input type="hidden" name="end_date" value="{esc(end_date)}">')

    placeholder = f"Search {label_plural} (merchant, notes, amount)"
    return f"""
    <form method="get" action="/" class="review-search">
      {''.join(hidden_inputs)}
      <label>Search {esc(label_plural)} <input name="edit_search" value="{esc(search_query)}" placeholder="{esc(placeholder)}"></label>
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
              <td>{bank_amount_html(row)}</td>
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
              <td>{bank_amount_html(row)}</td>
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
    for s in suggestions:
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
    workspace_rows: list,
    loan_suggestions: list[dict] | None = None,
    tx_filter: str = "needs_review",
    review_sort: str = "newest",
    review_search: str = "",
    edit_search: str = "",
    exclude_credits: bool = False,
    start_date: str = "",
    end_date: str = "",
    last_import: dict | None = None,
    last_statement_rows: list | None = None,
) -> str:
    """One amount style for every chip. Last statement is the last file only."""
    tx_filter = tx_filter if tx_filter in {
        "needs_review", "classified", "shared", "loan", "all", "last_statement"
    } else "needs_review"

    query = (review_search or edit_search or "").strip()

    if tx_filter == "last_statement":
        rows = list(last_statement_rows or [])
    else:
        rows = list(workspace_rows or [])
    if exclude_credits:
        rows = [r for r in rows if float(r["credit"] or 0) <= 0]

    unfiltered_pending = [r for r in rows if (r["status"] or "") == "needs_review"]
    unfiltered_classified = [r for r in rows if (r["status"] or "") != "needs_review"]

    total_pending = len(unfiltered_pending)
    total_classified = len(unfiltered_classified)
    total_shared = sum(1 for r in unfiltered_classified if (r["expense_type"] or "") == "Shared")
    total_loan = sum(1 for r in unfiltered_classified if (r["expense_type"] or "") == "Loan")
    total_all = total_pending + total_classified
    total_last_stmt = len([r for r in (last_statement_rows or []) if not exclude_credits or float(r["credit"] or 0) <= 0])

    pending_rows = list(unfiltered_pending)
    classified_rows = list(unfiltered_classified)
    if query:
        pending_rows = filter_review_rows(pending_rows, query)
        classified_rows = filter_editable_rows(classified_rows, query)

    pending_rows = sort_review_rows(pending_rows, review_sort)
    classified_rows = sorted(
        classified_rows,
        key=lambda r: (r["txn_date"], r["id"]),
        reverse=(review_sort != "oldest"),
    )

    pending_count = len(pending_rows)
    classified_count = len(classified_rows)
    shared_count = sum(1 for r in classified_rows if (r["expense_type"] or "") == "Shared")
    loan_count = sum(1 for r in classified_rows if (r["expense_type"] or "") == "Loan")

    def pill(fid: str, label: str, count: int) -> str:
        active = " active" if tx_filter == fid else " subtle"
        href = f"/?tx_filter={fid}"
        if exclude_credits:
            href += "&exclude_credits=1"
        if query:
            href += f"&review_search={urllib.parse.quote(query)}"
        if start_date:
            href += f"&start_date={urllib.parse.quote(start_date)}"
        if end_date:
            href += f"&end_date={urllib.parse.quote(end_date)}"
        href += f"&review_sort={urllib.parse.quote(review_sort)}#review"
        return (
            f'<a class="button filter-pill{active}" href="{href}" '
            f'style="padding:6px 14px; font-size:12px; border-radius:16px; text-decoration:none;">'
            f'{esc(label)} <strong>{count}</strong></a>'
        )

    btn_active = " active" if exclude_credits else " subtle"
    btn_label = "🚫 Credits Filtered (Debits Only)" if exclude_credits else "💳 Filter out credits"
    toggle_val = "0" if exclude_credits else "1"

    toggle_href = f"/?tx_filter={tx_filter}"
    if toggle_val == "1":
        toggle_href += "&exclude_credits=1"
    if query:
        toggle_href += f"&review_search={urllib.parse.quote(query)}"
    if start_date:
        toggle_href += f"&start_date={urllib.parse.quote(start_date)}"
    if end_date:
        toggle_href += f"&end_date={urllib.parse.quote(end_date)}"
    toggle_href += f"&review_sort={urllib.parse.quote(review_sort)}#review"

    exclude_credits_btn = (
        f'<a class="button filter-pill{btn_active}" href="{toggle_href}" '
        f'style="padding:6px 14px; font-size:12px; border-radius:16px; text-decoration:none;">'
        f'{btn_label}</a>'
    )

    pill_pending = pending_count if query else total_pending
    pill_classified = classified_count if query else total_classified
    pill_shared = shared_count if query else total_shared
    pill_loan = loan_count if query else total_loan
    pill_all = (pending_count + classified_count) if query else total_all

    filters = f"""
    <div class="tx-filter-bar" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:16px;">
      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
        {pill("needs_review", "Needs review", pill_pending)}
        {pill("classified", "Classified", pill_classified)}
        {pill("shared", "Shared", pill_shared)}
        {pill("loan", "Loans", pill_loan)}
        {pill("all", "All", pill_all)}
        {pill("last_statement", "Last statement", total_last_stmt) if last_import else ""}
      </div>
      <div>
        {exclude_credits_btn}
      </div>
    </div>
    """

    loan_html = render_loan_suggestions(loan_suggestions or [])

    def form_hidden_fields(fid: str) -> str:
        h = [f'<input type="hidden" name="tx_filter" value="{esc(fid)}">']
        if review_sort:
            h.append(f'<input type="hidden" name="review_sort" value="{esc(review_sort)}">')
        if query:
            h.append(f'<input type="hidden" name="review_search" value="{esc(query)}">')
            h.append(f'<input type="hidden" name="edit_search" value="{esc(query)}">')
        if exclude_credits:
            h.append('<input type="hidden" name="exclude_credits" value="1">')
        if start_date:
            h.append(f'<input type="hidden" name="start_date" value="{esc(start_date)}">')
        if end_date:
            h.append(f'<input type="hidden" name="end_date" value="{esc(end_date)}">')
        return "".join(h)

    # Body by filter
    if tx_filter == "needs_review":
        empty_msg = "Nothing waiting for review." if not query else "No matching transactions awaiting review."
        body = f"""
        {review_sort_controls(review_sort, query, tx_filter="needs_review", exclude_credits=exclude_credits, start_date=start_date, end_date=end_date, edit_search=query)}
        {review_search_controls(query, review_sort, total_pending, pending_count, tx_filter="needs_review", exclude_credits=exclude_credits, start_date=start_date, end_date=end_date)}
        <form method="post" action="/review" class="review-batch-form" id="unified-review-form">
          {form_hidden_fields("needs_review")}
          <div style="overflow-x:auto;">
            <table class="tx-table">
              <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th colspan="5">Classify</th></tr></thead>
              <tbody>{render_review_rows(pending_rows) if pending_rows else f'<tr><td colspan="8" class="empty">{empty_msg}</td></tr>'}</tbody>
            </table>
          </div>
          {review_batch_actions(pending_rows)}
        </form>
        """
    elif tx_filter in {"classified", "shared", "loan"}:
        if tx_filter == "shared":
            rows = [r for r in classified_rows if (r["expense_type"] or "") == "Shared"]
            raw_target_count = total_shared
            empty_msg = "No matching shared expenses." if query else "No shared expenses found."
        elif tx_filter == "loan":
            rows = [r for r in classified_rows if (r["expense_type"] or "") == "Loan"]
            raw_target_count = total_loan
            empty_msg = "No matching loans." if query else "No loan transactions found."
        else:
            rows = classified_rows
            raw_target_count = total_classified
            empty_msg = "No matching classified rows." if query else "No classified transactions found."
        body = f"""
        {review_sort_controls(review_sort, query, tx_filter=tx_filter, exclude_credits=exclude_credits, start_date=start_date, end_date=end_date, edit_search=query)}
        {edit_search_controls(query, raw_target_count, len(rows), len(rows), tx_filter=tx_filter, review_sort=review_sort, exclude_credits=exclude_credits, start_date=start_date, end_date=end_date)}
        <form method="post" action="/edit-classifications" class="review-batch-form" id="unified-edit-form">
          {form_hidden_fields(tx_filter)}
          <div style="overflow-x:auto;">
            <table class="tx-table">
              <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th>Status</th><th colspan="5">Correction</th></tr></thead>
              <tbody>{render_edit_rows(rows) if rows else f'<tr><td colspan="9" class="empty">{empty_msg}</td></tr>'}</tbody>
            </table>
          </div>
          {edit_batch_actions(rows)}
        </form>
        """
    elif tx_filter == "last_statement":
        ls = rows
        ls_pending = [r for r in ls if (r["status"] or "") == "needs_review"]
        ls_auto = [r for r in ls if (r["status"] or "") != "needs_review"]
        raw_ls_count = len(ls)
        if query:
            ls_pending = filter_review_rows(ls_pending, query)
            ls_auto = filter_editable_rows(ls_auto, query)
        ls_pending = sort_review_rows(ls_pending, review_sort)
        ls_auto = sorted(
            ls_auto,
            key=lambda r: (r["txn_date"], r["id"]),
            reverse=(review_sort != "oldest"),
        )
        fname = esc((last_import or {}).get("filename") or "last statement")
        body = f"""
        <p class="empty">From {fname} — {len(ls_pending)} to review, {len(ls_auto)} auto.</p>
        {review_sort_controls(review_sort, query, tx_filter="last_statement", exclude_credits=exclude_credits, start_date=start_date, end_date=end_date, edit_search=query)}
        {review_search_controls(query, review_sort, raw_ls_count, len(ls_pending) + len(ls_auto), tx_filter="last_statement", exclude_credits=exclude_credits, start_date=start_date, end_date=end_date)}
        <h3 class="tx-subhead">Needs review</h3>
        <form method="post" action="/review" class="review-batch-form" id="unified-review-form">
          {form_hidden_fields("last_statement")}
          <div style="overflow-x:auto;">
            <table class="tx-table">
              <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th colspan="5">Classify</th></tr></thead>
              <tbody>{render_review_rows(ls_pending) if ls_pending else '<tr><td colspan="8" class="empty">Nothing waiting for review in this statement.</td></tr>'}</tbody>
            </table>
          </div>
          {review_batch_actions(ls_pending)}
        </form>
        <h3 class="tx-subhead">Auto / classified</h3>
        <form method="post" action="/edit-classifications" class="review-batch-form" id="unified-edit-form">
          {form_hidden_fields("last_statement")}
          <div style="overflow-x:auto;">
            <table class="tx-table">
              <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th>Status</th><th colspan="5">Correction</th></tr></thead>
              <tbody>{render_edit_rows(ls_auto) if ls_auto else '<tr><td colspan="9" class="empty">No auto-classified rows in this statement.</td></tr>'}</tbody>
            </table>
          </div>
          {edit_batch_actions(ls_auto)}
        </form>
        """
    else:  # all — show pending then classified (two forms)
        body = f"""
        {review_sort_controls(review_sort, query, tx_filter="all", exclude_credits=exclude_credits, start_date=start_date, end_date=end_date, edit_search=query)}
        {review_search_controls(query, review_sort, total_all, pending_count + classified_count, tx_filter="all", exclude_credits=exclude_credits, start_date=start_date, end_date=end_date)}
        <h3 class="tx-subhead">Needs review</h3>
        <form method="post" action="/review" class="review-batch-form" id="unified-review-form">
          {form_hidden_fields("all")}
          <div style="overflow-x:auto;">
            <table class="tx-table">
              <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th colspan="5">Classify</th></tr></thead>
              <tbody>{render_review_rows(pending_rows) if pending_rows else '<tr><td colspan="8" class="empty">None pending.</td></tr>'}</tbody>
            </table>
          </div>
          {review_batch_actions(pending_rows)}
        </form>
        <h3 class="tx-subhead" style="margin-top:24px;">Classified</h3>
        <form method="post" action="/edit-classifications" class="review-batch-form" id="unified-edit-form">
          {form_hidden_fields("all")}
          <div style="overflow-x:auto;">
            <table class="tx-table">
              <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th>Status</th><th colspan="5">Correction</th></tr></thead>
              <tbody>{render_edit_rows(classified_rows) if classified_rows else '<tr><td colspan="9" class="empty">None classified.</td></tr>'}</tbody>
            </table>
          </div>
          {edit_batch_actions(classified_rows)}
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
      <a href="#import-add" class="mnav-item" data-tab-jump="import-add" data-tab="import-add">
        <span class="mnav-label">Import</span>
      </a>
      <a href="#dashboard" class="mnav-item" data-tab-jump="dashboard" data-tab="dashboard">
        <span class="mnav-label">Home</span>
      </a>
      <a href="#review" class="mnav-item" data-tab-jump="review" data-tab="review">
        <span class="mnav-label">Txns</span>{badge}
      </a>
      <a href="#contacts" class="mnav-item" data-tab-jump="contacts" data-tab="contacts">
        <span class="mnav-label">People</span>
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
    exclude_credits: bool = False,
    last_import: dict | None = None,
    gmail_on: bool = False,
    gmail_address: str | None = None,
    pdf_password_saved: bool = False,
    gemini_key_saved: bool = False,
) -> bytes:
    """Assemble the full dashboard HTML page from pre-fetched data."""
    all_users = all_users or []
    partner_balances = partner_balances or []
    review_sort = "oldest" if review_sort == "oldest" else "newest"
    review_search = review_search.strip()
    edit_search = edit_search.strip()
    person_search = person_search.strip()
    tx_filter = tx_filter if tx_filter in {
        "needs_review", "classified", "shared", "loan", "all", "last_statement"
    } else "needs_review"
    last_import = last_import or None
    # Full queue sizes for Home attention (not period-filtered — all-time)
    pending_items = [
        r for r in (data.get("transactions") or [])
        if ((r["status"] if hasattr(r, "keys") and "status" in r.keys() else r.get("status")) if isinstance(r, dict) or hasattr(r, "keys") else getattr(r, "status", None)) == "needs_review"
    ]
    attention_review_count = len(pending_items if pending_items or not data.get("pending") else data.get("pending") or [])
    attention_pt_count = len(data.get("passthrough_candidates") or [])
    if tx_filter == "needs_review" and not attention_review_count and data.get("transactions"):
        tx_filter = "classified"

    # Resolve the active date range (for dashboard charts + period badge counts only)
    min_date, max_date = date_bounds(data.get("transactions") or [])
    # Track whether the user explicitly chose a date range
    period_explicit = bool(start_date or end_date)
    li_start = str((last_import or {}).get("start") or "")[:10]
    li_end = str((last_import or {}).get("end") or "")[:10]
    # Last-statement chip uses import dates; Home default stays current month
    # so classified edits are not hidden after review.
    if tx_filter == "last_statement" and not period_explicit and li_start and li_end:
        start_date = li_start
        end_date = li_end
    elif not start_date and not end_date:
        from .services import default_dashboard_period

        start_date, end_date = default_dashboard_period(date.today(), min_date, max_date)
    else:
        start_date = start_date if start_date else min_date
        end_date = end_date if end_date else max_date

    if start_date and end_date and start_date > end_date:
        start_date = min_date


    def _in_period(r):
        txn_date = str(row_get(r, "txn_date") or "")[:10]
        start_str = str(start_date or "")[:10]
        end_str = str(end_date or "")[:10]
        if start_str and txn_date < start_str:
            return False
        if end_str and txn_date > end_str:
            return False
        return True

    # Apply date period to ALL tabs so everything is in sync with the dashboard.
    # The attention strip (captured above) remains all-time.
    pending_source = [r for r in (data.get("pending") or []) if _in_period(r)]
    filtered_review = filter_review_rows(pending_source, review_search)
    pending_review = sort_review_rows(filtered_review, review_sort)
    # Split review queue by debit/credit (legacy split still used for badge counts)
    debit_review = [r for r in pending_review if row_get(r, "debit") and float(row_get(r, "debit") or 0) > 0]
    credit_review = [r for r in pending_review if row_get(r, "credit") and float(row_get(r, "credit") or 0) > 0]
    unified_pending = pending_review
    pending_badge_count = len(unified_pending)

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
    # Classic Home keeps attention + spend only; settlement/NL/onboarding live in React /app/
    home_attention_html = render_home_attention_strip(
        attention_review_count, attention_pt_count, open_shared_null
    )
    mobile_nav_html = render_mobile_bottom_nav(pending_badge_count)
    # Home / money flow stay on the dashboard period
    tx_source = [r for r in data["transactions"] if _in_period(r)]
    last_import_id = (last_import or {}).get("import_id")
    last_statement_all = []
    if last_import_id is not None:
        last_statement_all = [
            r for r in data["transactions"]
            if str(r["import_id"]) == str(last_import_id)
        ]
    # Needs review / Classified / Shared = all rows (matches dashboard 125).
    # Last statement chip is the last WhatsApp file only.
    if period_explicit:
        workspace_rows = tx_source
    else:
        workspace_rows = list(data.get("transactions") or [])
    # Dashboard charts/totals use the same period + exclude_business
    period_rows = filter_dashboard_rows(data["transactions"], start_date, end_date, exclude_business)
    shared_source = [
        r for r in workspace_rows
        if (row_get(r, "expense_type") or "") == "Shared"
        and float(row_get(r, "debit") or 0) > 0
    ]

    unified_tx_html = render_unified_transactions_section(
        workspace_rows,
        loan_suggestions=data.get("loan_suggestions") or [],
        tx_filter=tx_filter,
        review_sort=review_sort,
        review_search=review_search,
        edit_search=edit_search,
        exclude_credits=exclude_credits,
        start_date=start_date if period_explicit else "",
        end_date=end_date if period_explicit else "",
        last_import=last_import,
        last_statement_rows=last_statement_all,
    )
    person_matches = sorted(
        filter_transactions_by_text(tx_source, person_search),
        key=lambda row: (row["txn_date"], row["id"]),
        reverse=True,
    )
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
    months_in_period = {
        str(
            (r["txn_date"] if hasattr(r, "keys") and "txn_date" in r.keys() else r.get("txn_date"))
            if isinstance(r, dict) or hasattr(r, "keys")
            else getattr(r, "txn_date", "")
        )[:7]
        for r in period_rows
        if r
    }
    months_in_period.discard("")
    if period_explicit and len(months_in_period) >= 2:
        trend_source_rows = period_rows
    else:
        trend_source_rows = filter_dashboard_rows(
            data.get("transactions") or [],
            end_date=end_date if period_explicit else "",
            exclude_business=exclude_business,
        )
    period_trends = monthly_trends_dict(trend_source_rows)
    message_html = f'<div class="notice">{esc(message)}</div>' if message else ""
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

    merge_suggestions: list[dict] = data.get("merge_suggestions") or []

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
  <link rel="stylesheet" href="/style.css?v=22">
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
        <a href="#import-add" class="tab-link" data-tab="import-add">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
          <span>Import</span>
        </a>
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
            <form class="gemini-key-form" method="post" action="/settings/gemini">
              <label>Gemini key
                <input type="password" name="gemini_api_key" autocomplete="off" placeholder="AIza…">
              </label>
              <button type="submit">Save</button>
              <span class="muted">{'Saved' if gemini_key_saved else 'For Ask on /app/'}</span>
            </form>
          </div>
        </details>
      </nav>
    </aside>

    <main class="main-content">
      <div id="toast-container" class="toast-container" data-message="{esc(message)}" data-error="{esc(error)}"></div>

      <!-- Tab 1: Dashboard (spend only — who-owes / NL / onboarding → /app/) -->
      <div id="pane-dashboard" class="tab-pane active">
        {home_attention_html}

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
            <h2 id="chart-trend-title">Monthly expense trend</h2>
            {render_monthly_trend_chart(period_trends)}
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
          {render_import_statement_section(
              last_import,
              gmail_on=gmail_on,
              gmail_address=gmail_address,
              pdf_password_saved=pdf_password_saved,
          )}
          {render_manual_transaction_form()}
        </div>
        
        <section style="margin-top:24px;">
          <h2>Money Flow & Cash Transfers</h2>
          {f'<p class="empty">Period {esc(start_date)} to {esc(end_date)}.' + (f' Last import {(last_import or {}).get("filename") or ""}. <a href="/?tx_filter=last_statement#review">Last statement only</a>' if last_import and not period_explicit else "") + "</p>"}
          {render_money_flows_view(tx_source)}
        </section>

        <section style="margin-top:24px;">
          <h2>Recent</h2>
          {render_recent_imports_view(data.get('recent_imports', []))}
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
                <tbody>{''.join(f"<tr><td>{esc(r['txn_date'])}</td><td>{esc(r['merchant_display'])}</td><td>{esc(r['category'])}</td><td>{bank_amount_html(r)}</td><td>{split_display(r['split_ratio'])}</td><td>{money(r['my_share'])}</td><td>{esc((r['shared_with'] if hasattr(r, 'keys') and 'shared_with' in r.keys() and r['shared_with'] else None) or '—')}</td></tr>" for r in shared_source) or '<tr><td colspan="7" class="empty">No shared expenses yet.</td></tr>'}</tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    </main>
  </div>
  
  {mobile_nav_html}
  <script src="/app.js?v=21"></script>
</body>
</html>
"""
    return html_doc.encode("utf-8")
