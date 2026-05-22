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
    const interval = setInterval(loadPnl, 300000)
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
      <div class="label">Unrealized P&L *</div>
      <div class="value" class:positive={(pnl.unrealized_pnl || 0) >= 0} class:negative={(pnl.unrealized_pnl || 0) < 0}>
        {formatCurrency(pnl.unrealized_pnl || 0)}
      </div>
      <small style="color: #999;">* positions open</small>
    </div>
    <div class="stat-box">
      <div class="label">Open Positions</div>
      <div class="value">{pnl.open_positions || 0}</div>
    </div>
    <div class="stat-box">
      <div class="label">Account Equity</div>
      <div class="value">{formatCurrency(pnl.account_equity || 0)}</div>
    </div>
    <div class="stat-box">
      <div class="label">Buying Power</div>
      <div class="value">{formatCurrency(pnl.buying_power || 0)}</div>
    </div>
  </div>
  <p style="text-align: center; color: #999; font-size: 12px; margin-top: 8px;">{pnl.note}</p>
{:else}
  <div class="empty">No trade data</div>
{/if}
