import { defineStore } from 'pinia'

const THEME_KEY = 'dcp_netdisk_theme'

export const useUiStore = defineStore('ui', {
  state: () => ({
    themeMode: localStorage.getItem(THEME_KEY) || 'system',
    sidebarCollapsed: false,
    unreadCount: 0,
  }),
  actions: {
    setThemeMode(mode) {
      this.themeMode = mode
      localStorage.setItem(THEME_KEY, mode)
    },
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed
    },
    setSidebarCollapsed(v) {
      this.sidebarCollapsed = !!v
    },
    setUnreadCount(v) {
      const n = Number(v)
      this.unreadCount = Number.isFinite(n) ? Math.max(0, n) : 0
    },
  },
})
