import { useCallback, useEffect, useState } from 'react'
import {
  fetchOnboarding,
  fetchSettlementByName,
  fetchSettlementSummary,
  money,
} from './api'
import './App.css'

function OnboardingCard({ onboarding }) {
  if (!onboarding) return null
  const steps = onboarding.steps || []
  const done = steps.filter((s) => s.done).length
  if (onboarding.complete) {
    return (
      <div className="card">
        <h2>You&apos;re set up</h2>
        <p className="muted">All onboarding steps complete. Use classic UI for import & review.</p>
      </div>
    )
  }
  return (
    <div className="card">
      <h2>Getting started ({done}/{steps.length})</h2>
      <ul className="checklist">
        {steps.map((s) => (
          <li key={s.id} className={s.done ? 'done' : ''}>
            <span className="check-mark">{s.done ? '✓' : ''}</span>
            <div>
              <div>{s.label}</div>
              {s.hint ? <div className="muted">{s.hint}</div> : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function HomeView({ summary, onboarding, onOpenPeople }) {
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  const ask = async (e) => {
    e.preventDefault()
    const query = q.trim()
    if (!query) return
    setLoading(true)
    setErr('')
    setAnswer(null)
    try {
      // Support natural phrasing: "How much does Highnes owe me?"
      const cleaned = query
        .replace(/how much (does|do)\s+/i, '')
        .replace(/\s+owe me\??/i, '')
        .replace(/\?/g, '')
        .trim() || query
      const data = await fetchSettlementByName(cleaned)
      setAnswer(data)
    } catch (ex) {
      setErr(ex.message || 'Could not answer')
      if (ex.data?.candidates) {
        setErr('Ambiguous — try a more specific name')
      }
    } finally {
      setLoading(false)
    }
  }

  const contacts = summary?.contacts || []
  const top = [...contacts]
    .sort((a, b) => Math.abs(b.net || 0) - Math.abs(a.net || 0))
    .slice(0, 5)

  return (
    <>
      <OnboardingCard onboarding={onboarding} />

      <div className="card">
        <h2>Ask about balances</h2>
        <p className="muted">e.g. “How much does Highnes owe me?”</p>
        <form className="nl-form" onSubmit={ask}>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Who owes whom?"
            aria-label="Settlement question"
          />
          <button className="btn primary" type="submit" disabled={loading}>
            {loading ? '…' : 'Ask'}
          </button>
        </form>
        {err ? <div className="error-banner" style={{ marginTop: 12 }}>{err}</div> : null}
        {answer?.answer ? (
          <div className="nl-answer">
            {answer.answer}
            <div className="muted" style={{ marginTop: 8 }}>
              Net {money(answer.net)} · ledger {money(answer.ledger_net)} ·
              open shared {money(answer.virtual_shared_net)}
            </div>
          </div>
        ) : null}
      </div>

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0 }}>Who owes whom</h2>
          <button type="button" className="btn" onClick={onOpenPeople}>People →</button>
        </div>
        {top.length === 0 ? (
          <div className="empty-state">
            <strong>No open person balances</strong>
            Import a statement and use People / khata in the classic UI.
          </div>
        ) : (
          <ul className="people-list" style={{ marginTop: 12 }}>
            {top.map((c) => (
              <li key={c.contact_id} className="people-row">
                <span>{c.contact_name}</span>
                <span className={c.net >= 0 ? 'credit' : 'debit'}>
                  {c.net >= 0 ? `owes you ${money(c.net)}` : `you owe ${money(c.net)}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  )
}

function PeopleView({ summary, loading }) {
  const contacts = summary?.contacts || []
  if (loading) return <div className="card muted">Loading…</div>
  if (!contacts.length) {
    return (
      <div className="card empty-state">
        <strong>No people yet</strong>
        Add contacts or import UPI activity, then merge fragments in the classic People tab.
        <div style={{ marginTop: 12 }}>
          <a className="btn primary" href="/#contacts">Open classic People</a>
        </div>
      </div>
    )
  }
  const sorted = [...contacts].sort(
    (a, b) => Math.abs(b.net || 0) - Math.abs(a.net || 0),
  )
  return (
    <div className="card">
      <h2>People ({sorted.length})</h2>
      <ul className="people-list">
        {sorted.map((c) => (
          <li key={c.contact_id} className="people-row">
            <div>
              <strong>{c.contact_name}</strong>
              <div className="muted">
                given {money(c.total_you_sent)} · received {money(c.total_they_sent)}
              </div>
            </div>
            <span className={c.net >= 0 ? 'credit' : 'debit'}>
              {c.net >= 0 ? `owes you ${money(c.net)}` : `you owe ${money(c.net)}`}
            </span>
          </li>
        ))}
      </ul>
      <p className="muted" style={{ marginTop: 12 }}>
        Merge, settle, and pass-through live in the{' '}
        <a href="/#contacts" style={{ color: 'var(--accent)' }}>classic People UI</a>.
      </p>
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState('home')
  const [summary, setSummary] = useState(null)
  const [onboarding, setOnboarding] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [sum, onb] = await Promise.all([
        fetchSettlementSummary(),
        fetchOnboarding(),
      ])
      setSummary(sum)
      setOnboarding(onb)
    } catch (ex) {
      setError(ex.message || 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>Expense Tracker</h1>
          <p>React shell · Home & People</p>
        </div>
        <div className="app-header-actions">
          <button type="button" className="btn" onClick={load}>Refresh</button>
          <a className="btn primary" href="/">Classic UI</a>
        </div>
      </header>

      <nav className="app-nav" aria-label="App sections">
        <button type="button" className={tab === 'home' ? 'active' : ''} onClick={() => setTab('home')}>
          Home
        </button>
        <button type="button" className={tab === 'people' ? 'active' : ''} onClick={() => setTab('people')}>
          People
        </button>
      </nav>

      <main className="app-main">
        {error ? <div className="error-banner">{error}</div> : null}
        {tab === 'home' ? (
          <HomeView
            summary={summary}
            onboarding={onboarding}
            onOpenPeople={() => setTab('people')}
          />
        ) : (
          <PeopleView summary={summary} loading={loading} />
        )}
      </main>

      <nav className="mobile-bottom-nav" aria-label="Mobile navigation">
        <button type="button" className={tab === 'home' ? 'active' : ''} onClick={() => setTab('home')}>
          Home
        </button>
        <button type="button" className={tab === 'people' ? 'active' : ''} onClick={() => setTab('people')}>
          People
        </button>
        <a className="btn" href="/#review" style={{ border: 'none', background: 'transparent', color: 'var(--muted)', fontSize: 11, fontWeight: 600, textDecoration: 'none', padding: '6px 4px' }}>
          Txns
        </a>
        <a className="btn" href="/" style={{ border: 'none', background: 'transparent', color: 'var(--muted)', fontSize: 11, fontWeight: 600, textDecoration: 'none', padding: '6px 4px' }}>
          Classic
        </a>
      </nav>
    </div>
  )
}
