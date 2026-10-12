<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NCard,
  NIcon,
  NInput,
  NList,
  NListItem,
  NModal,
  NSpace,
  NTabPane,
  NTabs,
  useMessage,
} from 'naive-ui'
import {
  ArrowBackOutline,
  ChatbubbleEllipsesOutline,
  MailUnreadOutline,
  PencilOutline,
  RefreshOutline,
  SendOutline,
} from '@vicons/ionicons5'
import { api } from '../api'
import UserSelect from '../components/UserSelect.vue'
import { useUiStore } from '../stores/ui'
import { formatDisplayDate } from '../utils/dateFormat'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const ui = useUiStore()

const threads = ref([])
const messages = ref([])
const loading = ref(false)
const activeThreadId = ref(null)
const notifications = ref([])
const notifLoading = ref(false)
const leftTab = ref('notifications')
const mobileDetailOpen = ref(false)

const composeOpen = ref(false)
const composeForm = ref({ recipients: [], subject: '', content_md: '' })
const sendText = ref('')

const activeThread = computed(() => (threads.value || []).find((x) => Number(x?.id) === Number(activeThreadId.value)))
const rightTitle = computed(() => {
  const t = activeThread.value
  if (!t) return '请选择会话'
  if (t.type === 'direct') return `与 ${t.subject || '对方'} 的会话`
  if (t.type === 'project_group') return t.subject || '项目会话'
  return t.subject || '会话'
})

async function loadThreads() {
  loading.value = true
  try {
    const d = await api.listThreads()
    threads.value = d.items || []
  } catch (e) {
    message.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadNotifications() {
  notifLoading.value = true
  try {
    const d = await api.listNotifications({ page: 1, page_size: 200 })
    notifications.value = d.items || []
    ui.setUnreadCount((notifications.value || []).filter((x) => !x.read_at).length)
  } catch (e) {
    message.error(e?.message || '加载失败')
  } finally {
    notifLoading.value = false
  }
}

async function loadMessages(threadId) {
  if (!threadId) return
  try {
    const d = await api.listMessages(threadId)
    messages.value = d.items || []
    await api.readThread(threadId)
  } catch (e) {
    message.error(e?.message || '加载失败')
  }
}

function openThread(t) {
  mobileDetailOpen.value = true
  router.replace({ path: '/inbox', query: { thread: String(t.id) } })
}

function backToList() {
  mobileDetailOpen.value = false
  router.replace({ path: '/inbox' })
}

async function openNotification(n) {
  try {
    if (!n.read_at) {
      await api.readNotification(n.id)
      await loadNotifications()
    }
  } catch {}
  if (n.link_url) router.push(n.link_url)
}

async function onSend() {
  if (!activeThreadId.value) return
  const content = sendText.value
  if (!content.trim()) return
  try {
    await api.sendMessage(activeThreadId.value, { content_md: content })
    sendText.value = ''
    await loadMessages(activeThreadId.value)
  } catch (e) {
    message.error(e?.message || '发送失败')
  }
}

async function onCreateThread() {
  try {
    const recipients = (composeForm.value.recipients || []).map((x) => Number(x)).filter((x) => Number.isFinite(x))
    if (recipients.length === 0) {
      message.error('请选择收件人')
      return
    }
    const d = await api.createThread({
      type: 'direct',
      recipients,
      subject: composeForm.value.subject,
      content_md: composeForm.value.content_md,
    })
    message.success('已创建会话')
    composeOpen.value = false
    composeForm.value = { recipients: [], subject: '', content_md: '' }
    await loadThreads()
    mobileDetailOpen.value = true
    router.replace({ path: '/inbox', query: { thread: String(d.thread.id) } })
  } catch (e) {
    message.error(e?.message || '创建失败')
  }
}

watch(
  () => route.query.thread,
  (v) => {
    activeThreadId.value = v ? Number(v) : null
    mobileDetailOpen.value = Boolean(v)
    messages.value = []
    if (activeThreadId.value) loadMessages(activeThreadId.value)
  },
  { immediate: true },
)

onMounted(loadThreads)
onMounted(loadNotifications)
</script>

<template>
  <NSpace vertical size="large" class="dcp-page inbox-page">
    <NCard class="inbox-header-card">
      <NSpace justify="space-between" align="center">
        <div class="inbox-page__title">消息</div>
        <NSpace>
          <NButton @click="() => { loadThreads(); loadNotifications(); }" :loading="loading || notifLoading">
            <template #icon><NIcon><RefreshOutline /></NIcon></template>
            刷新
          </NButton>
          <NButton type="primary" @click="composeOpen = true">
            <template #icon><NIcon><PencilOutline /></NIcon></template>
            写信
          </NButton>
        </NSpace>
      </NSpace>
      <div class="inbox-page__tip">
        @提及格式：<code>@{user_id}</code>，例如 <code>@{12}</code>
      </div>
    </NCard>

    <div class="inbox-layout" :class="{ 'is-detail-open': mobileDetailOpen }">
      <NCard class="inbox-sidebar">
        <NTabs v-model:value="leftTab" type="line" animated>
          <NTabPane name="notifications" tab="通知">
            <NList clickable hoverable>
              <NListItem v-for="n in notifications" :key="n.id" @click="openNotification(n)">
                <div class="inbox-list-item__head">
                  <div class="inbox-list-item__title">
                    <NIcon><MailUnreadOutline /></NIcon>
                    <span>{{ n.title }}</span>
                  </div>
                  <div v-if="!n.read_at" class="inbox-unread-dot" />
                </div>
                <div v-if="n.content" class="inbox-list-item__content">{{ n.content }}</div>
                <div class="inbox-list-item__time">{{ formatDisplayDate(n.created_at) }}</div>
              </NListItem>
            </NList>
          </NTabPane>
          <NTabPane name="threads" tab="会话">
            <NList clickable hoverable>
              <NListItem v-for="t in threads" :key="t.id" @click="openThread(t)">
                <div class="inbox-list-item__title">
                  <NIcon><ChatbubbleEllipsesOutline /></NIcon>
                  <span>{{ t.subject || `会话 #${t.id}` }}</span>
                </div>
                <div class="inbox-list-item__time">{{ t.type }} · {{ formatDisplayDate(t.updated_at) }}</div>
              </NListItem>
            </NList>
          </NTabPane>
        </NTabs>
      </NCard>

      <NCard class="inbox-detail" :title="rightTitle">
        <template #header-extra>
          <NButton class="inbox-mobile-back" size="small" quaternary @click="backToList">
            <template #icon><NIcon><ArrowBackOutline /></NIcon></template>
            返回
          </NButton>
        </template>

        <div v-if="!activeThreadId" class="inbox-empty">从左侧选择一个会话</div>
        <div v-else class="inbox-chat">
          <div class="inbox-chat__messages">
            <div v-for="m in messages" :key="m.id" class="inbox-message">
              <div class="inbox-message__meta">from {{ m.sender_name || m.sender_id }} · {{ formatDisplayDate(m.created_at) }}</div>
              <div class="inbox-message__body">{{ m.content_md }}</div>
            </div>
          </div>
          <div class="inbox-chat__composer">
            <NInput v-model:value="sendText" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="输入消息（支持 Markdown）" />
            <NButton type="primary" @click="onSend" :disabled="!sendText.trim()">
              <template #icon><NIcon><SendOutline /></NIcon></template>
              发送
            </NButton>
          </div>
        </div>
      </NCard>
    </div>

    <NModal v-model:show="composeOpen" preset="card" title="写信" style="width: 680px; max-width: 96vw">
      <NSpace vertical>
        <div class="inbox-compose-label">收件人</div>
        <UserSelect v-model="composeForm.recipients" multiple placeholder="选择收件人" />
        <NInput v-model:value="composeForm.subject" placeholder="主题（可选）" />
        <NInput v-model:value="composeForm.content_md" type="textarea" :autosize="{ minRows: 6, maxRows: 14 }" placeholder="正文（Markdown，可 @提及）" />
        <NSpace justify="end">
          <NButton @click="composeOpen = false">取消</NButton>
          <NButton type="primary" @click="onCreateThread">发送</NButton>
        </NSpace>
      </NSpace>
    </NModal>
  </NSpace>
</template>

<style scoped>
.inbox-page,
.inbox-layout,
.inbox-sidebar,
.inbox-detail,
.inbox-chat,
.inbox-chat__messages {
  min-width: 0;
}

.inbox-page__title {
  font-size: 18px;
  font-weight: 700;
}

.inbox-page__tip,
.inbox-compose-label,
.inbox-empty,
.inbox-list-item__time {
  color: var(--dcp-muted);
  font-size: 12px;
}

.inbox-page__tip {
  margin-top: 8px;
}

.inbox-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 12px;
}

.inbox-list-item__head,
.inbox-list-item__title {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
}

.inbox-list-item__head {
  justify-content: space-between;
}

.inbox-list-item__title {
  font-weight: 600;
}

.inbox-list-item__title span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inbox-list-item__content {
  margin-top: 4px;
  color: var(--dcp-text);
  font-size: 12px;
  opacity: 0.85;
  white-space: pre-wrap;
}

.inbox-list-item__time {
  margin-top: 4px;
}

.inbox-unread-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 999px;
  background: var(--dcp-primary);
}

.inbox-mobile-back {
  display: none;
}

.inbox-chat {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.inbox-chat__messages {
  max-height: 50vh;
  overflow: auto;
  padding: 4px 0;
}

.inbox-message {
  padding: 8px 0;
  border-bottom: 1px solid rgba(127, 127, 127, 0.18);
}

.inbox-message__meta {
  color: var(--dcp-muted);
  font-size: 12px;
}

.inbox-message__body {
  white-space: pre-wrap;
}

.inbox-chat__composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 12px;
}

@media (max-width: 768px) {
  .inbox-layout {
    display: block;
  }

  .inbox-layout.is-detail-open .inbox-sidebar {
    display: none;
  }

  .inbox-layout:not(.is-detail-open) .inbox-detail {
    display: none;
  }

  .inbox-mobile-back {
    display: inline-flex;
  }

  .inbox-chat__messages {
    max-height: calc(100vh - 320px);
  }

  .inbox-chat__composer {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
