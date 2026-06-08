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
