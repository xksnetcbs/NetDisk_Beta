<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter, RouterView } from 'vue-router'
import {
  NBadge,
  NDropdown,
  NIcon,
} from 'naive-ui'
import {
  BriefcaseOutline,
  CalendarOutline,
  ColorPaletteOutline,
  FolderOpenOutline,
  HomeOutline,
  MailOutline,
  PersonCircleOutline,
  SettingsOutline,
  ShieldCheckmarkOutline,
} from '@vicons/ionicons5'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { useInfoCenterStore } from '../stores/infocenter'
import { api } from '../api'

const auth = useAuthStore()
const ui = useUiStore()
const infoCenter = useInfoCenterStore()
const router = useRouter()

const isMobile = ref(false)
const myProjectsOpen = ref(false)
const myProjectsLoading = ref(false)
const myProjects = ref([])

let mq
let unreadTimer

function syncMobile() {
  isMobile.value = window.matchMedia?.('(max-width: 600px)')?.matches ?? false
  if (isMobile.value) ui.setSidebarCollapsed(true)
  else ui.setSidebarCollapsed(false)
}

async function refreshUnreadCount() {
  if (!auth.token) return
  if (auth.user?.role_system === 'super_admin') {
    try { await infoCenter.refresh() } catch { /* The shared store displays connection failure without inventing a zero count. */ }
    return
  }
  try {
    const d = await api.listNotifications({ page: 1, page_size: 50 })
    const items = d.items || []
    ui.setUnreadCount(items.filter((x) => !x.read_at).length)
  } catch {
    ui.setUnreadCount(0)
  }
}

async function loadMyProjects() {
  if (!auth.token) return
  myProjectsLoading.value = true
  try {
    const d = await api.listProjects({ page: 1, page_size: 200 })
    myProjects.value = d.items || []
  } catch {
    myProjects.value = []
  } finally {
    myProjectsLoading.value = false
  }
}

onMounted(async () => {
  syncMobile()
  mq = window.matchMedia?.('(max-width: 600px)')
  mq?.addEventListener?.('change', syncMobile)
  if (auth.token && !auth.user) {
    try {
      const d = await api.me()
      auth.setUser(d.user)
    } catch {
      auth.clearSession()
      router.replace('/login')
    }
  }
  if (auth.token) {
    loadMyProjects()
    await refreshUnreadCount()
  }
  unreadTimer = setInterval(refreshUnreadCount, 5000)
})

onUnmounted(() => {
  mq?.removeEventListener?.('change', syncMobile)
  clearInterval(unreadTimer)
  infoCenter.reset()
})

const currentPath = computed(() => router.currentRoute.value.path)
const unreadCount = computed(() => auth.user?.role_system === 'super_admin' ? infoCenter.unreadCount : ui.unreadCount)
const breadcrumb = computed(() => {
  const r = router.currentRoute.value
  if (r.path.startsWith('/projects/') && r.params.projectId) {
    const pid = Number(r.params.projectId)
    const p = (myProjects.value || []).find((x) => Number(x?.id) === pid)
    const name = p?.name || `#${pid}`
    if (r.path === `/projects/${pid}/manage`) return `项目管理 > ${name}`
    return `项目 > ${name}`
  }
  if (r.path === '/projects') return '项目'
  if (r.path === '/disk') return '我的网盘'
  if (r.path === '/calendar') return '日程'
  if (r.path === '/inbox') return '消息'
  if (r.path === '/admin') return '管理'
  if (r.path === '/settings') return '个人中心'
  return '工作台'
})

const navGroups = computed(() => [
  {
    title: '工作台',
    items: [
      { label: '工作台', path: '/', icon: HomeOutline },
      { label: '我的项目', path: '/projects', expandable: true, icon: BriefcaseOutline },
      { label: '我的网盘', path: '/disk', icon: FolderOpenOutline },
      { label: '日程', path: '/calendar', icon: CalendarOutline },
    ],
  },
  ...(auth.user?.role_system === 'super_admin' ? [{ title: '管理员', items: [{ label: '管理', path: '/admin', icon: ShieldCheckmarkOutline }] }] : []),
  {
    title: '个人中心',
    items: [
      { label: '消息', path: '/inbox', icon: MailOutline },
      { label: '设置', path: '/settings', icon: SettingsOutline },
    ],
  },
])

function goto(path) {
  router.push(path)
  if (isMobile.value) ui.setSidebarCollapsed(true)
}

async function toggleMyProjects() {
  myProjectsOpen.value = !myProjectsOpen.value
  if (myProjectsOpen.value && myProjects.value.length === 0 && !myProjectsLoading.value) {
    await loadMyProjects()
  }
  if (myProjectsOpen.value) {
    goto('/projects')
  }
}

function toggleSidebarFromBrand() {
  if (!isMobile.value) return
  ui.toggleSidebar()
}

watch(
  () => currentPath.value,
  () => {
    if (isMobile.value) ui.setSidebarCollapsed(true)
  },
)

const userMenuOptions = computed(() => [
  { label: '设置', key: 'settings' },
  { label: '退出登录', key: 'logout' },
])

async function onUserMenuSelect(key) {
  if (key === 'logout') {
    await auth.logout()
    router.replace('/login')
    return
  }
  if (key === 'settings') router.push('/settings')
}

watch(() => auth.isAuthed, (isAuthed) => {
  if (!isAuthed && auth.initialized) router.replace('/login')
})

const themeMenuOptions = computed(() => [
  { label: '跟随系统', key: 'system' },
  { label: '亮色', key: 'light' },
  { label: '暗色', key: 'dark' },
])
</script>

<template>
  <div class="dcp-shell" :class="{ 'is-mobile': isMobile, 'is-sidebar-open': isMobile && !ui.sidebarCollapsed }">
    <div class="dcp-topbar">
      <div class="dcp-topbar__left" @click="toggleSidebarFromBrand">DCP_NetDisk</div>
      <div class="dcp-topbar__center">{{ breadcrumb }}</div>
      <div class="dcp-topbar__right">
        <NBadge :value="unreadCount" :max="99" :show-zero="false">
          <button class="dcp-btn" @click="goto('/inbox')"><NIcon><MailOutline /></NIcon></button>
        </NBadge>
        <NDropdown :options="themeMenuOptions" trigger="click" @select="ui.setThemeMode">
          <button class="dcp-btn"><NIcon><ColorPaletteOutline /></NIcon></button>
        </NDropdown>
        <NDropdown :options="userMenuOptions" trigger="click" @select="onUserMenuSelect">
          <button class="dcp-btn"><NIcon><PersonCircleOutline /></NIcon>{{ auth.user?.display_name || auth.user?.username || '用户' }}</button>
        </NDropdown>
      </div>
    </div>

    <div class="dcp-body">
      <div v-if="isMobile && !ui.sidebarCollapsed" class="dcp-sidebar-mask" @click="ui.setSidebarCollapsed(true)" />
      <div class="dcp-sidebar">
        <div v-for="g in navGroups" :key="g.title">
          <div class="dcp-nav-group">{{ g.title }}</div>
          <template v-for="it in g.items" :key="it.path">
            <div
              class="dcp-nav-item"
              :class="{ 'is-active': currentPath === it.path || (it.path === '/projects' && currentPath.startsWith('/projects/')) }"
              @click="it.expandable ? toggleMyProjects() : goto(it.path)"
            >
              <span class="dcp-nav-label"><NIcon v-if="it.icon"><component :is="it.icon" /></NIcon>{{ it.label }}</span>
              <span v-if="it.path === '/inbox' && unreadCount > 0" style="color: var(--dcp-primary)">{{ unreadCount }}</span>
              <span v-if="it.expandable" style="color: var(--dcp-muted)">{{ myProjectsOpen ? '▾' : '▸' }}</span>
            </div>
            <Transition name="dcp-collapse">
              <div v-if="it.path === '/projects' && myProjectsOpen" class="dcp-nav-sublist">
                <div v-if="myProjectsLoading" class="dcp-nav-subitem" style="color: var(--dcp-muted)">加载中...</div>
                <div
                  v-for="p in myProjects"
                  :key="p.id"
                  class="dcp-nav-subitem"
                  :class="{ 'is-active': currentPath.startsWith(`/projects/${p.id}`) }"
                  @click="goto(`/projects/${p.id}`)"
                >
                  {{ p.name }}
                </div>
                <div v-if="!myProjectsLoading && myProjects.length === 0" class="dcp-nav-subitem" style="color: var(--dcp-muted)">暂无项目</div>
              </div>
            </Transition>
          </template>
        </div>
      </div>
      <div class="dcp-main">
        <RouterView v-slot="{ Component }">
          <Transition name="dcp-page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </div>
    </div>
  </div>
</template>
