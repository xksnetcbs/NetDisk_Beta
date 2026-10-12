<script setup>
import { computed, h, nextTick, ref, watch } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NDropdown,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NModal,
  NProgress,
  NSelect,
  NSpace,
  NUpload,
  useMessage,
} from 'naive-ui'
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
  RefreshOutline,
  TrashOutline,
  VideocamOutline,
} from '@vicons/ionicons5'
import { api } from '../api'
import { createResumableUpload } from '../utils/resumableUpload'

const props = defineProps({
  scope: { type: String, required: true },
  projectId: { type: [String, Number], default: null },
  embedded: { type: Boolean, default: false },
})

const emit = defineEmits(['changed'])

const message = useMessage()
const root = ref(null)
const currentFolder = ref(null)
const items = ref([])
const loading = ref(false)
const listReqSeq = ref(0)
const uploadFileList = ref([])
const uploadProgressMap = ref({})
const uploadTaskMap = ref({})
const zipProgressMap = ref({})
const zipTimerMap = ref({})

const pathStack = ref([])
const createFolderOpen = ref(false)
const folderForm = ref({ name: '' })
const contextMenu = ref({ show: false, x: 0, y: 0, row: null })
const longPressTimer = ref(null)
const longPressTriggered = ref(false)
const renameOpen = ref(false)
const renameForm = ref({ id: null, name: '' })
const moveOpen = ref(false)
const moveTarget = ref(null)
const moveNode = ref(null)
const moveFolderOptions = ref([])
const moveLoading = ref(false)
const videoPreviewOpen = ref(false)
const videoPreviewNode = ref(null)
const pdfPreviewOpen = ref(false)
const pdfPreviewNode = ref(null)
const imagePreviewOpen = ref(false)
const imagePreviewNode = ref(null)
const officePreviewOpen = ref(false)
const officePreviewNode = ref(null)

const folderId = computed(() => currentFolder.value?.id)
const videoPreviewUrl = computed(() => (videoPreviewNode.value ? api.filePreviewUrl(videoPreviewNode.value.id) : ''))
const pdfPreviewUrl = computed(() => (pdfPreviewNode.value ? api.filePreviewUrl(pdfPreviewNode.value.id) : ''))
const imagePreviewUrl = computed(() => (imagePreviewNode.value ? api.filePreviewUrl(imagePreviewNode.value.id) : ''))
const officePreviewUrl = computed(() => (officePreviewNode.value ? api.filePreviewUrl(officePreviewNode.value.id) : ''))
const contextMenuOptions = [
  { label: '移动到文件夹', key: 'move' },
  { label: '重命名', key: 'rename' },
  { label: '删除', key: 'delete' },
]
const uploadProgressItems = computed(() => Object.values(uploadProgressMap.value))
const zipProgressItems = computed(() => Object.values(zipProgressMap.value))
const uploadOverallProgress = computed(() => {
  const list = uploadProgressItems.value
  if (!list.length) return 0
  return Math.round(list.reduce((sum, item) => sum + Number(item.percent || 0), 0) / list.length)
})
const uploadProgressStatus = computed(() => {
  if (uploadProgressItems.value.some((x) => x.status === 'error')) return 'error'
  if (uploadOverallProgress.value >= 100) return 'success'
  return 'default'
})

function iconNode(icon, size = 16) {
  return h(NIcon, { size }, { default: () => h(icon) })
}

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

function setZipProgress(id, patch) {
  zipProgressMap.value = {
    ...zipProgressMap.value,
    [id]: {
      ...(zipProgressMap.value[id] || {}),
      ...patch,
    },
  }
}

function removeZipProgress(id) {
  const next = { ...zipProgressMap.value }
  delete next[id]
  zipProgressMap.value = next
}

function setZipTimer(id, timer) {
  zipTimerMap.value = {
    ...zipTimerMap.value,
    [id]: timer,
  }
}

function clearZipTimer(id) {
  const timer = zipTimerMap.value[id]
  if (timer) window.clearInterval(timer)
  const next = { ...zipTimerMap.value }
  delete next[id]
  zipTimerMap.value = next
}

async function loadRoot() {
  if (props.scope === 'project' && (props.projectId === null || props.projectId === undefined || props.projectId === '')) return
  const params = props.scope === 'project' ? { scope: 'project', project_id: Number(props.projectId) } : { scope: 'personal' }
  const d = await api.filesRoot(params)
  root.value = d.root
  currentFolder.value = d.root
  pathStack.value = [d.root]
}

async function loadList() {
  if (!folderId.value) return
  const seq = listReqSeq.value + 1
  listReqSeq.value = seq
  loading.value = true
  try {
    const d = await api.filesList({ parent_id: folderId.value })
    if (seq !== listReqSeq.value) return
    items.value = d.items || []
  } catch (e) {
    if (seq !== listReqSeq.value) return
    message.error(e?.message || '加载失败')
  } finally {
    if (seq !== listReqSeq.value) return
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

function isVideoFile(row) {
  if (!row || row.type !== 'file') return false
  const mime = String(row.mime_type || '').toLowerCase()
  if (mime.startsWith('video/')) return true
  return /\.(mp4|webm|ogg|ogv|mov|m4v|mkv|avi)$/i.test(row.name || '')
}

function isPdfFile(row) {
  if (!row || row.type !== 'file') return false
  const mime = String(row.mime_type || '').toLowerCase()
  if (mime === 'application/pdf') return true
  return /\.pdf$/i.test(row.name || '')
}

function isImageFile(row) {
  if (!row || row.type !== 'file') return false
  const mime = String(row.mime_type || '').toLowerCase()
  if (mime.startsWith('image/')) return true
  return /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(row.name || '')
}

function isOfficeFile(row) {
  if (!row || row.type !== 'file') return false
  return /\.(docx?|xlsx?|pptx?)$/i.test(row.name || '')
}

function onNameClick(row) {
  if (longPressTriggered.value) {
    longPressTriggered.value = false
    return
  }
  if (row.type === 'folder') {
    enterFolder(row)
    return
  }
  if (isVideoFile(row)) {
    openVideoPreview(row)
    return
  }
  if (isPdfFile(row)) {
    openPdfPreview(row)
    return
  }
  if (isImageFile(row)) {
    openImagePreview(row)
    return
  }
  if (isOfficeFile(row)) {
    openOfficePreview(row)
  }
}

function openVideoPreview(row) {
  videoPreviewNode.value = row
  videoPreviewOpen.value = true
}

function closeVideoPreview() {
  videoPreviewOpen.value = false
  videoPreviewNode.value = null
}

function openPdfPreview(row) {
  pdfPreviewNode.value = row
  pdfPreviewOpen.value = true
}

function closePdfPreview() {
  pdfPreviewOpen.value = false
  pdfPreviewNode.value = null
}

function openImagePreview(row) {
  imagePreviewNode.value = row
  imagePreviewOpen.value = true
}

function closeImagePreview() {
  imagePreviewOpen.value = false
  imagePreviewNode.value = null
}

function openOfficePreview(row) {
  officePreviewNode.value = row
  officePreviewOpen.value = true
}

function closeOfficePreview() {
  officePreviewOpen.value = false
  officePreviewNode.value = null
}

function goUp() {
  if (pathStack.value.length <= 1) return
  pathStack.value = pathStack.value.slice(0, -1)
  currentFolder.value = pathStack.value[pathStack.value.length - 1]
  loadList()
}

function folderOptionLabel(folder, depth) {
  const name = folder.id === root.value?.id ? `${folder.name}（根目录）` : folder.name
  return `${'　'.repeat(depth)}${name}`
}

async function collectFolderOptions(folder, depth = 0, out = [], blocked = false) {
  if (!folder) return out
  const currentBlocked =
    blocked || (moveNode.value?.type === 'folder' && Number(folder.id) === Number(moveNode.value.id))
  out.push({
    label: folderOptionLabel(folder, depth),
    value: folder.id,
    parent_id: folder.parent_id,
    disabled: currentBlocked,
  })
  const d = await api.filesList({ parent_id: folder.id })
  const folders = (d.items || []).filter((x) => x.type === 'folder')
  for (const child of folders) {
    await collectFolderOptions(child, depth + 1, out, currentBlocked)
  }
  return out
}

function clearLongPress() {
  if (!longPressTimer.value) return
  window.clearTimeout(longPressTimer.value)
  longPressTimer.value = null
}

async function openContextMenu(event, row) {
  event?.preventDefault?.()
  event?.stopPropagation?.()
  clearLongPress()
  longPressTriggered.value = true
  contextMenu.value.show = false
  await nextTick()
  const touch = event?.touches?.[0] || event?.changedTouches?.[0]
  contextMenu.value = {
    show: true,
    x: touch?.clientX ?? event?.clientX ?? 0,
    y: touch?.clientY ?? event?.clientY ?? 0,
    row,
  }
}

function onNamePointerDown(event, row) {
  clearLongPress()
  longPressTriggered.value = false
  if (event.pointerType !== 'touch') return
  longPressTimer.value = window.setTimeout(() => {
    openContextMenu(event, row)
  }, 550)
}

function onContextSelect(key) {
  const row = contextMenu.value.row
  contextMenu.value.show = false
  if (!row) return
  if (key === 'move') openMove(row)
  if (key === 'rename') openRename(row)
  if (key === 'delete') onDelete(row)
}

function openRename(row) {
  renameForm.value = { id: row.id, name: row.name || '' }
  renameOpen.value = true
}

async function onRename() {
  const name = (renameForm.value.name || '').trim()
  if (!renameForm.value.id || !name) {
    message.warning('请输入名称')
    return
  }
  try {
    await api.patchFileNode(renameForm.value.id, { name })
    message.success('已重命名')
    renameOpen.value = false
    await loadList()
    emit('changed')
  } catch (e) {
    message.error(e?.message || '重命名失败')
  }
}

async function openMove(row) {
  moveNode.value = row
  moveTarget.value = row.parent_id || null
  moveOpen.value = true
  moveLoading.value = true
  try {
    const options = await collectFolderOptions(root.value)
    moveFolderOptions.value = options
    const current = options.find((x) => Number(x.value) === Number(row.parent_id))
    if (current?.disabled) moveTarget.value = null
  } catch (e) {
    message.error(e?.message || '加载文件夹失败')
  } finally {
    moveLoading.value = false
  }
}

async function onMove() {
  if (!moveNode.value || !moveTarget.value) {
    message.warning('请选择目标文件夹')
    return
  }
  if (Number(moveTarget.value) === Number(moveNode.value.parent_id)) {
    moveOpen.value = false
    return
  }
  try {
    await api.patchFileNode(moveNode.value.id, { parent_id: moveTarget.value })
    message.success('已移动')
    moveOpen.value = false
    await loadList()
    emit('changed')
  } catch (e) {
    message.error(e?.message || '移动失败')
  }
}

async function onCreateFolder() {
  try {
    const payload = {
      name: folderForm.value.name,
      parent_id: folderId.value,
      scope: props.scope,
      project_id: props.scope === 'project' ? Number(props.projectId) : undefined,
    }
    await api.createFolder(payload)
    message.success('已创建')
    createFolderOpen.value = false
    folderForm.value.name = ''
    await loadList()
    emit('changed')
  } catch (e) {
    message.error(e?.message || '创建失败')
  }
}

async function onUpload({ file, onFinish, onError }) {
  const rawFile = file?.file
  if (!rawFile || !folderId.value) {
    onError?.()
    return false
  }

  const uploadId = file?.id || `${rawFile.name}-${rawFile.size}-${Date.now()}`
  setUploadProgress(uploadId, {
    id: uploadId,
    name: rawFile.name || '上传文件',
    percent: 0,
    speed: '--/s',
    status: 'default',
    state: 'uploading',
    loaded: 0,
    total: rawFile.size || 0,
  })

  const finishUpload = async () => {
    setUploadProgress(uploadId, { percent: 100, status: 'success', state: 'success', speed: '完成' })
    message.success('上传成功')
    await loadList()
    emit('changed')
    uploadFileList.value = (uploadFileList.value || []).filter((x) => x?.id !== file?.id)
    removeUploadTask(uploadId)
    window.setTimeout(() => removeUploadProgress(uploadId), 1200)
    onFinish?.()
    return true
  }

  const failUpload = (e) => {
    const current = uploadProgressMap.value[uploadId]
    if (current?.state === 'paused' || e?.code === 'UPLOAD_PAUSED' || e?.code === 'ERR_CANCELED') return false
    if (current?.state === 'canceled' || e?.code === 'UPLOAD_CANCELED') {
      removeUploadTask(uploadId)
      window.setTimeout(() => removeUploadProgress(uploadId), 1200)
      onError?.()
      return false
    }
    setUploadProgress(uploadId, { status: 'error', state: 'error', speed: '失败' })
    message.error(e?.message || '上传失败')
    removeUploadTask(uploadId)
    window.setTimeout(() => removeUploadProgress(uploadId), 2200)
    onError?.()
    return false
  }

  const runner = createResumableUpload(
    rawFile,
    {
      scope: props.scope,
      parentId: folderId.value,
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
    return await finishUpload()
  } catch (e) {
    return failUpload(e)
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
  } catch (e) {
    task.failUpload(e)
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

async function saveBlob(resp, filename) {
  const blob = new Blob([resp.data])
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'download'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

async function onDownloadFolder(row) {
  if (!row || row.type !== 'folder') return
  try {
    const d = await api.createFolderZipTask(row.id)
    const task = d.task
    if (!task?.id) throw new Error('创建打包任务失败')
    setZipProgress(task.id, {
      id: task.id,
      folderId: row.id,
      name: row.name,
      filename: task.filename || `${row.name}.zip`,
      percent: task.percent || 0,
      status: 'default',
      message: task.message || '等待打包',
      done: task.done || 0,
      total: task.total || 0,
    })
    message.info(`开始打包“${row.name}”`)
    const poll = async () => {
      try {
        const statusResp = await api.getFolderZipTask(task.id)
        const latest = statusResp.task || {}
        setZipProgress(task.id, {
          percent: latest.percent || 0,
          message: latest.message || '',
          done: latest.done || 0,
          total: latest.total || 0,
          status: latest.status === 'error' ? 'error' : latest.status === 'done' ? 'success' : 'default',
          filename: latest.filename || task.filename || `${row.name}.zip`,
        })
        if (latest.status === 'done') {
          clearZipTimer(task.id)
          const resp = await api.downloadFolderZipTask(task.id)
          await saveBlob(resp, latest.filename || task.filename || `${row.name}.zip`)
          message.success('文件夹下载已开始')
          window.setTimeout(() => removeZipProgress(task.id), 1500)
        } else if (latest.status === 'error') {
          clearZipTimer(task.id)
          message.error(latest.message || '文件夹打包失败')
        }
      } catch (e) {
        clearZipTimer(task.id)
        setZipProgress(task.id, { status: 'error', message: e?.message || '打包进度获取失败' })
        message.error(e?.message || '打包进度获取失败')
      }
    }
    await poll()
    if (zipProgressMap.value[task.id] && !['success', 'error'].includes(zipProgressMap.value[task.id].status)) {
      setZipTimer(task.id, window.setInterval(poll, 1000))
    }
  } catch (e) {
    message.error(e?.message || '文件夹下载失败')
  }
}

async function onDelete(row) {
  if (!window.confirm(`确定删除“${row.name}”？`)) return
  try {
    await api.deleteFileNode(row.id)
    message.success('已删除')
    await loadList()
    emit('changed')
  } catch (e) {
    message.error(e?.message || '删除失败')
  }
}

function typeText(row) {
  if (isVideoFile(row)) return '视频'
  if (isPdfFile(row)) return 'PDF'
  if (isImageFile(row)) return '图片'
  if (isOfficeFile(row)) return 'Office'
  return row.type === 'folder' ? '文件夹' : '文件'
}

const columns = computed(() => [
  {
    title: '名称',
    key: 'name',
    minWidth: 0,
    ellipsis: { tooltip: true },
    render: (row) =>
      h(
        'span',
        {
          class: [
            'file-name-cell',
            row.type === 'folder' || isVideoFile(row) || isPdfFile(row) || isImageFile(row) || isOfficeFile(row) ? 'file-name-cell--clickable' : '',
            row.type === 'folder' ? 'file-name-cell--folder' : '',
          ],
          onClick: () => onNameClick(row),
          onContextmenu: (event) => openContextMenu(event, row),
          onPointerdown: (event) => onNamePointerDown(event, row),
          onPointerup: clearLongPress,
          onPointercancel: clearLongPress,
          onPointerleave: clearLongPress,
        },
        [
          iconNode(row.type === 'folder' ? Folder : isVideoFile(row) ? VideocamOutline : DocumentOutline, 17),
          h('span', { class: 'file-name-cell__text' }, row.name),
        ],
      ),
  },
  { title: '类型', key: 'type', width: 76, render: typeText },
  {
    title: '操作',
    key: 'actions',
    width: 96,
    render: (row) =>
      h(
        'div',
        { class: 'file-row-actions' },
        [
          row.type === 'folder'
            ? h(NButton, { size: 'small', circle: true, quaternary: true, title: '进入', onClick: () => enterFolder(row) }, { icon: () => iconNode(FolderOpenOutline) })
            : h(NButton, { size: 'small', circle: true, quaternary: true, title: '下载', onClick: () => onDownload(row) }, { icon: () => iconNode(DownloadOutline) }),
          row.type === 'folder'
            ? h(NButton, { size: 'small', circle: true, quaternary: true, title: '打包下载', onClick: () => onDownloadFolder(row) }, { icon: () => iconNode(DownloadOutline) })
            : null,
          h(NButton, { size: 'small', circle: true, quaternary: true, type: 'error', title: '删除', onClick: () => onDelete(row) }, { icon: () => iconNode(TrashOutline) }),
        ].filter(Boolean),
      ),
  },
])

watch(
  () => [props.scope, props.projectId],
  () => {
    listReqSeq.value += 1
    root.value = null
    currentFolder.value = null
    items.value = []
    pathStack.value = []
    if (props.scope === 'project' && (props.projectId === null || props.projectId === undefined || props.projectId === '')) return
    refresh()
  },
  { immediate: true },
)
</script>

<template>
  <component :is="props.embedded ? 'div' : NCard">
    <NSpace class="file-browser-toolbar" justify="space-between" align="center">
      <NSpace align="center">
        <NButton size="small" :disabled="pathStack.length <= 1" @click="goUp">
          <template #icon><NIcon><ArrowUpOutline /></NIcon></template>
          返回上级
        </NButton>
        <div class="file-browser-current">{{ currentFolder?.name }}</div>
      </NSpace>
      <NSpace>
        <NButton size="small" @click="refresh">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>
          刷新
        </NButton>
        <NButton size="small" @click="createFolderOpen = true">
          <template #icon><NIcon><AddOutline /></NIcon></template>
          新建文件夹
        </NButton>
        <NUpload v-model:file-list="uploadFileList" :custom-request="onUpload" :show-file-list="false" multiple>
          <NButton size="small" type="primary">
            <template #icon><NIcon><CloudUploadOutline /></NIcon></template>
            上传文件
          </NButton>
        </NUpload>
      </NSpace>
    </NSpace>

    <div v-if="uploadProgressItems.length" class="file-upload-progress">
      <div class="file-upload-progress__head">
        <span>上传队列 {{ uploadProgressItems.length }} 个文件</span>
        <strong>{{ uploadOverallProgress }}%</strong>
      </div>
      <NProgress type="line" :percentage="uploadOverallProgress" :status="uploadProgressStatus" :height="8" />
      <div class="file-upload-progress__list">
        <div v-for="item in uploadProgressItems" :key="item.id" class="file-upload-progress__item">
          <div class="file-upload-progress__meta">
            <span class="file-upload-progress__name">{{ item.name }}</span>
            <span class="file-upload-progress__speed">{{ item.percent }}% · {{ item.speed }}</span>
            <NSpace size="small" :wrap="false">
              <NButton v-if="item.state === 'uploading'" size="tiny" quaternary @click="pauseUpload(item.id)">
                <template #icon><NIcon><PauseOutline /></NIcon></template>
                暂停
              </NButton>
              <NButton v-if="item.state === 'paused'" size="tiny" quaternary type="primary" @click="resumeUpload(item.id)">
                <template #icon><NIcon><PlayOutline /></NIcon></template>
                继续
              </NButton>
              <NButton v-if="!['success', 'canceled'].includes(item.state)" size="tiny" quaternary type="error" @click="cancelUpload(item.id)">
                <template #icon><NIcon><CloseCircleOutline /></NIcon></template>
                取消
              </NButton>
            </NSpace>
          </div>
          <NProgress type="line" :percentage="item.percent" :status="item.status" :height="6" :show-indicator="false" />
        </div>
      </div>
    </div>

    <div v-if="zipProgressItems.length" class="file-upload-progress">
      <div class="file-upload-progress__head">
        <span>文件夹打包 {{ zipProgressItems.length }} 个任务</span>
      </div>
      <div class="file-upload-progress__list">
        <div v-for="item in zipProgressItems" :key="item.id" class="file-upload-progress__item">
          <div class="file-upload-progress__meta">
            <span class="file-upload-progress__name">{{ item.name }}</span>
            <span class="file-upload-progress__speed">
              {{ item.percent }}% · {{ item.message }}
              <template v-if="item.total">（{{ item.done }}/{{ item.total }}）</template>
            </span>
          </div>
          <NProgress type="line" :percentage="item.percent" :status="item.status" :height="6" />
        </div>
      </div>
    </div>

    <div class="file-browser-table">
      <NDataTable
        class="file-browser-data-table"
        :columns="columns"
        :data="items"
        :row-key="(row) => row.id"
        :loading="loading"
        :pagination="false"
      />
    </div>
  </component>

  <NDropdown
    trigger="manual"
    placement="bottom-start"
    :show="contextMenu.show"
    :x="contextMenu.x"
    :y="contextMenu.y"
    :options="contextMenuOptions"
    @select="onContextSelect"
    @clickoutside="contextMenu.show = false"
  />

  <NModal v-model:show="createFolderOpen" preset="card" title="新建文件夹" style="width: 420px; max-width: 96vw">
    <NForm :model="folderForm">
      <NFormItem label="名称">
        <NInput v-model:value="folderForm.name" />
      </NFormItem>
      <NSpace justify="end">
        <NButton @click="createFolderOpen = false">取消</NButton>
        <NButton type="primary" @click="onCreateFolder">
          <template #icon><NIcon><AddOutline /></NIcon></template>
          创建
        </NButton>
      </NSpace>
    </NForm>
  </NModal>

  <NModal v-model:show="renameOpen" preset="card" title="重命名" style="width: 420px; max-width: 96vw">
    <NForm :model="renameForm">
      <NFormItem label="名称">
        <NInput v-model:value="renameForm.name" autofocus @keyup.enter="onRename" />
      </NFormItem>
      <NSpace justify="end">
        <NButton @click="renameOpen = false">取消</NButton>
        <NButton type="primary" @click="onRename">保存</NButton>
      </NSpace>
    </NForm>
  </NModal>

  <NModal v-model:show="moveOpen" preset="card" title="移动到文件夹" style="width: 460px; max-width: 96vw">
    <NForm>
      <NFormItem label="目标文件夹">
        <NSelect
          v-model:value="moveTarget"
          :options="moveFolderOptions"
          :loading="moveLoading"
          filterable
          placeholder="请选择目标文件夹"
        />
      </NFormItem>
      <NSpace justify="end">
        <NButton @click="moveOpen = false">取消</NButton>
        <NButton type="primary" :loading="moveLoading" @click="onMove">移动</NButton>
      </NSpace>
    </NForm>
  </NModal>

  <NModal
    :show="videoPreviewOpen"
    preset="card"
    :title="videoPreviewNode?.name || '视频预览'"
    style="width: min(960px, 96vw)"
    @update:show="(show) => (show ? (videoPreviewOpen = true) : closeVideoPreview())"
  >
    <video
      v-if="videoPreviewUrl"
      class="file-video-preview"
      :src="videoPreviewUrl"
      controls
      autoplay
      playsinline
    />
  </NModal>

  <NModal
    :show="pdfPreviewOpen"
    preset="card"
    :title="pdfPreviewNode?.name || 'PDF 预览'"
    style="width: min(1100px, 96vw)"
    @update:show="(show) => (show ? (pdfPreviewOpen = true) : closePdfPreview())"
  >
    <iframe
      v-if="pdfPreviewUrl"
      class="file-pdf-preview"
      :src="pdfPreviewUrl"
      title="PDF 预览"
    />
  </NModal>

  <NModal
    :show="imagePreviewOpen"
    preset="card"
    :title="imagePreviewNode?.name || '图片预览'"
    style="width: min(1000px, 96vw)"
    @update:show="(show) => (show ? (imagePreviewOpen = true) : closeImagePreview())"
  >
    <img
      v-if="imagePreviewUrl"
      class="file-image-preview"
      :src="imagePreviewUrl"
      :alt="imagePreviewNode?.name || '图片预览'"
    />
  </NModal>

  <NModal
    :show="officePreviewOpen"
    preset="card"
    :title="officePreviewNode?.name || 'Office 预览'"
    style="width: min(1100px, 96vw)"
    @update:show="(show) => (show ? (officePreviewOpen = true) : closeOfficePreview())"
  >
    <iframe
      v-if="officePreviewUrl"
      class="file-pdf-preview"
      :src="officePreviewUrl"
      title="Office 预览"
    />
  </NModal>
</template>

<style scoped>
.file-browser-toolbar,
.file-browser-current,
.file-upload-progress,
.file-browser-table {
  min-width: 0;
}

.file-browser-current {
  max-width: 38vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}

.file-browser-table {
  margin-top: 12px;
  overflow: hidden;
  border-radius: 8px;
}

:deep(.file-browser-data-table .n-data-table-base-table-body) {
  overflow-x: hidden !important;
}

:deep(.file-browser-data-table .n-data-table-table) {
  table-layout: fixed;
}

:deep(.file-browser-data-table .n-data-table-tr) {
  transition:
    background-color var(--dcp-dur-fast) var(--dcp-ease),
    transform var(--dcp-dur-fast) var(--dcp-ease);
}

:deep(.file-browser-data-table .n-data-table-tr:hover) {
  background: var(--dcp-hover);
}

:deep(.file-browser-data-table .n-data-table-tr:active) {
  transform: scale(0.995);
}

:deep(.file-browser-data-table .n-data-table-th),
:deep(.file-browser-data-table .n-data-table-td) {
  padding: 11px 12px;
}

:deep(.file-row-actions) {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
  min-width: 0;
}

:deep(.file-row-actions .n-button) {
  flex: 0 0 auto;
}

.file-upload-progress {
  margin-top: 10px;
}

.file-upload-progress__head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--dcp-muted);
}

.file-upload-progress__head strong {
  color: var(--dcp-text);
  font-weight: 700;
}

.file-upload-progress__list {
  display: grid;
  gap: 8px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--dcp-muted);
}

.file-upload-progress__item,
.file-upload-progress__meta {
  min-width: 0;
}

.file-upload-progress__meta {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}

.file-upload-progress__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-upload-progress__speed {
  white-space: nowrap;
}

:deep(.file-name-cell) {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
  width: 100%;
}

:deep(.file-name-cell .n-icon) {
  flex: 0 0 auto;
  color: var(--dcp-primary);
}

:deep(.file-name-cell--clickable) {
  cursor: pointer;
}

:deep(.file-name-cell--clickable:hover .file-name-cell__text) {
  color: var(--dcp-primary);
}

:deep(.file-name-cell__text) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-video-preview {
  display: block;
  width: 100%;
  max-height: 72vh;
  background: #000;
  border-radius: 6px;
}

.file-pdf-preview {
  display: block;
  width: 100%;
  height: 78vh;
  border: 0;
  border-radius: 6px;
  background: #f5f5f5;
}

.file-image-preview {
  display: block;
  max-width: 100%;
  max-height: 78vh;
  margin: 0 auto;
  object-fit: contain;
  border-radius: 6px;
}

@media (max-width: 640px) {
  .file-browser-toolbar {
    overflow: hidden;
  }

  .file-browser-table {
    max-width: 100%;
    overflow-x: hidden;
  }

  .file-browser-current {
    max-width: 100%;
  }

  .file-upload-progress__meta {
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
  }

  :deep(.file-browser-data-table .n-data-table-thead) {
    display: none;
  }

  :deep(.file-browser-data-table),
  :deep(.file-browser-data-table .n-data-table-wrapper),
  :deep(.file-browser-data-table .n-data-table-base-table),
  :deep(.file-browser-data-table .n-data-table-base-table-body) {
    max-width: 100% !important;
    overflow-x: hidden !important;
  }

  :deep(.file-browser-data-table .n-data-table-table),
  :deep(.file-browser-data-table .n-data-table-tbody) {
    display: block;
    width: 100% !important;
    min-width: 0 !important;
  }

  :deep(.file-browser-data-table .n-data-table-tr) {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 48px 86px;
    align-items: center;
    width: 100% !important;
    min-width: 0 !important;
    padding: 0;
    border-bottom: 1px solid var(--dcp-border);
  }

  :deep(.file-browser-data-table .n-data-table-td) {
    display: flex;
    align-items: center;
    min-width: 0;
    width: auto !important;
    border-bottom: 0 !important;
    padding: 10px 8px;
    overflow: hidden;
    white-space: nowrap;
  }

  :deep(.file-browser-data-table .n-data-table-td:last-child) {
    position: static;
    justify-content: flex-end;
    width: auto !important;
    transform: none;
  }

  :deep(.file-browser-data-table .n-data-table-td:nth-child(2)) {
    color: var(--dcp-muted);
    font-size: 13px;
  }

  :deep(.file-row-actions) {
    width: 100%;
    gap: 0;
  }

  :deep(.file-row-actions .n-button) {
    --n-width: 26px;
    --n-height: 26px;
    width: 26px;
    height: 26px;
  }

  :deep(.file-name-cell) {
    gap: 7px;
  }

  :deep(.file-name-cell__text) {
    font-size: 14px;
  }
}
</style>
