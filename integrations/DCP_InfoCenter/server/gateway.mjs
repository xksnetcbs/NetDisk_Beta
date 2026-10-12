import http from 'node:http'
import https from 'node:https'
import { createHash, randomBytes } from 'node:crypto'
import { readFileSync, writeFileSync, renameSync, mkdirSync, existsSync, openSync, closeSync, unlinkSync } from 'node:fs'
import { resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
// BaoTa may launch this file directly from server/, without npm's --env-file.
if (existsSync(root+'/.env.local')) process.loadEnvFile(root+'/.env.local')
const state = resolve(process.env.DCP_DEVICE_STORE || root + '/private/devices.json')
const read = () => existsSync(state) ? JSON.parse(readFileSync(state,'utf8')) : []
function save(rows) { mkdirSync(resolve(state,'..'),{recursive:true,mode:0o700}); writeFileSync(state+'.tmp',JSON.stringify(rows,null,2),{mode:0o600}); renameSync(state+'.tmp',state) }
function mutate(update) {
  mkdirSync(resolve(state,'..'),{recursive:true,mode:0o700})
  const lock=openSync(state+'.lock','wx',0o600)
  try {const rows=read();const result=update(rows);save(rows);return result}
  finally {closeSync(lock);unlinkSync(state+'.lock')}
}
const hash = value => createHash('sha256').update(value).digest('hex')
const [command,id] = process.argv.slice(2)
if (command) {
  const rows=read()
  if(command==='devices') console.table(rows.map(({id,name,status,created,expires})=>({id,name,status,created,expires})))
  else if(['approve','revoke'].includes(command)) {
    mutate(current=>{
      const row=current.find(r=>r.id===id);if(!row)throw Error('Unknown device ID')
      if(command==='approve' && row.status!=='pending')throw Error('Only pending requests can be approved')
      row.status=command==='approve'?'approved':'revoked';console.log(row.id,row.status)
    })
  } else throw Error('Use: devices | approve <id> | revoke <id>')
} else {
  const origin=new URL(process.env.DCP_PUBLIC_ORIGIN || 'http://127.0.0.1:4173')
  const secure=origin.protocol==='https:'
  if(!secure&&!['127.0.0.1','localhost'].includes(origin.hostname))throw Error('Remote access requires HTTPS')
  const cookieName=secure?'__Host-dcp_device':'dcp_device'
  const base=new URL((process.env.DCP_API_BASE || 'http://127.0.0.1:8766/api/terminal').replace(/\/$/,'')+'/desktop/')
  if(base.protocol!=='https:'&&!['localhost','127.0.0.1'].includes(base.hostname))throw Error('Upstream requires HTTPS')
  const token=process.env.DCP_API_TOKEN
  if(!token)throw Error('DCP_API_TOKEN is required on the server')
  const publicFiles=new Map()
  const index=readFileSync(root+'/dist/index.html')
  // Only the built public directory is reachable, never configuration or server files.
  const { readdirSync }=await import('node:fs')
  function collect(dir,prefix='') {for(const entry of readdirSync(dir,{withFileTypes:true})){const path=prefix+'/'+entry.name;if(entry.isDirectory())collect(dir+'/'+entry.name,path);else publicFiles.set(path,dir+'/'+entry.name)}}
  collect(root+'/dist')
  const json=(res,code,data)=>{res.writeHead(code,{'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(data))}
  const server=http.createServer(async(req,res)=>{
    res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer')
    res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    try {
      if(req.headers.host!==origin.host)return json(res,421,{error:'Invalid host'})
      const url=new URL(req.url,origin)
      const credential=(req.headers.cookie||'').split(';').map(x=>x.trim()).find(x=>x.startsWith(cookieName+'='))?.slice(cookieName.length+1)||''
      const rows=read(),device=rows.find(r=>r.hash===hash(credential)&&Date.parse(r.expires)>Date.now())
      if(url.pathname==='/auth/status'&&req.method==='GET')return json(res,200,{status:device?.status||'unregistered',id:device?.id||''})
      if(url.pathname==='/auth/request'&&req.method==='POST') {
        if(req.headers.origin!==origin.origin)return json(res,403,{error:'Origin rejected'})
        if(device)return json(res,200,{status:device.status,id:device.id})
        const active=rows.filter(r=>Date.parse(r.expires)>Date.now())
        if(active.filter(r=>r.status==='pending').length>=100)return json(res,429,{error:'Too many pending requests'})
        let body='';for await(const chunk of req){body+=chunk;if(body.length>1024)return json(res,413,{error:'Request too large'})}
        const name=String(JSON.parse(body||'{}').name||'Browser').trim().slice(0,80)
        const secret=randomBytes(32).toString('base64url'),id=randomBytes(8).toString('hex')
        // Re-read under the same lock used by approval/revocation; a slow request
        // must not restore a stale authorization list after an admin revokes it.
        mutate(current=>{
          const valid=current.filter(r=>Date.parse(r.expires)>Date.now())
          if(valid.filter(r=>r.status==='pending').length>=100)throw Error('Too many pending requests')
          valid.push({id,hash:hash(secret),name,status:'pending',created:new Date().toISOString(),expires:new Date(Date.now()+90*86400000).toISOString()})
          current.splice(0,current.length,...valid)
        })
        res.setHeader('Set-Cookie',`${cookieName}=${secret}; HttpOnly; SameSite=Strict; Path=/; Max-Age=7776000${secure?'; Secure':''}`)
        return json(res,201,{status:'pending',id})
      }
      const approved=device?.status==='approved'
      if(url.pathname.startsWith('/api/')) {
        if(!approved)return json(res,403,{error:'此设备尚未获准访问',device_required:true})
        const suffix=url.pathname.slice(5)
        const sending=/^send\/(prepare|select|submit|cancel|status)$/.test(suffix)
        if(!['GET','HEAD'].includes(req.method)&&!(sending&&req.method==='POST'))return json(res,405,{error:'Method not allowed'})
        if(sending&&req.method!=='POST')return json(res,405,{error:'POST required'})
        if(sending&&req.headers.origin!==origin.origin)return json(res,403,{error:'Origin rejected'})
        if(!sending&&!/^(status|conversations|messages(?:\/\d+\/(?:file|media))?)$/.test(suffix))return json(res,404,{error:'Not found'})
        let body
        if(sending){let value='';for await(const chunk of req){value+=chunk;if(value.length>30*1024*1024)return json(res,413,{error:'消息或附件过大'})}body=Buffer.from(value)}
        const upstream=new URL(suffix+url.search,base)
        const headers={Authorization:'Bearer '+token}
        if(body){headers['Content-Type']='application/json';headers['Content-Length']=String(body.length)}
        if(req.headers.range)headers.Range=req.headers.range
        const remote=(upstream.protocol==='https:'?https:http).request(upstream,{method:req.method,headers,timeout:45000},reply=>{
          if(reply.statusCode>=300&&reply.statusCode<400){reply.resume();return json(res,502,{error:'Upstream redirect rejected'})}
          for(const key of ['content-type','content-length','content-disposition','accept-ranges','content-range'])if(reply.headers[key])res.setHeader(key,reply.headers[key])
          res.writeHead(reply.statusCode);reply.pipe(res)
        })
        remote.on('timeout',()=>remote.destroy());remote.on('error',()=>{if(!res.headersSent)json(res,502,{error:'上游服务暂不可用'});else res.destroy()});res.on('close',()=>remote.destroy());remote.end(body);return
      }
      if(!['GET','HEAD'].includes(req.method))return json(res,405,{error:'Method not allowed'})
      if(!approved){res.setHeader('Content-Type','text/html; charset=utf-8');if(url.pathname==='/access.js'){res.setHeader('Content-Type','text/javascript');return res.end(readFileSync(root+'/server/access.js'))}return res.end(readFileSync(root+'/server/access.html'))}
      if(url.pathname==='/'){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(index)}
      const file=publicFiles.get(url.pathname)
      if(!file)return json(res,404,{error:'Not found'})
      res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.html':'text/html','.svg':'image/svg+xml','.png':'image/png'})[extname(file)]||'application/octet-stream');res.end(req.method==='HEAD'?undefined:readFileSync(file))
    } catch {if(!res.headersSent)json(res,400,{error:'Invalid request'});else res.destroy()}
  })
  server.listen(Number(process.env.PORT||4173),'127.0.0.1',()=>console.log('Device-protected gateway:',origin.origin))
}
