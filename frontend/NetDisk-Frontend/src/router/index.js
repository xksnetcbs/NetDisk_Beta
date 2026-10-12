import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { api } from '../api'

const PROJECT_ROLE_RANK = { guest: 0, user: 1, admin: 2, creator: 3 }

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue'),
    },
    {
      path: '/login',
      name: 'login',
      meta: { layout: 'auth', public: true },
      component: () => import('../views/LoginView.vue'),
    },
    {
      path: '/register',
      name: 'register',
      meta: { layout: 'auth', public: true },
      component: () => import('../views/RegisterView.vue'),
    },
    {
      path: '/projects',
      name: 'projects',
      component: () => import('../views/ProjectsView.vue'),
    },
    {
      path: '/projects/:projectId',
      name: 'project',
      component: () => import('../views/ProjectDetailView.vue'),
    },
    {
      path: '/projects/:projectId/manage',
      name: 'project-manage',
      meta: { requiredProjectRole: 'admin' },
      component: () => import('../views/ProjectManageView.vue'),
    },
    {
      path: '/disk',
      name: 'disk',
      component: () => import('../views/DiskView.vue'),
    },
    {
      path: '/calendar',
      name: 'calendar',
      component: () => import('../views/CalendarView.vue'),
    },
    {
      path: '/inbox',
      name: 'inbox',
      component: () => import('../views/MessageCenterView.vue'),
    },
    {
      path: '/admin',
      name: 'admin',
      meta: { requiredRoleSystem: 'super_admin' },
      component: () => import('../views/AdminView.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.initialize()
  if (to.meta?.public) {
    if (to.path === '/login' && auth.isAuthed) return '/'
    return true
  }
  if (!auth.isAuthed) return { path: '/login', query: { redirect: to.fullPath } }

  if (to.meta?.requiredRoleSystem) {
    if (!auth.user) {
      try {
        const d = await api.me()
        auth.setUser(d.user)
      } catch {
        auth.clearSession()
        return '/login'
      }
    }
    if (auth.user?.role_system !== to.meta.requiredRoleSystem) return '/'
  }

  if (to.meta?.requiredProjectRole) {
    const pid = Number(to.params?.projectId)
    if (!Number.isFinite(pid)) return '/projects'
    try {
      const d = await api.getProject(pid)
      const role = d?.project?.role
      if ((PROJECT_ROLE_RANK[role] ?? -1) < (PROJECT_ROLE_RANK[to.meta.requiredProjectRole] ?? 999)) {
        return `/projects/${pid}`
      }
    } catch {
      return '/projects'
    }
  }

  return true
})

export default router
