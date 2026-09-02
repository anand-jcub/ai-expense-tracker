import { useEffect, useRef, useState } from 'react'
import { fetchDashboardSummary, money } from '../../api/client'

const CATEGORY_COLORS = {
  Food: '#f59e0b',
  Groceries: '#10b981',
  Rent: '#6366f1',
  Flat: '#8b5cf6',
  Transport: '#3b82f6',
  Shopping: '#ec4899',
  Health: '#ef4444',
  'Personal Care': '#14b8a6',
  Utilities: '#06b6d4',
  Subscription: '#a855f7',
  Travel: '#f97316',
  Entertainment: '#eab308',
  Business: '#64748b',
  Transfer: '#0ea5e9',
  Loan: '#84cc16',
  Family: '#f43f5e',
  Other: '#94a3b8',
  Uncategorized: '#64748b',
}

export default function HomeScreen({ onAsk, onAskReview, onAdd, snapshot, syncedAt, refreshKey, onRefresh }) {
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState('')
  const [pull, setPull] = useState(0)
  const startY = useRef(null)
  const pullRef = useRef(0)

  useEffect(() => {
    let alive = true
    fetchDashboardSummary()
      .then((dash) => {
        if (!alive) return
        setSummary(dash)
      })
      .catch((ex) => {
        if (alive) setError(ex.message || 'Could not load')
      })
    return () => {
      alive = false
    }
  }, [refreshKey])

  if (error) return <p className="error-banner">{error}</p>
  if (!summary) return <p className="muted">…</p>

  const spend = summary.period_expense_share
  const rawCats = summary.by_category || []
  let categories = rawCats.filter((c) => Number(c.amount) > 0)
  const hasUncategorized = categories.some((c) => (c.category || '').toLowerCase() === 'uncategorized')
  if (!hasUncategorized && Number(summary.needs_review_count || 0) > 0) {
    categories = [...categories, { category: 'Uncategorized', amount: 0, pending: summary.needs_review_count }]
  }
  const totalCatSpend = categories.reduce((sum, c) => sum + Number(c.amount), 0) || spend || 1

  const onTouchStart = (e) => {
    const scroller = e.currentTarget.closest('.app-main')
    if (scroller && scroller.scrollTop > 4) {
      startY.current = null
      return
    }
    startY.current = e.touches[0].clientY
    pullRef.current = 0
  }
  const onTouchMove = (e) => {
    if (startY.current == null) return
    const dy = Math.max(0, Math.min(e.touches[0].clientY - startY.current, 88))
    pullRef.current = dy
    setPull(dy)
  }
  const onTouchEnd = () => {
    if (pullRef.current > 52 && onRefresh) onRefresh()
    startY.current = null
    pullRef.current = 0
    setPull(0)
  }

  return (
    <div
      className="glance"
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      {pull > 8 ? <p className="muted pull-hint">{pull > 52 ? 'Release to refresh' : '…'}</p> : null}

      <section className="glance-hero">
        <p className="muted">This month</p>
        <p className="glance-amount">{money(spend)}</p>
        <p className="muted">
          {summary.start_date} – {summary.end_date}
          {snapshot && (syncedAt || summary.syncedAt)
            ? ` · as of ${(syncedAt || summary.syncedAt || '').slice(0, 16).replace('T', ' ')}`
            : ''}
        </p>
      </section>

      <section className="glance-chart-section">
        {categories.length > 0 ? (
          <>
            <div className="category-proportion-bar" aria-label="Category distribution bar">
              {categories.map((c) => {
                const pct = Math.max(1, (Number(c.amount) / totalCatSpend) * 100)
                const color = CATEGORY_COLORS[c.category] || '#94a3b8'
                return (
                  <div
                    key={c.category}
                    className="prop-bar-segment"
                    style={{ width: `${pct}%`, backgroundColor: color }}
                    title={`${c.category}: ${money(c.amount)} (${Math.round((Number(c.amount) / totalCatSpend) * 100)}%)`}
                  />
                )
              })}
            </div>

            <ul className="category-breakdown-list">
              {categories.map((c) => {
                const pct = Math.round((Number(c.amount) / totalCatSpend) * 100)
                const color = CATEGORY_COLORS[c.category] || '#94a3b8'
                const isUncategorized = (c.category || '').toLowerCase() === 'uncategorized'
                return (
                  <li
                    key={c.category}
                    className={`category-row-item ${isUncategorized ? 'category-row-clickable' : ''}`}
                    role={isUncategorized ? 'button' : undefined}
                    tabIndex={isUncategorized ? 0 : undefined}
                    onClick={
                      isUncategorized
                        ? () => {
                            if (onAskReview) {
                              onAskReview({ start_date: summary.start_date, end_date: summary.end_date })
                            } else {
                              onAsk()
                            }
                          }
                        : undefined
                    }
                  >
                    <div className="category-row-left">
                      <span className="category-dot" style={{ backgroundColor: color }} />
                      <span className="category-name">
                        {c.category}
                        {isUncategorized && Number(summary.needs_review_count || 0) > 0 ? (
                          <span className="category-review-tag">
                            {summary.needs_review_count} to review →
                          </span>
                        ) : null}
                      </span>
                    </div>
                    <div className="category-row-right">
                      <span className="category-amount">{money(c.amount)}</span>
                      <span className="category-pct">{pct}%</span>
                    </div>
                  </li>
                )
              })}
            </ul>
          </>
        ) : (
          <p className="empty-state">No expenses recorded for this month.</p>
        )}
      </section>

      <div className="glance-actions">
        <button type="button" className="btn primary" onClick={onAdd}>
          Add
        </button>
        <button type="button" className="btn" onClick={onAsk}>
          Ask
        </button>
      </div>
    </div>
  )
}
