import { defineStore } from 'pinia'

const TOKEN_KEY = 'dcp_netdisk_token'
const SIGNED_OUT_KEY = 'dcp_netdisk_signed_out'
let initializationPromise = null

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(SIGNED_OUT_KEY) ? '' : localStorage.getItem(TOKEN_KEY) || '',
    user: null,
    loading: false,
    initialized: false,
    signedOut: !!localStorage.getItem(SIGNED_OUT_KEY),
    sessionVersion: 0,
  }),
  getters: {
    isAuthed: (s) => !!s.token && !!s.user,
  },
  actions: {
    setToken(token) {
      this.token = token || ''
      if (this.token) localStorage.setItem(TOKEN_KEY, this.token)
      else localStorage.removeItem(TOKEN_KEY)
    },
    setUser(user) {
      this.user = user || null
    },
    setSession(data) {
      this.signedOut = false
      localStorage.removeItem(SIGNED_OUT_KEY)
      this.setToken(data.access_token)
      this.setUser(data.user)
      this.initialized = true
    },
    clearSession() {
      this.sessionVersion += 1
      this.setToken('')
      this.setUser(null)
      this.initialized = true
    },
    async initialize() {
      if (this.initialized) return
      if (initializationPromise) return initializationPromise
      this.loading = true
      const version = this.sessionVersion
      initializationPromise = (async () => {
        const { api, restoreSession } = await import('../api')
        if (this.signedOut) return
        try {
          if (this.token) {
            const data = await api.me()
            if (version !== this.sessionVersion) return
            if (data.access_token) this.setSession(data)
            else this.setUser(data.user)
          } else {
            await restoreSession()
          }
        } catch {
          // Transient network failures keep the cookie available for a later visit.
          if (version === this.sessionVersion) this.clearSession()
        }
      })().finally(() => {
        this.initialized = true
        this.loading = false
        initializationPromise = null
      })
      return initializationPromise
    },
    async logout() {
      this.signedOut = true
      localStorage.setItem(SIGNED_OUT_KEY, '1')
      this.clearSession()
      try {
        const { api } = await import('../api')
        await api.logout()
      } catch {
        // The explicit sign-out marker also persists when the device is offline.
      }
    },
  },
})
