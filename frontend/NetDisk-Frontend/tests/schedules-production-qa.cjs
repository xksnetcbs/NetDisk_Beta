// Explicit QA accounts only. No mocked responses, private details in output,
// or changes to pre-existing schedules. All created IDs are cleaned in finally.
const { chromium } = require(process.env.PLAYWRIGHT_NODE_DIR || 'playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

async function main() {
  const fixturePath = process.env.NETDISK_QA_FILE
  if (!fixturePath) throw Error('Private QA fixture path is required')
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8').replace(/^\uFEFF/, ''))
  const base = fixture.url.replace(/\/$/, '')
  const origin = new URL(base)
  assert.ok(!origin.username && !origin.password && (origin.protocol === 'https:' || origin.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(origin.hostname)), 'QA origin must use HTTPS or localhost')
  const output = path.resolve(__dirname, '../../../doc/日程统一验收')
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined })
  const results = [], contexts = [], cleanups = []
  let stage = 'setup', failure = null
  const privateStrings = Object.values(fixture.accounts).flatMap(row => [row.username, row.password])
  const safeError = error => privateStrings.reduce((value, secret) => value.split(secret).join('[redacted]'), String(error?.message || error)).slice(0, 2000)
  async function api(page, suffix = '', method = 'GET', body) {
    const response = await page.evaluate(async ({ suffix, method, body }) => {
      const token = localStorage.getItem('dcp_netdisk_token') || ''
      const response = await fetch('/api/mobile/terminal/schedules' + suffix, {
        method, headers: { Authorization: 'Bearer ' + token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store',
      })
      return { status: response.status, data: await response.json() }
    }, { suffix, method, body })
    assert.equal(response.status, 200, `QA API ${method} status ${response.status}`)
    return response.data
  }
  async function logout(page) {
    if (!page.isClosed()) await page.evaluate(async () => {
      const token = localStorage.getItem('dcp_netdisk_token') || ''
      await fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + token, 'X-DCP-Session': '1' } }).catch(() => {})
      localStorage.removeItem('dcp_netdisk_token'); localStorage.setItem('dcp_netdisk_signed_out', '1')
    }).catch(() => {})
  }
  async function login(kind, width = 1440) {
    const account = fixture.accounts[kind]
    const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 }, timezoneId: 'Asia/Shanghai' })
    contexts.push(context)
    const page = await context.newPage()
    await page.goto(base + '/login?redirect=/calendar')
    await page.getByPlaceholder('username', { exact: true }).fill(account.username)
    await page.getByPlaceholder('password', { exact: true }).fill(account.password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.getByRole('heading', { name: '日程', exact: true }).waitFor()
    await page.waitForFunction(() => !document.querySelector('.schedule-actions button')?.disabled)
    return page
  }
  async function create(page, title, kind, surface) {
    await page.getByRole('button', { name: '新增日程', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '新增日程', exact: true })
    await dialog.getByLabel('标题', { exact: true }).fill(title)
    await dialog.getByLabel('地点', { exact: true }).fill('验收地点')
    await dialog.getByLabel('描述', { exact: true }).fill('此条是专用验收账号的临时个人日程，测试后删除。')
    const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/mobile/terminal/schedules' && response.request().method() === 'POST')
    await dialog.getByRole('button', { name: '保存日程', exact: true }).click()
    const response = await responsePromise
    assert.equal(response.status(), 200)
    const payload = await response.json()
    assert.match(payload.schedule.id, /^netdisk:event:\d+$/)
    assert.equal(Number(payload.schedule.user_id), Number(fixture.accounts[kind].user_id))
    cleanups.push({ page, id: payload.schedule.id })
    await page.getByRole('heading', { name: title, exact: true }).waitFor()
    results.push({ account: kind, surface, check: '本人新增', passed: true })
    return payload.schedule.id
  }
  async function filter(page, query) {
    const source = page.getByLabel('日程来源', { exact: true })
    if (await source.locator('option[value="netdisk"]').count()) await source.selectOption('netdisk')
    await page.getByLabel('搜索日程', { exact: true }).fill(query)
  }
  async function checkRow(page, id, forced, kind, surface) {
    const data = await api(page)
    assert.equal(Number(data.netdisk_user_id), Number(fixture.accounts[kind].user_id))
    const row = data.schedules.find(row => row.id === id)
    assert(row, 'Created QA schedule must exist')
    assert.equal(row.forced_completed, forced)
    assert.equal(row.completed, row.source_completed || forced)
    results.push({ account: kind, surface, check: forced ? '服务器强制完成' : '服务器取消强制完成', passed: true })
  }
  try {
    for (const kind of ['ordinary', 'super']) {
      stage = kind + ' login'
      const page = await login(kind)
      const prefix = 'QA日程 ' + kind + ' ' + Date.now()
      const title = prefix + ' 网盘新增'
      stage = kind + ' create'
      const id = await create(page, title, kind, 'NetDisk')
      await filter(page, prefix)
      stage = kind + ' force'
      await page.getByRole('button', { name: '强制完成 ' + title, exact: true }).click()
      await page.getByRole('button', { name: '已完成', exact: true }).click()
      await page.getByRole('heading', { name: title, exact: true }).waitFor()
      await checkRow(page, id, true, kind, 'NetDisk')

      stage = kind + ' fresh device'
      const second = await login(kind, 390)
      await filter(second, prefix)
      await second.getByRole('button', { name: '已完成', exact: true }).click()
      await second.getByRole('heading', { name: title, exact: true }).waitFor()
      await checkRow(second, id, true, kind, '新浏览器设备')
      await second.screenshot({ path: path.join(output, '线上-' + kind + '-新设备完成状态-390.png') })
      await logout(second); await second.context().close()

      stage = kind + ' unforce'
      await page.getByRole('button', { name: '取消强制完成 ' + title, exact: true }).click()
      await page.getByRole('button', { name: '待完成', exact: true }).click()
      await page.getByRole('heading', { name: title, exact: true }).waitFor()
      await checkRow(page, id, false, kind, 'NetDisk')
      stage = kind + ' edit'
      await page.getByRole('heading', { name: title, exact: true }).click()
      await page.getByRole('dialog', { name: '日程详情', exact: true }).getByRole('button', { name: '编辑', exact: true }).click()
      const edited = prefix + ' 已编辑'
      await page.getByRole('dialog', { name: '编辑日程', exact: true }).getByLabel('标题', { exact: true }).fill(edited)
      await page.getByRole('dialog', { name: '编辑日程', exact: true }).getByRole('button', { name: '保存日程', exact: true }).click()
      await page.getByRole('dialog', { name: '日程详情', exact: true }).getByRole('heading', { name: edited, exact: true }).waitFor()
      await page.getByRole('button', { name: '关闭详情', exact: true }).click()
      assert.equal((await api(page)).schedules.find(row => row.id === id).title, edited)
      results.push({ account: kind, surface: 'NetDisk', check: '本人编辑', passed: true })
      await page.screenshot({ path: path.join(output, '线上-' + kind + '-网盘日程-1440.png') })
      await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(450)
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      await page.screenshot({ path: path.join(output, '线上-' + kind + '-网盘日程-390.png') })

      if (kind === 'super') {
        stage = 'InfoCenter shared schedule'
        await page.goto(base + '/inbox')
        await page.locator('.infocenter-surface').getByRole('button', { name: '日程', exact: true }).click()
        await page.waitForFunction(() => !document.querySelector('.schedule-actions button')?.disabled)
        await filter(page, prefix)
        await page.getByRole('heading', { name: edited, exact: true }).waitFor()
        results.push({ account: kind, surface: 'InfoCenter', check: '网盘编辑跨页可见', passed: true })
        const infoTitle = prefix + ' InfoCenter新增'
        const infoId = await create(page, infoTitle, kind, 'InfoCenter')
        await page.getByRole('button', { name: '强制完成 ' + infoTitle, exact: true }).click()
        await page.getByRole('button', { name: '已完成', exact: true }).click()
        await page.getByRole('heading', { name: infoTitle, exact: true }).waitFor()
        await checkRow(page, infoId, true, kind, 'InfoCenter')
        await page.getByRole('button', { name: '取消强制完成 ' + infoTitle, exact: true }).click()
        await page.getByRole('button', { name: '待完成', exact: true }).click()
        await page.getByRole('heading', { name: infoTitle, exact: true }).waitFor()
        await checkRow(page, infoId, false, kind, 'InfoCenter')
        await page.screenshot({ path: path.join(output, '线上-InfoCenter日程-390.png') })
        await page.setViewportSize({ width: 1440, height: 1000 }); await page.waitForTimeout(350)
        await page.screenshot({ path: path.join(output, '线上-InfoCenter日程-1440.png') })
        stage = 'InfoCenter edit'
        await page.getByRole('heading', { name: infoTitle, exact: true }).click()
        await page.getByRole('button', { name: '编辑', exact: true }).click()
        const infoEdited = prefix + ' InfoCenter已编辑'
        await page.getByRole('dialog', { name: '编辑日程', exact: true }).getByLabel('标题', { exact: true }).fill(infoEdited)
        await page.getByRole('button', { name: '保存日程', exact: true }).click()
        await page.getByRole('dialog', { name: '日程详情', exact: true }).getByRole('heading', { name: infoEdited, exact: true }).waitFor()
        await page.getByRole('button', { name: '关闭详情', exact: true }).click()
        results.push({ account: kind, surface: 'InfoCenter', check: '本人编辑', passed: true })
        await page.goto(base + '/calendar'); await filter(page, prefix)
        await page.getByRole('heading', { name: infoEdited, exact: true }).waitFor()
        results.push({ account: kind, surface: 'NetDisk', check: 'InfoCenter新增及编辑跨页可见', passed: true })
        await page.goto(base + '/inbox')
        await page.locator('.infocenter-surface').getByRole('button', { name: '日程', exact: true }).click()
        await page.waitForFunction(() => !document.querySelector('.schedule-actions button')?.disabled)
        await filter(page, prefix)
        await page.getByRole('heading', { name: infoEdited, exact: true }).click()
        page.once('dialog', dialog => dialog.accept())
        await page.getByRole('dialog', { name: '日程详情', exact: true }).getByRole('button', { name: '删除', exact: true }).click()
        await page.locator('.schedule-cards').getByRole('heading', { name: infoEdited, exact: true }).waitFor({ state: 'hidden' })
        assert(!(await api(page)).schedules.some(row => row.id === infoId))
        cleanups.splice(cleanups.findIndex(item => item.id === infoId), 1)
        results.push({ account: kind, surface: 'InfoCenter', check: '本人删除', passed: true })
      }
      stage = kind + ' delete'
      await page.getByRole('heading', { name: edited, exact: true }).click()
      page.once('dialog', dialog => dialog.accept())
      await page.getByRole('dialog', { name: '日程详情', exact: true }).getByRole('button', { name: '删除', exact: true }).click()
      await page.locator('.schedule-cards').getByRole('heading', { name: edited, exact: true }).waitFor({ state: 'hidden' })
      assert(!(await api(page)).schedules.some(row => row.id === id))
      cleanups.splice(cleanups.findIndex(item => item.id === id), 1)
      results.push({ account: kind, surface: kind === 'super' ? 'InfoCenter删除网盘条目' : 'NetDisk', check: '本人删除', passed: true })
      await logout(page); await page.context().close()
    }
  } catch (error) { failure = { stage, message: safeError(error) } }
  finally {
    for (const item of cleanups) {
      try { await api(item.page, '/' + encodeURIComponent(item.id), 'DELETE') }
      catch { results.push({ check: 'QA created schedule cleanup', passed: false, id: item.id }) }
    }
    for (const context of contexts) {
      for (const page of context.pages()) await logout(page)
      await context.close().catch(() => {})
    }
    await browser.close()
  }
  const report = { generated_date: '2026-10-12', summary: '生产 HTTPS 浏览器日程全流程，专用 QA 账号与自身临时日程，含跨新设备及跨页面同步。', checks: results, failure }
  fs.writeFileSync(path.join(output, '线上浏览器验收.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify({ passed: results.filter(row => row.passed).length, failed: results.filter(row => row.passed === false).length, failure }))
  if (failure || results.some(row => row.passed === false)) process.exitCode = 1
}
main().catch(error => { console.error('Production browser QA could not initialize:', error.name); process.exitCode = 1 })
