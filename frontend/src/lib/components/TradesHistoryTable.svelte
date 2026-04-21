<script>
  import { onMount } from 'svelte'

  let trades = []
  let loading = true
  let error = ''

  onMount(async () => {
    try {
      const res = await fetch('/api/v1/trades/live')
      if (!res.ok) throw new Error('Failed to load trades')
      const data = await res.json()
      trades = data.filter(t => t.status === 'closed').sort((a, b) => new Date(b.exit_at) - new Date(a.exit_at))
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load trades'
    } finally {
      loading = false
    }
  })

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
</style>

<div>
  {#if error}
    <div class="error">{error}</div>
  {/if}

  {#if loading}
    <div class="loading">Loading trades...</div>
  {:else if trades.length === 0}
    <div class="no-trades">No closed trades yet</div>
  {:else}
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Side</th>
            <th>Qty</th>
            <th>Entry Price</th>
            <th>Exit Price</th>
            <th>Entry Date</th>
            <th>Exit Date</th>
            <th>P&L $</th>
            <th>P&L %</th>
            <th>Signal</th>
          </tr>
        </thead>
        <tbody>
          {#each trades as trade (trade.id)}
            <tr>
              <td><span class="symbol">{trade.symbol}</span></td>
              <td>{trade.side}</td>
              <td>{trade.quantity}</td>
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
              <td>{trade.strategy_signal || '-'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
