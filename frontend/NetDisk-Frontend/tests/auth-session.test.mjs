import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import axios from 'axios'
import { createPinia, defineStore, setActivePinia } from 'pinia'

// Load the production modules unchanged, with import.meta.env and localStorage
// supplied by the browser-shaped context. Axios uses a deterministic test adapter.
const values = new Map()
const localStorage = {
  getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
}
const context = vm.createContext({ localStorage, console, setTimeout, clearTimeout })
const axiosModule = new vm.SyntheticModule(['default'], function () { this.setExport('default', axios) }, { context })
const piniaModule = new vm.SyntheticModule(['defineStore'], function () { this.setExport('defineStore', defineStore) }, { context })
const authModule = new vm.SourceTextModule(await fs.readFile(new URL('../src/stores/auth.js', import.meta.url), 'utf8'), {
  context,
  importModuleDynamically: async () => apiModule,
})
const apiModule = new vm.SourceTextModule(await fs.readFile(new URL('../src/api.js', import.meta.url), 'utf8'), {
  context,
  initializeImportMeta: (meta) => { meta.env = {} },
})
await authModule.link(() => piniaModule)
await authModule.evaluate()
await apiModule.link((specifier) => specifier === 'axios' ? axiosModule : authModule)
await apiModule.evaluate()
setActivePinia(createPinia())
const auth = authModule.namespace.useAuthStore()
const { api, http, restoreSession } = apiModule.namespace
const user = { id: 1, username: 'member', role_system: 'user' }
const result = (config, data) => ({ config, status: 200, statusText: 'OK', headers: {}, data: { ok: true, data } })
const unauthorized = (config) => Promise.reject(Object.assign(new Error('Unauthorized'), { config, response: { status: 401 } }))
const pause = () => new Promise((resolve) => setTimeout(resolve, 0))

function reset() {
  values.clear()
  auth.clearSession()
  auth.initialized = false
  auth.signedOut = false
}

test('first navigation restores a remembered device, sharing concurrent initialization', async () => {
  reset()
  let refreshes = 0
  http.defaults.adapter = async (config) => {
    assert.equal(config.url, '/auth/refresh')
    assert.equal(config.withCredentials, true)
    assert.equal(config.headers.get('X-DCP-Session'), '1')
    refreshes += 1
    await pause()
    return result(config, { access_token: 'new-token', user })
  }
  await Promise.all([auth.initialize(), auth.initialize()])
  assert.equal(refreshes, 1)
  assert.equal(auth.isAuthed, true)
  assert.equal(auth.initialized, true)
})

test('parallel expired requests refresh once and replay with the new access token', async () => {
  reset()
  auth.setSession({ access_token: 'expired-token', user })
  let refreshes = 0
  let calls = 0
  http.defaults.adapter = async (config) => {
    if (config.url === '/auth/refresh') {
      refreshes += 1
      await pause()
      return result(config, { access_token: 'fresh-token', user })
    }
    calls += 1
    if (config.headers.get('Authorization') === 'Bearer expired-token') return unauthorized(config)
    assert.equal(config.headers.get('Authorization'), 'Bearer fresh-token')
    return result(config, { user })
  }
  await Promise.all([api.me(), api.me()])
  assert.equal(refreshes, 1)
  assert.equal(calls, 4)
  assert.equal(auth.isAuthed, true)
})

test('a late old-token response reuses an already refreshed token', async () => {
  reset()
  auth.setSession({ access_token: 'expired-token', user })
  let refreshes = 0
  let oldRequests = 0
  let releaseLate
  const late = new Promise((resolve) => { releaseLate = resolve })
  http.defaults.adapter = async (config) => {
    if (config.url === '/auth/refresh') {
      refreshes += 1
      return result(config, { access_token: 'fresh-token', user })
    }
    if (config.headers.get('Authorization') === 'Bearer expired-token') {
      oldRequests += 1
      if (oldRequests === 2) await late
      return unauthorized(config)
    }
    return result(config, { user })
  }
  const first = api.me()
  const second = api.me()
  await first
  releaseLate()
  await second
  assert.equal(refreshes, 1)
})

test('failed manual login does not silently refresh or clear another session', async () => {
  reset()
  auth.setSession({ access_token: 'existing-token', user })
  let calls = 0
  http.defaults.adapter = async (config) => {
    calls += 1
    assert.equal(config.url, '/auth/login')
    assert.equal(config.headers.get('Authorization'), undefined)
    return unauthorized(config)
  }
  await assert.rejects(api.login({ username: 'member', password: 'wrong' }))
  assert.equal(calls, 1)
  assert.equal(auth.token, 'existing-token')
})

test('logout wins against an in-flight refresh and persists offline sign-out', async () => {
  reset()
  auth.setSession({ access_token: 'old-token', user })
  let releaseRefresh
  const wait = new Promise((resolve) => { releaseRefresh = resolve })
  http.defaults.adapter = async (config) => {
    if (config.url === '/auth/logout') throw new Error('offline')
    await wait
    return result(config, { access_token: 'new-token', user })
  }
  const restoring = restoreSession()
  const rejection = assert.rejects(restoring)
  await pause()
  await auth.logout()
  releaseRefresh()
  await rejection
  assert.equal(auth.token, '')
  assert.equal(auth.user, null)
  assert.equal(values.get('dcp_netdisk_signed_out'), '1')
  auth.initialized = false
  await auth.initialize()
  assert.equal(auth.isAuthed, false)
})

test('an invalid remembered session clears state without recursive refresh', async () => {
  reset()
  auth.setSession({ access_token: 'old-token', user })
  let refreshes = 0
  http.defaults.adapter = async (config) => {
    if (config.url === '/auth/refresh') refreshes += 1
    return unauthorized(config)
  }
  await assert.rejects(api.me())
  assert.equal(refreshes, 1)
  assert.equal(auth.token, '')
  assert.equal(auth.user, null)
})

test('transient refresh errors preserve the session for a later request', async () => {
  reset()
  auth.setSession({ access_token: 'old-token', user })
  http.defaults.adapter = async (config) => {
    if (config.url === '/auth/refresh') throw new Error('offline')
    return unauthorized(config)
  }
  await assert.rejects(api.me())
  assert.equal(auth.token, 'old-token')
  assert.equal(auth.user.username, 'member')
})

test('a valid pre-upgrade token gets the replacement token from auth/me', async () => {
  reset()
  auth.setToken('legacy-token')
  http.defaults.adapter = async (config) => {
    assert.equal(config.url, '/auth/me')
    return result(config, { access_token: 'session-token', user })
  }
  await auth.initialize()
  assert.equal(auth.token, 'session-token')
  assert.equal(auth.isAuthed, true)
})
