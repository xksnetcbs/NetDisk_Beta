import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
const browser=await chromium.launch({headless:true})
try {
 const page=await browser.newPage({viewport:{width:390,height:844}})
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto(process.env.TEST_URL || 'http://127.0.0.1:5173')
 await page.locator('.conversation').first().click()
 await page.locator('.chat-heading').waitFor()
 const title=await page.locator('.chat-title').boundingBox()
 await page.mouse.move(title.x+10,title.y+12);await page.mouse.down();await page.mouse.move(title.x+190,title.y+12,{steps:15});await page.mouse.up()
 await page.waitForFunction(()=>!document.querySelector('.app-shell').classList.contains('mobile-chat'))
 await page.getByRole('button',{name:'连接信息',exact:true}).click()
 const header=await page.locator('.dialog header').boundingBox()
 await page.mouse.move(header.x+80,header.y+20);await page.mouse.down();await page.mouse.move(header.x+80,header.y+210,{steps:15});await page.mouse.up()
 await page.locator('.dialog').waitFor({state:'hidden'})
 await page.screenshot({path:'work/motion-mobile.png'})
 await page.emulateMedia({reducedMotion:'reduce'})
 await page.getByRole('button',{name:'媒体',exact:true}).click()
 await page.locator('.media-card').first().waitFor()
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
 assert.deepEqual(errors,[])
 console.log('PASS: mobile drag-back, sheet drag-dismiss, reduced motion, no overflow or JS errors')
} finally {await browser.close()}
