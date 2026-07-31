import { useEffect, useState } from 'react'

import Search from './Search'

const API_URL = import.meta.env.VITE_API_URL ?? '/api'

export default function App() {
  const [health, setHealth] = useState<string>('checking…')

  useEffect(() => {
    // /health lives at the root (not under /api) — probe endpoint
    fetch('/health')
      .then((r) => r.json())
      .then((d) => setHealth(`${d.status} (v${d.version})`))
      .catch(() => setHealth('backend unreachable'))
  }, [])

  return (
    <main style={{ fontFamily: 'system-ui', padding: '4rem', maxWidth: 640 }}>
      <h1>Core Platform</h1>
      <p>Enterprise middleware for Zoho — sales, delivery & analytics.</p>
      <p>
        Backend health: <strong>{health}</strong>
      </p>
      <p>
        API base: <code>{API_URL}</code>
      </p>
      <Search />
    </main>
  )
}
