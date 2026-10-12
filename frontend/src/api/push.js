import { getJson, postJson } from './client'

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(base64)
  const outputArray = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return outputArray
}

export function isPushSupported() {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

export async function getPushSubscription() {
  if (!isPushSupported()) return null
  try {
    const reg = await navigator.serviceWorker.ready
    return await reg.pushManager.getSubscription()
  } catch {
    return null
  }
}

export async function subscribeUserToPush() {
  if (!isPushSupported()) {
    throw new Error('Push notifications are not supported on this browser.')
  }

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    throw new Error(
      permission === 'denied'
        ? 'Notifications are blocked in your browser settings.'
        : 'Notification permission was not granted.'
    )
  }

  const { public_key: vapidKey } = await getJson('/api/push/vapid-public-key')
  if (!vapidKey) {
    throw new Error('Server did not provide a VAPID public key.')
  }

  const reg = await navigator.serviceWorker.ready
  let sub = await reg.pushManager.getSubscription()
  if (!sub) {
    const applicationServerKey = urlBase64ToUint8Array(vapidKey)
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey,
    })
  }

  await postJson('/api/push/subscribe', sub.toJSON())
  return sub
}

export async function unsubscribeUserFromPush() {
  if (!isPushSupported()) return false
  try {
    const reg = await navigator.serviceWorker.ready
    const sub = await reg.pushManager.getSubscription()
    if (sub) {
      await postJson('/api/push/unsubscribe', { endpoint: sub.endpoint }).catch(() => {})
      await sub.unsubscribe()
    }
    return true
  } catch {
    return false
  }
}

export async function sendTestNotification() {
  return postJson('/api/push/test', {})
}
