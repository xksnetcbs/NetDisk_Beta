<script setup>
import { defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import InboxView from './InboxView.vue'

const auth = useAuthStore()
const route = useRoute()
const InfoCenterView = defineAsyncComponent(() => import('./InfoCenterView.vue'))
</script>

<template>
  <InfoCenterView v-if="auth.user?.role_system === 'super_admin' && !route.query.thread" />
  <InboxView v-else />
</template>
