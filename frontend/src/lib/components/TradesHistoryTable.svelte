<script>
  import { onMount } from 'svelte'

  let liveTrades = []
  let backtestTrades = []
  let loading = true
  let error = ''
  let filterType = 'all'
  let selectedTicker = 'All'
  let allTickers = []

  onMount(async () => {
    try {
      const liveRes = await fetch('/api/v1/trades/live')
      if (!liveRes.ok) throw new Error('Failed to load live trades')
      const liveData = await liveRes.json()
      liveTrades = liveData.filter(t => t.status === 'closed').sort((a, b) => new Date(b.exit_at) - new Date(a.exit_at))

      const backtestRes = await fetch('/api/v1/trades/backtest')
      if (backtestRes.ok) {
        const backtestData = await backtestRes.json()
        backtestTrades = backtestData.sort((a, b) => new Date(b.exit_at) - new Date(a.exit_at))
      }

      // Get unique tickers
      const allTrades = [...liveTrades, ...backtestTrades]
      allTickers = ['All', ...new Set(allTrades.map(t => t.symbol))].sort()
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load trades'
    } finally {
      loading = false
    }
  })

  $: allDisplayTrades = filterType === 'all' ? [...backtestTrades, ...liveTrades] :
                        filterType === 'backtest' ? backtestTrades :
                        liveTrades

  $: filteredByTicker = selectedTicker === 'All'
    ? allDisplayTrades
    : allDisplayTrades.filter(t => t.symbol === selectedTicker)

  $: displayTrades = filteredByTicker.sort((a, b) => new Date(b.exit_at) - new Date(a.exit_at))

  $: tradesWithRunningTotal = (() => {
    // Calculate running total chronologically (oldest to newest)
    const chronological = [...displayTrades].reverse()
    const withRunning = chronological.map((trade, idx) => ({
      ...trade,
      runningTotal: chronological.slice(0, idx + 1).reduce((sum, t) => sum + (t.pnl_dollar || 0), 0)
    }))
    // Return in reverse order (newest to oldest) for display
    return withRunning.reverse()
  })()

  function formatDate(dateStr) {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  function formatPrice(price) {
    return typeof price === 'number' ? price.toFixed(2) : '-'
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

  .running-total {
    font-weight: 600;
  }

  .running-total.positive {
    color: #22c55e;
  }

  .running-total.negative {
    color: #ef4444;
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
        Backtest ({backtestTrades.length})
      </button>
      <button class="filter-btn" class:active={filterType === 'live'} on:click={() => filterType = 'live'}>
        Live ({liveTrades.length})
      </button>
    </div>

    <div class="ticker-selector">
      <label for="ticker-select">Ticker:</label>
      <select id="ticker-select" class="ticker-select" bind:value={selectedTicker}>
        {#each allTickers as ticker}
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
              <th>Side</th>
              <th>Qty</th>
              <th>Entry Price</th>
              <th>Exit Price</th>
              <th>Entry Date</th>
              <th>Exit Date</th>
              <th>P&L $</th>
              <th>P&L %</th>
              <th>Running Total</th>
            </tr>
          </thead>
          <tbody>
            {#each tradesWithRunningTotal as trade (trade.id || Math.random())}
              <tr>
                <td>
                  <span class="trade-type-badge" class:trade-type-backtest={!trade.status} class:trade-type-live={trade.status}>
                    {trade.status ? 'Live' : 'Backtest'}
                  </span>
                </td>
                <td><span class="symbol">{trade.symbol}</span></td>
                <td>{trade.side || '-'}</td>
                <td>{trade.quantity || '-'}</td>
                <td>${formatPrice(trade.entry_price)}</td>
                <td>${formatPrice(trade.exit_price)}</td>
                <td>{formatDate(trade.entry_at)}</td>
                <td>{formatDate(trade.exit_at)}</td>
                <td class={trade.pnl_dollar > 0 ? 'pnl-positive' : 'pnl-negative'}>
                  ${formatPrice(trade.pnl_dollar)}
                </td>
                <td class={trade.pnl_pct > 0 ? 'pnl-positive' : 'pnl-negative'}>
                  {(trade.pnl_pct * 100).toFixed(2)}%
                </td>
                <td class="running-total" class:positive={trade.runningTotal > 0} class:negative={trade.runningTotal < 0}>
                  ${formatPrice(trade.runningTotal)}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/if}
</div>
