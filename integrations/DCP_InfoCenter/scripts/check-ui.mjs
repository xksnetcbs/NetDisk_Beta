import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
import { mkdir, stat } from 'node:fs/promises'

await mkdir('work', { recursive: true })
const base = process.env.TEST_URL || 'http://127.0.0.1:5173'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 })
const failures = []
page.on('pageerror', e => failures.push(e.message))
try {
  await page.goto(base)
  await page.locator('.conversation').first().waitFor()
  await page.locator('.message').first().waitFor()
  await page.screenshot({ path: 'work/desktop.png', animations: 'disabled' })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  await page.getByRole('button', { name: '文件', exact: true }).click()
  await page.locator('tbody tr').first().waitFor()
  await page.screenshot({ path: 'work/files.png', animations: 'disabled' })
  const rows = await (await page.request.get(base + '/api/messages?kind=file')).json()
  const downloadable = rows.items.find(m => m.attachment?.available && m.attachment.size < 2 * 1024 * 1024)
  assert.ok(downloadable, 'Need one real downloadable attachment')
  const download = await page.request.get(base + '/api/messages/' + downloadable.id + '/file')
  assert.equal(download.status(), 200)
  assert.equal((await download.body()).length, downloadable.attachment.size)
  assert.match(download.headers()['content-disposition'], /attachment/)
  const [saved] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('tbody tr').filter({ hasText: downloadable.attachment.name }).first().getByRole('button', { name: '下载文件' }).click(),
  ])
  assert.equal((await stat(await saved.path())).size, downloadable.attachment.size)
  await page.getByLabel('搜索文件名').fill('no-such-document-923839')
  await page.getByText('没有匹配的文件', { exact: true }).waitFor()
  await page.getByLabel('搜索文件名').fill('')
  await page.locator('tbody tr').first().waitFor()
  await page.getByRole('button', { name: '切换配色' }).click()
  await page.screenshot({ path: 'work/files-dark.png', animations: 'disabled' })
  await page.getByRole('button', { name: '会话', exact: true }).click()
  await page.getByRole('button', { name: '会话文件', exact: true }).click()
  await page.waitForTimeout(450)
  await page.getByRole('button', { name: '显示全部消息', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('.conversation').first().click()
  await page.waitForTimeout(600)
  await page.screenshot({ path: 'work/mobile.png', animations: 'disabled' })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  assert.deepEqual(failures, [])
  console.log(JSON.stringify({ browserErrors: failures.length, realDownloadBytes: downloadable.attachment.size, desktop: '1440x960', mobile: '390x844', checks: ['conversations', 'messages', 'files', 'search', 'themes', 'download'] }))
} finally { await browser.close() }
