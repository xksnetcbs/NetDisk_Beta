<script setup>
import { NCard, NSpace } from 'naive-ui'
import FileBrowser from '../components/FileBrowser.vue'
</script>

<template>
  <NSpace vertical size="large" class="dcp-page">
    <NCard title="我的网盘">
      <FileBrowser scope="personal" embedded />
    </NCard>
  </NSpace>
</template>
