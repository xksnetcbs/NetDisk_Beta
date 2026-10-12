import {_electron as electron} from '@playwright/test'
import assert from 'node:assert/strict'
const env={...process.env};delete env.ELECTRON_RUN_AS_NODE
for(const offline of [false,true]){
 const app=await electron.launch({args:['electron/main.cjs'],env:offline?{...env,DCP_ELECTRON_URL:'http://127.0.0.1:1/'}:env})
 try{
  const page=await app.firstWindow();page.setDefaultTimeout(15000);await page.waitForLoadState('domcontentloaded');console.log('Electron URL',page.url());await page.screenshot({path:'work/electron144-debug.png'})
  if(offline)await page.getByText('暂时无法连接 InfoCenter',{exact:true}).waitFor()
  else {await page.waitForURL(new URL(process.env.DCP_ELECTRON_URL || 'http://127.0.0.1:4173').href);await page.locator('body').filter({hasText:/设备|InfoCenter/}).waitFor()}
  assert.ok(await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].isVisible()))
  await page.screenshot({path:offline?'work/electron144-offline.png':'work/electron144-online.png'})
 }finally{await app.close()}
}
console.log('PASS: Electron opens live domain and displays a retry page on connection failure')
