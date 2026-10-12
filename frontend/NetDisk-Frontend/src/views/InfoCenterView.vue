<script setup>
import { computed, onBeforeUnmount, onMounted, provide, ref } from 'vue'
import { useRouter } from 'vue-router'
import InfoCenter from '../../../../integrations/DCP_InfoCenter/src/App.vue'
import { INFOCENTER_RUNTIME } from '../../../../integrations/DCP_InfoCenter/src/runtime'
import '../../../../integrations/DCP_InfoCenter/src/style.css'
import { infoCenterApi } from '../infocenter'
import { useInfoCenterStore } from '../stores/infocenter'
import { useUiStore } from '../stores/ui'
import { terminalScheduleApi } from '../schedules'

const state = useInfoCenterStore()
const ui = useUiStore()
const router = useRouter()
const systemDark = ref(window.matchMedia('(prefers-color-scheme: dark)').matches)
const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
const syncTheme = event => { systemDark.value = event.matches }
onMounted(() => mediaQuery.addEventListener('change', syncTheme))
onBeforeUnmount(() => mediaQuery.removeEventListener('change', syncTheme))

provide(INFOCENTER_RUNTIME, {
  request: infoCenterApi.request,
  blob: infoCenterApi.blob,
  sendNetdisk: infoCenterApi.sendNetdisk,
  scheduleRequest: terminalScheduleApi.request,
  refreshUnread: () => state.refresh(),
  markRead: (chat, uid) => state.markRead(chat, uid),
  unreadByChat: computed(() => state.byChat),
  openLink: path => {
    if (typeof path === 'string' && path.startsWith('/') && !path.startsWith('//') && !path.includes('\\')) router.push(path)
  },
  theme: computed(() => ui.themeMode === 'dark' || (ui.themeMode === 'system' && systemDark.value) ? 'dark' : 'light'),
})
</script>

<template>
  <section class="infocenter-host" aria-label="DCP 信息中心">
    <InfoCenter embedded />
  </section>
</template>

<style scoped>
.infocenter-host { height: calc(100dvh - 104px); min-height: 460px; min-width: 0; border: 1px solid var(--dcp-border); border-radius: 12px; overflow: hidden; }
@media (max-width: 600px) { .infocenter-host { height: calc(100dvh - 96px); min-height: 400px; border-radius: 8px; } }
</style>
