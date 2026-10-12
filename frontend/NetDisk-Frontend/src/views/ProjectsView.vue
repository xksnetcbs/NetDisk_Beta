<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NModal,
  NSpace,
  useMessage,
} from 'naive-ui'
import { AddOutline, BriefcaseOutline, LogInOutline, RefreshOutline } from '@vicons/ionicons5'
import { api } from '../api'

const router = useRouter()
const message = useMessage()

const items = ref([])
const loading = ref(false)
const createOpen = ref(false)
const form = ref({ name: '', key: '', description: '' })

function iconNode(icon) {
  return h(NIcon, null, { default: () => h(icon) })
}

function openProject(row) {
  router.push(`/projects/${row.id}`)
}

const columns = computed(() => [
  {
    title: '项目名称',
    key: 'name',
    minWidth: 260,
    ellipsis: { tooltip: true },
    render: (row) =>
      h(
        'span',
        {
          class: 'dcp-link project-name-link',
          onClick: () => openProject(row),
        },
        row.name,
      ),
  },
  { title: 'Key', key: 'key', width: 140 },
  { title: '角色', key: 'role', width: 120 },
  { title: '状态', key: 'status', width: 120 },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render: (row) =>
      h(
        'a',
        { class: 'dcp-link dcp-inline-icon', onClick: () => openProject(row) },
        [iconNode(LogInOutline), '进入'],
      ),
  },
])

async function load() {
  loading.value = true
  try {
    const d = await api.listProjects({ page: 1, page_size: 200 })
    items.value = d.items || []
  } catch (e) {
    message.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  try {
    const d = await api.createProject(form.value)
    message.success('已创建')
    createOpen.value = false
    await load()
    router.push(`/projects/${d.project.id}`)
  } catch (e) {
    message.error(e?.message || '创建失败')
  }
}

onMounted(load)
</script>

<template>
  <NSpace vertical size="large" class="dcp-page">
    <NCard>
      <NSpace justify="space-between" align="center">
        <div class="dcp-title-with-icon">
          <NIcon><BriefcaseOutline /></NIcon>
          项目
        </div>
        <NSpace>
          <NButton @click="load" :loading="loading">
            <template #icon><NIcon><RefreshOutline /></NIcon></template>
            刷新
          </NButton>
          <NButton type="primary" @click="createOpen = true">
            <template #icon><NIcon><AddOutline /></NIcon></template>
            新建项目
          </NButton>
        </NSpace>
      </NSpace>
    </NCard>

    <NCard title="项目列表">
      <NDataTable
        :data="items"
        :pagination="{ pageSize: 20 }"
        :loading="loading"
        :columns="columns"
        :scroll-x="730"
      />
    </NCard>

    <NModal v-model:show="createOpen" preset="card" title="新建项目" style="width: 520px; max-width: 96vw">
      <NForm :model="form">
        <NFormItem label="名称">
          <NInput v-model:value="form.name" placeholder="项目名称" />
        </NFormItem>
        <NFormItem label="Key（短标识）">
          <NInput v-model:value="form.key" placeholder="如 DCP-001" />
        </NFormItem>
        <NFormItem label="描述">
          <NInput v-model:value="form.description" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" />
        </NFormItem>
        <NSpace justify="end">
          <NButton @click="createOpen = false">取消</NButton>
          <NButton type="primary" @click="onCreate">
            <template #icon><NIcon><AddOutline /></NIcon></template>
            创建
          </NButton>
        </NSpace>
      </NForm>
    </NModal>
  </NSpace>
</template>

<style scoped>
.project-name-link {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  white-space: nowrap;
}
</style>
