<script setup>
import TerminalSchedules from '../../../../integrations/DCP_InfoCenter/src/TerminalSchedules.vue'
import { terminalScheduleApi } from '../schedules'
</script>
<template><div class="terminal-calendar-host"><TerminalSchedules :request="terminalScheduleApi.request" /></div></template>
<style scoped>
.terminal-calendar-host{height:calc(100dvh - 140px);min-height:400px;border:1px solid var(--dcp-border);border-radius:12px;overflow:hidden}
@media(max-width:600px){.terminal-calendar-host{height:calc(100dvh - 120px)}}
</style>
