<script setup>
import { computed, h, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton,
  NCard,
  NDataTable,
  NDropdown,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NModal,
  NSpace,
  useMessage,
} from 'naive-ui'
import { AddOutline, DownloadOutline, PeopleOutline, SaveOutline, SendOutline } from '@vicons/ionicons5'
import { api, http } from '../api'
import UserSelect from '../components/UserSelect.vue'
import { useAuthStore } from '../stores/auth'
import { formatDisplayDate } from '../utils/dateFormat'

const route = useRoute()
const auth = useAuthStore()
const message = useMessage()

const projectId = computed(() => Number(route.params.projectId))

const loading = ref(false)
const project = ref(null)
const myRole = ref(null)
const stats = ref({
  tasks_total: 0,
  tasks_todo: 0,
  tasks_done: 0,
  files_count: 0,
  storage_bytes: 0,
})
const users = ref([])

const addMembersOpen = ref(false)
const addMemberIds = ref([])
const addMembersLoading = ref(false)

const existingMemberIdSet = computed(() => new Set((users.value || []).map((x) => Number(x?.user?.id)).filter((x) => Number.isFinite(x))))

async function onAddMembers() {
  const ids0 = (addMemberIds.value || []).map((x) => Number(x)).filter((x) => Number.isFinite(x))
  const ids = Array.from(new Set(ids0)).filter((x) => !existingMemberIdSet.value.has(x))
  if (ids.length === 0) {
    message.warning('请选择要添加的用户')
    return
  }

  addMembersLoading.value = true
  try {
    const results = await Promise.allSettled(ids.map((uid) => api.addProjectMember(projectId.value, { user_id: uid, role_project: 'user' })))
    const okCount = results.filter((x) => x.status === 'fulfilled').length
    const failCount = results.length - okCount
    if (okCount > 0) message.success(failCount > 0 ? `已添加 ${okCount} 人（${failCount} 人失败）` : `已添加 ${okCount} 人`)
    else message.error('添加失败')
    addMembersOpen.value = false
    addMemberIds.value = []
    await loadUsers()
  } finally {
    addMembersLoading.value = false
  }
}

const projectDraft = ref({ name: '', key: '', description: '' })
const canEditProjectMeta = computed(() => myRole.value === 'creator' || auth.user?.role_system === 'super_admin')
const projectDirty = computed(() => {
  const p = project.value || {}
  return (projectDraft.value.name || '') !== (p.name || '') || (projectDraft.value.key || '') !== (p.key || '') || (projectDraft.value.description || '') !== (p.description || '')
})

function bytesToText(n) {
  const v = Number(n)
  if (!Number.isFinite(v) || v <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let x = v
  let i = 0
  while (x >= 1024 && i < units.length - 1) {
    x /= 1024
    i += 1
  }
  const digits = i === 0 ? 0 : x < 10 ? 2 : x < 100 ? 1 : 0
  return `${x.toFixed(digits)} ${units[i]}`
}

function roleText(role) {
  if (role === 'creator') return '创建者'
  if (role === 'admin') return '管理员'
  if (role === 'user') return '成员'
  if (role === 'guest') return '访客'
  return role || '-'
}

async function loadOverview() {
  if (!Number.isFinite(projectId.value)) return
  loading.value = true
  try {
    const d = await api.projectManageOverview(projectId.value)
    project.value = d.project
    myRole.value = d.my_role
    stats.value = d.stats
    projectDraft.value = {
      name: d.project?.name || '',
      key: d.project?.key || '',
      description: d.project?.description || '',
    }
  } catch (e) {
    message.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadUsers() {
  if (!Number.isFinite(projectId.value)) return
  try {
    const d = await api.projectManageUsers(projectId.value)
    users.value = d.items || []
  } catch (e) {
    message.error(e?.message || '加载用户列表失败')
  }
}

async function reloadAll() {
  await Promise.all([loadOverview(), loadUsers()])
}

async function onDiscardProject() {
  projectDraft.value = {
    name: project.value?.name || '',
    key: project.value?.key || '',
    description: project.value?.description || '',
  }
}

async function onSaveProject() {
  try {
    const d = await api.patchProject(projectId.value, projectDraft.value)
    project.value = d.project
    message.success('已保存')
    await loadOverview()
  } catch (e) {
    message.error(e?.message || '保存失败')
  }
}

const siteMsgOpen = ref(false)
const siteMsgTarget = ref(null)
const siteMsgText = ref('')

function openSiteMsg(row) {
  siteMsgTarget.value = row
  siteMsgText.value = ''
  siteMsgOpen.value = true
}

async function sendSiteMsg() {
  const rid = Number(siteMsgTarget.value?.user?.id)
  if (!Number.isFinite(rid)) return
  const content = (siteMsgText.value || '').trim()
  if (!content) return
  try {
    await api.createThread({
      recipients: [rid],
      subject: `项目「${project.value?.name || projectId.value}」通知`,
      content_md: content,
    })
    message.success('已发送')
    siteMsgOpen.value = false
  } catch (e) {
    message.error(e?.message || '发送失败')
  }
}

const groupMsgOpen = ref(false)
const groupMsgText = ref('')

function openGroupMention(row) {
  const rid = Number(row?.user?.id)
  groupMsgText.value = Number.isFinite(rid) ? `@${rid} ` : ''
  groupMsgOpen.value = true
}

async function sendGroupMsg() {
  const content = (groupMsgText.value || '').trim()
  if (!content) return
  try {
    await api.sendProjectGroupMessage(projectId.value, { content_md: content })
    message.success('已发送')
    groupMsgOpen.value = false
  } catch (e) {
    message.error(e?.message || '发送失败')
  }
}

async function setAsAdmin(row) {
  const uid = Number(row?.user?.id)
  if (!Number.isFinite(uid)) return
  try {
    await api.patchProjectMember(projectId.value, uid, { role_project: 'admin' })
    message.success('已设置为管理员')
    await loadUsers()
  } catch (e) {
    message.error(e?.message || '操作失败')
  }
}

async function removeMember(row) {
  const uid = Number(row?.user?.id)
  if (!Number.isFinite(uid)) return
  try {
    await api.removeProjectMember(projectId.value, uid)
    message.success('已移除')
    await loadUsers()
  } catch (e) {
    message.error(e?.message || '操作失败')
  }
}

function userActionOptions(row) {
  const role = row?.role_project
  return [
    { label: '设为管理员', key: 'set_admin', disabled: role === 'creator' || role === 'admin' },
    { label: '开除成员', key: 'remove', disabled: role === 'creator' },
    { label: '发送站内信', key: 'site_msg' },
    { label: '群中@TA', key: 'group_mention' },
  ]
}

function onUserActionSelect(key, row) {
  if (key === 'set_admin') return setAsAdmin(row)
  if (key === 'remove') return removeMember(row)
  if (key === 'site_msg') return openSiteMsg(row)
  if (key === 'group_mention') return openGroupMention(row)
}

async function downloadUsers() {
  try {
    const resp = await http.get(`/projects/${projectId.value}/manage/users/export`, { responseType: 'blob' })
    const blob = new Blob([resp.data], { type: resp.headers?.['content-type'] || 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const name = project.value?.name || `project_${projectId.value}`
    a.href = url
    a.download = `${name}_用户信息.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (e) {
    message.error(e?.message || '下载失败')
  }
}

const userColumns = computed(() => [
  { title: '用户名', key: 'username', minWidth: 220, render: (row) => row?.user?.display_name || row?.user?.username || `#${row?.user?.id}` },
  { title: '状态', key: 'status', width: 90, render: (row) => (row?.user?.status === 'active' ? '正常' : row?.user?.status || '-') },
  { title: '身份', key: 'role_project', width: 110, render: (row) => roleText(row?.role_project) },
  {
    title: '加入时间',
    key: 'joined_at',
    width: 130,
    render: (row) => formatDisplayDate(row?.joined_at),
  },
  { title: '发布任务数', key: 'tasks_reported', width: 110 },
  { title: '完成任务数', key: 'tasks_completed', width: 110 },
  { title: '上传文件数', key: 'files_uploaded', width: 110 },
  { title: '发布消息数', key: 'messages_sent', width: 110 },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render: (row) =>
      h(
        NDropdown,
        { options: userActionOptions(row), trigger: 'click', onSelect: (k) => onUserActionSelect(k, row) },
        { default: () => h('a', { class: 'dcp-link' }, '操作') },
      ),
  },
])

watch(projectId, reloadAll, { immediate: true })
</script>

<template>
  <NSpace vertical size="large" class="dcp-page">
    <div class="pm-grid">
      <div class="pm-left">
        <NCard>
          <div class="pm-title">项目管理 · {{ project?.name || `#${projectId}` }}</div>
          <div class="pm-meta">
            <div class="pm-meta-row">
              <div class="pm-meta-k">项目名称：</div>
              <div class="pm-meta-v">
                <NInput v-model:value="projectDraft.name" size="small" :disabled="!canEditProjectMeta" />
              </div>
            </div>
            <div class="pm-meta-row">
              <div class="pm-meta-k">项目编号：</div>
              <div class="pm-meta-v">
                <NInput v-model:value="projectDraft.key" size="small" :disabled="!canEditProjectMeta" />
              </div>
            </div>
            <div class="pm-meta-row">
              <div class="pm-meta-k">项目创建时间：</div>
              <div class="pm-meta-v">{{ formatDisplayDate(project?.created_at) }}</div>
            </div>
          </div>

          <div class="pm-stats">
            <div class="pm-progress">
              <div class="pm-progress__head">
                <span>任务完成度</span>
                <strong>{{ stats.tasks_total ? Math.round((stats.tasks_done / stats.tasks_total) * 100) : 0 }}%</strong>
              </div>
              <div class="pm-progress__track">
                <div class="pm-progress__done" :style="{ width: `${stats.tasks_total ? Math.round((stats.tasks_done / stats.tasks_total) * 100) : 0}%` }" />
              </div>
              <div class="pm-progress__legend">
                <span><i class="is-done" />已完成 {{ stats.tasks_done }}</span>
                <span><i class="is-todo" />未完成 {{ stats.tasks_todo }}</span>
              </div>
            </div>
            <div class="pm-stat-row">
              <div class="pm-stat">
                <div class="pm-stat-num is-blue">{{ stats.tasks_total }}</div>
                <div class="pm-stat-label">总任务数</div>
              </div>
              <div class="pm-stat">
                <div class="pm-stat-num is-orange">{{ stats.tasks_todo }}</div>
                <div class="pm-stat-label">未完成</div>
              </div>
              <div class="pm-stat">
                <div class="pm-stat-num is-green">{{ stats.tasks_done }}</div>
                <div class="pm-stat-label">已完成</div>
              </div>
            </div>
            <div class="pm-stat-row">
              <div class="pm-stat">
                <div class="pm-stat-num is-blue">{{ stats.files_count }}</div>
                <div class="pm-stat-label">文件数量</div>
              </div>
              <div class="pm-stat">
                <div class="pm-stat-num is-blue">{{ bytesToText(stats.storage_bytes) }}</div>
                <div class="pm-stat-label">文件大小占用</div>
              </div>
            </div>
          </div>

          <div class="pm-meta pm-bottom">
            <div class="pm-meta-row">
              <div class="pm-meta-k">项目状态：</div>
              <div class="pm-meta-v">{{ project?.status || '-' }}</div>
            </div>
            <div class="pm-meta-row">
              <div class="pm-meta-k">项目邀请码：</div>
              <div class="pm-meta-v">{{ project?.key || '-' }}</div>
            </div>
          </div>

          <NSpace justify="space-between" style="margin-top: 14px">
            <NButton :disabled="!projectDirty" @click="onDiscardProject">放弃修改</NButton>
            <NButton type="primary" :disabled="!canEditProjectMeta || !projectDirty" @click="onSaveProject"><template #icon><NIcon><SaveOutline /></NIcon></template>保存</NButton>
          </NSpace>
        </NCard>
      </div>

      <div class="pm-right">
        <NCard>
          <NSpace justify="space-between" align="center">
            <div style="font-size: 16px; font-weight: 700">用户列表</div>
            <NSpace>
              <NButton @click="addMembersOpen = true"><template #icon><NIcon><PeopleOutline /></NIcon></template>添加项目成员</NButton>
              <NButton type="primary" @click="downloadUsers"><template #icon><NIcon><DownloadOutline /></NIcon></template>下载用户信息</NButton>
            </NSpace>
          </NSpace>
          <div style="margin-top: 12px">
            <NDataTable :data="users" :columns="userColumns" :pagination="{ pageSize: 20 }" />
          </div>
        </NCard>
      </div>
    </div>

    <NModal v-model:show="addMembersOpen" preset="card" title="添加项目成员" style="width: 520px; max-width: 96vw">
      <NForm>
        <NFormItem label="选择成员">
          <UserSelect v-model="addMemberIds" multiple placeholder="搜索用户名/显示名，支持多选" />
        </NFormItem>
        <NSpace justify="end">
          <NButton :disabled="addMembersLoading" @click="addMembersOpen = false">取消</NButton>
          <NButton type="primary" :loading="addMembersLoading" :disabled="(addMemberIds || []).length === 0" @click="onAddMembers"><template #icon><NIcon><AddOutline /></NIcon></template>添加</NButton>
        </NSpace>
      </NForm>
    </NModal>

    <NModal v-model:show="siteMsgOpen" preset="card" title="发送站内信" style="width: 520px; max-width: 96vw">
      <NForm>
        <NFormItem label="收件人">
          <div>{{ siteMsgTarget?.user?.display_name || siteMsgTarget?.user?.username || '-' }}</div>
        </NFormItem>
        <NFormItem label="内容（Markdown）">
          <NInput v-model:value="siteMsgText" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" />
        </NFormItem>
        <NSpace justify="end">
          <NButton @click="siteMsgOpen = false">取消</NButton>
          <NButton type="primary" :disabled="!siteMsgText.trim()" @click="sendSiteMsg"><template #icon><NIcon><SendOutline /></NIcon></template>发送</NButton>
        </NSpace>
      </NForm>
    </NModal>

    <NModal v-model:show="groupMsgOpen" preset="card" title="群组@提及" style="width: 520px; max-width: 96vw">
      <NForm>
        <NFormItem label="内容（Markdown）">
          <NInput v-model:value="groupMsgText" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" />
        </NFormItem>
        <NSpace justify="end">
          <NButton @click="groupMsgOpen = false">取消</NButton>
          <NButton type="primary" :disabled="!groupMsgText.trim()" @click="sendGroupMsg"><template #icon><NIcon><SendOutline /></NIcon></template>发送</NButton>
        </NSpace>
      </NForm>
    </NModal>
  </NSpace>
</template>

<style scoped>
.pm-grid {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 12px;
  min-width: 0;
}

.pm-left,
.pm-right {
  min-width: 0;
}

.pm-title {
  font-size: 18px;
  font-weight: 700;
}

.pm-meta {
  margin-top: 10px;
}

.pm-meta-row {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px;
  align-items: center;
  padding: 6px 0;
}

.pm-meta-k {
  opacity: 0.8;
  font-size: 12px;
}

.pm-meta-v {
  font-size: 12px;
}

.pm-stats {
  margin-top: 10px;
  border-top: 1px solid var(--dcp-border);
  border-bottom: 1px solid var(--dcp-border);
  padding: 10px 0;
}

.pm-progress {
  padding: 4px 0 12px;
}

.pm-progress__head,
.pm-progress__legend {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  color: var(--dcp-muted);
}

.pm-progress__head strong {
  color: var(--dcp-text);
  font-weight: 800;
}

.pm-progress__track {
  height: 12px;
  margin: 8px 0;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.22);
}

.pm-progress__done {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2f6df6, #10b981);
}

.pm-progress__legend i {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 5px;
  border-radius: 999px;
}

.pm-progress__legend .is-done {
  background: #10b981;
}

.pm-progress__legend .is-todo {
  background: #f59e0b;
}

.pm-stat-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  padding: 8px 0;
}

.pm-stat-row:last-child {
  grid-template-columns: repeat(2, 1fr);
}

.pm-stat {
  text-align: center;
}

.pm-stat-num {
  font-weight: 800;
  font-size: 32px;
  line-height: 1.1;
}

.pm-stat-num.is-blue {
  color: #2f6df6;
}

.pm-stat-num.is-orange {
  color: #f59e0b;
}

.pm-stat-num.is-green {
  color: #10b981;
}

.pm-stat-label {
  margin-top: 6px;
  font-size: 12px;
  opacity: 0.8;
}

.pm-bottom {
  margin-top: 10px;
}

@media (max-width: 1000px) {
  .pm-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 520px) {
  .pm-meta-row,
  .pm-stat-row,
  .pm-stat-row:last-child {
    grid-template-columns: 1fr;
  }

  .pm-stat-num {
    font-size: 24px;
  }
}
</style>
