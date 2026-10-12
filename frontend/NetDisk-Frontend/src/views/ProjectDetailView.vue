<script setup>
import { computed, h, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import {
  NButton,
  NCard,
  NDataTable,
  NDatePicker,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import FileBrowser from '../components/FileBrowser.vue'
import UserSelect from '../components/UserSelect.vue'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'
import { formatDisplayDate } from '../utils/dateFormat'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const message = useMessage()

const projectId = computed(() => Number(route.params.projectId))
const project = ref(null)
const myRole = ref(null)
const workflow = ref([])
const tasks = ref([])
const members = ref([])
const settings = ref({ guest_visible: false, task_workflow: [] })
const loading = ref(false)

const createTaskOpen = ref(false)
const taskForm = ref({ title: '', description_md: '', status: 'todo', priority: 3, assignee_id: null, start_at: null, due_at: null })

const canManageContent = computed(() => ['creator', 'admin'].includes(myRole.value) || auth.user?.role_system === 'super_admin')
const canEditProjectMeta = computed(() => myRole.value === 'creator' || auth.user?.role_system === 'super_admin')
const userId = computed(() => Number(auth.user?.id))

function toIso8(ms) {
  if (ms === null || ms === undefined || ms === '') return null
  const d = new Date(Number(ms))
  if (Number.isNaN(d.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(d)
  const m = {}
  for (const p of parts) {
    if (p.type !== 'literal') m[p.type] = p.value
  }
  return `${m.year}-${m.month}-${m.day}T${m.hour}:${m.minute}:${m.second}+08:00`
}

function gotoProjectManage() {
  router.push(`/projects/${projectId.value}/manage`)
}

async function loadAll() {
  loading.value = true
  try {
    const p = await api.getProject(projectId.value)
    project.value = p.project
    myRole.value = p.project.role
    const wf = await api.getProjectWorkflow(projectId.value)
    workflow.value = wf.workflow || []
    const s = await api.getProjectSettings(projectId.value)
    settings.value = s.settings
    const t = await api.listTasks(projectId.value, { page: 1, page_size: 1000 })
    tasks.value = t.items || []
    const m = await api.listProjectMembers(projectId.value)
    members.value = m.items || []
  } catch (e) {
    message.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function onCreateTask() {
  try {
    const payload = { ...taskForm.value }
    const s = toIso8(payload.start_at)
    const e = toIso8(payload.due_at)
    if (s) payload.start_at = s
    else delete payload.start_at
    if (e) payload.due_at = e
    else delete payload.due_at
    await api.createTask(projectId.value, payload)
    message.success('已创建任务')
    createTaskOpen.value = false
    taskForm.value = { title: '', description_md: '', status: workflow.value?.[0]?.key || 'todo', priority: 3, assignee_id: null, start_at: null, due_at: null }
    const t = await api.listTasks(projectId.value, { page: 1, page_size: 1000 })
    tasks.value = t.items || []
    loadGroupMessages()
  } catch (e) {
    message.error(e?.message || '创建失败')
  }
}

async function onDeleteTask(task) {
  try {
    await api.deleteTask(task.id)
    tasks.value = tasks.value.filter((x) => x.id !== task.id)
    loadGroupMessages()
  } catch (e) {
    message.error(e?.message || '删除失败')
  }
}

async function onTakeTask(task) {
  try {
    await api.takeTask(task.id)
    const t = await api.listTasks(projectId.value, { page: 1, page_size: 1000 })
    tasks.value = t.items || []
    await loadGroupMessages({ silent: true })
  } catch (e) {
    message.error(e?.message || '操作失败')
  }
}

async function onRejectTask(task) {
  try {
    await api.rejectTask(task.id)
    const t = await api.listTasks(projectId.value, { page: 1, page_size: 1000 })
    tasks.value = t.items || []
    await loadGroupMessages({ silent: true })
  } catch (e) {
    message.error(e?.message || '操作失败')
  }
}

const workflowOptions = computed(() =>
  (workflow.value || []).map((x) => ({ label: x.name || x.key, value: x.key })),
)

async function onChangeTaskStatus(task, status) {
  try {
    const d = await api.patchTask(task.id, { status })
    const idx = (tasks.value || []).findIndex((x) => Number(x?.id) === Number(task.id))
    if (idx >= 0) tasks.value[idx] = { ...tasks.value[idx], ...d.task }
    await loadGroupMessages({ silent: true })
  } catch (e) {
    message.error(e?.message || '操作失败')
  }
}

const editProjectOpen = ref(false)
const projectForm = ref({ name: '', key: '', description: '' })

function openEditProject() {
  projectForm.value = { name: project.value?.name || '', key: project.value?.key || '', description: project.value?.description || '' }
  editProjectOpen.value = true
}

async function onSaveProject() {
  try {
    const d = await api.patchProject(projectId.value, projectForm.value)
    project.value = d.project
    message.success('已保存')
    editProjectOpen.value = false
    loadGroupMessages()
  } catch (e) {
    message.error(e?.message || '保存失败')
  }
}

const settingsOpen = ref(false)
const settingsDraft = ref({ guest_visible: false, task_workflow_text: '' })

function openSettings() {
  settingsDraft.value.guest_visible = !!settings.value.guest_visible
  settingsDraft.value.task_workflow_text = JSON.stringify(settings.value.task_workflow || workflow.value || [], null, 2)
  settingsOpen.value = true
}

async function onSaveSettings() {
  try {
    const wf = JSON.parse(settingsDraft.value.task_workflow_text || '[]')
    const d = await api.patchProjectSettings(projectId.value, { guest_visible: settingsDraft.value.guest_visible, task_workflow: wf })
    settings.value = d.settings
    workflow.value = d.settings.task_workflow
    message.success('已保存')
    settingsOpen.value = false
    const t = await api.listTasks(projectId.value, { page: 1, page_size: 1000 })
    tasks.value = t.items || []
    loadGroupMessages()
  } catch (e) {
    message.error(e?.message || '保存失败')
  }
}

const groupMessages = ref([])
const groupLoading = ref(false)
const groupSendText = ref('')
const groupPollTimer = ref(null)
const groupListRef = ref(null)
const groupSig = ref('')

function groupSignature(items) {
  const list = items || []
  const last = list.length > 0 ? list[list.length - 1] : null
  const lastId = last?.id ?? 0
  return `${list.length}:${lastId}`
}

function scrollGroupToBottom() {
  const el = groupListRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

function scrollGroupToBottomSoon() {
  scrollGroupToBottom()
  requestAnimationFrame(() => scrollGroupToBottom())
  setTimeout(() => scrollGroupToBottom(), 0)
}

async function loadGroupMessages(opts = {}) {
  if (!projectId.value) return
  const silent = !!opts.silent
  if (!silent) groupLoading.value = true
  try {
    scrollGroupToBottomSoon()
    const d = await api.listProjectGroupMessages(projectId.value)
    const items = d.items || []
    const sig = groupSignature(items)
    if (sig !== groupSig.value) {
      groupSig.value = sig
      groupMessages.value = items
      await nextTick()
    }
    scrollGroupToBottomSoon()
  } catch (e) {
    message.error(e?.message || '加载群组消息失败')
  } finally {
    if (!silent) groupLoading.value = false
  }
}

async function sendGroupMessage() {
  const content = groupSendText.value
  if (!content.trim()) return
  try {
    await api.sendProjectGroupMessage(projectId.value, { content_md: content })
    groupSendText.value = ''
    await loadGroupMessages()
  } catch (e) {
    message.error(e?.message || '发送失败')
  }
}

watch(projectId, () => {
  groupSig.value = ''
  groupMessages.value = []
  loadAll()
  loadGroupMessages()
}, { immediate: true })

onMounted(() => {
  groupPollTimer.value = setInterval(() => {
    loadGroupMessages({ silent: true })
  }, 5000)
})

onUnmounted(() => {
  if (groupPollTimer.value) clearInterval(groupPollTimer.value)
})

const ganttCols = 14
const ganttStartOffsetDays = -1
const ganttTodayIndex = -ganttStartOffsetDays

const ganttStart = computed(() => dayjs().startOf('day').add(ganttStartOffsetDays, 'day'))
const ganttDays = computed(() =>
  Array.from({ length: ganttCols }, (_, i) => {
    const d = ganttStart.value.add(i, 'day')
    return { i, label: d.format('MM-DD'), dow: d.format('dd'), isToday: i === ganttTodayIndex }
  }),
)

function statusClass(status) {
  if (status === 'todo') return 'is-todo'
  if (status === 'doing') return 'is-doing'
  if (status === 'done') return 'is-done'
  return 'is-unknown'
}

function toBar(task) {
  const sRaw = task?.start_at || task?.due_at
  const eRaw = task?.due_at || task?.start_at || task?.due_at
  if (!sRaw || !eRaw) return null
  const s0 = dayjs(sRaw)
  const e0 = dayjs(eRaw)
  if (!s0.isValid() || !e0.isValid()) return null
  let s = s0.startOf('day')
  let e = e0.startOf('day')
  if (e.isBefore(s)) {
    const tmp = s
    s = e
    e = tmp
  }

  const startIndex0 = s.diff(ganttStart.value, 'day')
  const endIndex0 = e.diff(ganttStart.value, 'day')
  if (endIndex0 < 0 || startIndex0 > ganttCols - 1) return null

  const startIndex = Math.max(0, startIndex0)
  const endIndex = Math.min(ganttCols - 1, endIndex0)
  const span = endIndex - startIndex + 1

  const left = `${(startIndex / ganttCols) * 100}%`
  const width = `${(span / ganttCols) * 100}%`

  const title = (task?.title || '').trim()
  const shortTitle = title.length > 14 ? `${title.slice(0, 14)}…` : title
  return { left, width, status: task?.status || 'unknown', title, shortTitle }
}

const memberOptions = computed(() =>
  (members.value || [])
    .map((m) => ({
      id: Number(m?.user?.id),
      name: m?.user?.display_name || m?.user?.username || `#${m?.user?.id}`,
    }))
    .filter((x) => Number.isFinite(x.id)),
)

const memberMap = computed(() => {
  const out = new Map()
  for (const m of members.value || []) {
    const id = Number(m?.user?.id)
    if (!Number.isFinite(id)) continue
    const name = m?.user?.display_name || m?.user?.username || `#${id}`
    out.set(id, name)
  }
  return out
})

function watcherIds(row) {
  return (row?.watcher_user_ids || []).map((x) => Number(x)).filter((x) => Number.isFinite(x))
}

function assigneesLabel(row) {
  const ids = watcherIds(row)
  if (ids.length === 0) {
    const a = Number(row?.assignee_id)
    if (Number.isFinite(a)) ids.push(a)
  }
  if (ids.length === 0) return '-'
  return ids.map((id) => memberMap.value.get(id) || `#${id}`).join(', ')
}

function priorityNum(v) {
  const n = Number(v)
  if (Number.isFinite(n)) return Math.min(5, Math.max(0, Math.floor(n)))
  if (v === 'low') return 1
  if (v === 'medium') return 3
  if (v === 'high') return 4
  if (v === 'urgent') return 5
  return 3
}

function priorityTagType(n) {
  if (n >= 5) return 'error'
  if (n === 4) return 'warning'
  if (n === 3) return 'success'
  if (n === 2) return 'info'
  if (n === 1) return 'primary'
  return 'default'
}

const priorityOptions = computed(() => Array.from({ length: 6 }, (_, i) => ({ label: `P${i}`, value: i })))

const canEditTaskStatus = (row) => !!row?.watched_by_me
const canDeleteTask = (row) => canManageContent.value || Number(row?.reporter_id) === userId.value

const taskColumns = computed(() => [
  {
    title: '标题',
    key: 'title',
    minWidth: 0,
    ellipsis: { tooltip: true },
    render: (row) =>
      h('div', { class: 'task-title-cell' }, [
        h('div', { class: 'task-title-cell__main' }, row?.title || '-'),
        h('div', { class: 'task-title-cell__meta' }, assigneesLabel(row) === '-' ? '未指定' : assigneesLabel(row)),
      ]),
  },
  { title: '优先级', key: 'priority', width: 72, render: (row) => h(NTag, { size: 'small', bordered: false, type: priorityTagType(priorityNum(row?.priority)) }, { default: () => `P${priorityNum(row?.priority)}` }) },
  {
    title: '状态',
    key: 'status',
    width: 112,
    render: (row) =>
      canEditTaskStatus(row)
        ? h(NSelect, {
            size: 'small',
            value: row.status,
            options: workflowOptions.value,
            onUpdateValue: (v) => onChangeTaskStatus(row, v),
            style: 'min-width:0;width:76px',
          })
        : (workflowOptions.value.find((x) => x.value === row.status)?.label || row.status),
  },
  {
    title: '操作',
    key: 'actions',
    width: 96,
    render: (row) =>
      h(
        'div',
        { class: 'task-row-actions' },
        [
          !row?.watched_by_me && myRole.value !== 'guest'
            ? h(NButton, { size: 'tiny', quaternary: true, onClick: () => onTakeTask(row) }, { default: () => '接取' })
            : null,
          row?.watched_by_me
            ? h(NButton, { size: 'tiny', quaternary: true, onClick: () => onRejectTask(row) }, { default: () => '拒收' })
            : null,
          canDeleteTask(row)
            ? h(NButton, { size: 'tiny', quaternary: true, type: 'error', onClick: () => onDeleteTask(row) }, { default: () => '删除' })
            : null,
        ].filter(Boolean),
      ),
  },
])

const ganttRows = computed(() => {
  const rows = []
  for (const u of memberOptions.value) {
    const ts = (tasks.value || []).filter((t) => watcherIds(t).includes(u.id) || Number(t?.assignee_id) === u.id)
    const bars = ts
      .map((t) => ({ task: t, bar: toBar(t) }))
      .filter((x) => x.bar)
      .sort((a, b) => (a.task?.start_at || a.task?.due_at || '').localeCompare(b.task?.start_at || b.task?.due_at || ''))

    if (bars.length === 0) {
      rows.push({ key: `u-${u.id}-empty`, userId: u.id, userName: u.name, showName: true, task: null, bar: null })
      continue
    }

    bars.forEach((x, idx) => {
      rows.push({
        key: `u-${u.id}-t-${x.task.id}`,
        userId: u.id,
        userName: u.name,
        showName: idx === 0,
        task: x.task,
        bar: x.bar,
      })
    })
  }
  return rows
})
</script>

<template>
  <NSpace vertical size="large" class="dcp-page">
    <NCard>
      <NSpace justify="space-between" align="center">
        <div>
          <div style="font-size: 18px; font-weight: 700">项目 · {{ project?.name || '项目' }}</div>
          <div style="opacity: 0.7; margin-top: 6px; font-size: 12px">Key：{{ project?.key }} · 角色：{{ myRole }}</div>
        </div>
        <NSpace>
          <NButton @click="loadAll" :loading="loading">刷新</NButton>
          <NButton v-if="canManageContent" @click="gotoProjectManage">项目管理</NButton>
          <NButton v-if="canEditProjectMeta" @click="openEditProject">项目编辑</NButton>
          <NButton v-if="canManageContent" @click="openSettings">项目设置</NButton>
        </NSpace>
      </NSpace>
    </NCard>

    <div class="dcp-project-grid">
      <div class="dcp-project-grid__left">
        <NCard title="文件" class="dcp-panel" style="height: 100%">
          <FileBrowser scope="project" :project-id="projectId" embedded @changed="loadGroupMessages" />
        </NCard>
      </div>

      <div class="dcp-project-grid__mid">
        <NCard title="任务" class="dcp-panel" style="height: 100%">
          <template #header-extra>
            <NButton size="small" type="primary" :disabled="myRole === 'guest'" @click="createTaskOpen = true">新建任务</NButton>
          </template>
          <NDataTable
            class="project-task-table"
            :data="tasks"
            :pagination="false"
            :columns="taskColumns"
          />
          <div style="margin-top: 10px; opacity: 0.75; font-size: 12px">工作流：{{ workflow.map((x) => x.name || x.key).join(' / ') }}</div>
        </NCard>
      </div>

      <div class="dcp-project-grid__right">
        <NCard title="群组消息" class="dcp-panel" style="height: 100%">
          <div class="dcp-group">
            <div ref="groupListRef" class="dcp-group__list">
              <div v-if="groupLoading" style="opacity: 0.7; font-size: 12px">加载中…</div>
              <div v-else-if="groupMessages.length === 0" style="opacity: 0.7; font-size: 12px">暂无消息</div>
              <div v-else>
                <div v-for="m in groupMessages" :key="m.id" style="padding: 8px 0; border-bottom: 1px solid rgba(127,127,127,0.18)">
                  <div :style="m.is_system ? 'opacity:0.6;font-size:12px' : 'opacity:0.75;font-size:12px'">
                    {{ m.is_system ? '系统' : (m.sender_name || m.sender_id) }} · {{ formatDisplayDate(m.created_at) }}
                  </div>
                  <div :style="m.is_system ? 'opacity:0.75;font-size:12px;white-space:pre-wrap' : 'white-space:pre-wrap'">{{ m.content_md }}</div>
                </div>
              </div>
            </div>
            <div class="dcp-group__send">
              <div style="opacity: 0.7; font-size: 12px; margin-bottom: 8px">@提及格式：@{user_id}</div>
              <NInput v-model:value="groupSendText" type="textarea" :autosize="{ minRows: 4, maxRows: 6 }" placeholder="输入消息（Markdown）" />
              <div style="margin-top: 10px; display: flex; justify-content: flex-end">
                <NButton type="primary" :disabled="!groupSendText.trim()" @click="sendGroupMessage">发送</NButton>
              </div>
            </div>
          </div>
        </NCard>
      </div>

      <div class="dcp-project-grid__bottom">
        <NCard title="日程（甘特）">
          <div class="dcp-gantt" :style="{ '--dcp-gantt-cols': ganttDays.length, '--dcp-gantt-today': ganttTodayIndex }">
            <div class="dcp-gantt__head">
              <div class="dcp-gantt__head-name">人员</div>
              <div class="dcp-gantt__head-days">
                <div v-for="d in ganttDays" :key="d.i" class="dcp-gantt__head-day" :class="{ 'is-today': d.isToday }">
                  <div>{{ d.label }}</div>
                  <div class="dcp-gantt__head-dow">{{ d.dow }}</div>
                </div>
              </div>
            </div>

            <div class="dcp-gantt__body">
              <div v-if="ganttRows.length === 0" class="dcp-gantt__empty">暂无数据</div>
              <div v-for="r in ganttRows" :key="r.key" class="dcp-gantt__row">
                <div class="dcp-gantt__name" :class="{ 'is-blank': !r.showName }">{{ r.showName ? r.userName : '' }}</div>
                <div class="dcp-gantt__lane">
                  <div
                    v-if="r.bar"
                    class="dcp-gantt__bar"
                    :class="statusClass(r.bar.status)"
                    :style="{ left: r.bar.left, width: r.bar.width }"
                    :title="r.bar.title"
                  >
                    <span class="dcp-gantt__bar-text">{{ r.bar.shortTitle }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </NCard>
      </div>
    </div>

    <NModal v-model:show="createTaskOpen" preset="card" title="新建任务" style="width: 520px; max-width: 96vw">
      <NForm :model="taskForm">
        <NFormItem label="标题">
          <NInput v-model:value="taskForm.title" />
        </NFormItem>
        <NFormItem label="开始时间（可选）">
          <NDatePicker v-model:value="taskForm.start_at" type="datetime" clearable style="width: 100%" />
        </NFormItem>
        <NFormItem label="完成时间（可选）">
          <NDatePicker v-model:value="taskForm.due_at" type="datetime" clearable style="width: 100%" />
        </NFormItem>
        <NFormItem label="描述（Markdown）">
          <NInput v-model:value="taskForm.description_md" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" />
        </NFormItem>
        <NFormItem label="状态">
          <NSelect v-model:value="taskForm.status" :options="workflowOptions" placeholder="请选择状态" />
        </NFormItem>
        <NFormItem label="优先级">
          <NSelect v-model:value="taskForm.priority" :options="priorityOptions" placeholder="请选择优先级" />
        </NFormItem>
        <NFormItem label="负责人（可选）">
          <UserSelect v-model="taskForm.assignee_id" placeholder="请选择用户" />
        </NFormItem>
        <NSpace justify="end">
          <NButton @click="createTaskOpen = false">取消</NButton>
          <NButton type="primary" @click="onCreateTask">创建</NButton>
        </NSpace>
      </NForm>
    </NModal>

    <NModal v-model:show="editProjectOpen" preset="card" title="编辑项目" style="width: 520px; max-width: 96vw">
      <NForm :model="projectForm">
        <NFormItem label="名称">
          <NInput v-model:value="projectForm.name" />
        </NFormItem>
        <NFormItem label="Key">
          <NInput v-model:value="projectForm.key" />
        </NFormItem>
        <NFormItem label="描述">
          <NInput v-model:value="projectForm.description" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" />
        </NFormItem>
        <NSpace justify="end">
          <NButton @click="editProjectOpen = false">取消</NButton>
          <NButton type="primary" @click="onSaveProject">保存</NButton>
        </NSpace>
      </NForm>
    </NModal>

    <NModal v-model:show="settingsOpen" preset="card" title="项目设置" style="width: 680px; max-width: 96vw">
      <NForm :model="settingsDraft">
        <NFormItem label="游客可见">
          <NSwitch v-model:value="settingsDraft.guest_visible" />
        </NFormItem>
        <NFormItem label="工作流（JSON）">
          <NInput v-model:value="settingsDraft.task_workflow_text" type="textarea" :autosize="{ minRows: 8, maxRows: 18 }" />
        </NFormItem>
        <NSpace justify="end">
          <NButton @click="settingsOpen = false">取消</NButton>
          <NButton type="primary" @click="onSaveSettings">保存</NButton>
        </NSpace>
      </NForm>
    </NModal>
  </NSpace>
</template>

<style scoped>
.dcp-project-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: 520px 340px;
  gap: 10px;
  min-width: 0;
}

.dcp-project-grid__left {
  grid-column: 1;
  grid-row: 1;
  min-width: 0;
  min-height: 0;
}

.dcp-project-grid__mid {
  grid-column: 2;
  grid-row: 1;
  min-width: 0;
  min-height: 0;
}

.dcp-project-grid__right {
  grid-column: 3;
  grid-row: 1;
  min-width: 0;
  min-height: 0;
}

.dcp-project-grid__bottom {
  grid-column: 1 / 4;
  grid-row: 2;
  min-width: 0;
}

.dcp-panel {
  display: flex;
  flex-direction: column;
  overflow: auto !important;
  min-height: 0;
  min-width: 0;
  height: 100%;
}

.dcp-panel :deep(.n-card-header),
.dcp-panel :deep(.n-card__header) {
  flex: 0 0 auto;
}

.dcp-panel :deep(.n-card__content),
.dcp-panel :deep(.n-card-content),
.dcp-panel :deep(.n-card__content-wrapper),
.dcp-panel :deep(.n-card-content-wrapper) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto !important;
}

.project-task-table {
  min-width: 0;
}

.project-task-table :deep(.n-data-table-base-table-body) {
  overflow-x: hidden !important;
}

.project-task-table :deep(.n-data-table-table) {
  table-layout: fixed;
}

.project-task-table :deep(.n-data-table-th),
.project-task-table :deep(.n-data-table-td) {
  padding: 11px 14px;
}

.project-task-table :deep(.n-data-table-tr) {
  transition:
    background-color var(--dcp-dur-fast) var(--dcp-ease),
    transform var(--dcp-dur-fast) var(--dcp-ease);
}

.project-task-table :deep(.n-data-table-tr:hover) {
  background: var(--dcp-hover);
}

.project-task-table :deep(.n-data-table-tr:active) {
  transform: scale(0.995);
}

.task-title-cell {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.task-title-cell__main,
.task-title-cell__meta {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-title-cell__main {
  font-weight: 620;
}

.task-title-cell__meta {
  color: var(--dcp-muted);
  font-size: 12px;
}

.task-row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
  min-width: 0;
}

.task-row-actions :deep(.n-button) {
  padding: 0 6px;
}

.dcp-group {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.dcp-group__list {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 4px 0;
}

.dcp-group__send {
  flex: 0 0 auto;
  position: sticky;
  bottom: 0;
  padding-top: 10px;
  border-top: 1px solid rgba(127, 127, 127, 0.18);
  background: var(--dcp-panel);
}

.dcp-gantt {
  display: flex;
  flex-direction: column;
  height: 300px;
  border: 1px solid var(--dcp-border);
}

.dcp-gantt__head {
  display: grid;
  grid-template-columns: 160px 1fr;
  border-bottom: 1px solid var(--dcp-border);
  background: rgba(47, 109, 246, 0.08);
}

.dcp-gantt__head-name {
  padding: 8px 8px;
  font-weight: 700;
  font-size: 12px;
  border-right: 1px solid var(--dcp-border);
}

.dcp-gantt__head-days {
  display: grid;
  grid-template-columns: repeat(var(--dcp-gantt-cols), 1fr);
}

.dcp-gantt__head-day {
  padding: 6px 6px;
  font-size: 12px;
  text-align: center;
  border-right: 1px solid var(--dcp-border);
}

.dcp-gantt__head-day:last-child {
  border-right: none;
}

.dcp-gantt__head-day.is-today {
  background: rgba(47, 109, 246, 0.14);
}

.dcp-gantt__head-dow {
  font-size: 11px;
  opacity: 0.75;
}

.dcp-gantt__body {
  flex: 1;
  overflow: auto;
  background: var(--dcp-panel);
}

.dcp-gantt__empty {
  padding: 10px;
  color: var(--dcp-muted);
  font-size: 12px;
}

.dcp-gantt__row {
  display: grid;
  grid-template-columns: 160px 1fr;
  border-bottom: 1px solid var(--dcp-border);
}

.dcp-gantt__name {
  padding: 6px 8px;
  font-size: 12px;
  border-right: 1px solid var(--dcp-border);
  display: flex;
  align-items: center;
  min-height: 30px;
  color: var(--dcp-text);
}

.dcp-gantt__name.is-blank {
  color: transparent;
}

.dcp-gantt__lane {
  position: relative;
  min-height: 30px;
  background-image: linear-gradient(
    to right,
    transparent calc(100% - 1px),
    rgba(255, 255, 255, 0.06) calc(100% - 1px)
  );
  background-size: calc(100% / var(--dcp-gantt-cols)) 100%;
}

.dcp-gantt__lane::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: calc(var(--dcp-gantt-today) * 100% / var(--dcp-gantt-cols));
  width: calc(100% / var(--dcp-gantt-cols));
  background: rgba(47, 109, 246, 0.08);
  pointer-events: none;
}

.dcp-gantt__bar {
  position: absolute;
  top: 5px;
  bottom: 5px;
  border-radius: 3px;
  display: flex;
  align-items: center;
  padding: 0 8px;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border: 1px solid rgba(255, 255, 255, 0.12);
  z-index: 1;
}

.dcp-gantt__bar.is-todo {
  background: rgba(59, 130, 246, 0.35);
}

.dcp-gantt__bar.is-doing {
  background: rgba(245, 158, 11, 0.35);
}

.dcp-gantt__bar.is-done {
  background: rgba(16, 185, 129, 0.35);
}

.dcp-gantt__bar.is-unknown {
  background: rgba(148, 163, 184, 0.28);
}

.dcp-gantt__bar-text {
  color: var(--dcp-text);
  opacity: 0.95;
}

@media (max-width: 1100px) {
  .dcp-project-grid {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }
  .dcp-project-grid__left,
  .dcp-project-grid__mid,
  .dcp-project-grid__right,
  .dcp-project-grid__bottom {
    grid-column: auto;
    grid-row: auto;
  }
}

@media (max-width: 640px) {
  .dcp-project-grid {
    gap: 8px;
    overflow-x: hidden;
  }

  .dcp-panel,
  .dcp-panel :deep(.n-card__content),
  .dcp-panel :deep(.n-card-content),
  .dcp-panel :deep(.n-card__content-wrapper),
  .dcp-panel :deep(.n-card-content-wrapper) {
    overflow-x: hidden !important;
  }

  .project-task-table {
    max-width: 100%;
    overflow-x: hidden;
  }

  .project-task-table :deep(.n-data-table-thead) {
    display: none;
  }

  .project-task-table :deep(.n-data-table-wrapper),
  .project-task-table :deep(.n-data-table-base-table),
  .project-task-table :deep(.n-data-table-base-table-body) {
    max-width: 100% !important;
    overflow-x: hidden !important;
  }

  .project-task-table :deep(.n-data-table-table),
  .project-task-table :deep(.n-data-table-tbody) {
    display: block;
    width: 100% !important;
    min-width: 0 !important;
  }

  .project-task-table :deep(.n-data-table-tr) {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 42px 82px 72px;
    align-items: center;
    width: 100% !important;
    min-width: 0 !important;
    padding: 0;
    border-bottom: 1px solid var(--dcp-border);
  }

  .project-task-table :deep(.n-data-table-td) {
    display: flex;
    align-items: center;
    min-width: 0;
    width: auto !important;
    border-bottom: 0 !important;
    padding: 10px 6px;
    overflow: hidden;
    white-space: nowrap;
  }

  .project-task-table :deep(.n-data-table-td:first-child) {
    padding-left: 12px;
  }

  .project-task-table :deep(.n-data-table-td:last-child) {
    position: static;
    justify-content: flex-end;
    width: auto !important;
    padding-right: 8px;
    transform: none;
  }

  .task-title-cell {
    display: flex;
    align-items: baseline;
    gap: 6px;
    min-width: 0;
  }

  .task-title-cell__main {
    min-width: 0;
    max-width: 58%;
    font-size: 14px;
  }

  .task-title-cell__meta {
    min-width: 0;
    flex: 1 1 auto;
    font-size: 12px;
  }

  .task-row-actions {
    width: 100%;
    justify-content: flex-end;
    gap: 0;
  }

  .task-row-actions :deep(.n-button) {
    min-width: 0;
    height: 26px;
    padding: 0 3px;
    font-size: 12px;
  }

  .project-task-table :deep(.n-tag) {
    min-width: 34px;
    justify-content: center;
  }

  .project-task-table :deep(.n-base-selection) {
    min-width: 0 !important;
    width: 76px !important;
  }

  .project-task-table :deep(.n-base-selection-label) {
    min-width: 0;
  }

  .dcp-gantt {
    min-width: 0;
  }

  .dcp-gantt__head,
  .dcp-gantt__row {
    grid-template-columns: 92px minmax(0, 1fr);
  }

  .dcp-gantt__head-day {
    padding: 6px 2px;
    font-size: 11px;
  }
}
</style>
