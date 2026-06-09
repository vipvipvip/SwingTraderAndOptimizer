<script>
  import { onMount } from 'svelte'

  let liveTrades = []
  let backtestTrades = []
  let allTickerList = []
  let loading = true
  let error = ''
  let filterType = 'all'
  let selectedTicker = 'All'

  onMount(async () => {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 5000)

      const [liveRes, backtestRes] = await Promise.all([
        fetch('/api/v1/trades/live', { signal: controller.signal }),
        fetch('/api/v1/trades/backtest', { signal: controller.signal }),
      ])

      if (!liveRes.ok) throw new Error('Failed to load live trades')

      const liveData = await liveRes.json()
      liveTrades = liveData.sort((a, b) => {
        const aTime = a.entry_at ? new Date(a.entry_at) : new Date(0)
        const bTime = b.entry_at ? new Date(b.entry_at) : new Date(0)
        return bTime - aTime
      })

      if (backtestRes.ok) {
        const btData = await backtestRes.json()
        const btArray = Array.isArray(btData) ? btData : (btData.data ?? [])
        backtestTrades = btArray.sort((a, b) => new Date(b.exit_at) - new Date(a.exit_at))
      }

      const allTrades = [...liveTrades, ...backtestTrades]
      allTickerList = ['All', ...new Set(allTrades.map(t => t.symbol))].sort()
      clearTimeout(timeoutId)
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load trades'
    } finally {
      loading = false
    }
  })

  $: filteredBacktest = selectedTicker === 'All'
    ? backtestTrades
    : backtestTrades.filter(t => t.symbol === selectedTicker)

  $: filteredLive = selectedTicker === 'All'
    ? liveTrades
    : liveTrades.filter(t => t.symbol === selectedTicker)

  $: displayTrades = (() => {
    const pool = filterType === 'all' ? [...filteredBacktest, ...filteredLive]
      : filterType === 'backtest' ? filteredBacktest
      : filteredLive
    return pool.sort((a, b) => {
      const aTime = a.exit_at || a.entry_at
      const bTime = b.exit_at || b.entry_at
      return new Date(bTime) - new Date(aTime)
    })
  })()

  function formatDate(dateStr) {
    if (!dateStr) return '-'
    const date = new Date(dateStr)
    const mm = String(date.getMonth() + 1).padStart(2, '0')
    const dd = String(date.getDate()).padStart(2, '0')
    const yy = String(date.getFullYear()).slice(-2)
    const hh = String(date.getHours()).padStart(2, '0')
    const mi = String(date.getMinutes()).padStart(2, '0')
    return `${mm}/${dd}/${yy} ${hh}:${mi}`
  }

  function formatPrice(price) {
    if (price == null) return '-'
    const num = typeof price === 'number' ? price : parseFloat(price)
    return isNaN(num) ? '-' : num.toFixed(2)
  }

  function getPnlColor(pnl) {
    if (!pnl) return '#666'
    return pnl > 0 ? '#22c55e' : '#ef4444'
  }

  function getTradeType(trade) {
    return trade.status ? 'live' : 'backtest'
  }
</script>

<style>
  .table-container {
    overflow-x: auto;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }

  thead {
    background: #f9fafb;
    border-bottom: 1px solid #e5e7eb;
  }

  th {
    padding: 12px 16px;
    text-align: left;
    font-weight: 600;
    color: #374151;
  }

  td {
    padding: 12px 16px;
    border-bottom: 1px solid #e5e7eb;
    color: #374151;
  }

  tbody tr:hover {
    background: #f9fafb;
  }

  .symbol {
    font-weight: 600;
    color: #1f2937;
  }

  .pnl-positive {
    color: #22c55e;
    font-weight: 600;
  }

  .pnl-negative {
    color: #ef4444;
    font-weight: 600;
  }

  .status-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
  }

  .status-closed {
    background: #dbeafe;
    color: #1e40af;
  }

  .status-open {
    background: #fef3c7;
    color: #92400e;
  }

  .trade-type-open {
    background: #fef3c7;
    color: #92400e;
  }

  .no-trades {
    text-align: center;
    padding: 40px;
    color: #999;
  }

  .error {
    color: #ef4444;
    padding: 16px;
    background: #fee;
    border-radius: 4px;
    margin-bottom: 16px;
  }

  .loading {
    text-align: center;
    padding: 32px;
    color: #666;
  }

  .filter-controls {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
  }

  .filter-btn {
    padding: 6px 12px;
    border: 1px solid #d1d5db;
    background: white;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    transition: all 0.2s;
  }

  .filter-btn:hover {
    border-color: #9ca3af;
  }

  .filter-btn.active {
    background: #3b82f6;
    color: white;
    border-color: #3b82f6;
  }

  .trade-type-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .trade-type-backtest {
    background: #f3e8ff;
    color: #6d28d9;
  }

  .trade-type-live {
    background: #dcfce7;
    color: #166534;
  }

  .ticker-selector {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }

  .ticker-selector label {
    font-weight: 600;
    color: #374151;
    font-size: 14px;
  }

  .ticker-select {
    padding: 8px 12px;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    background: white;
    font-size: 14px;
    cursor: pointer;
    min-width: 150px;
  }

  .ticker-select:hover {
    border-color: #9ca3af;
  }

  .ticker-select:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  .portfolio-value {
    font-weight: 600;
    color: #3b82f6;
  }

  .simulated-note {
    margin-top: 8px;
    font-size: 12px;
    color: #9ca3af;
    font-style: italic;
  }
</style>

<div>
  {#if error}
    <div class="error">{error}</div>
  {/if}

  {#if loading}
    <div class="loading">Loading trades...</div>
  {:else}
    <div class="filter-controls">
      <button class="filter-btn" class:active={filterType === 'all'} on:click={() => filterType = 'all'}>
        All ({backtestTrades.length + liveTrades.length})
      </button>
      <button class="filter-btn" class:active={filterType === 'backtest'} on:click={() => filterType = 'backtest'}>
        Backtest ({filteredBacktest.length})
      </button>
      <button class="filter-btn" class:active={filterType === 'live'} on:click={() => filterType = 'live'}>
        Live ({filteredLive.length})
      </button>
    </div>

    <div class="ticker-selector">
      <label for="ticker-select">Ticker:</label>
      <select id="ticker-select" class="ticker-select" bind:value={selectedTicker}>
        {#each allTickerList as ticker}
          <option value={ticker}>{ticker}</option>
        {/each}
      </select>
    </div>

    {#if displayTrades.length === 0}
      <div class="no-trades">No trades yet</div>
    {:else}
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Symbol</th>
              <th>Allocation</th>
              <th>Entry Price</th>
              <th>Exit Price</th>
              <th>Entry Date</th>
              <th>Exit Date</th>
              <th>P&L $</th>
              <th>P&L %</th>
              <th>Portfolio Value</th>
            </tr>
          </thead>
          <tbody>
            {#each displayTrades as trade (trade.id || trade.symbol + trade.entry_at + (trade.exit_at || ''))}
              <tr>
                <td>
                  <span class="trade-type-badge" class:trade-type-live={trade.status === 'closed'} class:trade-type-open={trade.status === 'open'}>
                    {trade.status === 'open' ? 'Open' : trade.status === 'closed' ? 'Live' : 'Backtest'}
                  </span>
                </td>
                <td><span class="symbol">{trade.symbol}</span></td>
                <td>{trade.allocation_weight ? trade.source_symbol + ' ' + trade.allocation_weight + '%' : (trade.quantity || '-')}</td>
                <td>${formatPrice(trade.entry_price)}</td>
                <td>${trade.exit_price ? formatPrice(trade.exit_price) : '-'}</td>
                <td>{formatDate(trade.entry_at)}</td>
                <td>{formatDate(trade.exit_at)}{!trade.exit_at ? ' *' : ''}{trade.simulated_close ? ' *' : ''}</td>
                <td class={trade.pnl_dollar > 0 ? 'pnl-positive' : 'pnl-negative'}>
                  {trade.pnl_dollar != null ? `$${formatPrice(trade.pnl_dollar)}` : '-'}
                </td>
                <td class={(trade.pnl_pct ?? trade.return) > 0 ? 'pnl-positive' : 'pnl-negative'}>
                  {(trade.pnl_pct ?? trade.return) != null ? `${((trade.pnl_pct ?? trade.return) * 100).toFixed(2)}%` : '-'}
                </td>
                <td class="portfolio-value">
                  ${formatPrice(trade.portfolio_value)}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if displayTrades.some(t => t.simulated_close || !t.exit_at)}
        <div class="simulated-note">* position still open</div>
      {/if}
    {/if}
  {/if}
</div>
