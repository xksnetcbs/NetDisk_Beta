// Production-build browser checks using only mocked APIs and generated test data.
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from '../../../integrations/DCP_InfoCenter/node_modules/playwright-core/index.mjs'

const base = process.argv[2] || 'http://127.0.0.1:5117'
const browser = await chromium.launch({ headless: true })
const fixtures = [
  { id: 1, uid: 'mock-message-1', chat_id: 'mock-room', chat_name: '测试会话', sender: '测试联系人', sender_id: 'mock-user', outgoing: false, time: 1791763200, kind: 'text', text: '集成测试消息' },
  { id: 2, uid: 'mock-message-2', chat_id: 'mock-room', chat_name: '测试会话', sender: '测试联系人', sender_id: 'mock-user', outgoing: false, time: 1791763201, kind: 'image', text: '测试图片', media_available: true, media_status: 'ready' },
  { id: 3, uid: 'mock-message-3', chat_id: 'mock-room', chat_name: '测试会话', sender: '测试联系人', sender_id: 'mock-user', outgoing: false, time: 1791763202, kind: 'file', text: '测试附件', attachment: { name: 'sample.txt', size: 4, extension: 'txt', available: true, verified: true } },
]
const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jfT0AAAAASUVORK5CYII=', 'base64')

async function scenario(role, viewport) {
  const context = await browser.newContext({ viewport, acceptDownloads: true })
  await context.addInitScript(() => localStorage.setItem('dcp_netdisk_token', 'mock-netdisk-access-token'))
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  let unread = 2, reads = 0, infoRequests = 0, authenticatedMedia = 0
  const json = (route, data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
  await page.route('**/api/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname.slice(4)
    const ok = data => json(route, { ok: true, data })
    if (path === '/auth/me') return ok({ user: { id: 1, username: 'mock-user', display_name: '测试账号', role_system: role } })
    if (path === '/projects' || path === '/notifications' || path === '/inbox/threads') return ok({ items: [] })
    if (!path.startsWith('/infocenter/')) return ok({})
    infoRequests++
    assert.equal(req.headers().authorization, 'Bearer mock-netdisk-access-token')
    assert.ok(!url.searchParams.has('token'))
    if (path.endsWith('/terminal/unread')) return json(route, { unread_count: unread, total_count: 3, by_chat: unread ? { 'mock-room': unread } : {}, latest: [] })
    if (path.endsWith('/terminal/conversations/read')) {
      reads++
      const body = req.postDataJSON()
      assert.equal(body.chat_id, 'mock-room')
      assert.equal(body.through_uid, 'mock-message-3')
      unread = 0
      return json(route, { pending: false, changed: 2 })
    }
    if (path.endsWith('/desktop/status')) return json(route, { version: 'mock', messages: 3, conversations: 1, file_messages: 1, available_files: 1, latest_at: 1791763202, captured_at: '2026-10-12T00:00:00Z', cursor: 3, self_name: '测试微信' })
    if (path.endsWith('/desktop/conversations')) return json(route, { cursor: 3, items: [{ id: 'mock-room', name: '测试会话', nickname: '', is_group: false, muted: false, count: 3, file_count: 1, last: fixtures[2] }] })
    if (path.endsWith('/desktop/messages')) {
      const items = url.searchParams.get('kind') === 'file' ? [fixtures[2]] : url.searchParams.get('kind') === 'media' ? [fixtures[1]] : fixtures
      return json(route, { items, more: false, before: null, cursor: 3 })
    }
    if (path.endsWith('/media')) { authenticatedMedia++; return route.fulfill({ status: 200, contentType: 'image/png', body: pixel }) }
    if (path.endsWith('/file')) return route.fulfill({ status: 200, contentType: 'application/octet-stream', headers: { 'Content-Disposition': 'attachment; filename="sample.txt"' }, body: 'test' })
    throw Error('Unexpected mock API: ' + path)
  })
  await page.goto(base + '/')
  if (role === 'super_admin') {
    await page.getByText('信息中心未读', { exact: true }).waitFor()
    await page.waitForFunction(() => document.querySelector('.dcp-nav-item') && [...document.querySelectorAll('.dcp-nav-item')].some(el => el.textContent.includes('消息') && el.textContent.includes('2')))
  }
  if (viewport.width < 720) await page.locator('.dcp-topbar__right .dcp-btn').first().click()
  else await page.locator('.dcp-nav-item').filter({ hasText: '消息' }).click()
  if (role !== 'super_admin') {
    await page.locator('.inbox-page').waitFor()
    assert.equal(await page.locator('.infocenter-surface').count(), 0)
    assert.equal(infoRequests, 0)
  } else {
    await page.locator('.infocenter-surface').waitFor()
    assert.equal(await page.locator('iframe').count(), 0)
    if (viewport.width < 720) {
      await page.locator('.conversation').waitFor()
      assert.equal(reads, 0, 'A hidden mobile chat must not mark messages read')
      await page.locator('.conversation').click()
    }
    await page.getByText('集成测试消息', { exact: true }).waitFor()
    await page.waitForFunction(() => [...document.querySelectorAll('.dcp-nav-item')].some(el => el.textContent.trim() === '消息'))
    assert.ok(reads > 0)
    await page.locator('.dcp-topbar__right .n-badge-sup').waitFor({ state: 'hidden' })
    const img = page.locator('.message-content img').first()
    await img.waitFor()
    await page.waitForFunction(() => document.querySelector('.message-content img')?.src.startsWith('blob:'))
    assert.ok(authenticatedMedia > 0)
    const downloadEvent = page.waitForEvent('download')
    await page.locator('.file-bottom button').click()
    const download = await downloadEvent
    assert.equal(download.suggestedFilename(), 'sample.txt')
    assert.equal(await fs.readFile(await download.path(), 'utf8'), 'test')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    assert.equal(overflow, false, 'Page must not overflow horizontally')
    await page.screenshot({ path: fileURLToPath(new URL(`../../../doc/InfoCenter合并_${viewport.width}.png`, import.meta.url)), fullPage: true })
  }
  assert.deepEqual(errors, [])
  await context.close()
  return { role, width: viewport.width, infoRequests, reads, authenticatedMedia }
}

async function internalReplyScenario(kind) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
  await context.addInitScript(() => localStorage.setItem('dcp_netdisk_token', 'mock-netdisk-access-token'))
  const page = await context.newPage()
  const chat = kind === 'project_group' ? 'netdisk:test:project:7@chatroom' : 'netdisk:test:thread:10'
  const item = { ...fixtures[0], uid: 'netdisk:test:inbox:100', source: 'netdisk', chat_id: chat, chat_name: '站内测试会话',
    payload: { thread_type: kind, thread_id: 10 }, link_url: kind === 'system' ? '/admin?user_id=4' : null }
  let localWrites = 0, wechatWrites = 0
  let cursor = 1, messages = [item]
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(4)
    const json = data => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
    if (path === '/auth/me') return json({ ok: true, data: { user: { id: 1, username: 'test', role_system: 'super_admin' } } })
    if (path.endsWith('/desktop/conversations')) return json({ cursor, items: [{ id: chat, name: '站内测试会话', nickname: '', is_group: kind === 'project_group', muted: false, count: messages.length, file_count: 0, last: messages.at(-1) }] })
    if (path.endsWith('/desktop/messages')) {
      const after = Number(new URL(request.url()).searchParams.get('after'))
      return json({ items: messages.filter(message => !after || message.id > after), more: false, before: null, cursor })
    }
    if (path.endsWith('/desktop/status')) return json({ version: 'test', messages: 1, conversations: 1, file_messages: 0, available_files: 0, cursor: 1, self_name: 'test' })
    if (path.endsWith('/terminal/unread')) return json({ unread_count: 0, total_count: 1, by_chat: {}, latest: [] })
    if (path.endsWith('/terminal/conversations/read')) return json({ pending: false, changed: 0 })
    if (path.startsWith('/infocenter/netdisk/conversations/')) {
      localWrites++
      assert.equal(request.headers().authorization, 'Bearer mock-netdisk-access-token')
      assert.equal(request.postDataJSON().message_uid, item.uid)
      assert.equal(request.postDataJSON().text, '测试站内回复')
      setTimeout(() => {
        cursor = 2
        messages.push({ ...item, id: 2, uid: 'netdisk:test:inbox:101', time: item.time + 1, text: '测试站内回复' })
      }, 350)
      return json({ status: 'confirmed', source: 'netdisk', message_id: 101 })
    }
    if (path.includes('/desktop/send/')) { wechatWrites++; return json({ status: 'unexpected' }) }
    return json({ ok: true, data: { items: [] } })
  })
  await page.goto(base + '/inbox')
  await page.locator('.message-content').getByText('集成测试消息', { exact: true }).waitFor()
  if (kind === 'system') {
    assert.equal(await page.getByRole('textbox', { name: '消息内容' }).count(), 0)
    await page.getByRole('button', { name: '打开详情' }).click()
    await page.waitForURL('**/admin?user_id=4')
  } else {
    await page.getByRole('textbox', { name: '消息内容' }).fill('测试站内回复')
    await page.getByRole('button', { name: '发送站内消息' }).click()
    await page.getByRole('status').filter({ hasText: '已确认发送' }).waitFor()
    await page.locator('.message-content').getByText('测试站内回复', { exact: true }).waitFor({ timeout: 15000 })
    assert.equal(localWrites, 1)
  }
  assert.equal(wechatWrites, 0)
  assert.deepEqual(errors, [])
  await context.close()
  return { kind, localWrites, wechatWrites }
}

try {
  console.log(JSON.stringify(await scenario('super_admin', { width: 1440, height: 960 })))
  console.log(JSON.stringify(await scenario('super_admin', { width: 390, height: 844 })))
  console.log(JSON.stringify(await scenario('user', { width: 1440, height: 960 })))
  for (const kind of ['project_group', 'direct', 'system']) console.log(JSON.stringify(await internalReplyScenario(kind)))
  const login = await browser.newPage()
  await login.goto(base + '/login')
  assert.equal(await login.getByText('新网盘维护中', { exact: false }).count(), 0)
  await login.close()
  console.log('InfoCenter production browser checks passed; all API data was mocked.')
} finally { await browser.close() }
