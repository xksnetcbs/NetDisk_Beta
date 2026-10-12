// Explicit live QA for temporary accounts and a temporary project provisioned by
// the deployment task. Credentials stay in memory, and WeChat sends are blocked.
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from '../../../integrations/DCP_InfoCenter/node_modules/playwright-core/index.mjs'

const fixturePath = process.env.NETDISK_QA_FILE
if (!fixturePath) throw new Error('Set NETDISK_QA_FILE to an explicitly provisioned test fixture')
const fixture = JSON.parse((await fs.readFile(fixturePath, 'utf8')).replace(/^\uFEFF/, ''))
const base = fixture.url.replace(/\/$/, '')
const origin = new URL(base)
assert.ok(!origin.username && !origin.password && (origin.protocol === 'https:' || origin.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(origin.hostname)), 'QA origin must use HTTPS or localhost')
const browser = await chromium.launch({ headless: true })
const clients = []
const runId = Date.now()
const incoming = `NetDisk live browser QA ${runId}: ordinary test message`
const reply = `NetDisk live browser QA ${runId}: super test reply`

async function client(role, width) {
  const context = await browser.newContext({ viewport: { width, height: width < 720 ? 844 : 960 } })
  const page = await context.newPage()
  const state = { context, page, role, width, infoRequests: 0, readRequests: 0, localSends: 0, blockedWechat: 0, errors: [], messagePolls: [] }
  clients.push(state)
  page.on('pageerror', () => state.errors.push('pageerror'))
  page.on('response', async response => {
    const url = new URL(response.url())
    if (url.pathname === '/api/infocenter/desktop/messages') {
      try {
        const data = await response.json()
        state.messagePolls.push({ after: url.searchParams.get('after'), cursor: data.cursor, rows: data.items?.length, hasReply: !!data.items?.some(message => message.text === reply) })
      } catch { /* A transport failure is reported by UI checks. */ }
    }
  })
  await page.route('**/api/infocenter/desktop/send/**', route => {
    state.blockedWechat++
    return route.abort()
  })
  // This uses real server data but only exposes the temporary project to the UI.
  // It prevents the component's initial selection from opening a real WeChat chat.
  await page.route('**/api/infocenter/desktop/conversations', async route => {
    const response = await route.fetch()
    assert.equal(response.status(), 200, 'Live conversations endpoint must be available')
    const data = await response.json()
    const items = data.items.filter(item => item.last?.source === 'netdisk' && Number(item.last?.payload?.project_id) === Number(fixture.project_id))
    await route.fulfill({ response, json: { ...data, items } })
  })
  page.on('request', request => {
    const path = new URL(request.url()).pathname
    if (path.startsWith('/api/infocenter/')) state.infoRequests++
    if (path.endsWith('/terminal/conversations/read')) state.readRequests++
    if (path.startsWith('/api/infocenter/netdisk/conversations/')) state.localSends++
  })
  await page.goto(base + '/login')
  assert.equal(await page.getByText('新网盘维护中', { exact: false }).count(), 0)
  await page.getByPlaceholder('username', { exact: true }).fill(fixture.accounts[role].username)
  await page.getByPlaceholder('password', { exact: true }).fill(fixture.accounts[role].password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL(base + '/', { timeout: 45000 })
  await page.locator('.dcp-shell').waitFor()
  console.log(JSON.stringify({ phase: 'login', role, width, success: true }))
  return state
}

async function api(state, path, method = 'GET', body) {
  return state.page.evaluate(async ({ path, method, body }) => {
    const token = localStorage.getItem('dcp_netdisk_token')
    const response = await fetch('/api' + path, { method, headers: { ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined })
    return { status: response.status, data: await response.json() }
  }, { path, method, body })
}

async function dashboardCount(state) {
  await state.page.getByText('信息中心未读', { exact: true }).waitFor()
  return Number((await state.page.locator('.dashboard-card').filter({ hasText: '信息中心未读' }).locator('.n-statistic-value').innerText()).replace(/,/g, ''))
}

async function sidebarCount(state) {
  const text = await state.page.locator('.dcp-nav-item').filter({ hasText: '消息' }).innerText()
  return Number(text.replace(/\D/g, '')) || 0
}

async function waitCounts(state, expected) {
  await state.page.waitForFunction(expected => {
    const card = [...document.querySelectorAll('.dashboard-card')].find(node => node.textContent.includes('信息中心未读'))
    const nav = [...document.querySelectorAll('.dcp-nav-item')].find(node => node.textContent.includes('消息'))
    return Number(card?.querySelector('.n-statistic-value')?.textContent.replace(/[,\s]/g, '')) === expected && (Number(nav?.textContent.replace(/\D/g, '')) || 0) === expected
  }, expected, { timeout: 45000 })
}

async function logout(state) {
  await state.page.locator('.dcp-topbar__right .dcp-btn').last().click()
  await state.page.getByText('退出登录', { exact: true }).click()
  await state.page.waitForURL('**/login')
  const remaining = await state.page.evaluate(() => localStorage.getItem('dcp_netdisk_token'))
  assert.equal(remaining, null)
  const auth = await api(state, '/auth/me')
  assert.equal(auth.status, 401)
  console.log(JSON.stringify({ phase: 'logout', role: state.role, width: state.width, success: true }))
  state.loggedOut = true
}

try {
  const ordinary = await client('ordinary', 390)
  const beforeInfo = ordinary.infoRequests
  await ordinary.page.locator('.dcp-topbar__right .dcp-btn').first().click()
  await ordinary.page.locator('.inbox-page').waitFor()
  assert.equal(await ordinary.page.locator('.infocenter-surface').count(), 0)
  assert.equal(ordinary.infoRequests, beforeInfo)
  const denied = await api(ordinary, '/infocenter/terminal/unread')
  assert.equal(denied.status, 403)
  const posted = await api(ordinary, `/projects/${fixture.project_id}/group-messages`, 'POST', { content_md: incoming })
  assert.equal(posted.status, 200, 'Temporary project must allow the ordinary QA participant')
  console.log(JSON.stringify({ phase: 'ordinary-isolation', width: 390, nativeInfoVisible: false, directApiStatus: denied.status, testMessagePosted: true }))

  const admin = await client('super', 1440)
  let unread
  for (let attempt = 0; attempt < 12; attempt++) {
    unread = await api(admin, '/infocenter/terminal/unread')
    assert.equal(unread.status, 200)
    if (unread.data.latest.some(item => item.body === incoming)) break
    await new Promise(resolve => setTimeout(resolve, 2000))
  }
  assert.ok(unread.data.latest.some(item => item.body === incoming), 'Bridge must deliver the temporary project message to Terminal')
  const expected = unread.data.unread_count
  await waitCounts(admin, expected)
  assert.equal(await dashboardCount(admin), expected)
  assert.equal(await sidebarCount(admin), expected)
  console.log(JSON.stringify({ phase: 'canonical-unread', count: expected, dashboardMatches: true, sidebarMatches: true }))

  await admin.page.locator('.dcp-nav-item').filter({ hasText: '消息' }).click()
  await admin.page.locator('.infocenter-surface').waitFor()
  assert.equal(await admin.page.locator('iframe').count(), 0)
  await admin.page.locator('.message-content').getByText(incoming, { exact: true }).waitFor({ timeout: 45000 })
  await admin.page.getByRole('textbox', { name: '消息内容' }).fill(reply)
  await admin.page.getByRole('button', { name: '发送站内消息' }).click()
  await admin.page.getByRole('status').filter({ hasText: '已确认发送' }).waitFor({ timeout: 45000 })
  try {
    await admin.page.locator('.message-content').getByText(reply, { exact: true }).waitFor({ timeout: 45000 })
  } catch (error) {
    console.log(JSON.stringify({ phase: 'reply-refresh-diagnostic', polls: admin.messagePolls, documentHidden: await admin.page.evaluate(() => document.hidden), errorBanner: await admin.page.locator('.error-banner').allInnerTexts() }))
    throw error
  }
  assert.equal(admin.localSends, 1)
  assert.equal(admin.blockedWechat, 0)
  assert.ok(admin.readRequests > 0)
  const project = await api(admin, `/projects/${fixture.project_id}/group-messages`)
  assert.equal(project.status, 200)
  assert.ok(project.data.data.items.some(item => item.content_md === reply), 'Native reply must exist in canonical NetDisk project messages')
  assert.equal(await admin.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  await admin.page.locator('.infocenter-host').screenshot({ path: fileURLToPath(new URL('../../../doc/InfoCenter线上QA_1440.png', import.meta.url)) })
  console.log(JSON.stringify({ phase: 'native-super', width: 1440, canonicalReplyConfirmed: true, readRequests: admin.readRequests, wechatRequests: admin.blockedWechat }))

  const mobile = await client('super', 390)
  await mobile.page.locator('.dcp-topbar__right .dcp-btn').first().click()
  await mobile.page.locator('.conversation').waitFor()
  assert.equal(mobile.readRequests, 0, 'Hidden mobile pane must not read the test conversation')
  await mobile.page.locator('.conversation').click()
  await mobile.page.locator('.message-content').getByText(reply, { exact: true }).waitFor()
  assert.equal(await mobile.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  assert.equal(await mobile.page.locator('iframe').count(), 0)
  await mobile.page.locator('.infocenter-host').screenshot({ path: fileURLToPath(new URL('../../../doc/InfoCenter线上QA_390.png', import.meta.url)) })
  console.log(JSON.stringify({ phase: 'native-super', width: 390, hiddenPaneInitiallyRead: false, noHorizontalOverflow: true }))
  for (const state of clients) assert.deepEqual(state.errors, [])
  console.log('Live InfoCenter browser checks passed. Only the temporary NetDisk project was displayed; no WeChat sends were called.')
} finally {
  for (const state of clients) {
    if (!state.loggedOut) {
      try { await logout(state) } catch { console.log(JSON.stringify({ phase: 'logout', role: state.role, width: state.width, success: false })); }
    }
    await state.context.close()
  }
  await browser.close()
}
