<script >
  import { onMount } from 'svelte'
  import { api } from '../api'

  let account = null
  let loading = true

  async function loadAccount() {
    try {
      account = await api.account.get()
    } catch (e) {
      console.error('Failed to load account:', e)
    } finally {
      loading = false
    }
  }

  onMount(() => {
    loadAccount()
    const interval = setInterval(loadAccount, 60000)
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
  .card {
    background: white;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  }

  h3 {
    margin: 0 0 16px 0;
    font-size: 14px;
    color: #999;
    text-transform: uppercase;
    letter-spacing: 1px;
  }

  .stat {
    margin-bottom: 12px;
  }

  .stat-label {
    font-size: 12px;
    color: #999;
    margin-bottom: 4px;
  }

  .stat-value {
    font-size: 24px;
    font-weight: 600;
    color: #333;
  }

  .loading {
    color: #999;
  }
</style>

<div class="card">
  <h3>Account Balance</h3>
  {#if loading}
    <div class="loading">Loading...</div>
  {:else if account}
    <div class="stat">
      <div class="stat-label">Equity</div>
      <div class="stat-value">{formatCurrency(account.equity)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Buying Power</div>
      <div class="stat-value">{formatCurrency(account.buying_power)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Cash</div>
      <div class="stat-value">{formatCurrency(account.cash)}</div>
    </div>
  {/if}
</div>
