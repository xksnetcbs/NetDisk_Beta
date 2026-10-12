<script setup>
import { computed, onMounted, ref } from 'vue'
import { NIcon, NInput, NModal, NProgress, NSpace, useMessage } from 'naive-ui'
import {
  AddOutline,
  ArrowUpOutline,
  CloseCircleOutline,
  CloudUploadOutline,
  DocumentOutline,
  DownloadOutline,
  Folder,
  FolderOpenOutline,
  PauseOutline,
  PlayOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import { api } from '../api'
import { createResumableUpload } from '../utils/resumableUpload'

const props = defineProps({
  scope: { type: String, required: true },
  projectId: { type: [String, Number], default: null },
})

const message = useMessage()
const root = ref(null)
const currentFolder = ref(null)
const items = ref([])
const loading = ref(false)
const uploadProgressMap = ref({})
const uploadTaskMap = ref({})
const pathStack = ref([])

const createFolderOpen = ref(false)
const folderName = ref('')
const fileInputRef = ref(null)

const uploading = computed(() => Object.values(uploadProgressMap.value).some((x) => x.state === 'uploading'))
const uploadProgressItems = computed(() => Object.values(uploadProgressMap.value))

function setUploadProgress(id, patch) {
  uploadProgressMap.value = {
    ...uploadProgressMap.value,
    [id]: {
      ...(uploadProgressMap.value[id] || {}),
      ...patch,
    },
  }
}

function removeUploadProgress(id) {
  const next = { ...uploadProgressMap.value }
  delete next[id]
  uploadProgressMap.value = next
}

function setUploadTask(id, task) {
  uploadTaskMap.value = {
    ...uploadTaskMap.value,
    [id]: task,
  }
}

function removeUploadTask(id) {
  const next = { ...uploadTaskMap.value }
  delete next[id]
  uploadTaskMap.value = next
}

async function loadRoot() {
  const params = props.scope === 'project' ? { scope: 'project', project_id: props.projectId } : { scope: 'personal' }
  const d = await api.filesRoot(params)
  root.value = d.root
  currentFolder.value = d.root
  pathStack.value = [d.root]
}

async function loadList() {
  if (!currentFolder.value?.id) return
  loading.value = true
  try {
    const d = await api.filesList({ parent_id: currentFolder.value.id })
    items.value = d.items || []
  } catch (e) {
    message.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function refresh() {
  if (!root.value) await loadRoot()
  await loadList()
}

function enterFolder(row) {
  if (row.type !== 'folder') return
  currentFolder.value = row
  pathStack.value = [...pathStack.value, row]
  loadList()
}

function goUp() {
  if (pathStack.value.length <= 1) return
  pathStack.value = pathStack.value.slice(0, -1)
  currentFolder.value = pathStack.value[pathStack.value.length - 1]
  loadList()
}

function openUpload() {
  fileInputRef.value?.click?.()
}

async function startUpload(file, index) {
  const uploadId = `${file.name}-${file.size}-${index}-${Date.now()}`
  setUploadProgress(uploadId, {
    id: uploadId,
    name: file.name,
    percent: 0,
    speed: '--/s',
    status: 'default',
    state: 'uploading',
  })

  const finishUpload = async () => {
    setUploadProgress(uploadId, { percent: 100, speed: '完成', status: 'success', state: 'success' })
    removeUploadTask(uploadId)
    window.setTimeout(() => removeUploadProgress(uploadId), 1200)
    await loadList()
  }

  const failUpload = (err) => {
    const current = uploadProgressMap.value[uploadId]
    if (current?.state === 'paused' || err?.code === 'UPLOAD_PAUSED' || err?.code === 'ERR_CANCELED') return
    if (current?.state === 'canceled' || err?.code === 'UPLOAD_CANCELED') {
      removeUploadTask(uploadId)
      window.setTimeout(() => removeUploadProgress(uploadId), 1200)
      return
    }
    setUploadProgress(uploadId, { status: 'error', state: 'error', speed: '失败' })
    message.error(err?.message || '上传失败')
    removeUploadTask(uploadId)
    window.setTimeout(() => removeUploadProgress(uploadId), 2200)
  }

  const runner = createResumableUpload(
    file,
    {
      scope: props.scope,
      parentId: currentFolder.value.id,
      projectId: props.scope === 'project' ? Number(props.projectId) : null,
    },
    {
      onProgress: (progress) => {
        const current = uploadProgressMap.value[uploadId]
        setUploadProgress(uploadId, {
          ...progress,
          id: uploadId,
          percent: Math.max(0, Math.min(100, Number(progress.percent || 0))),
          state: current?.state === 'paused' || current?.state === 'canceled' ? current.state : 'uploading',
        })
      },
    },
  )

  setUploadTask(uploadId, { runner, finishUpload, failUpload })

  try {
    await runner.start()
    await finishUpload()
  } catch (err) {
    failUpload(err)
  }
}

async function onPickFiles(e) {
  const files = Array.from(e?.target?.files || [])
  e.target.value = ''
  if (!files.length || !currentFolder.value?.id) return

  await Promise.all(files.map((file, index) => startUpload(file, index)))
  if (!uploadProgressItems.value.some((x) => x.state === 'error')) {
    message.success('上传任务已处理')
  }
}

function pauseUpload(id) {
  const task = uploadTaskMap.value[id]
  if (!task) return
  setUploadProgress(id, { state: 'paused', status: 'warning', speed: '已暂停' })
  task.runner.pause()
}

async function resumeUpload(id) {
  const task = uploadTaskMap.value[id]
  if (!task) return
  setUploadProgress(id, { state: 'uploading', status: 'default', speed: '--/s' })
  try {
    await task.runner.resume()
    await task.finishUpload()
  } catch (err) {
    task.failUpload(err)
  }
}

async function cancelUpload(id) {
  const task = uploadTaskMap.value[id]
  setUploadProgress(id, { state: 'canceled', status: 'error', speed: '已取消' })
  if (task) {
    await task.runner.cancel()
    removeUploadTask(id)
  }
  window.setTimeout(() => removeUploadProgress(id), 1200)
}

async function onCreateFolder() {
  const name = folderName.value.trim()
  if (!name) return
  try {
    await api.createFolder({
      name,
      parent_id: currentFolder.value.id,
      scope: props.scope,
      project_id: props.scope === 'project' ? Number(props.projectId) : undefined,
    })
    createFolderOpen.value = false
    folderName.value = ''
    await loadList()
  } catch (e) {
    message.error(e?.message || '创建失败')
  }
}

async function onDownload(row) {
  try {
    const resp = await api.downloadFile(row.id)
    const blob = new Blob([resp.data])
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = row.name || 'download'
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
  } catch (e) {
    message.error(e?.message || '下载失败')
  }
}

async function onDelete(row) {
  try {
    await api.deleteFileNode(row.id)
    await loadList()
  } catch (e) {
    message.error(e?.message || '删除失败')
  }
}

onMounted(refresh)
</script>

<template>
  <div class="dcp-panel project-file-pane">
    <div class="dcp-panel__header project-file-pane__header">
      <div class="dcp-panel__title">文件</div>
      <div class="project-file-pane__actions">
        <button class="dcp-btn" :disabled="loading" @click="goUp"><NIcon><ArrowUpOutline /></NIcon>上级</button>
        <button class="dcp-btn" :disabled="loading" @click="createFolderOpen = true"><NIcon><AddOutline /></NIcon>新建</button>
        <button class="dcp-btn primary" :disabled="loading" @click="openUpload"><NIcon><CloudUploadOutline /></NIcon>上传</button>
        <input ref="fileInputRef" type="file" multiple style="display: none" @change="onPickFiles" />
      </div>
    </div>

    <div class="project-file-pane__current">
      当前：{{ currentFolder?.name }}
    </div>

    <div v-if="uploadProgressItems.length" class="project-file-upload-progress">
      <div v-for="item in uploadProgressItems" :key="item.id" class="project-file-upload-progress__item">
        <div class="project-file-upload-progress__head">
          <span>{{ item.name }}</span>
          <strong>{{ item.percent }}% · {{ item.speed }}</strong>
          <NSpace size="small" :wrap="false">
            <button v-if="item.state === 'uploading'" class="dcp-btn tiny" @click="pauseUpload(item.id)"><NIcon><PauseOutline /></NIcon>暂停</button>
            <button v-if="item.state === 'paused'" class="dcp-btn tiny" @click="resumeUpload(item.id)"><NIcon><PlayOutline /></NIcon>继续</button>
            <button v-if="!['success', 'canceled'].includes(item.state)" class="dcp-btn tiny danger" @click="cancelUpload(item.id)"><NIcon><CloseCircleOutline /></NIcon>取消</button>
          </NSpace>
        </div>
        <NProgress type="line" :percentage="item.percent" :status="item.status" :height="6" />
      </div>
    </div>

    <div class="project-file-pane__table-wrap">
      <table class="dcp-table project-file-pane__table">
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.id">
            <td>
              <span v-if="row.type === 'folder'" class="dcp-link file-name-inline" @click="enterFolder(row)">
                <NIcon><Folder /></NIcon>{{ row.name }}
              </span>
              <span v-else class="file-name-inline"><NIcon><DocumentOutline /></NIcon>{{ row.name }}</span>
            </td>
            <td>{{ row.type === 'folder' ? '文件夹' : '文件' }}</td>
            <td>
              <span v-if="row.type === 'folder'" class="dcp-link file-action-inline" @click="enterFolder(row)"><NIcon><FolderOpenOutline /></NIcon></span>
              <span v-if="row.type === 'file'" class="dcp-link file-action-inline" @click="onDownload(row)"><NIcon><DownloadOutline /></NIcon></span>
              <span class="dcp-link file-action-inline" @click="onDelete(row)"><NIcon><TrashOutline /></NIcon></span>
            </td>
          </tr>
          <tr v-if="items.length === 0">
            <td colspan="3" style="color: var(--dcp-muted)">暂无</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <NModal v-model:show="createFolderOpen" preset="card" title="新建文件夹" style="width: 420px; max-width: 96vw">
    <div class="project-file-pane__modal-row">
      <NInput v-model:value="folderName" placeholder="文件夹名称" />
      <button class="dcp-btn primary" @click="onCreateFolder"><NIcon><AddOutline /></NIcon>创建</button>
    </div>
  </NModal>
</template>

<style scoped>
.project-file-pane {
  height: 100%;
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.project-file-pane__header,
.project-file-pane__actions,
.project-file-pane__current,
.project-file-pane__table-wrap {
  min-width: 0;
}

.project-file-pane__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.project-file-pane__current {
  padding: 6px 8px;
  overflow: hidden;
  color: var(--dcp-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-file-pane__table-wrap {
  flex: 1;
  overflow: auto;
}

.project-file-pane__table {
  width: 100%;
  table-layout: fixed;
}

.project-file-pane__table th:nth-child(1) {
  width: 56%;
}

.project-file-pane__table th:nth-child(2) {
  width: 18%;
}

.project-file-pane__table th:nth-child(3) {
  width: 26%;
}

.project-file-upload-progress {
  padding: 0 8px 8px;
  min-width: 0;
  display: grid;
  gap: 8px;
}

.project-file-upload-progress__head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--dcp-muted);
}

.project-file-upload-progress__head span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-file-upload-progress__head strong {
  color: var(--dcp-text);
  font-weight: 700;
  white-space: nowrap;
}

.file-name-inline,
.file-action-inline,
.dcp-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.file-name-inline {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-name-inline .n-icon {
  flex: 0 0 auto;
  color: var(--dcp-primary);
}

.file-action-inline + .file-action-inline {
  margin-left: 8px;
}

.dcp-btn.tiny {
  padding: 2px 6px;
  font-size: 12px;
}

.dcp-btn.danger {
  color: #c00000;
}

.project-file-pane__modal-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

@media (max-width: 640px) {
  .project-file-upload-progress__head {
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
  }

  .project-file-pane__modal-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
