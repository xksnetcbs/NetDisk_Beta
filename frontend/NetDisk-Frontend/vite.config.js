import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'NETDISK_')
  const apiBase = env.NETDISK_API_BASE || 'http://127.0.0.1:5005'
  const upstream = new URL(apiBase)
  if (upstream.username || upstream.password || upstream.search || upstream.hash || !['http:', 'https:'].includes(upstream.protocol)) throw new Error('Use a plain HTTP(S) NETDISK_API_BASE without credentials or query parameters')
  if (upstream.protocol !== 'https:' && !['127.0.0.1', 'localhost', '[::1]'].includes(upstream.hostname)) throw new Error('Remote API requires HTTPS')
  return {
    plugins: [vue(), vueDevTools()],
    server: {
      fs: {
        allow: [
          fileURLToPath(new URL('.', import.meta.url)),
          fileURLToPath(new URL('../../integrations/DCP_InfoCenter/src', import.meta.url)),
        ],
      },
      port: 5105,
      strictPort: true,
      allowedHosts: (env.NETDISK_ALLOWED_HOSTS || '').split(',').map(host => host.trim()).filter(Boolean),
      proxy: { '/api': { target: apiBase, changeOrigin: true } },
    },
    resolve: {
      dedupe: ['vue', 'gsap', 'lucide-vue-next'],
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
  }
})
