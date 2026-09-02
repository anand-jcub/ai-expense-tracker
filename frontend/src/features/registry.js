/**
 * Feature registry — only place nav is derived.
 * Later: implement Screen.jsx and set enabled: true (and nav if it earns a tab).
 */
import HomeScreen from './home/Screen.jsx'
import AskScreen from './ask/Screen.jsx'
import AddScreen from './add/Screen.jsx'

export const features = [
  { id: 'home', title: 'Home', nav: true, enabled: true, Screen: HomeScreen },
  { id: 'ask', title: 'Ask', nav: true, enabled: true, Screen: AskScreen },
  { id: 'add', title: 'Add', nav: true, enabled: true, Screen: AddScreen },
  { id: 'people', title: 'People', nav: false, enabled: false, Screen: null },
  { id: 'graphs', title: 'Graphs', nav: false, enabled: false, Screen: null },
  { id: 'ledger', title: 'Ledger', nav: false, enabled: false, Screen: null },
]

export function navFeatures() {
  return features.filter((f) => f.enabled && f.nav && f.Screen)
}

export function getFeature(id) {
  return features.find((f) => f.id === id && f.enabled && f.Screen) || navFeatures()[0]
}
