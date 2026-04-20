<script >
  import { onMount } from 'svelte'
  import { api } from '../api'

  let positions = []
  let loading = true

  async function loadPositions() {
    try {
      const account = await api.account.positions()
      positions = account
    } catch (e) {
      console.error('Failed to load positions:', e)
    } finally {
      loading = false
    }
  }

  onMount(() => {
    loadPositions()
    const interval = setInterval(loadPositions, 60000)
    return () => clearInterval(interval)
  })

  function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value)
  }

  function formatPercent(value) {
    return ((value / 100) * 100).toFixed(2) + '%'
  }
</script>

<style>
  table {
    width: 100%;
    border-collapse: collapse;
  }

  th {
    text-align: left;
    padding: 8px;
    border-bottom: 2px solid #eee;
    font-size: 12px;
    color: #999;
    font-weight: 600;
    text-transform: uppercase;
  }

  td {
    padding: 12px 8px;
    border-bottom: 1px solid #eee;
  }

  .symbol {
    font-weight: 600;
    color: #333;
  }

  .pnl-positive {
    color: #2e7d32;
  }

  .pnl-negative {
    color: #d32f2f;
  }

  .empty {
    text-align: center;
    padding: 32px;
    color: #999;
  }
</style>

{#if loading}
  <p style="text-align: center; color: #999;">Loading...</p>
{:else if positions.length === 0}
  <div class="empty">No open positions</div>
{:else}
  <table>
    <thead>
      <tr>
        <th>Symbol</th>
        <th>Qty</th>
        <th>Entry Price</th>
        <th>Current Price</th>
        <th>Market Value</th>
        <th>Unrealized P&L</th>
      </tr>
    </thead>
    <tbody>
      {#each positions as position (position.symbol)}
        <tr>
          <td class="symbol">{position.symbol}</td>
          <td>{position.qty}</td>
          <td>{formatCurrency(position.avg_entry_price)}</td>
          <td>{formatCurrency(position.current_price)}</td>
          <td>{formatCurrency(position.market_value)}</td>
          <td class={position.unrealized_pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}>
            {formatCurrency(position.unrealized_pnl)}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
