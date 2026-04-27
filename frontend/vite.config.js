import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { resolve } from 'path'

export default defineConfig({
  plugins: [svelte()],
  resolve: {
    alias: {
      $lib: resolve(__dirname, 'src/lib')
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    middlewareMode: false,
    proxy: {
      '/api': {
        target: 'http://192.168.1.232:9000',
        changeOrigin: true,
        rewrite: (path) => path
      }
    }
  },
  optimizeDeps: {
    exclude: ['@sveltejs/vite-plugin-svelte']
  }
})
