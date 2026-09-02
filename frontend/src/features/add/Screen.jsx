import { useEffect, useState } from 'react'
import { addManual, fetchMeta } from '../../api/client'

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

export default function AddScreen({ onDone, snapshot, writes }) {
  const [meta, setMeta] = useState({ categories: [], expense_types: ['Personal'] })
  const [txn_date, setDate] = useState(todayIso)
  const [amount, setAmount] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('Food')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetchMeta()
      .then((m) => {
        setMeta(m)
        if (m.categories?.includes('Food')) setCategory('Food')
        else if (m.categories?.[0]) setCategory(m.categories[0])
      })
      .catch(() => {})
  }, [])

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setSaved(false)
    const n = Number(amount)
    if (!description.trim() || !n || n <= 0) {
      setError('Amount and what it was for.')
      return
    }
    setBusy(true)
    try {
      await addManual({
        txn_date,
        amount: n,
        description: description.trim(),
        category,
        expense_type: 'Personal',
        direction: 'debit',
      })
      setSaved(true)
      setAmount('')
      setDescription('')
      if (onDone) onDone()
    } catch (ex) {
      setError(ex.message || 'Could not save')
    } finally {
      setBusy(false)
    }
  }

  if (writes === null) {
    return <p className="muted">…</p>
  }

  return (
    <form className="add-form" onSubmit={submit}>
      <label>
        <span className="muted">Amount</span>
        <input
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="0"
          autoFocus
        />
      </label>
      <label>
        <span className="muted">What</span>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Coffee"
        />
      </label>
      <div className="add-row">
        <label>
          <span className="muted">Date</span>
          <input type="date" value={txn_date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          <span className="muted">Category</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {(meta.categories || []).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error ? <p className="error-banner">{error}</p> : null}
      {saved ? <p className="muted">Saved.</p> : null}
      <button className="btn primary" type="submit" disabled={busy}>
        {busy ? '…' : 'Save'}
      </button>
    </form>
  )
}
