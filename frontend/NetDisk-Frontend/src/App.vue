<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { RouterView } from 'vue-router'
import { darkTheme, NConfigProvider, NDialogProvider, NMessageProvider } from 'naive-ui'
import AppShell from './layouts/AppShell.vue'
import { useUiStore } from './stores/ui'

const ui = useUiStore()
const route = useRoute()
const osDark = ref(false)

function syncOsTheme() {
  const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
  osDark.value = !!mq?.matches
}

onMounted(() => {
  syncOsTheme()
  const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
  mq?.addEventListener?.('change', syncOsTheme)
})

const useDark = computed(() => {
  if (ui.themeMode === 'dark') return true
  if (ui.themeMode === 'light') return false
  return osDark.value
})

const theme = computed(() => (useDark.value ? darkTheme : null))
const themeOverrides = computed(() => ({
  common: {
    primaryColor: '#007aff',
    primaryColorHover: '#3395ff',
    primaryColorPressed: '#0062cc',
    primaryColorSuppl: '#5ac8fa',
    successColor: '#34c759',
    warningColor: '#ff9f0a',
    errorColor: '#ff3b30',
    infoColor: '#5ac8fa',
    borderRadius: '8px',
    borderRadiusSmall: '7px',
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif',
    cubicBezierEaseInOut: 'cubic-bezier(0.22, 1, 0.36, 1)',
    cubicBezierEaseOut: 'cubic-bezier(0.16, 1, 0.3, 1)',
    cubicBezierEaseIn: 'cubic-bezier(0.7, 0, 0.84, 0)',
  },
  Card: {
    borderRadius: '8px',
    paddingMedium: '18px',
    color: useDark.value ? 'rgba(28, 28, 30, 0.72)' : 'rgba(255, 255, 255, 0.72)',
    borderColor: useDark.value ? 'rgba(255, 255, 255, 0.10)' : 'rgba(60, 60, 67, 0.12)',
  },
  Button: {
    borderRadiusMedium: '999px',
    borderRadiusSmall: '999px',
    borderRadiusTiny: '999px',
    heightMedium: '34px',
    heightSmall: '30px',
  },
  DataTable: {
    borderRadius: '8px',
    thColor: useDark.value ? 'rgba(44, 44, 46, 0.88)' : 'rgba(242, 242, 247, 0.88)',
    tdColor: 'transparent',
    borderColor: useDark.value ? 'rgba(255, 255, 255, 0.08)' : 'rgba(60, 60, 67, 0.10)',
  },
  Input: {
    borderRadius: '8px',
  },
  Modal: {
    borderRadius: '8px',
  },
}))
const isAuthLayout = computed(() => route.meta?.layout === 'auth')

watch(
  useDark,
  (v) => {
    const root = document.documentElement
    if (v) root.dataset.theme = 'dark'
    else delete root.dataset.theme
  },
  { immediate: true },
)
</script>

<template>
  <NConfigProvider :theme="theme" :theme-overrides="themeOverrides">
    <NDialogProvider>
      <NMessageProvider>
        <AppShell v-if="!isAuthLayout" />
        <RouterView v-else />
      </NMessageProvider>
    </NDialogProvider>
  </NConfigProvider>
</template>
