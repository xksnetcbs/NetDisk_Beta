import { defineStore } from 'pinia'
import { useAuthStore } from './auth'
import { infoCenterApi } from '../infocenter'

let refreshPromise = null

export const useInfoCenterStore = defineStore('infocenter', {
  state: () => ({ userId: null, unreadCount: 0, totalCount: 0, byChat: {}, latest: [], pendingRead: {}, readCursor: {}, error: '', refreshedAt: 0 }),
  actions: {
    reset() {
      this.$reset()
    },
    async refresh(force = false) {
      const auth = useAuthStore()
      if (!auth.isAuthed || auth.user?.role_system !== 'super_admin') { this.reset(); return }
      const uid = auth.user.id
      if (this.userId !== uid) { this.reset(); this.userId = uid }
      if (refreshPromise) return refreshPromise
      if (!force && !Object.keys(this.pendingRead).length && Date.now() - this.refreshedAt < 3000) return
      refreshPromise = (async () => {
        for (const [chat, throughUid] of Object.entries({ ...this.pendingRead })) {
          const result = await infoCenterApi.markRead(chat, throughUid)
          if (auth.user?.id !== uid || this.userId !== uid) return
          if (!result.pending && this.pendingRead[chat] === throughUid) {
            delete this.pendingRead[chat]
            this.readCursor[chat] = throughUid
          }
        }
        const data = await infoCenterApi.unread()
        if (auth.user?.id !== uid || this.userId !== uid || auth.user?.role_system !== 'super_admin') return
        this.unreadCount = Math.max(0, Number(data.unread_count) || 0)
        this.totalCount = Math.max(0, Number(data.total_count) || 0)
        this.byChat = data.by_chat || {}
        this.latest = data.latest || []
        this.error = ''
        this.refreshedAt = Date.now()
      })().catch(error => {
        if (this.userId === uid) this.error = error?.message || '信息中心连接失败'
        throw error
      }).finally(() => { refreshPromise = null })
      return refreshPromise
    },
    async markRead(chat, uid) {
      const auth = useAuthStore()
      if (!auth.isAuthed || auth.user?.role_system !== 'super_admin') return
      if (this.userId !== auth.user.id) { this.reset(); this.userId = auth.user.id }
      if (!chat || !uid || this.readCursor[chat] === uid) return
      this.pendingRead[chat] = uid
      return this.refresh(true)
    },
  },
})
