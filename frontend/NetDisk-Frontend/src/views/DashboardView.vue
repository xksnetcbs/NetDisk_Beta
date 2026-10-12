<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NCard, NDataTable, NIcon, NSpace, NStatistic, useMessage } from 'naive-ui'
import { BriefcaseOutline, CalendarOutline, FolderOpenOutline, LogInOutline, MailOutline, RefreshOutline } from '@vicons/ionicons5'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'
import { useInfoCenterStore } from '../stores/infocenter'
import { formatDisplayDate } from '../utils/dateFormat'

const auth = useAuthStore()
const infoCenter = useInfoCenterStore()
const router = useRouter()
const message = useMessage()

const projects = ref([])
const notifications = ref([])
const loading = ref(false)

const isSuperAdmin = computed(() => auth.user?.role_system === 'super_admin')
const displayedNotifications = computed(() => isSuperAdmin.value ? infoCenter.latest.map(item => ({
  ...item, type: item.source === 'netdisk' ? '站内消息' : '微信消息', created_at: item.occurred_at,
})) : notifications.value)
const notificationCount = computed(() => isSuperAdmin.value ? infoCenter.totalCount : notifications.value.length)
const unreadCount = computed(() => isSuperAdmin.value ? infoCenter.unreadCount : notifications.value.filter((x) => !x.read_at).length)
const readCount = computed(() => Math.max(0, notificationCount.value - unreadCount.value))
const roleRows = computed(() => {
  const rows = [
    { key: 'owner', label: '创建/管理', value: projects.value.filter((x) => ['creator', 'admin'].includes(x?.role)).length, color: '#2f6df6' },
    { key: 'member', label: '成员', value: projects.value.filter((x) => x?.role === 'user').length, color: '#10b981' },
    { key: 'guest', label: '访客', value: projects.value.filter((x) => x?.role === 'guest').length, color: '#f59e0b' },
  ]
  const max = Math.max(1, ...rows.map((x) => x.value))
  return rows.map((x) => ({ ...x, pct: `${Math.max(6, Math.round((x.value / max) * 100))}%` }))
})
const notificationRows = computed(() => [
  { key: 'unread', label: '未读', value: unreadCount.value, color: '#f59e0b' },
  { key: 'read', label: '已读', value: readCount.value, color: '#10b981' },
])

async function load() {
  loading.value = true
  try {
    const p = await api.listProjects({ page: 1, page_size: 20 })
    projects.value = p.items || []
    if (isSuperAdmin.value) await infoCenter.refresh(true)
    else {
      const n = await api.listNotifications({ page: 1, page_size: 20 })
      notifications.value = n.items || []
    }
  } catch (e) {
    message.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <NSpace vertical size="large" class="dcp-page">
    <NCard>
      <NSpace justify="space-between" align="center">
        <div>
          <div style="font-size: 18px; font-weight: 700">工作台</div>
          <div style="opacity: 0.7; margin-top: 6px; font-size: 12px">你好，{{ auth.user?.display_name || auth.user?.username }}</div>
        </div>
        <NButton @click="load" :loading="loading">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>
          刷新
        </NButton>
      </NSpace>
    </NCard>

    <NSpace :wrap="true" size="large">
      <NCard class="dashboard-card">
        <NStatistic label="项目数" :value="projects.length" />
      </NCard>
      <NCard class="dashboard-card">
        <NStatistic :label="isSuperAdmin ? '信息中心未读' : '未读通知'" :value="unreadCount" />
      </NCard>
      <NCard class="dashboard-card">
        <NSpace vertical>
          <div style="opacity: 0.7; font-size: 12px">快捷入口</div>
          <NSpace>
            <NButton size="small" @click="router.push('/projects')"><template #icon><NIcon><BriefcaseOutline /></NIcon></template>项目</NButton>
            <NButton size="small" @click="router.push('/disk')"><template #icon><NIcon><FolderOpenOutline /></NIcon></template>网盘</NButton>
            <NButton size="small" @click="router.push('/calendar')"><template #icon><NIcon><CalendarOutline /></NIcon></template>日程</NButton>
            <NButton size="small" @click="router.push('/inbox')"><template #icon><NIcon><MailOutline /></NIcon></template>消息</NButton>
          </NSpace>
        </NSpace>
      </NCard>
    </NSpace>

    <div class="dashboard-charts">
      <NCard title="项目角色分布">
        <div class="mini-bars">
          <div v-for="row in roleRows" :key="row.key" class="mini-bar-row">
            <div class="mini-bar-label">{{ row.label }}</div>
            <div class="mini-bar-track">
              <div class="mini-bar-fill" :style="{ width: row.pct, background: row.color }" />
            </div>
            <div class="mini-bar-value">{{ row.value }}</div>
          </div>
        </div>
      </NCard>

      <NCard :title="isSuperAdmin ? '信息中心消息状态' : '通知状态'">
        <div v-if="isSuperAdmin && infoCenter.error" role="status" style="margin-bottom: 12px; color: var(--dcp-muted)">{{ infoCenter.error }}</div>
        <div class="donut-wrap">
          <div
            class="donut"
            :style="{
              '--unread': notificationCount ? `${Math.round((unreadCount / notificationCount) * 100)}%` : '0%',
            }"
          >
            <div>
              <strong>{{ notificationCount }}</strong>
              <span>总计</span>
            </div>
          </div>
          <div class="donut-legend">
            <div v-for="row in notificationRows" :key="row.key">
              <span :style="{ background: row.color }" />
              {{ row.label }} {{ row.value }}
            </div>
          </div>
        </div>
      </NCard>
    </div>

    <NSpace :wrap="true" size="large" align="start">
      <NCard title="我的项目" class="dashboard-table-card">
        <NDataTable
          :data="projects"
          :pagination="{ pageSize: 10 }"
          :columns="[
            { title: '项目', key: 'name', minWidth: 180 },
            { title: 'Key', key: 'key', width: 110 },
            { title: '角色', key: 'role', width: 90 },
            { title: '操作', key: 'actions', width: 72, render: (row) => h('a', { class: 'dcp-link dcp-inline-icon', onClick: () => router.push(`/projects/${row.id}`) }, [h(NIcon, null, { default: () => h(LogInOutline) }), '进入']) },
          ]"
        />
      </NCard>

      <NCard :title="isSuperAdmin ? '信息中心未读消息' : '最新通知'" class="dashboard-table-card">
        <NDataTable
          :data="displayedNotifications"
          :pagination="{ pageSize: 10 }"
          :columns="[
            { title: '标题', key: 'title', minWidth: 180 },
            { title: '类型', key: 'type', width: 120 },
            { title: '时间', key: 'created_at', width: 160, render: (row) => formatDisplayDate(row?.created_at) },
          ]"
        />
      </NCard>
    </NSpace>
  </NSpace>
</template>

<style scoped>
.dashboard-card,
.dashboard-table-card {
  flex: 1 1 260px;
  min-width: 0;
}

.dashboard-charts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.mini-bars {
  display: grid;
  gap: 12px;
}

.mini-bar-row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) 36px;
  gap: 10px;
  align-items: center;
  font-size: 12px;
}

.mini-bar-label,
.mini-bar-value {
  color: var(--dcp-muted);
}

.mini-bar-track {
  height: 10px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(127, 127, 127, 0.16);
}

.mini-bar-fill {
  height: 100%;
  border-radius: inherit;
}

.donut-wrap {
  display: flex;
  gap: 18px;
  align-items: center;
  min-width: 0;
}

.donut {
  width: 112px;
  aspect-ratio: 1;
  border-radius: 50%;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  background: conic-gradient(#f59e0b 0 var(--unread), #10b981 var(--unread) 100%);
}

.donut > div {
  width: 72px;
  aspect-ratio: 1;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--dcp-panel);
  line-height: 1.1;
}

.donut strong {
  font-size: 20px;
  font-weight: 800;
}

.donut span,
.donut-legend {
  font-size: 12px;
  color: var(--dcp-muted);
}

.donut-legend {
  display: grid;
  gap: 8px;
}

.donut-legend span {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 6px;
  border-radius: 999px;
}

@media (max-width: 760px) {
  .dashboard-charts {
    grid-template-columns: 1fr;
  }

  .donut-wrap {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
