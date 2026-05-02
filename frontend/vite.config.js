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
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
        rewrite: (path) => path,
        router: (req) => {
          const host = req.headers.host?.split(':')[0]
          if (host && host !== 'localhost' && host !== '127.0.0.1') {
            return `http://${host}:9000`
          }
          return 'http://127.0.0.1:9000'
        }
      }
    }
  },
  optimizeDeps: {
    exclude: ['@sveltejs/vite-plugin-svelte']
  }
})
