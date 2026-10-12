import { spawn, execFileSync } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import http from 'node:http'
import assert from 'node:assert/strict'

const upstream=http.createServer((req,res)=>{assert.equal(req.headers.authorization,'Bearer test-secret');res.setHeader('Content-Type','application/json');res.end('{"ok":true}')})
await new Promise(resolve=>upstream.listen(0,'127.0.0.1',resolve))
const port=4189,origin=`http://127.0.0.1:${port}`
const env={...process.env,PORT:String(port),DCP_PUBLIC_ORIGIN:origin,DCP_API_BASE:`http://127.0.0.1:${upstream.address().port}/api/terminal`,DCP_API_TOKEN:'test-secret',DCP_DEVICE_STORE:join(mkdtempSync(join(tmpdir(),'dcp-gate-')),'devices.json')}
const gateway=spawn(process.execPath,['server/gateway.mjs'],{env,stdio:['ignore','pipe','pipe']})
try {
  await new Promise((resolve,reject)=>{gateway.stdout.once('data',resolve);gateway.once('exit',code=>reject(Error(`Gateway exited ${code}`)))})
  assert.equal((await fetch(origin+'/api/messages')).status,403)
  assert.equal((await fetch(origin+'/auth/request',{method:'POST',headers:{Origin:'https://example.invalid'}})).status,403)
  const request=await fetch(origin+'/auth/request',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:'{"name":"test browser"}'})
  assert.equal(request.status,201)
  const {id}=await request.json(),cookie=request.headers.get('set-cookie').split(';')[0]
  assert.match(request.headers.get('set-cookie'),/HttpOnly/)
  assert.equal((await fetch(origin+'/api/messages',{headers:{Cookie:cookie}})).status,403)
  execFileSync(process.execPath,['server/gateway.mjs','approve',id],{env})
  assert.equal((await fetch(origin+'/api/messages',{headers:{Cookie:cookie}})).status,200)
  assert.equal((await fetch(origin+'/api/messages')).status,403)
  assert.equal((await fetch(origin+'/api/messages',{headers:{Cookie:cookie+'tampered'}})).status,403)
  assert.equal((await fetch(origin+'/.env.local',{headers:{Cookie:cookie}})).status,404)
  assert.equal((await fetch(origin+'/api/llm',{headers:{Cookie:cookie}})).status,404)
  assert.equal((await fetch(origin+'/api/messages',{method:'POST',headers:{Cookie:cookie}})).status,405)
  assert.equal((await fetch(origin+'/api/send/prepare',{method:'POST',headers:{Origin:origin}})).status,403)
  assert.equal((await fetch(origin+'/api/send/prepare',{method:'POST',headers:{Cookie:cookie,Origin:'https://example.invalid'}})).status,403)
  assert.equal((await fetch(origin+'/api/send/prepare',{method:'POST',headers:{Cookie:cookie,Origin:origin,'Content-Type':'application/json'},body:'{"chat":"filehelper","text":"mock only"}'})).status,200)
  assert.equal((await fetch(origin+'/api/send/submit',{headers:{Cookie:cookie,Origin:origin}})).status,405)
  execFileSync(process.execPath,['server/gateway.mjs','revoke',id],{env})
  assert.equal((await fetch(origin+'/api/messages',{headers:{Cookie:cookie}})).status,403)
  console.log('PASS: approval, isolation, tampering, revocation, secret-file exclusion, send authorization and Origin checks')
} finally {gateway.kill();await new Promise(resolve=>gateway.once('exit',resolve));upstream.close()}
