/** One HTTP owner. Session cookie on same origin; optional Bearer / hub key. */

import { hubKey, isSnapshotHost } from './mode'

function headers(extra = {}) {
  const out = { Accept: 'application/json', ...extra }
  const token = localStorage.getItem('expense_token')
  if (token) out.Authorization = `Bearer ${token}`
  const hub = hubKey()
  if (hub) {
    out['X-Sync-Key'] = hub
    if (!out.Authorization) out.Authorization = `Bearer ${hub}`
  }
  return out
}

async function request(path, opts = {}) {
  const { timeoutMs = 20000, headers: extraHeaders, ...rest } = opts
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  let res
  try {
    res = await fetch(path, {
      credentials: 'same-origin',
      ...rest,
      signal: ctrl.signal,
      headers: headers(extraHeaders),
    })
  } catch (ex) {
    if (ex && ex.name === 'AbortError') throw new Error('Ask timed out. Try a shorter question.')
    throw ex
  } finally {
    clearTimeout(timer)
  }
  if (res.status === 401 || res.redirected) {
    if (isSnapshotHost()) {
      throw new Error('Open the pairing link from the PC (the /app/?key=… URL).')
    }
    window.location.href = '/login?next=/app/'
    throw new Error('Unauthorized')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data.error || data.reply || res.statusText || 'Request failed')
    err.status = res.status
    err.data = data
    throw err
  }
  return data
}

export function getJson(path) {
  return request(path)
}

export function postJson(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  })
}

export function fetchDashboardSummary(params = {}) {
  const q = new URLSearchParams()
  if (params.start_date) q.set('start_date', params.start_date)
  if (params.end_date) q.set('end_date', params.end_date)
  if (params.exclude_business === false) q.set('exclude_business', '0')
  const suffix = q.toString() ? `?${q}` : ''
  return getJson(`/api/dashboard/summary${suffix}`)
}

export function fetchSettlementSummary() {
  return getJson('/api/settlement/summary')
}

export function fetchMeta() {
  return getJson('/api/meta')
}

export function fetchHealth() {
  return getJson('/api/health')
}

export function addManual(payload) {
  return postJson('/api/manual', payload)
}

export function assistantChat(message, history = []) {
  return postJson('/api/assistant/chat', { message, history })
}

export function assistantConfirm(confirm_token) {
  return postJson('/api/assistant/confirm', { confirm_token })
}

export function money(n) {
  const v = Number(n) || 0
  return '₹' + Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })
}
