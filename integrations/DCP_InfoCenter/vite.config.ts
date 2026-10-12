import { defineConfig, loadEnv, type ProxyOptions } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'DCP_')
  const base = (env.DCP_API_BASE || 'http://127.0.0.1:8766/api/terminal').replace(/\/$/, '')
  const url = new URL(base)
  if (url.protocol !== 'https:' && !['127.0.0.1', 'localhost'].includes(url.hostname)) throw new Error('Remote API requires HTTPS')
  const proxy: Record<string, ProxyOptions> = {
    '/api': {
      target: url.origin, changeOrigin: true,
      rewrite: (path: string) => base.slice(url.origin.length) + '/desktop' + path.slice(4),
      headers: { Authorization: `Bearer ${env.DCP_API_TOKEN || ''}` },
      configure(p) {
        p.on('proxyRes', res => { res.headers['cache-control'] = 'no-store' })
      },
    },
  }
  return { plugins: [vue()], server: { host: '127.0.0.1', port: 5173, proxy }, preview: { host: '127.0.0.1', port: 4173, proxy } }
})
