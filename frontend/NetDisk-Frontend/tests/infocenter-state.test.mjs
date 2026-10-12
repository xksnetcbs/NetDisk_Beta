import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import axios from 'axios'
import { createPinia, defineStore, setActivePinia } from 'pinia'

const values = new Map()
const localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key) }
const context = vm.createContext({ localStorage, console, setTimeout, clearTimeout })
const axiosModule = new vm.SyntheticModule(['default'], function () { this.setExport('default', axios) }, { context })
const piniaModule = new vm.SyntheticModule(['defineStore'], function () { this.setExport('defineStore', defineStore) }, { context })
const load = async name => new vm.SourceTextModule(await fs.readFile(new URL('../src/' + name, import.meta.url), 'utf8'), {
  context, initializeImportMeta: meta => { meta.env = {} }, importModuleDynamically: async () => apiModule,
})
const authModule = await load('stores/auth.js')
const apiModule = await load('api.js')
const transportModule = await load('infocenter.js')
const stateModule = await load('stores/infocenter.js')
await authModule.link(() => piniaModule)
await authModule.evaluate()
await apiModule.link(name => name === 'axios' ? axiosModule : authModule)
await apiModule.evaluate()
await transportModule.link(() => apiModule)
await transportModule.evaluate()
await stateModule.link(name => name === 'pinia' ? piniaModule : name === './auth' ? authModule : transportModule)
await stateModule.evaluate()
const { http } = apiModule.namespace
const { infoCenterApi } = transportModule.namespace
const { useAuthStore } = authModule.namespace
const { useInfoCenterStore } = stateModule.namespace
const pause = () => new Promise(resolve => setTimeout(resolve, 0))
const response = (config, data, status = 200) => ({ config, status, statusText: 'OK', headers: {}, data })
function fresh(role = 'super_admin') {
  values.clear()
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.setSession({ access_token: 'netdisk-test-token', user: { id: 1, role_system: role } })
  return { auth, state: useInfoCenterStore() }
}

test('all consumers share precise canonical unread state and concurrent reads', async () => {
  const { state } = fresh()
  let calls = 0
  http.defaults.adapter = async config => { calls++; await pause(); return response(config, { unread_count: 1106, total_count: 1200, by_chat: { room: 1106 }, latest: [{ id: 42 }] }) }
  await Promise.all([state.refresh(true), useInfoCenterStore().refresh(true)])
  assert.equal(calls, 1)
  assert.equal(state.unreadCount, 1106)
  assert.equal(state.byChat.room, 1106)
  assert.equal(state.latest[0].id, 42)
  assert.equal(state, useInfoCenterStore())
})

test('uncaptured desktop cursor is retained and retried until terminal persists it', async () => {
  const { state } = fresh()
  let pending = true, marks = 0
  http.defaults.adapter = async config => {
    if (config.url.endsWith('/conversations/read')) { marks++; assert.equal(JSON.parse(config.data).through_uid, 'new-message'); return response(config, { pending }) }
    return response(config, { unread_count: pending ? 1 : 0, by_chat: pending ? { room: 1 } : {}, total_count: 1 })
  }
  await state.markRead('room', 'new-message')
  assert.equal(state.pendingRead.room, 'new-message')
  assert.equal(state.readCursor.room, undefined)
  pending = false
  await state.refresh(true)
  assert.equal(marks, 2)
  assert.equal(state.pendingRead.room, undefined)
  assert.equal(state.readCursor.room, 'new-message')
  assert.equal(state.unreadCount, 0)
})

test('read cursor arriving during a refresh is not discarded by an older result', async () => {
  const { state } = fresh()
  let release, requested
  const gate = new Promise(resolve => { release = resolve })
  http.defaults.adapter = async config => {
    if (config.url.endsWith('/conversations/read')) { requested = JSON.parse(config.data).through_uid; await gate; return response(config, { pending: false }) }
    return response(config, { unread_count: 0, total_count: 2 })
  }
  const first = state.markRead('room', 'first')
  await pause()
  const second = state.markRead('room', 'second')
  release()
  await Promise.all([first, second])
  assert.equal(requested, 'first')
  assert.equal(state.pendingRead.room, 'second')
  await state.refresh(true)
  assert.equal(requested, 'second')
  assert.equal(state.readCursor.room, 'second')
})

test('logout cannot restore a late InfoCenter result from a previous account', async () => {
  const { auth, state } = fresh()
  let release
  http.defaults.adapter = config => new Promise(resolve => { release = () => resolve(response(config, { unread_count: 99, total_count: 99 })) })
  const request = state.refresh(true)
  await pause()
  auth.clearSession()
  state.reset()
  release()
  await request
  assert.equal(state.unreadCount, 0)
  assert.equal(state.latest.length, 0)
})

test('ordinary users never request InfoCenter data', async () => {
  const { state } = fresh('user')
  let calls = 0
  http.defaults.adapter = config => { calls++; return response(config, {}) }
  await state.refresh(true)
  assert.equal(calls, 0)
})

test('media and send use the NetDisk bearer header, never a query credential', async () => {
  fresh()
  const configs = []
  http.defaults.adapter = async config => { configs.push(config); return response(config, config.responseType === 'blob' ? 'test-blob' : { status: 'submitted' }) }
  assert.equal(await infoCenterApi.blob(12, 'media'), 'test-blob')
  await infoCenterApi.request('/send/prepare', { method: 'POST', body: { text: 'mock only' } })
  assert.equal(configs[0].responseType, 'blob')
  for (const config of configs) { assert.equal(config.headers.get('Authorization'), 'Bearer netdisk-test-token'); assert.ok(!config.url.includes('?token=')) }
})

test('upstream connection failures preserve the account and last known unread state', async () => {
  const { auth, state } = fresh()
  state.userId = 1
  state.unreadCount = 4
  http.defaults.adapter = async config => { throw Object.assign(new Error('upstream failure'), { config, response: { status: 502, data: { error: '服务暂时无法连接' } } }) }
  await assert.rejects(state.refresh(true), /服务暂时无法连接/)
  assert.equal(state.unreadCount, 4)
  assert.equal(auth.token, 'netdisk-test-token')
})
