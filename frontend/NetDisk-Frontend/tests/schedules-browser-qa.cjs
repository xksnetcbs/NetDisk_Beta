const { chromium } = require(process.env.PLAYWRIGHT_NODE_DIR || 'playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

async function main() {
  const output = path.resolve(__dirname, '../../../doc/日程统一验收')
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined })
  const checks = []
  try {
    for (const role of ['super_admin', 'user']) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
      const page = await context.newPage()
      const errors = []; page.on('pageerror', error => errors.push(error.message))
      const start = Date.now() + 86400000
      const own = { id: 'netdisk:event:301', title: '个人安排示例', source: 'netdisk', course: '个人日程', start_at: start, end_at: start + 3600000, description: '跨设备同步的本人日程', location: '天津', editable: true, deletable: true, source_completed: false, forced_completed: false, completed: false, status: 'active' }
      let rows = [own]
      let nextId = 302
      if (role === 'super_admin') rows.push(
        { ...own, id: 'canvas-fixture', title: 'Canvas 阅读作业', source: 'calendar', course: '计算方法', editable: false, deletable: false },
        { ...own, id: 'llm-fixture', title: '微信识别组会', source: 'terminal', course: '微信识别日程', editable: true, deletable: true },
        { ...own, id: 'timetable:demo:1', title: '线性代数', source: 'timetable', course: '课表 · 第1周', editable: false, deletable: false },
        { ...own, id: 'canvas-complete-fixture', title: '已提交作业', source: 'calendar', course: '课程作业', editable: false, deletable: false, source_completed: true, completed: true, status: 'completed' },
      )
      await context.route('**/api/**', async route => {
        const request = route.request(), url = new URL(request.url()), method = request.method()
        let result = { ok: true, data: { items: [], total: 0 } }, status = 200
        if (url.pathname.includes('/auth/')) result = { ok: true, data: { access_token: 'mock-device-session', user: { id: 2, username: 'schedule-qa', display_name: '日程验收账号', role_system: role, status: 'active', is_activated: true } } }
        else if (url.pathname.startsWith('/api/mobile/terminal/schedules')) {
          const suffix = decodeURIComponent(url.pathname.slice('/api/mobile/terminal/schedules'.length).replace(/^\//, ''))
          const body = request.postDataJSON()
          if (method === 'GET') result = { schedules: rows, netdisk_user_id: 2, terminal_access: role === 'super_admin' }
          else if (method === 'POST') { const row = { ...own, ...body, id: 'netdisk:event:' + nextId++ }; rows.push(row); result = { ok: true, schedule: row }; checks.push(role + ': POST personal schedule') }
          else if (method === 'PATCH') { const row = rows.find(row => row.id === suffix); assert(row); Object.assign(row, body); row.completed = row.source_completed || row.forced_completed; row.status = row.completed ? 'completed' : 'active'; result = { ok: true, schedule: row }; checks.push(role + ': PATCH server completion') }
          else if (method === 'DELETE') { rows = rows.filter(row => row.id !== suffix); result = { ok: true }; checks.push(role + ': DELETE personal schedule') }
        } else if (url.pathname.endsWith('/unread')) result = { unread: 0, by_chat: {}, chats: [] }
        else if (url.pathname.endsWith('/conversations')) result = { items: [], conversations: [] }
        else if (url.pathname.endsWith('/status')) result = { self_name: '日程验收账号', messages: 0, file_messages: 0, available_files: 0 }
        else if (url.pathname.includes('/infocenter/')) result = { items: [], more: false, before: null, cursor: 0 }
        await route.fulfill({ status, json: result })
      })
      await page.goto('http://127.0.0.1:5515/calendar')
      await page.getByRole('heading', { name: '个人安排示例', exact: true }).waitFor()
      if (role === 'super_admin') {
        for (const title of ['Canvas 阅读作业', '微信识别组会']) assert(await page.getByRole('heading', { name: title, exact: true }).isVisible())
        assert.equal(await page.getByRole('heading', { name: '线性代数', exact: true }).count(), 0)
        assert.equal(await page.getByLabel('日程来源').locator('option[value="timetable"]').count(), 0)
        checks.push('NetDisk: stale timetable schedules excluded')
      } else assert.equal(await page.getByText('Canvas 阅读作业').count(), 0)
      await page.screenshot({ path: path.join(output, role + '-calendar-1440.png') })
      await page.getByRole('button', { name: '新增日程', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '新增日程', exact: true })
      await dialog.getByLabel('标题', { exact: true }).fill('网页新增跨端日程')
      await dialog.getByLabel('地点', { exact: true }).fill('A102')
      await dialog.getByRole('button', { name: '保存日程', exact: true }).click()
      await page.getByRole('heading', { name: '网页新增跨端日程', exact: true }).waitFor()
      await page.getByRole('button', { name: '强制完成 网页新增跨端日程', exact: true }).click()
      await page.getByRole('button', { name: '已完成', exact: true }).click()
      await page.getByRole('heading', { name: '网页新增跨端日程', exact: true }).waitFor()
      await page.getByRole('button', { name: '取消强制完成 网页新增跨端日程', exact: true }).click()
      await page.getByRole('button', { name: '待完成', exact: true }).click()
      await page.getByRole('heading', { name: '网页新增跨端日程', exact: true }).waitFor()
      await page.getByRole('heading', { name: '网页新增跨端日程', exact: true }).click()
      await page.getByRole('dialog', { name: '日程详情', exact: true }).getByRole('button', { name: '编辑', exact: true }).click()
      await page.getByRole('dialog', { name: '编辑日程', exact: true }).getByLabel('标题', { exact: true }).fill('网页编辑后的跨端日程')
      await page.getByRole('dialog', { name: '编辑日程', exact: true }).getByRole('button', { name: '保存日程', exact: true }).click()
      await page.getByRole('dialog', { name: '日程详情', exact: true }).getByRole('heading', { name: '网页编辑后的跨端日程', exact: true }).waitFor()
      await page.getByRole('button', { name: '关闭详情', exact: true }).click()
      await page.setViewportSize({ width: 390, height: 844 })
      await page.waitForTimeout(450)
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      await page.screenshot({ path: path.join(output, role + '-calendar-390.png') })
      await page.getByRole('button', { name: '新增日程', exact: true }).click()
      await page.screenshot({ path: path.join(output, role + '-create-390.png') })
      await page.getByRole('dialog', { name: '新增日程', exact: true }).getByRole('button', { name: '关闭日程表单', exact: true }).click()
      if (role === 'super_admin') {
        await page.goto('http://127.0.0.1:5515/inbox')
        await page.locator('.infocenter-surface').getByRole('button', { name: '日程', exact: true }).click()
        assert.equal(await page.getByRole('heading', { name: '线性代数', exact: true }).count(), 0)
        assert.equal(await page.getByLabel('日程来源').locator('option[value="timetable"]').count(), 0)
        checks.push('InfoCenter: stale timetable schedules excluded')
        await page.getByRole('heading', { name: '网页编辑后的跨端日程', exact: true }).waitFor()
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        await page.screenshot({ path: path.join(output, 'infocenter-schedules-390.png') })
        await page.setViewportSize({ width: 1440, height: 1000 })
        await page.screenshot({ path: path.join(output, 'infocenter-schedules-1440.png') })
        await page.getByRole('button', { name: '新增日程', exact: true }).click()
        await page.getByRole('dialog', { name: '新增日程', exact: true }).getByLabel('标题', { exact: true }).fill('InfoCenter 新增日程')
        await page.getByRole('button', { name: '保存日程', exact: true }).click()
        await page.getByRole('heading', { name: 'InfoCenter 新增日程', exact: true }).waitFor()
        checks.push('InfoCenter: same personal schedule CRUD transport')
      }
      await page.getByRole('heading', { name: '网页编辑后的跨端日程', exact: true }).click()
      page.once('dialog', dialog => dialog.accept())
      await page.getByRole('dialog', { name: '日程详情', exact: true }).getByRole('button', { name: '删除', exact: true }).click()
      await page.locator('.schedule-cards').getByRole('heading', { name: '网页编辑后的跨端日程', exact: true }).waitFor({ state: 'hidden' })
      assert.deepEqual(errors, [])
      checks.push(role + ': desktop/mobile visible and no overflow')
      await context.close()
    }
    fs.writeFileSync(path.join(output, '浏览器验收.json'), JSON.stringify({ generated_date: '2026-10-12', summary: 'Mock transport UI CRUD, shared Terminal sources and responsive screenshots', checks }, null, 2))
    console.log(JSON.stringify({ passed: checks.length, checks }))
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
