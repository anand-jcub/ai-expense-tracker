import { useEffect, useRef, useState } from 'react'
import { fetchDashboardSummary, money } from '../../api/client'
import CategoryModal from './CategoryModal.jsx'

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

function getPrevMonthStr(ym) {
  if (!ym) return ''
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m - 2, 1)
  const py = d.getFullYear()
  const pm = String(d.getMonth() + 1).padStart(2, '0')
  return `${py}-${pm}`
}

function getNextMonthStr(ym) {
  if (!ym) return ''
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m, 1)
  const ny = d.getFullYear()
  const nm = String(d.getMonth() + 1).padStart(2, '0')
  return `${ny}-${nm}`
}

function getMonthDateBounds(ym) {
  if (!ym) return { start: '', end: '' }
  const [y, m] = ym.split('-').map(Number)
  const start = `${y}-${String(m).padStart(2, '0')}-01`
  const lastDay = new Date(y, m, 0).getDate()
  const end = `${y}-${String(m).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
  return { start, end }
}

function formatMonthTitle(ym) {
  if (!ym) return ''
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m - 1, 1)
  return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
}

export default function HomeScreen({ onAsk, onAskReview, onAdd: _onAdd, snapshot: _snapshot, syncedAt: _syncedAt, refreshKey, onRefresh }) {
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState('')
  const [pull, setPull] = useState(0)
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [modalCategory, setModalCategory] = useState(null)
  const [showAll, setShowAll] = useState(false)
  const [currentMonth, setCurrentMonth] = useState(null)
  const [latestMonth, setLatestMonth] = useState(null)
  const [loading, setLoading] = useState(false)

  const startX = useRef(null)
  const startY = useRef(null)
  const isHorizontalSwipe = useRef(null)
  const pullRef = useRef(0)

  useEffect(() => {
    let alive = true
    setLoading(true)
    const params = {}
    if (currentMonth) {
      const { start, end } = getMonthDateBounds(currentMonth)
      params.start_date = start
      params.end_date = end
    }
    fetchDashboardSummary(params)
      .then((dash) => {
        if (!alive) return
        setSummary(dash)
        setLoading(false)
        if (dash.start_date) {
          const ym = dash.start_date.slice(0, 7)
          if (!currentMonth) {
            setCurrentMonth(ym)
          }
          if (!latestMonth) {
            setLatestMonth(ym)
          }
        }
      })
      .catch((ex) => {
        if (alive) {
          setError(ex.message || 'Could not load')
          setLoading(false)
        }
      })
    return () => {
      alive = false
    }
  }, [refreshKey, currentMonth, latestMonth])

  const canGoNext = Boolean(currentMonth && latestMonth && currentMonth < latestMonth)

  const handlePrevMonth = () => {
    if (!currentMonth) return
    setSelectedCategory(null)
    setModalCategory(null)
    setCurrentMonth(getPrevMonthStr(currentMonth))
  }

  const handleNextMonth = () => {
    if (!canGoNext) return
    setSelectedCategory(null)
    setModalCategory(null)
    setCurrentMonth(getNextMonthStr(currentMonth))
  }

  const openCategoryModal = (catName) => {
    setSelectedCategory(catName)
    setModalCategory(catName)
  }

  const closeCategoryModal = () => {
    setModalCategory(null)
  }

  const onTouchStart = (e) => {
    if (modalCategory || e.target.closest('.category-modal-backdrop') || e.target.closest('.category-modal-sheet')) {
      startY.current = null
      startX.current = null
      return
    }
    const scroller = e.currentTarget.closest('.app-main')
    if (scroller && scroller.scrollTop > 4) {
      startY.current = null
      startX.current = null
      return
    }
    startX.current = e.touches[0].clientX
    startY.current = e.touches[0].clientY
    isHorizontalSwipe.current = null
    pullRef.current = 0
  }

  const onTouchMove = (e) => {
    if (startY.current == null || startX.current == null) return
    const dx = e.touches[0].clientX - startX.current
    const dy = e.touches[0].clientY - startY.current

    if (isHorizontalSwipe.current == null) {
      if (Math.abs(dx) > 10 || Math.abs(dy) > 10) {
        isHorizontalSwipe.current = Math.abs(dx) > Math.abs(dy)
      }
    }

    if (isHorizontalSwipe.current === false) {
      const pullVal = Math.max(0, Math.min(dy, 88))
      pullRef.current = pullVal
      setPull(pullVal)
    }
  }

  const onTouchEnd = (e) => {
    if (isHorizontalSwipe.current === true && startX.current != null) {
      const dx = e.changedTouches[0].clientX - startX.current
      if (dx > 45) {
        handlePrevMonth()
      } else if (dx < -45) {
        handleNextMonth()
      }
    } else if (pullRef.current > 52 && onRefresh) {
      onRefresh()
    }
    startX.current = null
    startY.current = null
    isHorizontalSwipe.current = null
    pullRef.current = 0
    setPull(0)
  }

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

  // Donut geometry
  const radius = 72
  const circumference = 2 * Math.PI * radius
  let accumulatedPct = 0
  const slices = categories
    .filter((c) => Number(c.amount) > 0)
    .map((c) => {
      const amount = Number(c.amount) || 0
      const fraction = amount / totalCatSpend
      const length = fraction * circumference
      const gap = categories.length > 1 ? 2.5 : 0
      const arcLength = Math.max(0, length - gap)
      const dashArray = `${arcLength} ${circumference}`
      const dashOffset = -(accumulatedPct * circumference)
      accumulatedPct += fraction
      const isSelected = selectedCategory === c.category
      const isDimmed = selectedCategory !== null && !isSelected
      return {
        category: c.category,
        amount,
        pct: Math.round(fraction * 100),
        color: CATEGORY_COLORS[c.category] || '#94a3b8',
        dashArray,
        dashOffset,
        isSelected,
        isDimmed,
      }
    })

  const activeCat = selectedCategory ? categories.find((c) => c.category === selectedCategory) : null

  // Visible categories: top 5 by default, or all if expanded / category selected
  const displayedCategories =
    showAll || selectedCategory || categories.length <= 5
      ? categories
      : categories.slice(0, 5)

  const monthDisplayTitle = formatMonthTitle(currentMonth)

  return (
    <div
      className={`glance ${loading ? 'glance-loading' : ''}`}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      {pull > 8 ? <p className="muted pull-hint">{pull > 52 ? 'Release to refresh' : '…'}</p> : null}

      <section className="glance-hero">
        <div className="month-nav-bar">
          <button
            type="button"
            className="month-nav-btn"
            onClick={handlePrevMonth}
            aria-label="Previous month"
            title="Previous month (or swipe right)"
          >
            ‹
          </button>
          <span className="month-nav-title">{monthDisplayTitle}</span>
          <button
            type="button"
            className={`month-nav-btn ${!canGoNext ? 'month-nav-btn-disabled' : ''}`}
            onClick={handleNextMonth}
            disabled={!canGoNext}
            aria-label="Next month"
            title={canGoNext ? 'Next month (or swipe left)' : 'Latest month'}
          >
            ›
          </button>
        </div>
      </section>

      <section className="glance-chart-section">
        {categories.length > 0 ? (
          <>
            {/* Interactive Donut Chart */}
            <div className="donut-chart-wrapper">
              <svg
                viewBox="0 0 200 200"
                className="donut-chart-svg"
                aria-label="Category spend distribution donut chart"
              >
                {/* Background Ring */}
                <circle
                  cx="100"
                  cy="100"
                  r={radius}
                  fill="none"
                  stroke="rgba(255, 255, 255, 0.05)"
                  strokeWidth="15"
                />
                {/* Colored Slices */}
                {slices.map((s) => (
                  <circle
                    key={s.category}
                    cx="100"
                    cy="100"
                    r={radius}
                    fill="none"
                    stroke={s.color}
                    strokeWidth={s.isSelected ? 22 : 15}
                    strokeDasharray={s.dashArray}
                    strokeDashoffset={s.dashOffset}
                    strokeLinecap="round"
                    className={`donut-segment ${s.isSelected ? 'selected' : ''} ${s.isDimmed ? 'dimmed' : ''}`}
                    style={{
                      opacity: s.isDimmed ? 0.35 : 1,
                    }}
                  />
                ))}
              </svg>

              {/* Center Metrics (Only Amount) */}
              <div
                className="donut-center-content"
                onClick={() => setSelectedCategory(null)}
                role="button"
                tabIndex={0}
                aria-label="Reset chart selection"
              >
                <span className="donut-center-amount">
                  {money(activeCat ? activeCat.amount : spend)}
                </span>
              </div>
            </div>

            {/* Category Breakdown List with Progress Tracks */}
            <ul className="category-breakdown-list">
              {displayedCategories.map((c) => {
                const pct = Math.round((Number(c.amount) / totalCatSpend) * 100)
                const color = CATEGORY_COLORS[c.category] || '#94a3b8'
                const isUncategorized = (c.category || '').toLowerCase() === 'uncategorized'
                const isSelected = selectedCategory === c.category
                const isDimmed = selectedCategory !== null && !isSelected

                return (
                  <li
                    key={c.category}
                    className={`category-row-item ${isSelected ? 'category-row-active' : ''} ${
                      isDimmed ? 'category-row-dimmed' : ''
                    } ${isUncategorized ? 'category-row-clickable' : ''}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => openCategoryModal(c.category)}
                  >
                    {/* Visual Progress Track */}
                    <div
                      className="category-row-progress"
                      style={{
                        width: `${pct}%`,
                        backgroundColor: color,
                        opacity: isSelected ? 0.22 : 0.08,
                      }}
                    />

                    <div className="category-row-left">
                      <span className="category-dot" style={{ backgroundColor: color }} />
                      <span className="category-name">
                        {c.category}
                        {isUncategorized && Number(summary.needs_review_count || 0) > 0 ? (
                          <span
                            className="category-review-tag"
                            role="button"
                            tabIndex={0}
                            onClick={(e) => {
                              e.stopPropagation()
                              if (onAskReview) {
                                onAskReview({ start_date: summary.start_date, end_date: summary.end_date })
                              } else {
                                onAsk()
                              }
                            }}
                          >
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

            {categories.length > 5 && !selectedCategory ? (
              <button
                type="button"
                className="category-show-toggle"
                onClick={() => setShowAll((v) => !v)}
              >
                {showAll
                  ? 'Show top 5 categories ↑'
                  : `Show all ${categories.length} categories (${categories.length - 5} more) ↓`}
              </button>
            ) : null}
          </>
        ) : (
          <p className="empty-state">No expenses recorded for {monthDisplayTitle || 'this month'}.</p>
        )}
      </section>

      <CategoryModal
        isOpen={Boolean(modalCategory)}
        category={modalCategory}
        color={modalCategory ? (CATEGORY_COLORS[modalCategory] || '#94a3b8') : '#94a3b8'}
        totalAmount={modalCategory ? (categories.find((c) => c.category === modalCategory)?.amount ?? 0) : 0}
        period={{
          start: currentMonth ? getMonthDateBounds(currentMonth).start : (summary?.start_date || ''),
          end: currentMonth ? getMonthDateBounds(currentMonth).end : (summary?.end_date || ''),
          title: monthDisplayTitle,
        }}
        onClose={closeCategoryModal}
        onAskReview={onAskReview}
      />
    </div>
  )
}
