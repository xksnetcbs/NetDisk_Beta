import {chromium} from '@playwright/test'
import assert from 'node:assert/strict'
const browser=await chromium.launch({headless:true})
const page=await browser.newPage({viewport:{width:1440,height:960}})
const errors=[];page.on('pageerror',e=>errors.push(e.message))
let sends=0
try{
 await page.route('**/api/send/**',async route=>{
  sends++;assert.equal(route.request().url().split('/').pop(),'prepare')
  await route.fulfill({json:{id:'mock',status:'submitted'}})
 })
 await page.goto(process.env.TEST_URL || 'http://127.0.0.1:5173')
 await page.getByRole('button',{name:'发送到文件传输助手',exact:true}).click()
 await page.getByLabel('消息内容').fill('Mock UI check only')
 await page.getByRole('button',{name:'直接发送',exact:true}).click()
 await page.getByText('已交给微信发送',{exact:true}).waitFor()
 await page.getByLabel('消息内容').fill('Second draft is editable')
 assert.equal(await page.getByLabel('消息内容').inputValue(),'Second draft is editable')
 assert.equal(sends,1)
 assert.equal(await page.locator('.send-dialog').count(),0)
 await page.screenshot({path:'work/send144-desktop.png'})
 await page.setViewportSize({width:390,height:844})
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
 assert.deepEqual(errors,[])
 console.log('PASS: direct single request, no confirmation, editable after sending, mobile overflow; no real sends')
}finally{await browser.close()}
