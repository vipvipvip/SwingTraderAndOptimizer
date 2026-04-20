<script >
  import { onMount } from 'svelte'
  import { api } from '../api'

  let pnl = null
  let loading = true

  async function loadPnl() {
    try {
      pnl = await api.trades.pnl()
    } catch (e) {
      console.error('Failed to load P&L:', e)
    } finally {
      loading = false
    }
  }

  onMount(() => {
    loadPnl()
    const interval = setInterval(loadPnl, 60000)
    return () => clearInterval(interval)
  })

  function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value)
  }
</script>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
  }

  .stat-box {
    background: #f9f9f9;
    padding: 16px;
    border-radius: 4px;
    text-align: center;
  }

  .label {
    font-size: 12px;
    color: #999;
    margin-bottom: 8px;
    text-transform: uppercase;
  }

  .value {
    font-size: 24px;
    font-weight: 600;
    color: #333;
  }

  .positive {
    color: #2e7d32;
  }

  .negative {
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
{:else if pnl}
  <div class="grid">
    <div class="stat-box">
      <div class="label">Total P&L</div>
      <div class="value" class:positive={pnl.total_pnl >= 0} class:negative={pnl.total_pnl < 0}>
        {formatCurrency(pnl.total_pnl)}
      </div>
    </div>
    <div class="stat-box">
      <div class="label">Win Rate</div>
      <div class="value">{pnl.win_rate.toFixed(1)}%</div>
    </div>
    <div class="stat-box">
      <div class="label">Closed Trades</div>
      <div class="value">{pnl.closed_trades}</div>
    </div>
    <div class="stat-box">
      <div class="label">Winning Trades</div>
      <div class="value">{pnl.winning_trades}</div>
    </div>
  </div>
{:else}
  <div class="empty">No trade data</div>
{/if}
