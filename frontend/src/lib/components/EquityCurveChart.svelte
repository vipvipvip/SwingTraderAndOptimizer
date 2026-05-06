<script>
  import { onMount } from 'svelte'
  import { api } from '../api'
  import { Chart, registerables } from 'chart.js'

  Chart.register(...registerables)

  export let symbol

  let canvas
  let chart = null
  let loading = true
  let hasData = false

  // Cache fetched data per symbol so switching is instant on revisit
  const cache = {}

  function buildChartData(data) {
    return {
      labels: [
        ...data.backtest.map((d) => new Date(d.date).toLocaleDateString()),
        ...data.live.map((d) => new Date(d.date).toLocaleDateString()),
      ],
      datasets: [
        {
          label: 'Backtest',
          data: data.backtest.map((d) => d.value),
          borderColor: '#ccc',
          borderDash: [5, 5],
          fill: false,
          tension: 0.1,
        },
        {
          label: 'Live',
          data: data.live.map((d) => d.value),
          borderColor: '#2e7d32',
          fill: false,
          tension: 0.1,
        },
      ],
    }
  }

  async function loadChart() {
    try {
      if (!cache[symbol]) {
        cache[symbol] = await api.equity.curve(symbol)
      }
      const data = cache[symbol]
      hasData = (data.backtest && data.backtest.length > 0) || (data.live && data.live.length > 0)

      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (!ctx || !hasData) return

      const chartData = buildChartData(data)

      if (chart) {
        // Update existing chart in-place — no flicker, no destroy/recreate
        chart.data.labels = chartData.labels
        chart.data.datasets[0].data = chartData.datasets[0].data
        chart.data.datasets[1].data = chartData.datasets[1].data
        chart.update('none')
      } else {
        chart = new Chart(ctx, {
          type: 'line',
          data: chartData,
          options: {
            responsive: true,
            maintainAspectRatio: true,
            animation: false,
            plugins: {
              legend: { display: true, position: 'top' },
            },
            scales: {
              y: {
                beginAtZero: false,
                title: { display: true, text: 'Equity ($)' },
              },
            },
          },
        })
      }
    } catch (e) {
      console.error('Failed to load chart:', e)
    } finally {
      loading = false
    }
  }

  onMount(() => {
    loadChart()
    const interval = setInterval(() => {
      // Invalidate cache on periodic refresh so data stays fresh
      delete cache[symbol]
      loadChart()
    }, 60000)

    // Handle window resize - update canvas resolution and chart
    const resizeObserver = new ResizeObserver(() => {
      if (canvas && canvas.parentElement) {
        const rect = canvas.parentElement.getBoundingClientRect()
        canvas.width = rect.width
        canvas.height = 300
      }
      if (chart) chart.resize()
    })
    if (canvas?.parentElement) {
      resizeObserver.observe(canvas.parentElement)
    }

    return () => {
      clearInterval(interval)
      resizeObserver.disconnect()
    }
  })

  $: if (symbol) {
    loading = !cache[symbol]
    loadChart()
  }
</script>

<style>
  .container {
    position: relative;
    width: 100%;
    height: 300px;
    display: block;
  }

  .overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #999;
    background: white;
    margin: 0;
  }

  canvas {
    width: 100% !important;
    height: 300px !important;
    max-width: 100%;
    display: block;
  }
</style>

<div class="container">
  <!-- canvas stays mounted at all times so bind:this is always valid -->
  <canvas bind:this={canvas} style:visibility={hasData ? 'visible' : 'hidden'}></canvas>
  {#if loading}
    <p class="overlay">Loading...</p>
  {:else if !hasData}
    <p class="overlay">No equity data available yet</p>
  {/if}
</div>
