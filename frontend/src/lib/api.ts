const BASE_URL = '/api/v1'

export async function apiFetch<T>(path: string, options?: RequestInit, timeout: number = 5000): Promise<T> {
  const url = `${BASE_URL}${path.startsWith('/') ? path : '/' + path}`
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  try {
    const res = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
      signal: controller.signal,
    })

    if (!res.ok) {
      const error = await res.text().catch(() => res.statusText)
      throw new Error(`${res.status}: ${error}`)
    }

    return res.json()
  } finally {
    clearTimeout(timeoutId)
  }
}

export const api = {
  account: {
    get: () => apiFetch('/account'),
    positions: () => apiFetch('/account/positions'),
  },
  strategies: {
    list: () => apiFetch('/strategies'),
    get: (symbol: string) => apiFetch(`/strategies/${symbol}`),
    history: (symbol: string) => apiFetch(`/strategies/${symbol}/history`),
  },
  equity: {
    curve: (symbol: string) => apiFetch(`/equity/${symbol}`),
  },
  trades: {
    list: () => apiFetch('/trades/live'),
    pnl: () => apiFetch('/trades/pnl'),
  },
}
