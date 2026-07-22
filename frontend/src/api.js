/** Thin fetch helpers — cookies/session from the Python server. */

async function getJson(path) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
  if (res.status === 401 || res.redirected) {
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data.error || res.statusText || 'Request failed')
    err.status = res.status
    err.data = data
    throw err
  }
  return data
}

export function fetchSettlementSummary() {
  return getJson('/api/settlement/summary')
}

export function fetchSettlementByName(q) {
  return getJson('/api/settlement/by-name?q=' + encodeURIComponent(q))
}

export function fetchSettlement(contactId) {
  return getJson('/api/settlement?contact_id=' + encodeURIComponent(contactId))
}

export function fetchOnboarding() {
  return getJson('/api/onboarding')
}

export function money(n) {
  const v = Number(n) || 0
  return '₹' + Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })
}
