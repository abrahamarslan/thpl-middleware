import { useEffect, useRef, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL ?? '/api'
const DEBOUNCE_MS = 200

type Hit = {
  id: number
  name?: string | null
  email?: string | null
  address_city?: string | null
  address_state?: string | null
  address_country?: string | null
  [key: string]: unknown
}

/**
 * Acquire a bearer token for search calls.
 * Order: localStorage (a real login flow can stash one) -> DEBUG-only
 * /auth/dev-token mint (development stacks run with DEBUG=true).
 */
async function getToken(): Promise<string | null> {
  const stored = localStorage.getItem('access_token')
  if (stored) return stored
  try {
    const r = await fetch(`${API_URL}/auth/dev-token`, { method: 'POST' })
    if (!r.ok) return null
    const body = await r.json()
    const token: string | undefined = body?.data?.access_token
    if (token) localStorage.setItem('access_token', token)
    return token ?? null
  } catch {
    return null
  }
}

/**
 * Search-as-you-type against /api/search/{index}.
 * Meilisearch ranks; the backend hydrates fresh rows from Postgres —
 * the CDC pipeline keeps the index ~1-3s behind writes.
 */
export default function Search({ index = 'zoho_organizations' }: { index?: string }) {
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<Hit[]>([])
  const [status, setStatus] = useState<'idle' | 'searching' | 'error' | 'unauthorized'>('idle')
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const timer = setTimeout(async () => {
      abortRef.current?.abort()
      if (!query.trim()) {
        setHits([])
        setStatus('idle')
        return
      }
      const controller = new AbortController()
      abortRef.current = controller
      setStatus('searching')

      const token = await getToken()
      if (!token) {
        setStatus('unauthorized')
        return
      }
      try {
        const r = await fetch(
          `${API_URL}/search/${index}?q=${encodeURIComponent(query)}&limit=10`,
          { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal },
        )
        if (r.status === 401) {
          // Stale token — drop it; the next keystroke re-mints.
          localStorage.removeItem('access_token')
          setStatus('unauthorized')
          return
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const body = await r.json()
        setHits(body?.data?.hits ?? [])
        setStatus('idle')
      } catch (err) {
        if ((err as Error).name !== 'AbortError') setStatus('error')
      }
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [query, index])

  return (
    <section style={{ marginTop: '2rem' }}>
      <h2 style={{ fontSize: '1.1rem' }}>Search organizations</h2>
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Type to search… (name, city, email)"
        style={{
          width: '100%',
          padding: '0.6rem 0.8rem',
          fontSize: '1rem',
          border: '1px solid #ccc',
          borderRadius: 6,
        }}
      />
      {status === 'searching' && <p style={{ color: '#888' }}>Searching…</p>}
      {status === 'error' && <p style={{ color: '#c00' }}>Search failed — is the backend up?</p>}
      {status === 'unauthorized' && (
        <p style={{ color: '#c60' }}>
          No auth token available. Log in, or run the stack in development (DEBUG=true) for
          automatic dev tokens.
        </p>
      )}
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {hits.map((h) => (
          <li
            key={h.id}
            style={{ padding: '0.5rem 0', borderBottom: '1px solid #eee', lineHeight: 1.4 }}
          >
            <strong>{h.name ?? `#${h.id}`}</strong>
            <br />
            <small style={{ color: '#666' }}>
              {[h.address_city, h.address_state, h.address_country].filter(Boolean).join(', ') ||
                h.email ||
                '—'}
            </small>
          </li>
        ))}
        {status === 'idle' && query.trim() && hits.length === 0 && (
          <li style={{ color: '#888', padding: '0.5rem 0' }}>No results.</li>
        )}
      </ul>
    </section>
  )
}
