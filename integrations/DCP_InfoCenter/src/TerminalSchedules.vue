<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CalendarDays, Check, CheckCircle2, Clock, MapPin, Plus, RefreshCw, Trash2, X } from 'lucide-vue-next'
type Schedule = { id: string; title: string; start_at: number; end_at: number; location?: string; description?: string; course?: string; source: string; url?: string; forced_completed: boolean; source_completed: boolean; completed: boolean; status: string; all_day?: boolean; editable?: boolean; deletable?: boolean }
type Transport = (path: string, options?: { method?: string; body?: object; signal?: AbortSignal }) => Promise<any>
const props = defineProps<{ request: Transport }>()
const schedules = ref<Schedule[]>([]), busy = ref(false), saving = ref(false), error = ref(''), partial = ref(false)
const filter = ref('active'), source = ref('all'), query = ref(''), selected = ref<Schedule | null>(null)
const editing = ref(false), dialog = ref(false), requestId = ref('')
const form = ref({ title: '', start: '', end: '', location: '', description: '', all_day: false })
let timer: ReturnType<typeof setTimeout>, stopped = false
const controller = new AbortController()
const format = (time: number) => time <= 0 ? "未设置截止时间" : new Date(time).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit' })
const inputDate = (time: number) => { const d = new Date(time); return new Date(time - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }
const sourceLink = (row: Schedule) => row.url && (/^https?:\/\//i.test(row.url) || /^\/(?!\/)/.test(row.url)) && !row.url.includes("\\") ? row.url : ""
const sources = computed(() => [...new Set(schedules.value.map(row => row.source))])
const label = (value: string) => ({ netdisk: '网盘', terminal: '微信识别', calendar: 'Canvas / 日历' } as Record<string,string>)[value] || value
const shown = computed(() => schedules.value.filter(row => row.status !== 'cancelled' && (source.value === 'all' || row.source === source.value) && (!query.value || `${row.title} ${row.course || ''} ${row.location || ''}`.toLowerCase().includes(query.value.toLowerCase())) && (filter.value === 'all' || (filter.value === 'done' ? row.completed : !row.completed))).sort((a, b) => Number(a.completed) - Number(b.completed) || (a.completed ? (b.end_at || Number.MAX_SAFE_INTEGER) - (a.end_at || Number.MAX_SAFE_INTEGER) : (a.end_at || Number.MAX_SAFE_INTEGER) - (b.end_at || Number.MAX_SAFE_INTEGER))))
const unfinished = computed(() => schedules.value.filter(row => !row.completed && row.status !== 'cancelled').length)
async function load() {
  if (busy.value || stopped) return
  busy.value = true
  try {
    const data = await props.request('', { signal: controller.signal })
    if (stopped) return
    schedules.value = (data.schedules || []).filter((row: Schedule) => row.source !== 'timetable' && !String(row.id || '').startsWith('timetable:'))
    partial.value = !!(data.upstream_unavailable || data.calendar_unavailable)
    if (selected.value) selected.value = schedules.value.find(row => row.id === selected.value?.id) || null
    error.value = ''
  } catch (e) { if (!stopped) error.value = (e as Error).message }
  finally { busy.value = false }
}
async function poll() { if (stopped) return; if (!document.hidden) await load(); if (!stopped) timer = setTimeout(poll, 15000) }
function openCreate() {
  selected.value = null; editing.value = false; requestId.value = crypto.randomUUID()
  const start = Date.now(); form.value = { title: '', start: inputDate(start), end: inputDate(start + 3600000), location: '', description: '', all_day: false }; dialog.value = true
}
function openEdit(row: Schedule) {
  editing.value = true; form.value = { title: row.title, start: inputDate(row.start_at), end: inputDate(row.end_at), location: row.location || '', description: row.description || '', all_day: !!row.all_day }; dialog.value = true
}
async function save() {
  if (saving.value) return
  const start = new Date(form.value.start).getTime(), end = new Date(form.value.end).getTime()
  if (!form.value.title.trim() || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) { error.value = '请输入标题，并让结束时间晚于开始时间'; return }
  saving.value = true
  try {
    const body = { title: form.value.title.trim(), start_at: start, end_at: end, location: form.value.location, description: form.value.description, all_day: form.value.all_day }
    await props.request(editing.value ? '/' + encodeURIComponent(selected.value!.id) : '', { method: editing.value ? 'PATCH' : 'POST', body: editing.value ? body : { ...body, id: requestId.value }, signal: controller.signal })
    if (stopped) return
    dialog.value = false; await load()
  } catch (e) { if (!stopped) error.value = (e as Error).message }
  finally { saving.value = false }
}
async function complete(row: Schedule) {
  if (saving.value) return
  saving.value = true
  try {
    const data = await props.request('/' + encodeURIComponent(row.id), { method: 'PATCH', body: { forced_completed: !row.forced_completed }, signal: controller.signal })
    if (stopped) return
    const next = { ...row, ...data.schedule }; schedules.value = schedules.value.map(item => item.id === row.id ? next : item)
    if (selected.value?.id === row.id) selected.value = next
    error.value = ''
  } catch (e) { if (!stopped) error.value = (e as Error).message }
  finally { saving.value = false }
}
async function remove(row: Schedule) {
  if (saving.value || !confirm(`删除“${row.title}”？`)) return
  saving.value = true
  try {
    await props.request('/' + encodeURIComponent(row.id), { method: 'DELETE', signal: controller.signal })
    if (!stopped) { schedules.value = schedules.value.filter(item => item.id !== row.id); selected.value = null }
  } catch (e) { if (!stopped) error.value = (e as Error).message }
  finally { saving.value = false }
}
onMounted(poll)
onBeforeUnmount(() => { stopped = true; clearTimeout(timer); controller.abort() })
</script>
<template>
  <section class="terminal-schedules" aria-label="Terminal 日程">
    <header class="schedule-heading"><div><div class="schedule-eyebrow">DCP TERMINAL</div><h1><CalendarDays :size="25" />日程</h1><p>{{ unfinished }} 项待完成 · 当前账号同步</p></div><div class="schedule-actions"><button :disabled="busy" @click="load"><RefreshCw :size="17" :class="{ spinning: busy }" /><span>刷新</span></button><button class="accent" @click="openCreate"><Plus :size="18" /><span>新增日程</span></button></div></header>
    <div v-if="error" class="schedule-error" role="alert">{{ error }}</div><div v-if="partial" class="schedule-notice">部分共享日程暂时无法连接，已显示可用日程。稍后可刷新重试。</div>
    <div class="schedule-toolbar"><div class="schedule-tabs"><button v-for="tab in [{ id: 'active', text: '待完成' }, { id: 'done', text: '已完成' }, { id: 'all', text: '全部' }]" :key="tab.id" :class="{ active: filter === tab.id }" @click="filter = tab.id">{{ tab.text }}</button></div><select v-model="source" aria-label="日程来源"><option value="all">全部来源</option><option v-for="value in sources" :key="value" :value="value">{{ label(value) }}</option></select><input v-model="query" placeholder="搜索日程、课程或地点" aria-label="搜索日程" /></div>
    <div class="schedule-scroll"><div class="schedule-cards"><article v-for="row in shown" :key="row.id" class="schedule-card" :class="{ completed: row.completed, overdue: !row.completed && row.end_at > 0 && row.end_at < Date.now() }"><button class="schedule-card-content" @click="selected = row"><div class="schedule-card-top"><span>{{ row.course || label(row.source) }}</span><span v-if="row.forced_completed" class="schedule-state"><CheckCircle2 :size="14" />已强制完成</span><span v-else-if="row.source_completed" class="schedule-state"><Check :size="14" />已完成</span><span v-else-if="row.end_at > 0 && row.end_at < Date.now()" class="schedule-state">已逾期</span></div><h2>{{ row.title }}</h2><p><Clock :size="15" />{{ format(row.end_at) }}</p><p v-if="row.location"><MapPin :size="15" />{{ row.location }}</p></button><button class="schedule-complete" :disabled="saving" :aria-label="row.forced_completed ? '取消强制完成 ' + row.title : '强制完成 ' + row.title" :title="row.forced_completed ? '取消强制完成' : '强制完成'" @click="complete(row)"><CheckCircle2 v-if="row.completed" :size="22" /><span v-else class="schedule-empty-check" /></button></article></div><div v-if="!shown.length" class="schedule-empty"><CalendarDays :size="32" /><h2>{{ busy ? '正在同步日程' : '没有匹配的日程' }}</h2><p>新增的个人日程会同步到 APK、网盘和 InfoCenter。</p></div></div>
    <div v-if="selected && !dialog" class="schedule-backdrop" @click.self="selected = null"><section class="schedule-dialog" role="dialog" aria-modal="true" aria-label="日程详情"><header><h2>{{ selected.title }}</h2><button aria-label="关闭详情" @click="selected = null"><X :size="20" /></button></header><p class="schedule-detail-source">{{ selected.course || label(selected.source) }}</p><p><Clock :size="17" />{{ format(selected.start_at) }} — {{ format(selected.end_at) }}</p><p v-if="selected.location"><MapPin :size="17" />{{ selected.location }}</p><div class="schedule-description">{{ selected.description }}</div><p v-if="selected.source_completed" class="schedule-notice">来源已标记完成。取消强制完成会保留来源状态。</p><footer><a v-if="sourceLink(selected)" :href="sourceLink(selected)" target="_blank" rel="noopener noreferrer">打开来源</a><button :disabled="saving" @click="complete(selected)">{{ selected.forced_completed ? '取消强制完成' : '强制完成' }}</button><button v-if="selected.editable" @click="openEdit(selected)">编辑</button><button v-if="selected.deletable" class="danger" :disabled="saving" @click="remove(selected)"><Trash2 :size="16" />删除</button></footer></section></div>
    <div v-if="dialog" class="schedule-backdrop" @click.self="!saving && (dialog = false)"><form class="schedule-dialog" role="dialog" aria-modal="true" :aria-label="editing ? '编辑日程' : '新增日程'" @submit.prevent="save"><header><h2>{{ editing ? '编辑日程' : '新增日程' }}</h2><button type="button" :disabled="saving" aria-label="关闭日程表单" @click="dialog = false"><X :size="20" /></button></header><label>标题<input v-model="form.title" required maxlength="255" placeholder="安排什么？" /></label><div class="schedule-time-fields"><label>开始<input v-model="form.start" type="datetime-local" required /></label><label>结束<input v-model="form.end" type="datetime-local" required /></label></div><label>地点<input v-model="form.location" maxlength="255" /></label><label>描述<textarea v-model="form.description" rows="4" maxlength="20000" /></label><label class="schedule-checkbox"><input v-model="form.all_day" type="checkbox" />全天</label><p>保存到当前账号，其他设备登录后自动同步。</p><div v-if="error" class="schedule-error" role="alert">{{ error }}</div><footer><button type="button" :disabled="saving" @click="dialog = false">取消</button><button type="submit" class="accent" :disabled="saving">{{ saving ? '保存中…' : '保存日程' }}</button></footer></form></div>
  </section>
</template>
<style scoped>
.terminal-schedules{--ts-bg:var(--panel,var(--dcp-panel-solid,#fff));--ts-line:var(--line,var(--dcp-border,#dce3e8));--ts-ink:var(--text,var(--dcp-text,#263a46));--ts-muted:var(--muted,var(--dcp-muted,#697d86));--ts-accent:var(--accent,#457f74);color:var(--ts-ink);display:flex;flex-direction:column;height:100%;min-height:400px;background:var(--ts-bg);font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;font-size:14px;line-height:1.5;overflow:hidden}.schedule-heading{display:flex;align-items:center;justify-content:space-between;padding:24px 28px;gap:16px;border-bottom:1px solid var(--ts-line)}.schedule-eyebrow{font-size:11px;letter-spacing:2px;color:var(--ts-muted)}.terminal-schedules h1{display:flex;align-items:center;gap:9px;font-size:25px;margin:5px 0}.terminal-schedules p{margin:6px 0;color:var(--ts-muted)}.terminal-schedules button,.terminal-schedules input,.terminal-schedules textarea,.terminal-schedules select{font:inherit}.terminal-schedules :where(button){cursor:pointer;background:transparent;border:1px solid var(--ts-line);color:inherit;border-radius:9px;padding:8px 12px;display:inline-flex;align-items:center;justify-content:center;gap:6px}button:disabled{opacity:.5;cursor:wait}.terminal-schedules button.accent{background:var(--ts-accent);border-color:var(--ts-accent);color:white}.schedule-actions,.schedule-tabs{display:flex;gap:8px}.schedule-toolbar{padding:16px 28px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}.schedule-tabs{gap:4px;background:color-mix(in srgb,var(--ts-muted) 8%,transparent);padding:3px;border-radius:10px}.schedule-tabs button{border:0;padding:6px 14px}.schedule-tabs button.active{background:var(--ts-bg);box-shadow:0 1px 4px #0001;color:var(--ts-accent)}.terminal-schedules :where(input,select,textarea){background:var(--ts-bg);color:inherit;border:1px solid var(--ts-line);padding:9px 11px;border-radius:8px;box-sizing:border-box;min-width:0}.schedule-toolbar input{flex:1;min-width:150px}.schedule-scroll{flex:1;min-height:0;overflow:auto;padding:0 28px 28px}.schedule-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}.schedule-card{border:1px solid var(--ts-line);border-radius:12px;display:flex;align-items:center;overflow:hidden}.schedule-card.overdue{border-left:3px solid #bb826e}.schedule-card.completed{opacity:.75}.schedule-card-content{display:block;text-align:left;border:0;border-radius:0;flex:1;min-width:0;padding:17px 15px}.schedule-card-top{display:flex;gap:12px;justify-content:space-between;flex-wrap:wrap;color:var(--ts-muted);font-size:11px}.schedule-card h2{font-size:16px;margin:9px 0;overflow-wrap:anywhere}.schedule-card p,.schedule-state{display:flex;align-items:center;gap:6px;font-size:12px}.schedule-state{color:var(--ts-accent)}.schedule-complete{border:0;margin:0 12px 0 0;padding:10px;color:var(--ts-accent)}.schedule-empty-check{width:20px;height:20px;border:1.5px solid var(--ts-muted);border-radius:50%;display:block}.schedule-empty{padding:55px 15px;text-align:center;color:var(--ts-muted)}.schedule-empty svg{margin:auto}.schedule-empty h2{font-size:18px}.schedule-error,.schedule-notice{padding:10px 15px;margin:12px 28px 0;border-radius:8px;background:color-mix(in srgb,#bd7159 12%,transparent);color:#aa614c}.schedule-notice{background:color-mix(in srgb,var(--ts-accent) 10%,transparent);color:var(--ts-muted)}.schedule-backdrop{position:fixed;inset:0;z-index:2000;background:#14263170;display:flex;align-items:center;justify-content:center;padding:18px}.schedule-dialog{background:var(--ts-bg);color:var(--ts-ink);border:1px solid var(--ts-line);border-radius:15px;box-shadow:0 15px 70px #0003;width:560px;max-width:100%;max-height:90dvh;overflow:auto;padding:23px;box-sizing:border-box}.schedule-dialog header{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:20px}.schedule-dialog h2{margin:0;font-size:20px;overflow-wrap:anywhere}.schedule-dialog header button{border:0;padding:5px}.schedule-dialog label{display:flex;flex-direction:column;gap:6px;margin-top:13px;font-size:13px}.schedule-time-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}.schedule-dialog footer{display:flex;justify-content:flex-end;gap:9px;flex-wrap:wrap;margin-top:24px}.schedule-dialog p{display:flex;align-items:center;gap:6px;font-size:12px}.schedule-dialog .schedule-checkbox{flex-direction:row;align-items:center}.schedule-description{white-space:pre-wrap;overflow-wrap:anywhere;margin-top:18px;max-height:35dvh;overflow:auto}.schedule-dialog footer a{display:inline-flex;align-items:center;padding:8px 12px;border:1px solid var(--ts-line);border-radius:9px;color:var(--ts-accent);text-decoration:none}.danger{color:#ae6455}.spinning{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:600px){.schedule-heading{padding:17px 16px;align-items:flex-start;flex-wrap:wrap}.schedule-heading>div:first-child{flex:1 0 100%}.schedule-actions{margin-left:auto}.schedule-actions{gap:5px}.schedule-actions button{padding:8px;white-space:nowrap}.schedule-actions button:first-child span{display:none}.schedule-toolbar{padding:12px 16px;gap:8px}.schedule-tabs button{padding:6px 12px}.schedule-toolbar input{flex-basis:100%}.schedule-scroll{padding:0 16px 20px}.schedule-cards{grid-template-columns:1fr}.schedule-error,.schedule-notice{margin-left:16px;margin-right:16px}.schedule-time-fields{grid-template-columns:1fr}.schedule-dialog{padding:20px;max-height:94dvh}.schedule-heading h1{font-size:22px}}@media(prefers-reduced-motion:reduce){.spinning{animation:none}}
</style>
