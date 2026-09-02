import { useEffect, useState } from 'react'
import { fetchHealth } from './api/client'
import { isSnapshotHost } from './api/mode'
import { getFeature, navFeatures } from './features/registry'
import './App.css'

export default function App() {
  const nav = navFeatures()
  const [tab, setTab] = useState(nav[0]?.id || 'home')
  const [menu, setMenu] = useState(false)
  const [writes, setWrites] = useState(null)
  const [syncedAt, setSyncedAt] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [askMessages, setAskMessages] = useState(() => {
    try {
      const saved = sessionStorage.getItem('expense_ask_chat')
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })

  useEffect(() => {
    try {
      sessionStorage.setItem('expense_ask_chat', JSON.stringify(askMessages))
    } catch {}
  }, [askMessages])

  const [askPrompt, setAskPrompt] = useState(null)

  const handleAskReview = (period) => {
    if (period && period.start_date && period.end_date) {
      setAskPrompt(`Review pending transactions from ${period.start_date} to ${period.end_date}`)
    } else {
      setAskPrompt("Review pending statement transactions")
    }
    setTab('ask')
  }

  const handleNewAskChat = () => {
    setAskMessages([])
    setAskPrompt(null)
    try {
      sessionStorage.removeItem('expense_ask_chat')
    } catch {}
  }

  const feature = getFeature(tab)
  const Screen = feature.Screen
  const hub = isSnapshotHost()

  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return undefined
    const sync = () => {
      const kb = window.innerHeight - vv.height > 80
      document.documentElement.style.setProperty('--vv-height', `${vv.height}px`)
      document.body.classList.toggle('keyboard-open', kb)
    }
    sync()
    vv.addEventListener('resize', sync)
    vv.addEventListener('scroll', sync)
    return () => {
      vv.removeEventListener('resize', sync)
      vv.removeEventListener('scroll', sync)
      document.body.classList.remove('keyboard-open')
    }
  }, [])

  useEffect(() => {
    const load = () =>
      fetchHealth()
        .then((h) => {
          setWrites(typeof h.writes === 'boolean' ? h.writes : false)
          if (h.syncedAt) setSyncedAt(h.syncedAt)
        })
        .catch(() => setWrites(false))
    load()
    const id = setInterval(load, 20000)
    const onVis = () => {
      if (document.visibilityState === 'visible') load()
    }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  return (
    <div className={`app-shell tab-${tab}`}>
      <header className="app-header">
        <h1>Expenses</h1>
        <div className="app-header-actions">
          {tab === 'ask' ? (
            <button
              type="button"
              className="btn ghost icon-btn"
              aria-label="New chat"
              title="Start new chat"
              onClick={handleNewAskChat}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </button>
          ) : null}
          <button
            type="button"
            className="btn ghost"
            aria-label="More"
            onClick={() => setMenu((v) => !v)}
          >
            ···
          </button>
        </div>
      </header>

      {menu ? (
        <div className="overflow-menu">
          {hub ? (
            <>
              <span className="muted">
                {writes === true
                  ? 'Live'
                  : writes === false
                    ? `Last sync ${syncedAt ? syncedAt.slice(0, 16).replace('T', ' ') : ''}`
                    : '…'}
              </span>
              <button
                type="button"
                className="btn ghost"
                onClick={() => {
                  setRefreshKey((k) => k + 1)
                  setMenu(false)
                }}
              >
                Refresh
              </button>
            </>
          ) : (
            <>
              <a href="/">Classic</a>
              <a href="/logout">Sign out</a>
            </>
          )}
        </div>
      ) : null}

      <main className="app-main">
        {Screen ? (
          <Screen
            writes={writes}
            snapshot={writes === false}
            syncedAt={syncedAt}
            refreshKey={refreshKey}
            messages={askMessages}
            setMessages={setAskMessages}
            onNewChat={handleNewAskChat}
            askPrompt={askPrompt}
            clearAskPrompt={() => setAskPrompt(null)}
            onAsk={() => setTab('ask')}
            onAskReview={handleAskReview}
            onAdd={() => setTab('add')}
            onRefresh={() => setRefreshKey((k) => k + 1)}
            onDone={() => {
              setRefreshKey((k) => k + 1)
              setTab('home')
            }}
          />
        ) : null}
      </main>

      <nav className="mobile-bottom-nav" aria-label="Sections">
        {nav.map((f) => (
          <button
            key={f.id}
            type="button"
            className={tab === f.id ? 'active' : ''}
            onClick={() => setTab(f.id)}
          >
            {f.title}
          </button>
        ))}
      </nav>
    </div>
  )
}
