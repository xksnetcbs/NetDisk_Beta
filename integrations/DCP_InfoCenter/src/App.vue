<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { MessageSquare, FolderOpen, Search, Settings, RefreshCw, Download, FileText, FileSpreadsheet, FileArchive, File, ChevronLeft, ChevronDown, X, Moon, Sun, BellOff, Users, Link, Image, Mic, Video, Smile, ShieldCheck, Check, AlertCircle, ArrowDown, ExternalLink, LockKeyhole, MoreHorizontal, CalendarDays } from 'lucide-vue-next'
import { api as standaloneApi, fileUrl, formatSize, timeLabel } from './api'
import type { Conversation, Message, Status } from './types'
import { vMotion, vSwipe } from './motion'
import Composer from './Composer.vue'
import TerminalSchedules from './TerminalSchedules.vue'
import { useAuthenticatedMedia, useInfoCenterRuntime } from './runtime'

const props = defineProps<{ embedded?: boolean }>()
const runtime = useInfoCenterRuntime()
const mediaUrl = useAuthenticatedMedia(runtime)
const api = <T,>(path: string, signal?: AbortSignal): Promise<T> => runtime ? runtime.request<T>(path, { signal }) : standaloneApi<T>(path, signal)

const conversations = ref<Conversation[]>([]), messages = ref<Message[]>([]), files = ref<Message[]>([])
const sendHelper = ref(false)
const status = ref<Status | null>(null), selectedId = ref(''), view = ref<'chats' | 'files' | 'media' | 'schedules'>('chats')
const mediaItems = ref<Message[]>([]), mediaFilter = ref('all'), mediaBefore = ref<string | null>(null), mediaMore = ref(false), mediaLoading = ref(false)
const shownMedia = computed(() => [...mediaItems.value].reverse().filter(m => mediaFilter.value === 'all' || m.kind === mediaFilter.value || (mediaFilter.value === 'ready' && m.media_available)))
function mediaState(m: Message) { return m.media_available ? '可用' : ({ pending: '等待处理', missing_file: '等待 Linux 微信下载', missing_metadata: '缺少媒体索引', missing_key: '缺少图片解密密钥', decode_failed: '缓存解码失败', unsupported_hevc: '暂不支持的图片格式' } as Record<string,string>)[m.media_status || 'pending'] || '等待处理' }
async function loadMedia(older = false) {
  if (mediaLoading.value) return
  mediaLoading.value = true
  try {
    const params = new URLSearchParams({ kind: 'media', limit: '100' })
    if (older && mediaBefore.value) params.set('before', mediaBefore.value)
    const page = await api<Page>('/messages?' + params)
    const merged = new Map((older ? mediaItems.value : []).map(m => [m.id,m]))
    page.items.forEach(m => merged.set(m.id,m))
    mediaItems.value = [...merged.values()].sort((a,b) => a.time-b.time || a.id-b.id)
    mediaBefore.value = page.before; mediaMore.value = page.more
  } catch (e) { error.value = (e as Error).message }
  finally { mediaLoading.value = false }
}
async function refreshMediaStates() {
  const targets = [...messages.value, ...mediaItems.value].filter(m => ['image','voice'].includes(m.kind) && !m.media_available)
  const ids = [...new Set(targets.map(m => m.id))]
  for (let start = 0; start < ids.length; start += 100) {
    const page = await api<Page>('/messages?limit=100&ids=' + ids.slice(start,start+100).join(','))
    const updates = new Map(page.items.map(m => [m.id,m]))
    messages.value = messages.value.map(m => updates.get(m.id) || m)
    mediaItems.value = mediaItems.value.map(m => updates.get(m.id) || m)
  }
}
const conversationQuery = ref(''), chatQuery = ref(''), fileQuery = ref(''), chatKind = ref(''), fileFilter = ref('all')
const conversationFilter = ref('all'), error = ref(''), loading = ref(false), syncing = ref(false), loadingOlder = ref(false)
const settings = ref(false), searchOpen = ref(false), detailOpen = ref(false), mobileChat = ref(false), lightbox = ref<Message | null>(null)
const more = ref(false), before = ref<string | null>(null), fileMore = ref(false), fileBefore = ref<string | null>(null)
const downloading = ref(new Set<number>()), pane = ref<HTMLElement>(), newCount = ref(0), bottom = ref(true)
const localTheme = ref(localStorage.getItem('dcp-theme') || 'light')
const theme = computed(() => runtime?.theme?.value || localTheme.value)
let pollTimer: ReturnType<typeof setTimeout>, debounceTimer: ReturnType<typeof setTimeout>, cursor = 0, fileCursor = 0, stopped = false
let messageAbort: AbortController | null = null, fileAbort: AbortController | null = null
const selected = computed(() => conversations.value.find(c => c.id === selectedId.value))
const shownConversations = computed(() => conversations.value.filter(c => (conversationFilter.value !== 'groups' || c.is_group) && (conversationFilter.value !== 'contacts' || !c.is_group) && `${c.name} ${c.nickname} ${c.id}`.toLowerCase().includes(conversationQuery.value.toLowerCase())))
const shownFiles = computed(() => [...files.value].reverse().filter(m => fileFilter.value === 'all' || (fileFilter.value === 'available') === !!m.attachment?.available))
const shownMessages = computed(() => messages.value)
const stats = computed(() => ({ files: status.value?.file_messages || 0, available: status.value?.available_files || 0 }))
const palette = ['#548777', '#6089aa', '#a07792', '#af835d', '#7b82a8', '#639696']
function color(id: string) { let n = 0; for (const c of id) n = (n + c.charCodeAt(0)) % palette.length; return palette[n] }
function initial(name: string) { return [...name.replace(/^[\s\W]+/u, '')][0] || [...name][0] || '?' }
function fileIcon(ext = '') { return /xlsx?|csv/.test(ext.toLowerCase()) ? FileSpreadsheet : /zip|rar|7z|tar|gz/.test(ext.toLowerCase()) ? FileArchive : /pdf|docx?|txt|pptx?/.test(ext.toLowerCase()) ? FileText : File }
function mediaIcon(kind: string) { return ({ image: Image, voice: Mic, video: Video, sticker: Smile } as Record<string, typeof Image>)[kind] || MessageSquare }
function preview(m: Message) { return m.kind === 'file' ? `[文件] ${m.attachment?.name}` : m.text || '[消息]' }
function markSeen() { const latest = [...messages.value].reverse().find(message => !message.outgoing); if (runtime && latest && selectedId.value && pane.value?.getClientRects().length && !document.hidden && view.value === 'chats' && !chatQuery.value && !chatKind.value) runtime.markRead(selectedId.value, latest.uid).catch(e => { error.value = (e as Error).message }) }
function choose(c: Conversation) { const same = selectedId.value === c.id; view.value = 'chats'; selectedId.value = c.id; chatQuery.value = ''; chatKind.value = ''; searchOpen.value = false; mobileChat.value = true; detailOpen.value = false; if (same) scrollBottom() }
function isNew(c: Conversation) { return (runtime?.unreadByChat.value[c.id] || 0) > 0 }
function date(m: Message) { return new Date(m.time * 1000).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' }) }
function showDate(index: number) { return index === 0 || date(shownMessages.value[index]!) !== date(shownMessages.value[index - 1]!) }
function clock(m: Message) { return new Date(m.time * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }) }
function hostname(url: string) { return new URL(url).hostname }
function scrollState() { if (!pane.value) return; bottom.value = pane.value.scrollHeight - pane.value.scrollTop - pane.value.clientHeight < 100; if (bottom.value) { newCount.value = 0; markSeen() } }
async function scrollBottom(smooth = false) { await nextTick(); pane.value?.scrollTo({ top: pane.value.scrollHeight, behavior: smooth && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'instant' }); bottom.value = true; newCount.value = 0; markSeen() }
function merge(rows: Message[]) { const all = new Map(messages.value.map(m => [m.id, m])); rows.forEach(m => all.set(m.id, m)); messages.value = [...all.values()].sort((a,b) => a.time - b.time || a.id - b.id) }
interface Page { items: Message[]; more: boolean; before: string | null; cursor: number }
async function loadMessages(older = false) {
  if (!selectedId.value) return
  if (older && (!more.value || loadingOlder.value)) return
  messageAbort?.abort(); const controller = new AbortController(); messageAbort = controller
  const id = selectedId.value, query = chatQuery.value, kind = chatKind.value, previousHeight = pane.value?.scrollHeight || 0, previousScroll = pane.value?.scrollTop || 0
  if (older) loadingOlder.value = true; else loading.value = true
  try {
    const params = new URLSearchParams({ chat: id, q: chatQuery.value, kind: chatKind.value })
    if (older && before.value) params.set('before', before.value)
    const data = await api<Page>('/messages?' + params, controller.signal)
    if (id !== selectedId.value || query !== chatQuery.value || kind !== chatKind.value) return
    if (older) merge(data.items); else { messages.value = data.items; cursor = data.cursor }
    more.value = data.more; before.value = data.before; error.value = ''
    if (older) { await nextTick(); if (pane.value) pane.value.scrollTop = previousScroll + pane.value.scrollHeight - previousHeight }
    else await scrollBottom()
  } catch (e) { if (!(e instanceof DOMException && e.name === 'AbortError')) error.value = String((e as Error).message) }
  finally { if (messageAbort === controller) { loading.value = false; loadingOlder.value = false } }
}
async function loadFiles(older = false) {
  fileAbort?.abort(); const controller = new AbortController(); fileAbort = controller
  try {
    const params = new URLSearchParams({ kind: 'file', q: fileQuery.value })
    if (older && fileBefore.value) params.set('before', fileBefore.value)
    const data = await api<Page>('/messages?' + params, controller.signal)
    files.value = older ? [...data.items, ...files.value] : data.items; fileMore.value = data.more; fileBefore.value = data.before; if (!older) fileCursor = data.cursor; error.value = ''
  } catch (e) { if (!(e instanceof DOMException && e.name === 'AbortError')) error.value = (e as Error).message }
}
async function synchronize(force = false) {
  if (syncing.value) return
  syncing.value = true
  try {
    const data = await api<{ items: Conversation[]; cursor: number }>('/conversations')
    conversations.value = data.items
    if (runtime) await runtime.refreshUnread()
    if (!selectedId.value && data.items.length) selectedId.value = data.items[0]!.id
    if (!status.value || force || Date.now() % 30000 < 6500) status.value = await api<Status>('/status')
    error.value = ''
    if (force && selectedId.value) await loadMessages()
    else if (selectedId.value && !loading.value && !loadingOlder.value && data.cursor > cursor) {
      const id = selectedId.value, query = chatQuery.value, kind = chatKind.value; const params = new URLSearchParams({ chat: id, after: String(cursor), q: query, kind })
      const page = await api<Page>('/messages?' + params)
      if (id === selectedId.value && query === chatQuery.value && kind === chatKind.value && !loading.value && !loadingOlder.value) { const stay = bottom.value; const fresh = page.items.filter(m => !messages.value.some(old => old.id === m.id)).length; merge(page.items); cursor = page.cursor; if (stay) await scrollBottom(); else newCount.value += fresh }
    }
    if (view.value === 'files' && (force || !files.value.length || data.cursor > fileCursor)) await loadFiles()
    await refreshMediaStates()
    if (view.value === 'media' && !mediaLoading.value) {
      const latest = await api<Page>('/messages?kind=media&limit=100')
      const all = new Map(mediaItems.value.map(m => [m.id,m])); latest.items.forEach(m => all.set(m.id,m))
      mediaItems.value = [...all.values()].sort((a,b) => a.time-b.time || a.id-b.id)
    }
  } catch (e) { error.value = (e as Error).message }
  finally { syncing.value = false }
}
async function poll() { if (stopped) return; if (!document.hidden) await synchronize(); if (!stopped) pollTimer = setTimeout(poll, 5000) }
async function download(m: Message) {
  downloading.value.add(m.id)
  try { if (runtime) { const blob = await runtime.blob(m.id, m.attachment ? 'file' : 'media'); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = m.attachment?.name || `media-${m.id}`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 10000) } else { const response = await fetch(fileUrl(m.id), { method: 'HEAD', cache: 'no-store' }); if (!response.ok) throw new Error('文件暂不可下载，请刷新后重试'); const a = document.createElement('a'); a.href = fileUrl(m.id); a.download = m.attachment?.name || ''; a.click() } }
  catch (e) { error.value = (e as Error).message }
  finally { downloading.value.delete(m.id) }
}
function openFileChat(m: Message) { const c = conversations.value.find(c => c.id === m.chat_id); if (c) { choose(c); chatKind.value = 'file' } }
function toggleTheme() { localTheme.value = theme.value === 'dark' ? 'light' : 'dark' }
watch(localTheme, value => { if (!props.embedded) localStorage.setItem('dcp-theme', value) })
watch(selectedId, () => { messages.value = []; newCount.value = 0; cursor = 0; loadMessages() })
watch([chatQuery, chatKind], () => { clearTimeout(debounceTimer); debounceTimer = setTimeout(() => loadMessages(), 250) })
watch(fileQuery, () => { clearTimeout(debounceTimer); debounceTimer = setTimeout(() => loadFiles(), 250) })
watch(view, value => { if (value === 'files') loadFiles(); if (value === 'media') loadMedia() })
onMounted(poll)
onBeforeUnmount(() => { stopped = true; clearTimeout(pollTimer); clearTimeout(debounceTimer); messageAbort?.abort(); fileAbort?.abort() })
</script>

<template>
  <div class="infocenter-surface app-shell" :data-theme="theme" :class="{ 'mobile-chat': mobileChat && view === 'chats', 'is-embedded': embedded }">
    <nav class="rail" aria-label="主导航">
      <div class="brand-mark" title="DCP 信息中心"><MessageSquare :size="24" /></div>
      <button class="rail-button" :class="{ active: view === 'media' }" title="媒体" aria-label="媒体" @click="view = 'media'; mobileChat = false"><Image /><span>媒体</span></button>
      <button class="rail-button" :class="{ active: view === 'chats' }" title="会话" aria-label="会话" @click="view = 'chats'"><MessageSquare /><span>会话</span></button>
      <button class="rail-button" :class="{ active: view === 'files' }" title="文件" aria-label="文件" @click="view = 'files'; mobileChat = false"><FolderOpen /><span>文件</span></button>
      <button v-if="runtime?.scheduleRequest" class="rail-button" :class="{ active: view === 'schedules' }" title="日程" aria-label="日程" @click="view = 'schedules'; mobileChat = false"><CalendarDays /><span>日程</span></button>
      <div class="rail-spacer" />
      <button v-if="!embedded" class="icon-button" :title="theme === 'light' ? '深色模式' : '浅色模式'" aria-label="切换配色" @click="toggleTheme"><Moon v-if="theme === 'light'" /><Sun v-else /></button>
      <button class="icon-button" title="连接信息" aria-label="连接信息" @click="settings = true"><Settings /></button>
      <div class="self-avatar" :title="status?.self_name || '微信账号'">{{ initial(status?.self_name || '我') }}</div>
    </nav>

    <aside v-if="view === 'chats'" class="conversation-sidebar">
      <header class="sidebar-heading"><div><div class="eyebrow">DCP INFOCENTER</div><h1>信息中心</h1></div><button class="icon-button" title="刷新" aria-label="刷新" @click="synchronize(true)"><RefreshCw :class="{ spinning: syncing }" :size="18" /></button></header>
      <div class="sidebar-search"><Search :size="16" /><input v-model="conversationQuery" aria-label="搜索会话" placeholder="搜索联系人、群聊" /><button v-if="conversationQuery" class="icon-button small" title="清空搜索" @click="conversationQuery = ''"><X :size="14" /></button></div>
      <div class="conversation-tabs" role="tablist" aria-label="会话类型"><button v-for="tab in [{ id: 'all', text: '全部' }, { id: 'groups', text: '群聊' }, { id: 'contacts', text: '联系人' }]" :key="tab.id" role="tab" :aria-selected="conversationFilter === tab.id" :class="{ selected: conversationFilter === tab.id }" @click="conversationFilter = tab.id">{{ tab.text }}</button></div>
      <div class="conversation-list">
        <button v-for="c in shownConversations" :key="c.id" class="conversation" :class="{ selected: selectedId === c.id }" @click="choose(c)">
          <div class="avatar" :style="{ background: color(c.id) }"><Users v-if="c.is_group" :size="20" /><span v-else>{{ initial(c.name) }}</span><i v-if="isNew(c)" class="unread-dot" /></div>
          <div class="conversation-copy"><div class="conversation-line"><strong>{{ c.name }}</strong><time>{{ new Date(c.last.time * 1000).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) }}</time></div><div class="conversation-line"><p>{{ preview(c.last) }}</p><BellOff v-if="c.muted" :size="12" /></div></div>
        </button>
        <div v-if="!shownConversations.length" class="empty compact"><Search /><p>{{ conversations.length ? '没有匹配的会话' : error ? '暂时无法载入会话' : '正在连接 Linux 微信' }}</p><button v-if="error" class="text-button" @click="synchronize(true)">重试</button></div>
      </div>
      <footer class="sidebar-footer"><span class="connection-dot" :class="{ offline: !!error }" /><span>{{ error ? '连接异常' : status ? 'Linux 已连接' : '正在连接' }}</span><span class="count">{{ conversations.length }} 个会话</span></footer>
    </aside>

    <main v-if="view === 'chats'" v-motion v-swipe="{axis:'x',trigger:'.chat-heading',close:()=>mobileChat=false}" class="chat-panel">
      <header class="chat-heading"><button class="icon-button mobile-back" title="返回会话" @click="mobileChat = false"><ChevronLeft /></button><div class="chat-title"><h2>{{ selected?.name || '微信消息' }}</h2><p>{{ selected ? `${selected.is_group ? '群聊' : '联系人'} · ${selected.count.toLocaleString()} 条记录` : 'Linux 消息源' }}<span v-if="selected?.muted"> · 已免打扰</span></p></div><div class="header-actions"><button class="icon-button" :class="{ selected: searchOpen }" title="搜索聊天记录" aria-label="搜索聊天记录" @click="searchOpen = !searchOpen; if (!searchOpen) chatQuery = ''"><Search :size="19" /></button><button class="icon-button" :class="{ selected: chatKind === 'file' }" title="会话文件" aria-label="会话文件" @click="chatKind = chatKind ? '' : 'file'"><FolderOpen :size="19" /></button><button class="icon-button" title="会话信息" aria-label="会话信息" @click="detailOpen = !detailOpen"><MoreHorizontal /></button></div></header>
      <div v-if="searchOpen" class="chat-search"><Search :size="16" /><input v-model="chatQuery" placeholder="在此会话中搜索" aria-label="在此会话中搜索" /><button class="icon-button small" title="关闭搜索" @click="chatQuery = ''; searchOpen = false"><X :size="16" /></button></div>
      <div v-if="chatKind" class="filter-line"><FolderOpen :size="14" />会话文件<button class="icon-button small" title="显示全部消息" @click="chatKind = ''"><X :size="14" /></button></div>
      <div v-if="error" class="error-banner" role="alert"><AlertCircle :size="16" /><span>{{ error }}</span><button @click="synchronize(true)">重试</button></div>
      <div class="chat-body">
        <div ref="pane" class="message-scroll" @scroll="scrollState">
          <div v-if="loading" class="loading-state"><RefreshCw class="spinning" :size="20" />正在载入</div>
          <button v-if="more && !loading" class="history-button" :disabled="loadingOlder" @click="loadMessages(true)">{{ loadingOlder ? '正在载入…' : '查看更早的消息' }}</button>
          <div v-if="!loading && !messages.length" class="empty"><MessageSquare :size="36" /><h3>{{ selected ? '没有匹配的消息' : '选择一个会话' }}</h3><p>{{ selected ? '可调整搜索条件或刷新消息。' : '聊天记录将在这里显示。' }}</p></div>
          <template v-for="(m, index) in shownMessages" :key="m.id">
            <div v-if="showDate(index)" class="date-separator">{{ date(m) }}</div>
            <div v-if="m.kind === 'system'" class="system-message">{{ m.text }}</div>
            <article v-else class="message" :class="{ outgoing: m.outgoing }">
              <div class="avatar message-avatar" :style="{ background: color(m.sender_id || m.sender) }" :title="m.sender">{{ initial(m.outgoing ? status?.self_name || '我' : m.sender) }}</div>
              <div class="message-content"><div class="message-meta"><span>{{ m.outgoing ? '我' : m.sender }}</span><small v-if="m.source === 'netdisk'">站内消息</small><time>{{ clock(m) }}</time></div>
                <div v-if="m.attachment" class="file-bubble"><div class="file-content"><div class="file-symbol" :class="m.attachment.extension.toLowerCase()"><component :is="fileIcon(m.attachment.extension)" :size="28" /><span>{{ m.attachment.extension.toUpperCase().slice(0,5) || 'FILE' }}</span></div><div class="file-copy"><strong>{{ m.attachment.name }}</strong><small>{{ formatSize(m.attachment.size) }}</small></div></div><div class="file-bottom"><span :class="{ available: m.attachment.available }"><Check v-if="m.attachment.verified" :size="12" />{{ m.attachment.available ? (m.attachment.verified ? 'MD5 已核验' : '本地文件') : 'Linux 尚未下载' }}</span><button :disabled="!m.attachment.available || downloading.has(m.id)" @click="download(m)"><Download :size="14" />{{ downloading.has(m.id) ? '准备中' : '下载' }}</button></div></div>
                <div v-else-if="['image','sticker','voice','video'].includes(m.kind)" class="media-bubble">
                  <button v-if="m.media_available && ['image','sticker'].includes(m.kind)" class="image-button" @click="lightbox = m"><img :src="mediaUrl(m.id)" :alt="m.text" loading="lazy" @load="bottom && scrollBottom()" /></button>
                  <audio v-else-if="m.media_available && m.kind === 'voice'" :src="mediaUrl(m.id)" controls preload="none" />
                  <video v-else-if="m.media_available && m.kind === 'video'" :src="mediaUrl(m.id)" controls preload="metadata" />
                  <div v-else class="media-placeholder"><component :is="mediaIcon(m.kind)" :size="24" /><span>{{ m.text }}{{ m.duration ? ` · ${m.duration} 秒` : '' }}<small>{{ mediaState(m) }}</small></span></div>
                </div>
                <a v-else-if="m.url" class="link-bubble" :href="m.url" target="_blank" rel="noopener noreferrer"><div><Link :size="18" /><strong>{{ m.text.split('\n')[0] }}</strong><ExternalLink :size="14" /></div><p v-if="m.text.includes('\n')">{{ m.text.split('\n').slice(1).join('\n') }}</p><small>{{ hostname(m.url) }}</small></a>
                <div v-else class="text-bubble"><p>{{ m.text }}</p><blockquote v-if="m.quote">{{ m.quote }}</blockquote><button v-if="m.source === 'netdisk' && m.link_url && runtime?.openLink" class="text-button" @click="runtime.openLink(m.link_url)">打开详情</button></div>
              </div>
            </article>
          </template>
        </div>
        <Transition name="pop"><button v-if="!bottom && messages.length" class="jump-button" @click="scrollBottom(true)"><ArrowDown :size="16" />{{ newCount ? `${newCount} 条新消息` : '回到最新' }}</button></Transition>
        <Transition name="drawer"><aside v-if="detailOpen && selected" v-swipe="{axis:'x',trigger:'header',close:()=>detailOpen=false}" class="chat-details"><header><h3>会话信息</h3><button class="icon-button" title="关闭" @click="detailOpen = false"><X :size="17" /></button></header><div class="avatar large" :style="{ background: color(selected.id) }"><Users v-if="selected.is_group" :size="28" /><span v-else>{{ initial(selected.name) }}</span></div><h3>{{ selected.name }}</h3><p>{{ selected.nickname }}</p><dl><dt>消息</dt><dd>{{ selected.count }}</dd><dt>文件</dt><dd>{{ selected.file_count }}</dd><dt>微信免打扰</dt><dd>{{ selected.muted ? '已开启' : '未开启' }}</dd></dl><button class="primary-button" @click="chatKind = 'file'; detailOpen = false"><FolderOpen :size="16" />查看会话文件</button></aside></Transition>
      </div>
      <div class="send-target"><button class="text-button" @click="sendHelper=!sendHelper">{{ sendHelper?'返回当前会话发送':'发送到文件传输助手' }}</button></div>
      <Composer v-if="(selected||sendHelper) && (sendHelper || selected?.last.payload?.thread_type !== 'system')" :chat="sendHelper?'filehelper':selectedId" :name="sendHelper?'文件传输助手':selected?.name||''" :message-uid="selected?.last.uid" @sent="synchronize(true)" />
      <div v-else-if="selected?.last.payload?.thread_type === 'system'" class="chat-footer">系统通知仅供查看；可通过消息中的详情入口处理。</div>
      <footer class="chat-footer"><LockKeyhole :size="13" /><span>1.4.4 · 直接发送 · 不自动回复</span><span class="footer-right">{{ syncing ? '同步中' : '每 5 秒同步' }}<span class="connection-dot" :class="{ offline: !!error }" /></span></footer>
    </main>

    <main v-else-if="view === 'media'" v-motion class="file-center">
      <header class="file-heading"><div><div class="eyebrow">DCP INFOCENTER</div><h1>媒体</h1><p>图片与语音<span>·</span>自动同步</p></div><button class="icon-button" title="刷新媒体" aria-label="刷新媒体" :disabled="mediaLoading" @click="loadMedia()"><RefreshCw :class="{ spinning: mediaLoading }" :size="19" /></button></header>
      <div v-if="error" class="error-banner" role="alert"><AlertCircle :size="16" />{{ error }}</div>
      <div class="file-toolbar"><div class="conversation-tabs"><button v-for="tab in [{id:'all',text:'全部'},{id:'image',text:'图片'},{id:'voice',text:'语音'},{id:'ready',text:'可用'}]" :key="tab.id" :class="{selected:mediaFilter===tab.id}" @click="mediaFilter=tab.id">{{ tab.text }}</button></div><span class="media-count">已载入 {{ mediaItems.length }} 条 · {{ mediaItems.filter(m => m.media_available).length }} 条可用</span></div>
      <div class="media-scroll"><div class="media-grid"><article v-for="m in shownMedia" :key="m.id" class="media-card"><div class="media-preview"><button v-if="m.media_available && m.kind==='image'" class="image-button" @click="lightbox=m"><img :src="mediaUrl(m.id)" alt="聊天图片" loading="lazy" /></button><audio v-else-if="m.media_available && m.kind==='voice'" :src="mediaUrl(m.id)" controls preload="none" /><div v-else class="media-waiting"><component :is="mediaIcon(m.kind)" :size="28" /><span>{{ mediaState(m) }}</span></div></div><div class="media-caption"><button class="chat-link" @click="openFileChat(m); chatKind=''">{{ m.chat_name }}</button><small>{{ m.outgoing ? '我' : m.sender }} · {{ timeLabel(m.time) }}</small><div><span :class="{available:m.media_available}">{{ mediaState(m) }}</span><button v-if="m.media_available" class="icon-button" title="下载媒体" aria-label="下载媒体" @click="download(m)"><Download :size="16" /></button></div></div></article></div><div v-if="!shownMedia.length" class="empty"><Image /><p>{{ mediaLoading ? '正在载入媒体' : '没有匹配的媒体' }}</p></div><button v-if="mediaMore" class="history-button" :disabled="mediaLoading" @click="loadMedia(true)">载入更早的媒体 <ChevronDown :size="14" /></button></div>
      <footer class="file-footer"><ShieldCheck :size="14" />Linux 媒体库<span>·</span>只接收，不发送</footer>
    </main>
    <main v-else-if="view === 'schedules' && runtime?.scheduleRequest" class="file-center"><TerminalSchedules :request="runtime.scheduleRequest" /></main>
    <main v-else v-motion class="file-center">
      <header class="file-heading"><div><div class="eyebrow">DCP INFOCENTER</div><h1>文件</h1><p>{{ stats.files }} 条文件消息<span>·</span>{{ stats.available }} 条可下载</p></div><button class="icon-button" title="刷新文件" aria-label="刷新文件" @click="loadFiles(); synchronize(true)"><RefreshCw :class="{ spinning: syncing }" :size="19" /></button></header>
      <div v-if="error" class="error-banner" role="alert"><AlertCircle :size="16" /><span>{{ error }}</span><button @click="synchronize(true)">重试</button></div>
      <div class="file-toolbar"><div class="sidebar-search"><Search :size="16" /><input v-model="fileQuery" placeholder="搜索文件名" aria-label="搜索文件名" /></div><div class="conversation-tabs"><button v-for="tab in [{ id: 'all', text: '全部' }, { id: 'available', text: '可下载' }, { id: 'missing', text: '未下载' }]" :key="tab.id" :class="{ selected: fileFilter === tab.id }" @click="fileFilter = tab.id">{{ tab.text }}</button></div></div>
      <div class="file-table-scroll"><table><thead><tr><th>文件名称</th><th>来源会话</th><th>大小</th><th>收到时间</th><th>状态</th><th><span class="sr-only">下载</span></th></tr></thead><tbody><tr v-for="m in shownFiles" :key="m.id"><td><div class="file-name-cell"><div class="file-symbol compact" :class="m.attachment?.extension.toLowerCase()"><component :is="fileIcon(m.attachment?.extension)" :size="23" /></div><div><strong>{{ m.attachment?.name }}</strong><small>{{ m.outgoing ? '我发送的' : m.sender }}</small></div></div></td><td><button class="chat-link" @click="openFileChat(m)">{{ m.chat_name }}</button></td><td class="nowrap">{{ formatSize(m.attachment?.size || 0) }}</td><td class="nowrap">{{ timeLabel(m.time) }}</td><td><span class="file-state" :class="{ available: m.attachment?.available }">{{ m.attachment?.available ? '可下载' : '未下载' }}</span></td><td><button class="icon-button" :disabled="!m.attachment?.available || downloading.has(m.id)" :title="m.attachment?.available ? '下载文件' : 'Linux 微信尚未下载此附件'" aria-label="下载文件" @click="download(m)"><Download :size="18" /></button></td></tr></tbody></table><div v-if="!shownFiles.length" class="empty"><FolderOpen :size="36" /><h3>没有匹配的文件</h3></div><button v-if="fileMore" class="history-button" @click="loadFiles(true)">载入更早的文件 <ChevronDown :size="14" /></button></div>
      <footer class="file-footer"><ShieldCheck :size="14" />{{ status?.self_name || '当前微信账号' }}<span>·</span>Linux 本地附件</footer>
    </main>

    <Transition name="pop"><div v-if="settings" class="modal-backdrop" @click.self="settings = false"><section v-swipe="{axis:'y',trigger:'header',close:()=>settings=false}" class="dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title"><header><h2 id="settings-title">连接信息</h2><button class="icon-button" title="关闭" aria-label="关闭连接信息" @click="settings = false"><X :size="18" /></button></header><div class="connection-summary"><ShieldCheck :size="26" /><div><strong>Linux 微信</strong><p>{{ error ? '连接异常' : '已连接' }}</p></div></div><dl><dt>账号</dt><dd>{{ status?.self_name || '—' }}</dd><dt>消息记录</dt><dd>{{ status?.messages.toLocaleString() || '—' }}</dd><dt>最新消息</dt><dd>{{ status?.latest_at ? timeLabel(status.latest_at, true) : '—' }}</dd><dt>最近入库</dt><dd>{{ status?.captured_at ? new Date(status.captured_at).toLocaleString('zh-CN') : '—' }}</dd><dt>接口版本</dt><dd>{{ status?.version || '—' }}</dd><dt>消息发送</dt><dd>未启用</dd></dl><div v-if="error" class="error-banner">{{ error }}</div><button class="primary-button" @click="synchronize(true)"><RefreshCw :size="16" />重新连接</button></section></div></Transition>
    <div v-if="lightbox" class="lightbox" @click="lightbox = null"><button class="icon-button" title="关闭图片"><X /></button><img :src="mediaUrl(lightbox.id)" :alt="lightbox.text" /></div>
  </div>
</template>
