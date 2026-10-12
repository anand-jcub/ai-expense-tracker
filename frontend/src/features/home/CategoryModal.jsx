import { useEffect, useState } from 'react'
import { fetchCategoryTransactions, money } from '../../api/client'

function formatShortDate(iso) {
  if (!iso) return ''
  try {
    const parts = iso.slice(0, 10).split('-')
    if (parts.length === 3) {
      const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
      return d.toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
    }
  } catch {
    // fallback
  }
  return iso.slice(5, 10)
}

export default function CategoryModal({
  isOpen,
  category,
  color = '#94a3b8',
  totalAmount,
  period,
  onClose,
  onAskReview,
}) {
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!isOpen || !category) {
      setTransactions([])
      setError('')
      setLoading(false)
      return
    }

    let alive = true
    setLoading(true)
    setError('')

    const params = {
      category,
      start_date: period?.start || '',
      end_date: period?.end || '',
    }

    fetchCategoryTransactions(params)
      .then((data) => {
        if (!alive) return
        setTransactions(data.transactions || [])
        setLoading(false)
      })
      .catch((err) => {
        if (!alive) return
        setError(err.message || 'Could not load transactions')
        setLoading(false)
      })

    return () => {
      alive = false
    }
  }, [isOpen, category, period?.start, period?.end])

  useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isOpen, onClose])

  if (!isOpen || !category) return null

  const isUncategorized = (category || '').toLowerCase() === 'uncategorized'

  return (
    <div
      className="category-modal-backdrop"
      onClick={onClose}
      onTouchStart={(e) => e.stopPropagation()}
      onTouchMove={(e) => e.stopPropagation()}
      onTouchEnd={(e) => e.stopPropagation()}
      role="presentation"
    >
      <div
        className="category-modal-sheet"
        onClick={(e) => e.stopPropagation()}
        onTouchStart={(e) => e.stopPropagation()}
        onTouchMove={(e) => e.stopPropagation()}
        onTouchEnd={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`${category} transactions`}
      >
        <div className="sheet-grabber" />

        <div className="category-modal-header">
          <div className="category-modal-title-row">
            <div className="category-modal-title-left">
              <span className="category-dot" style={{ backgroundColor: color }} />
              <h2 className="category-modal-title">{category}</h2>
              {totalAmount !== undefined && (
                <span className="category-modal-amount-pill">{money(totalAmount)}</span>
              )}
            </div>
            <button
              type="button"
              className="btn ghost icon-btn category-modal-close-btn"
              onClick={onClose}
              aria-label="Close"
              title="Close"
            >
              ✕
            </button>
          </div>

          <div className="category-modal-meta-row">
            <span className="category-modal-period-text">
              {period?.title || 'This period'}
            </span>
            {!loading && (
              <span className="category-modal-count-text">
                {transactions.length} {transactions.length === 1 ? 'transaction' : 'transactions'}
              </span>
            )}
          </div>

          {isUncategorized && onAskReview && (
            <button
              type="button"
              className="category-modal-review-action"
              onClick={() => {
                onClose()
                onAskReview({ start_date: period?.start, end_date: period?.end })
              }}
            >
              Review pending transactions with AI →
            </button>
          )}
        </div>

        <div className="category-modal-body">
          {loading && (
            <div className="category-modal-loading">
              <span className="category-modal-spinner" />
              <p className="muted">Loading transactions…</p>
            </div>
          )}

          {error && <p className="error-banner">{error}</p>}

          {!loading && !error && transactions.length === 0 && (
            <p className="empty-state category-modal-empty">
              No transactions recorded for {category} in {period?.title || 'this month'}.
            </p>
          )}

          {!loading && !error && transactions.length > 0 && (
            <ul className="category-modal-list">
              {transactions.map((t) => {
                const payee = t.merchant_display || t.description || 'Expense'
                const fullDebit = Number(t.debit) || 0
                const shareAmount =
                  t.my_share !== null && t.my_share !== undefined
                    ? Number(t.my_share)
                    : fullDebit
                const isSplit = t.my_share !== null && t.my_share !== undefined && shareAmount < fullDebit

                return (
                  <li key={t.id || `${t.txn_date}-${payee}-${t.debit}`} className="category-modal-item">
                    <div className="category-modal-item-left">
                      <span className="category-modal-item-payee" title={payee}>
                        {payee}
                      </span>
                      <span className="category-modal-item-date">
                        {formatShortDate(t.txn_date)}
                      </span>
                    </div>

                    <div className="category-modal-item-right">
                      <span className="category-modal-item-amount">{money(shareAmount)}</span>
                      {isSplit && (
                        <span className="category-modal-item-split" title={`Full debit ${money(fullDebit)}`}>
                          split · full {money(fullDebit)}
                        </span>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
