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
    date_bounds,
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


def money(value) -> str:
    try:
        return f"Rs {Decimal(str(value or 0)):,.2f}"
    except InvalidOperation:
        return "Rs 0.00"


def signed_amount(value) -> str:
    try:
        amount = Decimal(str(value or 0))
    except InvalidOperation:
        amount = Decimal("0")
    if amount > 0:
        return f'<span class="amount credit">+ {money(amount)}</span>'
    if amount < 0:
        return f'<span class="amount debit">- {money(abs(amount))}</span>'
    return '<span class="amount">Rs 0.00</span>'


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
    use_my_share: bool,
) -> str:
    return f"""
    <section class="dashboard-controls">
      <div class="section-head">
        <h2>Dashboard period</h2>
      </div>
      <form method="get" action="/" class="period-form">
        <label>Start date <input type="date" name="start_date" value="{esc(start_date)}" min="{esc(min_date)}" max="{esc(max_date)}"></label>
        <label>End date <input type="date" name="end_date" value="{esc(end_date)}" min="{esc(min_date)}" max="{esc(max_date)}"></label>
        <label class="check"><input type="checkbox" name="exclude_business" value="1" {"checked" if exclude_business else ""}> Exclude Business</label>
        <label class="check"><input type="checkbox" name="use_my_share" value="1" {"checked" if use_my_share else ""}> Use my share for split debits</label>
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


def render_categories_chart(categories: list[tuple[str, Decimal]]) -> str:
    import json
    if not categories:
        return '<p class="empty">No category data for this period.</p>'
    labels = [c[0] for c in categories]
    values = [float(c[1]) for c in categories]
    return f"""
    <div class="chart-container" style="position: relative; min-height: 200px; width: 100%;">
      <canvas id="categoriesChart" data-labels="{esc(json.dumps(labels))}" data-values="{esc(json.dumps(values))}"></canvas>
    </div>
    """


def render_merchants_chart(merchants: list[tuple[str, Decimal]]) -> str:
    import json
    if not merchants:
        return '<p class="empty">No merchant data for this period.</p>'
    labels = [m[0] for m in merchants]
    values = [float(m[1]) for m in merchants]
    return f"""
    <div class="chart-container" style="position: relative; min-height: 260px; width: 100%;">
      <canvas id="merchantsChart" data-labels="{esc(json.dumps(labels))}" data-values="{esc(json.dumps(values))}"></canvas>
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
              <td>{esc(row['category'] or 'Uncategorized')}</td>
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


def render_review_rows(rows) -> str:
    if not rows:
        return '<tr><td colspan="8" class="empty">Nothing waiting for review.</td></tr>'
    output = []
    for row in rows:
        row_id = row["id"]
        output.append(
            f"""
            <tr>
              <td>{esc(row['txn_date'])}</td>
              <td>
                <strong>{esc(row['merchant_display'])}</strong>
                <span>{esc(row['description'])}</span>
              </td>
              <td>{signed_amount(row['amount_signed'])}</td>
              <td colspan="5">
                <div class="review-form">
                  <input type="hidden" name="review_ids" value="{row_id}">
                  <label class="review-field"><span>Category</span><select name="category_{row_id}">
                    <option value="">Choose</option>
                    {option_tags(CATEGORIES, row['category'])}
                  </select></label>
                  <label class="review-field"><span>Type</span><select name="expense_type_{row_id}">
                    {option_tags(EXPENSE_TYPES, row['expense_type'])}
                  </select></label>
                  <label class="review-field"><span>People</span><input name="split_people_{row_id}" type="number" min="1" step="1" value="{review_people_value(row)}" title="Number of people sharing this expense"></label>
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
        badge = "ok" if row["status"] != "needs_review" else "warn"
        output.append(
            f"""
            <tr>
              <td>{esc(row['txn_date'])}</td>
              <td>
                <strong>{esc(row['merchant_display'])}</strong>
                <span>{esc(row['description'])}</span>
              </td>
              <td>{signed_amount(row['amount_signed'])}</td>
              <td><span class="badge {badge}">{esc(row['status'])}</span></td>
              <td colspan="5">
                <div class="review-form">
                  <input type="hidden" name="edit_ids" value="{row_id}">
                  <label class="review-field"><span>Category</span><select name="edit_category_{row_id}">
                    <option value="">Choose</option>
                    {option_tags(CATEGORIES, row['category'])}
                  </select></label>
                  <label class="review-field"><span>Type</span><select name="edit_expense_type_{row_id}">
                    {option_tags(EXPENSE_TYPES, row['expense_type'])}
                  </select></label>
                  <label class="review-field"><span>People</span><input name="edit_split_people_{row_id}" type="number" min="1" step="1" value="{review_people_value(row)}" title="Number of people sharing this expense"></label>
                  <label class="review-field"><span>Notes</span><input name="edit_notes_{row_id}" value="{esc(row_get(row, 'notes', '') or '')}" placeholder="Optional"></label>
                  <label class="check"><input type="checkbox" name="edit_learn_{row_id}"> Learn</label>
                </div>
              </td>
            </tr>
            """
        )
    return "".join(output)


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
          <span>Link Amount (Rs)</span>
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
    <div class="review-actions">
      <button type="submit">Confirm review changes</button>
    </div>
    """


def edit_batch_actions(rows) -> str:
    if not rows:
        return ""
    return """
    <div class="review-actions">
      <button type="submit">Save classification edits</button>
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
        return '<tr><td colspan="5" class="empty">Merchant mappings will appear after confirmations.</td></tr>'
    return "".join(
        f"""
        <tr>
          <td>{esc(row['merchant_display'])}</td>
          <td>{esc(row['category'])}</td>
          <td>{esc(row['expense_type'])}</td>
          <td>{split_display(row['split_ratio'])}</td>
          <td>{esc(row['match_count'])}</td>
        </tr>
        """
        for row in rows
    )


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
) -> bytes:
    """Assemble the full dashboard HTML page from pre-fetched data."""
    review_sort = "oldest" if review_sort == "oldest" else "newest"
    review_search = review_search.strip()
    edit_search = edit_search.strip()
    person_search = person_search.strip()
    filtered_review = filter_review_rows(data["pending"], review_search)
    pending_review = sort_review_rows(filtered_review, review_sort)
    editable_all = [row for row in data["transactions"] if row["status"] != "needs_review"]
    filtered_edit = filter_editable_rows(data["transactions"], edit_search)
    editable_rows = filtered_edit if edit_search else filtered_edit[:25]
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
    period_categories = expenses_by_category(period_rows, use_my_share)
    category_max = max((amount for _, amount in period_categories), default=Decimal("1"))
    period_merchants = top_merchants_from_rows(period_rows, use_my_share)
    merchant_max = max((amount for _, amount in period_merchants), default=Decimal("1"))
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
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Personal Expense Tracker</title>
  <link rel="stylesheet" href="/style.css?v=3">
  <script src="/chart.js?v=3"></script>
</head>
<body>
  <header>
    <div class="header-title">
      <h1>Personal Expense Tracker</h1>
      <p>SBI statement imports, merchant learning, review queue, and shared expense tracking.</p>
    </div>
    <button id="theme-toggle" class="theme-toggle-btn" aria-label="Toggle theme">
      <!-- Sun icon (for dark mode) -->
      <svg class="sun-icon" viewBox="0 0 24 24" style="display:none;"><path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1zM5.99 4.58c-.39-.39-1.03-.39-1.41 0s-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41L5.99 4.58zm12.37 12.37c-.39-.39-1.03-.39-1.41 0s-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41l-1.06-1.06zm1.06-10.96c.39-.39.39-1.03 0-1.41s-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06zM7.05 18.36c.39-.39.39-1.03 0-1.41s-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06z"/></svg>
      <!-- Moon icon (for light mode) -->
      <svg class="moon-icon" viewBox="0 0 24 24" style="display:none;"><path d="M12.3 22h-.1c-5.5 0-10-4.5-10-10 0-4.8 3.5-9 8.3-9.8.6-.1 1.2.3 1.3.9.1.6-.2 1.2-.8 1.4-3.4 1-5.8 4.1-5.8 7.6 0 4.4 3.6 8 8 8 3.5 0 6.6-2.4 7.6-5.8.2-.6.8-.9 1.4-.8.6.1 1 .7.9 1.3-.8 4.8-5 8.2-9.9 8.2z"/></svg>
    </button>
  </header>
  
  <div class="app-container">
    <aside class="sidebar">
      <nav class="nav-tabs" aria-label="Main Navigation">
        <a href="#dashboard" class="tab-link active" data-tab="dashboard">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>
          <span>Dashboard</span>
        </a>
        <a href="#import-add" class="tab-link" data-tab="import-add">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
          <span>Import / Add</span>
        </a>
        <a href="#loops" class="tab-link" data-tab="loops">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>
          <span>Loops</span>
          {f'<span class="tab-badge ok" id="suggestions-badge">{len(data["suggestions"])}</span>' if len(data["suggestions"]) > 0 else ""}
        </a>
        <a href="#review" class="tab-link" data-tab="review">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-2 10H7v-2h10v2zm0-4H7V7h10v2zm0 8H7v-2h10v2z"/></svg>
          <span>Review Queue</span>
          <span class="tab-badge warn" id="review-count-badge">{len(data['pending'])}</span>
        </a>
        <a href="#transactions" class="tab-link" data-tab="transactions">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
          <span>Edit Classifications</span>
        </a>
        <a href="#search" class="tab-link" data-tab="search">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
          <span>Credit / Debit Search</span>
        </a>
        <a href="#rules" class="tab-link" data-tab="rules">
          <svg class="nav-icon" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>
          <span>Knowledge & Shared</span>
        </a>
      </nav>
    </aside>

    <main class="main-content">
      <div id="toast-container" class="toast-container" data-message="{esc(message)}" data-error="{esc(error)}"></div>

      <!-- Tab 1: Dashboard -->
      <div id="pane-dashboard" class="tab-pane active">
        {render_dashboard_filters(start_date, end_date, min_date, max_date, exclude_business, use_my_share)}
        
        <div class="grid metrics">
          <div class="metric"><span>Period credits</span><strong>{money(period_totals['credit'])}</strong></div>
          <div class="metric"><span>Period debits</span><strong>{money(period_totals['debit'])}</strong></div>
          <div class="metric"><span>Expense basis</span><strong>{money(period_totals['expense'])}</strong></div>
          <div class="metric"><span>Awaiting review</span><strong>{len(data['pending'])}</strong></div>
        </div>

        <div class="grid two" style="margin-top:24px;">
          <section>
            <h2>Total credits / debits</h2>
            {render_credit_debit_pie(period_totals)}
          </section>
          <section>
            <h2>Expenses by category</h2>
            {render_categories_chart(period_categories)}
          </section>
        </div>

        <section style="margin-top:24px;">
          <h2>Top merchants</h2>
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
      </div>

      <!-- Tab 3: Loops -->
      <div id="pane-loops" class="tab-pane">
        <section>
          <h2>Suggested connections</h2>
          <p class="section-desc">The matching engine finds credits that correspond to prior debits (e.g. repayments, reimbursements) based on name and amount correlations.</p>
          {render_suggestions(data['suggestions'])}
        </section>

        <section style="margin-top: 24px;">
          <h2>Link transactions manually</h2>
          {render_manual_linker(data['linkable'])}
        </section>

        <section style="margin-top: 24px;">
          <h2>Active connections</h2>
          {render_active_connections(data['links'])}
        </section>
      </div>

      <!-- Tab 4: Review Queue -->
      <div id="pane-review" class="tab-pane">
        <section>
          <h2>Transactions awaiting review</h2>
          {review_sort_controls(review_sort, review_search)}
          {review_search_controls(review_search, review_sort, len(data['pending']), len(filtered_review))}
          <form method="post" action="/review" class="review-batch-form">
            <div style="overflow-x: auto;">
              <table>
                <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th colspan="5">Confirmation</th></tr></thead>
                <tbody>{render_review_rows(pending_review)}</tbody>
              </table>
            </div>
            {review_batch_actions(pending_review)}
          </form>
        </section>
      </div>

      <!-- Tab 5: Edit Classifications -->
      <div id="pane-transactions" class="tab-pane">
        <section>
          <h2>Edit classifications</h2>
          {edit_search_controls(edit_search, len(editable_all), len(filtered_edit), len(editable_rows))}
          <form method="post" action="/edit-classifications" class="review-batch-form">
            <div style="overflow-x: auto;">
              <table>
                <thead><tr><th>Date</th><th>Merchant</th><th>Amount</th><th>Status</th><th colspan="5">Correction</th></tr></thead>
                <tbody>{render_edit_rows(editable_rows)}</tbody>
              </table>
            </div>
            {edit_batch_actions(editable_rows)}
          </form>
        </section>
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
            <div style="overflow-x: auto;">
              <table>
                <thead><tr><th>Merchant</th><th>Category</th><th>Type</th><th>Split</th><th>Uses</th></tr></thead>
                <tbody>{render_rules(data['rules'])}</tbody>
              </table>
            </div>
          </section>
          <section>
            <h2>Shared expenses</h2>
            <div style="overflow-x: auto;">
              <table>
                <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Total</th><th>Split</th><th>My share</th></tr></thead>
                <tbody>{''.join(f"<tr><td>{esc(r['txn_date'])}</td><td>{esc(r['merchant_display'])}</td><td>{esc(r['category'])}</td><td>{money(r['debit'])}</td><td>{split_display(r['split_ratio'])}</td><td>{money(r['my_share'])}</td></tr>" for r in data['shared']) or '<tr><td colspan="6" class="empty">No shared expenses yet.</td></tr>'}</tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    </main>
  </div>
  
  <script src="/app.js?v=3"></script>
</body>
</html>
"""
    return html_doc.encode("utf-8")
