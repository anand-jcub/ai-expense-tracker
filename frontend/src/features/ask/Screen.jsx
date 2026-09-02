import { useEffect, useRef, useState } from 'react'
import { assistantChat, assistantConfirm } from '../../api/client'

function FormattedMessage({ text }) {
  if (!text) return null
  // Clean any legacy UTF-8 mojibake (â‚¹ -> ₹)
  const clean = text.replace(/â‚¹/g, '₹').replace(/\u00e2\u201a\u00b9/g, '₹')
  const lines = clean.split('\n')
  const blocks = []
  let currentList = []

  const renderInline = (str) => {
    const parts = str.split(/(\*\*.*?\*\*)/g)
    return parts.map((part, idx) => {
      if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
        return <strong key={idx}>{part.slice(2, -2)}</strong>
      }
      return part
    })
  }

  const flushList = () => {
    if (currentList.length > 0) {
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="ask-list">
          {currentList.map((item, liIdx) => (
            <li key={liIdx}>{renderInline(item)}</li>
          ))}
        </ul>,
      )
      currentList = []
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim()
    if (!line) {
      flushList()
      continue
    }
    const listMatch = line.match(/^[*•-]\s+(.*)$/) || line.match(/^\d+\.\s+(.*)$/)
    if (listMatch) {
      currentList.push(listMatch[1])
    } else {
      flushList()
      blocks.push(
        <p key={`p-${blocks.length}`} className="ask-p">
          {renderInline(line)}
        </p>,
      )
    }
  }
  flushList()

  return <div className="ask-text-block">{blocks}</div>
}

export default function AskScreen({
  messages: propMessages,
  setMessages: propSetMessages,
  askPrompt,
  clearAskPrompt,
  onNewChat,
  onRefresh,
}) {
  const [input, setInput] = useState('')
  const [localMessages, setLocalMessages] = useState([])
  const messages = propMessages ?? localMessages
  const setMessages = propSetMessages ?? setLocalMessages
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [messages, busy])

  useEffect(() => {
    if (askPrompt && !busy) {
      const p = askPrompt
      if (clearAskPrompt) clearAskPrompt()
      send(p)
    }
  }, [askPrompt])

  const send = async (text) => {
    const message = (text ?? input).trim()
    if (!message || busy) return
    setInput('')
    const history = messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({ role: m.role === 'assistant' ? 'model' : 'user', text: m.text }))
    setMessages((prev) => [...prev, { role: 'user', text: message }])
    setBusy(true)
    try {
      const data = await assistantChat(message, history)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: data.reply || '',
          cards: data.cards || [],
          model: data.model || '',
          live: true,
        },
      ])
    } catch (ex) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: ex.message || 'Ask failed', cards: [] },
      ])
    } finally {
      setBusy(false)
    }
  }

  const confirm = async (msgIdx, cardIdx, token) => {
    if (!token) return
    setBusy(true)
    try {
      const data = await assistantConfirm(token)
      setMessages((prev) =>
        prev.map((m, i) => {
          if (i !== msgIdx) return m
          const remainingCards = (m.cards || []).filter((_, ci) => ci !== cardIdx)
          const replyText = data.ok ? (data.reply || 'Saved.') : (data.error || 'Confirm failed')
          return {
            ...m,
            text: m.text ? `${m.text}\n\n✓ ${replyText}` : `✓ ${replyText}`,
            cards: remainingCards,
            live: remainingCards.length > 0,
          }
        }),
      )
      if (data.ok && onRefresh) onRefresh()
    } catch (ex) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: ex.message || 'Confirm failed', cards: [] },
      ])
    } finally {
      setBusy(false)
    }
  }

  const last = messages.length - 1

  return (
    <div className="ask">
      <div className="ask-thread">
        {messages.length === 0 ? (
          <div className="ask-empty-hero">
            <p className="muted ask-hint">Ask anything about your expenses, bank transactions, or balances.</p>
            <div className="ask-chips">
              <button type="button" className="ask-chip" onClick={() => send('Review pending statement transactions')}>
                ⚡ Review pending statement
              </button>
              <button type="button" className="ask-chip" onClick={() => send('How much did Highnes send me on July?')}>
                Highnes transfers in July
              </button>
              <button type="button" className="ask-chip" onClick={() => send('What did I spend on food this month?')}>
                Food spend this month
              </button>
              <button type="button" className="ask-chip" onClick={() => send('Who owes me money?')}>
                Who owes me?
              </button>
            </div>
          </div>
        ) : null}
        {messages.map((m, i) => (
          <div key={i} className={`ask-msg ${m.role}`}>
            <FormattedMessage text={m.text} />
            {m.cards?.map((card, ci) => (
              <div key={ci} className={`confirm-card ${m.live && i === last ? '' : 'disabled'}`}>
                <p>{card.message || card.title}</p>
                {m.live && i === last && card.confirm_token ? (
                  <div className="confirm-actions">
                    <button
                      type="button"
                      className="btn primary"
                      disabled={busy}
                      onClick={() => confirm(i, ci, card.confirm_token)}
                    >
                      Confirm
                    </button>
                    <button
                      type="button"
                      className="btn"
                      onClick={() =>
                        setMessages((prev) =>
                          prev.map((x, xi) =>
                            xi === i
                              ? {
                                  ...x,
                                  cards: (x.cards || []).filter((_, cIndex) => cIndex !== ci),
                                  live: (x.cards || []).length > 1,
                                }
                              : x,
                          ),
                        )
                      }
                    >
                      Dismiss
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
            {m.model && m.role === 'assistant' ? <span className="ask-model-pill">{m.model}</span> : null}
          </div>
        ))}
        {busy ? (
          <div className="ask-typing-dots">
            <span />
            <span />
            <span />
          </div>
        ) : null}
        <div ref={endRef} />
      </div>
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask…"
          aria-label="Ask"
          enterKeyHint="send"
          disabled={busy}
        />
        <button className="btn primary" type="submit" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}

