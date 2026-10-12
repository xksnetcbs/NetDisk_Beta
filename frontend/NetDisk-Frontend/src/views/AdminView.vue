<script setup>
import { computed, onMounted, ref } from 'vue'
import { h } from 'vue'
import { NButton, NCard, NDataTable, NDropdown, NInput, NModal, NSpace, NStatistic, useMessage } from 'naive-ui'
import { api } from '../api'
import { formatDisplayDate } from '../utils/dateFormat'

const message = useMessage()
const overview = ref(null)
const projects = ref([])
const storage = ref(null)
const loading = ref(false)
const pendingUsers = ref([])
const inviteCodes = ref([])
const newInviteCode = ref('')
const newInviteNote = ref('')
const newInviteMaxUses = ref('')
const usersAll = ref([])
const usersQ = ref('')
const usersLoading = ref(false)
const inviteMaxOpen = ref(false)
const inviteMaxRow = ref(null)
const inviteMaxValue = ref('')
const chartColors = ['#18a058', '#2080f0', '#f0a020', '#d03050', '#8a2be2', '#00a2ae', '#c97b2b', '#6c7a89']

const storageMetricCards = computed(() => [
  { label: '物理占用', value: bytesToText(storage.value?.storage_bytes), hint: `${storage.value?.objects_count || 0} 个对象` },
  { label: '逻辑文件大小', value: bytesToText(storage.value?.logical_bytes), hint: `${storage.value?.files_count || 0} 个文件` },
  { label: '目录节点', value: storage.value?.folders_count || 0, hint: `${storage.value?.nodes_count || 0} 个有效节点` },
  { label: '平均对象大小', value: bytesToText(storage.value?.avg_object_size), hint: `最大 ${bytesToText(storage.value?.largest_object_bytes)}` },
  { label: '重复对象', value: storage.value?.duplicate_objects_count || 0, hint: `可回收 ${bytesToText(storage.value?.duplicate_reclaimable_bytes)}` },
  { label: '已删节点', value: storage.value?.deleted_nodes_count || 0, hint: '软删除记录' },
])

const storageScopeRows = computed(() =>
  makeShareRows(storage.value?.scopes || [], 'scope', storage.value?.logical_bytes || storage.value?.storage_bytes, scopeText),
)
const storageTypeRows = computed(() => makeShareRows(storage.value?.types || [], 'type', storage.value?.storage_bytes))
const storageTypePieStyle = computed(() => ({ background: makeConicGradient(storageTypeRows.value) }))
const topProjectRows = computed(() => makeShareRows(storage.value?.top_projects || [], 'name', maxStorage(storage.value?.top_projects)))
const topUserRows = computed(() => makeShareRows(storage.value?.top_users || [], 'name', maxStorage(storage.value?.top_users)))

async function load() {
  loading.value = true
  try {
    overview.value = await api.adminOverview()
    storage.value = await api.adminStorage()
    const p = await api.adminProjects()
    projects.value = p.items || []
    const pu = await api.listUsers({ page: 1, page_size: 200, activated: 0 })
    pendingUsers.value = pu.items || []
    const ic = await api.adminInviteCodes()
    inviteCodes.value = ic.items || []
    await loadAllUsers()
  } catch (e) {
    message.error(e?.message || '无权限或加载失败')
  } finally {
    loading.value = false
  }
}

async function loadAllUsers() {
  usersLoading.value = true
  try {
    const d = await api.adminUsers({ q: usersQ.value, page: 1, page_size: 200 })
    usersAll.value = d.items || []
  } catch (e) {
    message.error(e?.message || '加载用户列表失败')
    usersAll.value = []
  } finally {
    usersLoading.value = false
  }
}

const columns = [
  { title: '名称', key: 'name', minWidth: 260 },
  { title: 'Key', key: 'key', width: 140 },
  { title: '状态', key: 'status', width: 120 },
  { title: '创建者', key: 'creator_id', width: 120 },
]

function roleSystemText(v) {
  if (v === 'super_admin') return '超级管理员'
  if (v === 'user') return '用户'
  return v || '-'
}

function statusText(v) {
  if (v === 'active') return '正常'
  if (v === 'disabled') return '禁用'
  if (v === 'deleted') return '已删除'
  return v || '-'
}

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

function scopeText(v) {
  if (v === 'personal') return '个人空间'
  if (v === 'project') return '项目空间'
  return v || '未知'
}

function maxStorage(rows = []) {
  return Math.max(...(rows || []).map((x) => Number(x?.storage_bytes || 0)), 0)
}

function makeShareRows(rows = [], labelKey, total, labeler = (v) => v || '-') {
  const t = Number(total) || 0
  return (rows || []).map((row, index) => {
    const size = Number(row?.storage_bytes || 0)
    const rawPct = t > 0 ? (size / t) * 100 : 0
    const pct = Math.round(rawPct)
    return {
      ...row,
      label: labeler(row?.[labelKey]),
      sizeText: bytesToText(size),
      countText: `${row?.files_count ?? row?.objects_count ?? 0} 个`,
      pctText: `${pct}%`,
      pctValue: rawPct,
      width: `${Math.max(pct, size > 0 ? 2 : 0)}%`,
      color: chartColors[index % chartColors.length],
    }
  })
}

function makeConicGradient(rows = []) {
  const visibleRows = (rows || []).slice(0, 8).filter((row) => Number(row?.pctValue || 0) > 0)
  if (!visibleRows.length) return 'rgba(127, 127, 127, 0.14)'

  let cursor = 0
  const segments = visibleRows.map((row, index) => {
    const start = cursor
    cursor += Number(row.pctValue || 0)
    const end = index === visibleRows.length - 1 ? 100 : cursor
    return `${row.color} ${start.toFixed(2)}% ${end.toFixed(2)}%`
  })
  return `conic-gradient(${segments.join(', ')})`
}

function userActions(row) {
  const id = Number(row?.id)
  const status = row?.status
  const role = row?.role_system
  return [
    { label: status === 'disabled' ? '恢复登录' : '禁止登录', key: 'toggle_login', disabled: !Number.isFinite(id) || status === 'deleted' },
    { label: role === 'super_admin' ? '设为普通用户' : '设为超级管理员', key: 'toggle_super', disabled: !Number.isFinite(id) || status === 'deleted' },
    { label: '删除用户', key: 'delete', disabled: !Number.isFinite(id) || status === 'deleted' },
  ]
}

async function onUserActionSelect(key, row) {
  const id = Number(row?.id)
  if (!Number.isFinite(id)) return

  try {
    if (key === 'toggle_login') {
      if (row?.status === 'disabled') await api.adminEnableUser(id)
      else {
        if (!window.confirm(`确认禁止用户 #${id} 登录？`)) return
        await api.adminDisableUser(id)
      }
      message.success('已更新')
      await loadAllUsers()
      return
    }
    if (key === 'toggle_super') {
      if (row?.role_system === 'super_admin') {
        if (!window.confirm(`确认将用户 #${id} 设为普通用户？`)) return
        await api.adminSetUser(id)
      } else {
        if (!window.confirm(`确认将用户 #${id} 设为超级管理员？`)) return
        await api.adminSetSuperAdmin(id)
      }
      message.success('已更新')
      await loadAllUsers()
      return
    }
    if (key === 'delete') {
      if (!window.confirm(`确认删除用户 #${id}？此操作不可恢复。`)) return
      await api.adminDeleteUser(id)
      message.success('已删除')
      await loadAllUsers()
    }
  } catch (e) {
    message.error(e?.message || '操作失败')
  }
}

const usersColumns = [
  { title: '用户名', key: 'username', minWidth: 180, fixed: 'left', render: (row) => row?.display_name || row?.username || `#${row?.id}` },
  { title: 'ID', key: 'id', width: 90, fixed: 'left' },
  { title: '账号', key: 'username_raw', minWidth: 160, render: (row) => row?.username || '-' },
  { title: '邮箱', key: 'email', minWidth: 200, render: (row) => row?.email || '-' },
  { title: '系统角色', key: 'role_system', width: 120, render: (row) => roleSystemText(row?.role_system) },
  { title: '状态', key: 'status', width: 100, render: (row) => statusText(row?.status) },
  { title: '已激活', key: 'is_activated', width: 90, render: (row) => (row?.is_activated ? '是' : '否') },
  { title: '邀请码', key: 'invite_code', width: 140, render: (row) => row?.invite_code || '-' },
  { title: '注册时间', key: 'created_at', width: 170, render: (row) => formatDisplayDate(row?.created_at) },
  { title: '最近登录', key: 'last_login_at', width: 170, render: (row) => formatDisplayDate(row?.last_login_at) },
  { title: '上传文件数', key: 'uploads_count', width: 110, render: (row) => row?.stats?.uploads_count ?? 0 },
  { title: '上传大小', key: 'uploads_bytes', width: 140, render: (row) => bytesToText(row?.stats?.uploads_bytes) },
  { title: '完成任务数', key: 'tasks_completed', width: 110, render: (row) => row?.stats?.tasks_completed ?? 0 },
  { title: '发布任务数', key: 'tasks_reported', width: 110, render: (row) => row?.stats?.tasks_reported ?? 0 },
  { title: '创建项目数', key: 'projects_created', width: 110, render: (row) => row?.stats?.projects_created ?? 0 },
  { title: '加入项目数', key: 'memberships', width: 110, render: (row) => row?.stats?.memberships ?? 0 },
  { title: '站内信数', key: 'inbox_sent', width: 110, render: (row) => row?.stats?.inbox_sent ?? 0 },
  { title: '创建邀请码数', key: 'invite_codes_created', width: 120, render: (row) => row?.stats?.invite_codes_created ?? 0 },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    fixed: 'right',
    render: (row) =>
      h(
        NDropdown,
        { options: userActions(row), trigger: 'click', onSelect: (k) => onUserActionSelect(k, row) },
        { default: () => h('a', { class: 'dcp-link' }, '操作') },
      ),
  },
]

async function approveUser(row) {
  try {
    await api.activateUser(row.id)
    message.success('已批准')
    await load()
  } catch (e) {
    message.error(e?.message || '操作失败')
  }
}

async function createInvite() {
  try {
    const max0 = (newInviteMaxUses.value || '').trim()
    const payload = { code: newInviteCode.value, note: newInviteNote.value || undefined }
    if (max0) {
      const n = Number(max0)
      if (!Number.isFinite(n) || n < 0) {
        message.error('最大使用次数非法')
        return
      }
      payload.max_uses = Math.floor(n)
    }
    const d = await api.createInviteCode(payload)
    message.success(`已创建邀请码：${d.invite_code.code}`)
    newInviteCode.value = ''
    newInviteNote.value = ''
    newInviteMaxUses.value = ''
    await load()
  } catch (e) {
    message.error(e?.message || '创建失败')
  }
}

const pendingColumns = [
  { title: 'ID', key: 'id', width: 80 },
  { title: '用户名', key: 'username', minWidth: 180 },
  { title: '显示名', key: 'display_name', minWidth: 180 },
  { title: '邀请码', key: 'invite_code', width: 140 },
  {
    title: '操作',
    key: 'actions',
    width: 120,
    render: (row) => h(NButton, { size: 'small', type: 'primary', onClick: () => approveUser(row) }, { default: () => '批准' }),
  },
]

const inviteColumns = [
  { title: '邀请码', key: 'code', width: 160 },
  { title: '启用', key: 'enabled', width: 80, render: (row) => (row.enabled ? '是' : '否') },
  { title: '使用次数', key: 'used_count', width: 100 },
  { title: '最大次数', key: 'max_uses', width: 100, render: (row) => (row?.max_uses === null || row?.max_uses === undefined ? '∞' : row.max_uses) },
  { title: '备注', key: 'note', minWidth: 260 },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render: (row) =>
      h(
        NDropdown,
        {
          options: [
            { label: row.enabled ? '设为失效' : '设为生效', key: 'toggle' },
            { label: '设置最大次数', key: 'set_max' },
            { label: '取消最大次数', key: 'clear_max' },
          ],
          trigger: 'click',
          onSelect: (k) => onInviteAction(k, row),
        },
        { default: () => h('a', { class: 'dcp-link' }, '操作') },
      ),
  },
]

function openInviteMax(row) {
  inviteMaxRow.value = row
  inviteMaxValue.value = row?.max_uses === null || row?.max_uses === undefined ? '' : String(row.max_uses)
  inviteMaxOpen.value = true
}

async function saveInviteMax() {
  const row = inviteMaxRow.value
  const id = Number(row?.id)
  if (!Number.isFinite(id)) return
  const v0 = (inviteMaxValue.value || '').trim()
  let payload
  if (!v0) payload = { max_uses: null }
  else {
    const n = Number(v0)
    if (!Number.isFinite(n) || n < 0) {
      message.error('最大使用次数非法')
      return
    }
    payload = { max_uses: Math.floor(n) }
  }
  try {
    await api.patchInviteCode(id, payload)
    message.success('已更新')
    inviteMaxOpen.value = false
    inviteMaxRow.value = null
    await load()
  } catch (e) {
    message.error(e?.message || '操作失败')
  }
}

async function onInviteAction(key, row) {
  const id = Number(row?.id)
  if (!Number.isFinite(id)) return
  try {
    if (key === 'toggle') {
      await api.patchInviteCode(id, { enabled: !row.enabled })
      message.success('已更新')
      await load()
      return
    }
    if (key === 'set_max') {
      openInviteMax(row)
      return
    }
    if (key === 'clear_max') {
      await api.patchInviteCode(id, { max_uses: null })
      message.success('已更新')
      await load()
    }
  } catch (e) {
    message.error(e?.message || '操作失败')
  }
}

onMounted(load)
</script>

<template>
  <NSpace vertical size="large">
    <NCard>
      <div style="font-size: 18px; font-weight: 700">管理后台</div>
      <div style="opacity: 0.7; margin-top: 8px; font-size: 12px">仅 super_admin 可用</div>
    </NCard>

    <NSpace :wrap="true" size="large">
      <NCard style="min-width: 220px; flex: 1">
        <NStatistic label="用户数" :value="overview?.users || 0" />
      </NCard>
      <NCard style="min-width: 220px; flex: 1">
        <NStatistic label="项目数" :value="overview?.projects || 0" />
      </NCard>
      <NCard style="min-width: 220px; flex: 1">
        <NStatistic label="存储占用" :value="bytesToText(overview?.storage_bytes)" />
      </NCard>
    </NSpace>

    <NCard title="存储统计">
      <div class="storage-metrics">
        <div v-for="item in storageMetricCards" :key="item.label" class="storage-metric">
          <div class="storage-metric__label">{{ item.label }}</div>
          <div class="storage-metric__value">{{ item.value }}</div>
          <div class="storage-metric__hint">{{ item.hint }}</div>
        </div>
      </div>

      <div class="storage-charts">
        <div class="storage-panel">
          <div class="storage-panel__title">空间范围占用</div>
          <div v-if="storageScopeRows.length" class="storage-bars">
            <div v-for="row in storageScopeRows" :key="row.scope" class="storage-bar-row">
              <div class="storage-bar-row__head">
                <span>{{ row.label }}</span>
                <strong>{{ row.sizeText }}</strong>
              </div>
              <div class="storage-bar-track">
                <div class="storage-bar-fill" :style="{ width: row.width, background: row.color }" />
              </div>
              <div class="storage-bar-row__meta">{{ row.countText }} · {{ row.pctText }}</div>
            </div>
          </div>
          <div v-else class="storage-empty">暂无空间占用数据</div>
        </div>

        <div class="storage-panel">
          <div class="storage-panel__title">文件类型分布</div>
          <div v-if="storageTypeRows.length" class="storage-donut-wrap">
            <div class="storage-donut" :style="storageTypePieStyle">
              <div class="storage-donut__center">
                <strong>{{ bytesToText(storage?.storage_bytes) }}</strong>
                <span>总占用</span>
              </div>
            </div>
            <div class="storage-legend">
              <div v-for="row in storageTypeRows.slice(0, 8)" :key="row.type">
                <span :style="{ background: row.color }" />
                {{ row.label }} {{ row.sizeText }} · {{ row.pctText }}
              </div>
            </div>
          </div>
          <div v-else class="storage-empty">暂无类型分布数据</div>
        </div>

        <div class="storage-panel">
          <div class="storage-panel__title">项目占用排行</div>
          <div v-if="topProjectRows.length" class="storage-bars">
            <div v-for="row in topProjectRows" :key="row.project_id" class="storage-bar-row is-compact">
              <div class="storage-bar-row__head">
                <span>{{ row.label }}</span>
                <strong>{{ row.sizeText }}</strong>
              </div>
              <div class="storage-bar-track">
                <div class="storage-bar-fill" :style="{ width: row.width, background: row.color }" />
              </div>
            </div>
          </div>
          <div v-else class="storage-empty">暂无项目文件数据</div>
        </div>

        <div class="storage-panel">
          <div class="storage-panel__title">用户占用排行</div>
          <div v-if="topUserRows.length" class="storage-bars">
            <div v-for="row in topUserRows" :key="row.user_id" class="storage-bar-row is-compact">
              <div class="storage-bar-row__head">
                <span>{{ row.label }}</span>
                <strong>{{ row.sizeText }}</strong>
              </div>
              <div class="storage-bar-track">
                <div class="storage-bar-fill" :style="{ width: row.width, background: row.color }" />
              </div>
            </div>
          </div>
          <div v-else class="storage-empty">暂无用户文件数据</div>
        </div>
      </div>
    </NCard>

    <NCard title="待审核用户">
      <NDataTable :columns="pendingColumns" :data="pendingUsers" :loading="loading" :pagination="{ pageSize: 20 }" />
      <div style="margin-top: 8px; font-size: 12px; opacity: 0.75">用户注册后默认为未激活，需要在此处批准</div>
    </NCard>

    <NCard title="用户管理">
      <NSpace align="center">
        <NInput v-model:value="usersQ" placeholder="搜索用户名/显示名/邮箱" style="max-width: 260px" />
        <NButton :loading="usersLoading" @click="loadAllUsers">查询</NButton>
        <NButton :loading="usersLoading" @click="usersQ = ''; loadAllUsers()">清空</NButton>
      </NSpace>
      <div style="margin-top: 10px">
        <NDataTable :columns="usersColumns" :data="usersAll" :loading="usersLoading" :pagination="{ pageSize: 20 }" />
      </div>
      <div style="margin-top: 8px; font-size: 12px; opacity: 0.75">注意：禁止登录只会阻止后续登录，已登录 token 可能仍可在过期前继续使用</div>
    </NCard>

    <NCard title="邀请码">
      <NSpace align="center">
        <NInput v-model:value="newInviteCode" placeholder="邀请码（必填）" style="max-width: 200px" />
        <NInput v-model:value="newInviteNote" placeholder="备注（可选）" style="max-width: 260px" />
        <NInput v-model:value="newInviteMaxUses" placeholder="最大使用次数（空=不限）" style="max-width: 200px" />
        <NButton type="primary" :disabled="!newInviteCode.trim()" @click="createInvite">创建</NButton>
      </NSpace>
      <div style="margin-top: 10px">
        <NDataTable :columns="inviteColumns" :data="inviteCodes" :loading="loading" :pagination="{ pageSize: 20 }" />
      </div>
    </NCard>

    <NModal v-model:show="inviteMaxOpen" preset="card" title="设置最大使用次数" style="width: 460px; max-width: 96vw">
      <NSpace vertical>
        <div style="opacity: 0.8; font-size: 12px">邀请码：{{ inviteMaxRow?.code }}</div>
        <NInput v-model:value="inviteMaxValue" placeholder="留空表示不限（∞）" />
        <NSpace justify="end">
          <NButton @click="inviteMaxOpen = false">取消</NButton>
          <NButton type="primary" @click="saveInviteMax">保存</NButton>
        </NSpace>
      </NSpace>
    </NModal>

    <NCard title="项目列表">
      <NDataTable :columns="columns" :data="projects" :loading="loading" :pagination="{ pageSize: 20 }" />
    </NCard>
  </NSpace>
</template>

<style scoped>
.storage-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.storage-metric {
  min-width: 0;
  padding: 12px;
  border: 1px solid rgba(127, 127, 127, 0.16);
  border-radius: 8px;
  background: rgba(127, 127, 127, 0.06);
}

.storage-metric__label,
.storage-metric__hint,
.storage-bar-row__meta,
.storage-empty {
  color: var(--dcp-muted);
  font-size: 12px;
}

.storage-metric__value {
  margin-top: 6px;
  font-size: 20px;
  font-weight: 700;
}

.storage-metric__hint {
  margin-top: 4px;
}

.storage-charts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.storage-panel {
  min-width: 0;
  padding: 14px;
  border: 1px solid rgba(127, 127, 127, 0.16);
  border-radius: 8px;
}

.storage-panel__title {
  margin-bottom: 12px;
  font-weight: 700;
}

.storage-bars {
  display: grid;
  gap: 12px;
}

.storage-bar-row__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
}

.storage-bar-row__head span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.storage-bar-row__head strong {
  flex: 0 0 auto;
}

.storage-bar-track {
  height: 10px;
  margin-top: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(127, 127, 127, 0.14);
}

.storage-bar-fill {
  height: 100%;
  border-radius: inherit;
}

.storage-bar-row__meta {
  margin-top: 4px;
}

.storage-bar-row.is-compact .storage-bar-track {
  height: 8px;
}

.storage-donut-wrap {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 16px;
  align-items: center;
}

.storage-donut {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  display: grid;
  place-items: center;
}

.storage-donut__center {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  border-radius: 50%;
  background: var(--n-color);
  text-align: center;
  line-height: 1.2;
}

.storage-donut__center strong {
  max-width: 50px;
  overflow: hidden;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.storage-donut__center span {
  color: var(--dcp-muted);
  font-size: 10px;
}

.storage-legend {
  display: grid;
  gap: 8px;
  min-width: 0;
  font-size: 12px;
}

.storage-legend div {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.storage-legend span {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 6px;
  border-radius: 999px;
}

.storage-empty {
  padding: 22px 0;
  text-align: center;
}

@media (max-width: 900px) {
  .storage-metrics,
  .storage-charts {
    grid-template-columns: 1fr;
  }
}
</style>
