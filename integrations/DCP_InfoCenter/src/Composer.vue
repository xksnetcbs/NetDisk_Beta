<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useInfoCenterRuntime } from './runtime'
const runtime = useInfoCenterRuntime()
const props=defineProps<{chat:string;name:string;messageUid?:string}>()
const emit=defineEmits<{sent:[]}>()
const draft=ref(''),busy=ref(false),error=ref(''),notice=ref(''),attachment=ref<{name:string;type:string;data:string}|null>(null)
const internal = computed(() => props.chat.startsWith('netdisk:'))
const unnamed=computed(()=>!internal.value&&props.chat!=='filehelper'&&(!props.name.trim()||props.name===props.chat||props.name.endsWith('@chatroom')))
let pending:{key:string;id:string}|null=null
async function request(action:string,body:object){if(internal.value){if(!runtime?.sendNetdisk)throw Error('此会话需要通过 NetDisk 发送');return runtime.sendNetdisk(props.chat,{...body,message_uid:props.messageUid})}if(runtime)return runtime.request<{status:string}>('/send/'+action,{method:'POST',body});const response=await fetch('/api/send/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.error||'发送请求失败');return data}
function readFile(file:File){return new Promise<string>((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]||'');r.onerror=()=>reject(r.error||Error('读取附件失败'));r.readAsDataURL(file)})}
async function attach(file?:File){if(!file)return;if(internal.value){error.value='站内会话当前仅支持文字';return}if(file.size>20*1024*1024){error.value='附件不能超过 20 MB';return}try{attachment.value={name:file.name,type:file.type||'application/octet-stream',data:await readFile(file)};error.value=''}catch(e){error.value=(e as Error).message}}
async function paste(e:ClipboardEvent){const file=[...(e.clipboardData?.files||[])][0];if(file){e.preventDefault();await attach(file)}}
async function submit(){if(busy.value||unnamed.value||(!draft.value.trim()&&!attachment.value))return;const chat=props.chat,text=draft.value,file=attachment.value;const key=JSON.stringify({chat,text,file});if(pending?.key!==key)pending={key,id:crypto.randomUUID()};busy.value=true;error.value='';notice.value='';try{const result=await request('prepare',{id:pending!.id,chat,text,attachment:file});if(!['submitted','confirmed'].includes(result.status))throw Error(result.status==='uncertain'?'发送结果待核实，请检查微信记录，勿重复发送':'未完成发送：'+result.status);if(props.chat===chat){draft.value='';attachment.value=null;notice.value=result.status==='confirmed'?'已确认发送':'已交给微信发送';}pending=null;emit('sent')}catch(e){if(props.chat===chat)error.value=(e as Error).message}finally{busy.value=false}}
function drop(e:DragEvent){e.preventDefault();attach(e.dataTransfer?.files?.[0])}
watch(()=>props.chat,()=>{draft.value='';attachment.value=null;notice.value='';error.value=''})
</script>
<template>
 <section class="composer">
  <div class="composer-heading"><span>发送至 {{ name }}</span><small>{{ internal ? 'NetDisk 站内消息 · 文字' : '微信 · 文字 / 文件 / 图片' }}</small></div>
  <p v-if="unnamed" class="send-error">此会话没有可识别的名称，暂不能发送。</p>
  <div class="attachment-chip" v-if="attachment">{{ attachment.name }} <button type="button" @click="attachment=null" aria-label="移除附件">×</button></div>
  <textarea v-model="draft" :disabled="busy" maxlength="4000" rows="2" aria-label="消息内容" :placeholder="internal ? '输入站内消息' : '输入消息，拖入或粘贴文件/图片'" @paste="paste" @dragover.prevent @drop="drop" />
  <div class="composer-actions"><small>{{ draft.length }} / 4000</small><label v-if="!internal" class="file-button">添加附件<input type="file" hidden :disabled="busy" @change="attach(($event.target as HTMLInputElement).files?.[0])" /></label><button class="primary-button" :disabled="busy||unnamed||(!draft.trim()&&!attachment)" @click="submit">{{ busy?'发送中…':internal?'发送站内消息':'直接发送' }}</button></div>
  <p v-if="notice" role="status">{{ notice }}</p><p v-if="error" role="alert" class="send-error">{{ error }}</p>
 </section>
</template>
<style scoped>
.composer-actions{justify-content:flex-end}.composer-actions>small{margin-right:auto;white-space:nowrap;flex-shrink:0}.composer-actions>button{width:auto;flex-shrink:0;white-space:nowrap;margin:0}.composer-actions>.primary-button{padding:9px 16px}.send-dialog .composer-actions{flex-wrap:wrap}.send-dialog .composer-actions>.text-button{min-width:72px}.send-dialog h2{margin-bottom:8px}.send-dialog p{margin-bottom:8px}
.attachment-chip{display:flex;gap:8px;align-items:center;font-size:11px;color:var(--secondary);padding:4px 0}.attachment-chip button{font-size:15px}.file-button{font-size:11px;color:var(--secondary);cursor:pointer}
.composer{border-top:1px solid var(--line);background:var(--panel);padding:10px 20px}.composer-heading,.composer-actions{display:flex;align-items:center;justify-content:space-between;gap:12px}.composer-heading{font-size:11px;color:var(--secondary);margin-bottom:8px}.composer small{color:var(--muted);font-size:10px}.composer textarea{width:100%;resize:vertical;max-height:160px;min-height:52px;border:0;background:var(--sidebar);color:var(--text);padding:9px;border-radius:6px;font:inherit}.composer-actions{margin-top:8px}.composer p{font-size:11px}.send-error{color:var(--danger)}.send-dialog{background:var(--panel);color:var(--text);padding:20px;border-radius:12px;width:min(960px,95vw);max-height:95dvh;overflow:auto}.send-dialog p{line-height:1.6;font-size:12px}.send-dialog img{width:100%;max-height:65vh;object-fit:contain;background:#202020}.primary-button:disabled{opacity:.5;cursor:default}@media(max-width:720px){.composer{padding:9px 12px}.send-dialog{width:100%;border-radius:12px 12px 0 0}}
</style>
