const {app,BrowserWindow,Tray,Menu,globalShortcut,desktopCapturer,nativeImage,screen}=require('electron')
const path=require('node:path'),fs=require('node:fs')
let win,tray
const url=process.env.DCP_ELECTRON_URL||'http://127.0.0.1:4173'
function create(){
 win=new BrowserWindow({width:1440,height:920,show:true,backgroundColor:'#f3f5f4',webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true}})
 win.webContents.on('did-fail-load',(_event,code,_description,_url,main)=>{
  if(!main||code===-3)return
  win.loadFile(path.join(__dirname,'offline.html'))
 })
 win.webContents.on('will-navigate',(event,target)=>{if(target==='https://dcp-retry.invalid/'){event.preventDefault();win.loadURL(url)}})
 win.loadURL(url)
 win.on('close',e=>{if(!app.isQuitting){e.preventDefault();win.hide()}})
}
async function shot(){const display=screen.getPrimaryDisplay();const sources=await desktopCapturer.getSources({types:['screen'],thumbnailSize:{width:display.bounds.width*display.scaleFactor,height:display.bounds.height*display.scaleFactor}});const image=sources[0]?.thumbnail;if(!image||image.isEmpty())return;const dir=path.join(app.getPath('pictures'),'DCP InfoCenter');fs.mkdirSync(dir,{recursive:true});const file=path.join(dir,'截屏-'+new Date().toISOString().replaceAll(':','-')+'.png');fs.writeFileSync(file,image.toPNG());if(win&&!win.isDestroyed())win.webContents.send('screenshot-saved',file)}
if(!app.requestSingleInstanceLock())app.quit()
else {
app.on('second-instance',()=>{if(win){win.show();win.focus()}})
app.whenReady().then(()=>{create();const pixels=Buffer.alloc(16*16*4);for(let i=0;i<pixels.length;i+=4){pixels[i]=118;pixels[i+1]=146;pixels[i+2]=42;pixels[i+3]=255}tray=new Tray(nativeImage.createFromBitmap(pixels,{width:16,height:16}));tray.setToolTip('DCP InfoCenter');tray.on('double-click',()=>{win.show();win.focus()});tray.setContextMenu(Menu.buildFromTemplate([{label:'显示窗口',click:()=>win.show()},{label:'重新连接',click:()=>win.loadURL(url)},{label:'退出',click:()=>{app.isQuitting=true;app.quit()}}]));globalShortcut.register('Alt+A',shot)})
}
app.on('before-quit',()=>{app.isQuitting=true});app.on('window-all-closed',()=>{});app.on('will-quit',()=>globalShortcut.unregisterAll())
