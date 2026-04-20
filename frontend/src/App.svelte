<script>
  import { onMount } from 'svelte'
  import AccountBalance from './lib/components/AccountBalance.svelte'
  import StrategyCard from './lib/components/StrategyCard.svelte'
  import EquityCurveChart from './lib/components/EquityCurveChart.svelte'
  import LivePositionsPanel from './lib/components/LivePositionsPanel.svelte'
  import PnlTable from './lib/components/PnlTable.svelte'

  let strategies = []
  let loading = true
  let error = ''
  let selectedSymbol = 'SPY'

  onMount(async () => {
    try {
      const res = await fetch('/api/v1/strategies')
      if (!res.ok) throw new Error('Failed to load strategies')
      strategies = await res.json()
      if (strategies.length > 0) {
        selectedSymbol = strategies[0].symbol
      }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Unknown error'
    } finally {
      loading = false
    }
  })
</script>

<style>
  :global(body) {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    margin: 0;
    padding: 16px;
    background: #f5f5f5;
  }

  .container {
    max-width: 1400px;
    margin: 0 auto;
  }

  .header {
    margin-bottom: 32px;
  }

  .header h1 {
    margin: 0 0 8px 0;
    font-size: 32px;
    color: #333;
  }

  .header p {
    margin: 0;
    color: #666;
  }

  .error {
    background: #fee;
    color: #c33;
    padding: 16px;
    border-radius: 4px;
    margin-bottom: 16px;
  }

  .loading {
    text-align: center;
    padding: 32px;
    color: #666;
  }

  .dashboard {
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .top-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }

  .strategies-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px;
  }

  .chart-section {
    background: white;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }

  .chart-section h2 {
    margin: 0 0 16px 0;
    font-size: 18px;
    color: #333;
  }

  @media (max-width: 768px) {
    .top-row {
      grid-template-columns: 1fr;
    }
  }
</style>

<div class="container">
  <div class="header">
    <h1>Trading Dashboard</h1>
    <p>Live trading with SPY, QQQ, IWM</p>
  </div>

  {#if error}
    <div class="error">Error: {error}</div>
  {/if}

  {#if loading}
    <div class="loading">Loading...</div>
  {:else}
    <div class="dashboard">
      <div class="top-row">
        <AccountBalance />
        <div style="background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
          <h3 style="margin: 0 0 16px 0;">Next Trade Execution</h3>
          <p style="margin: 0 0 8px 0; color: #666;">Monday 9:35 AM ET</p>
          <p style="margin: 0; font-size: 12px; color: #999;">Market opens at 9:30 AM ET</p>
        </div>
      </div>

      <div>
        <h2 style="margin: 0 0 16px 0; color: #333;">Strategies</h2>
        <div class="strategies-row">
          {#each strategies as strategy (strategy.id)}
            <StrategyCard {strategy} onClick={() => selectedSymbol = strategy.symbol} />
          {/each}
        </div>
      </div>

      {#if selectedSymbol}
        <div class="chart-section">
          <h2>Equity Curve - {selectedSymbol}</h2>
          <EquityCurveChart symbol={selectedSymbol} />
        </div>
      {/if}

      <div class="chart-section">
        <h2>Live Positions</h2>
        <LivePositionsPanel />
      </div>

      <div class="chart-section">
        <h2>P&L Summary</h2>
        <PnlTable />
      </div>
    </div>
  {/if}
</div>
