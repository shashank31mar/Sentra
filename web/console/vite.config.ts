import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev-only proxy for /v1 -> public API Gateway.
// The x-api-key is injected here, in the dev server (Node side), so it is
// NEVER bundled into client code. In prod, nginx performs the same injection.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiBase = env.VITE_API_BASE ?? 'https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod'
  const apiKey = env.VITE_API_KEY ?? ''

  return {
    plugins: [react(), tailwindcss()],
    build: {
      // Split the entry bundle so the app shell isn't blocked on heavy libs.
      // `chart.js` + `react-chartjs-2` (only the Overview/Threats charts need it)
      // and the router/query vendors move into their own long-cached chunks;
      // per-route code-splitting (React.lazy in router.tsx) does the rest, so the
      // first paint downloads far less than the old ~645 KB monolith.
      // Function form (not the {name: [...]} record) to satisfy vite's config
      // overload typing. Order matters: match the more specific package before
      // the bare `react` catch-all (react-router / react-chartjs both contain
      // "react" in their path).
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return
            if (id.includes('chart.js') || id.includes('react-chartjs-2')) return 'vendor-charts'
            if (id.includes('react-router')) return 'vendor-router'
            if (id.includes('@tanstack')) return 'vendor-query'
            if (id.includes('/react-dom/') || id.includes('/react/')) return 'vendor-react'
          },
        },
      },
    },
    server: {
      proxy: {
        '/v1': {
          target: apiBase,
          changeOrigin: true,
          secure: true,
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              if (apiKey) proxyReq.setHeader('x-api-key', apiKey)
            })
          },
        },
      },
    },
  }
})
