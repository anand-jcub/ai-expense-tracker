const KEY = 'expense_hub_key'

export function captureHubKey() {
  const q = new URLSearchParams(window.location.search)
  const key = (q.get('key') || '').trim()
  if (!key) return
  localStorage.setItem(KEY, key)
  q.delete('key')
  const rest = q.toString()
  const next = `${window.location.pathname}${rest ? `?${rest}` : ''}${window.location.hash}`
  window.history.replaceState({}, '', next)
}

export function hubKey() {
  return (localStorage.getItem(KEY) || '').trim()
}

export function isSnapshotHost() {
  return /\.workers\.dev$/i.test(window.location.hostname)
}
