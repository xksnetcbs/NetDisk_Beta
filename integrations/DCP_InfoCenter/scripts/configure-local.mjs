import { writeFile } from 'node:fs/promises'

const base = process.env.DCP_API_BASE || 'http://127.0.0.1:8766/api/terminal'
const token = process.env.DCP_API_TOKEN
if (!token || /[\r\n]/.test(base + token)) throw new Error('Set DCP_API_TOKEN and optional DCP_API_BASE in the environment')
const url = new URL(base)
if (url.username || url.password || url.search || url.hash || !['http:', 'https:'].includes(url.protocol)) throw new Error('Use a plain HTTP(S) API URL without credentials or query parameters')
if (url.protocol !== 'https:' && !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) throw new Error('Remote API requires HTTPS')
await writeFile('.env.local', `DCP_API_BASE=${JSON.stringify(base)}\nDCP_API_TOKEN=${JSON.stringify(token)}\n`, { mode: 0o600 })
console.log('Local server connection configured. Credentials stay in the ignored server configuration.')
