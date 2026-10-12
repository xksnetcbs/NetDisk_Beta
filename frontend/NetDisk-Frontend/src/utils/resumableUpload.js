import { api } from '../api'

export const DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024

const SESSION_PREFIX = 'netdisk-upload-session:'

function storageKey(file, target) {
  return [
    SESSION_PREFIX,
    target.scope,
    target.projectId || '',
    target.parentId,
    file.name,
    file.size,
    file.lastModified || '',
  ].join(':')
}

export function formatUploadSpeed(bytesPerSecond) {
  const n = Number(bytesPerSecond)
  if (!Number.isFinite(n) || n <= 0) return '--/s'
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
  let value = n
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  const digits = value < 10 && index > 0 ? 1 : 0
  return `${value.toFixed(digits)} ${units[index]}`
}

function readStoredSession(key) {
  try {
    return JSON.parse(window.localStorage.getItem(key) || 'null')
  } catch {
    return null
  }
}

function writeStoredSession(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // localStorage can be unavailable in private browsing; upload still works.
  }
}

function removeStoredSession(key) {
  try {
    window.localStorage.removeItem(key)
  } catch {
    // ignore
  }
}

function makeError(code, message) {
  const err = new Error(message)
  err.code = code
  return err
}

export function createResumableUpload(file, target, callbacks = {}) {
  const key = storageKey(file, target)
  const state = {
    uploadId: null,
    status: 'idle',
    paused: false,
    canceled: false,
    controller: null,
    uploadedBytes: 0,
    chunkSize: target.chunkSize || DEFAULT_CHUNK_SIZE,
    uploadedChunks: new Set(),
    lastUploadedBytes: 0,
    lastAt: performance.now(),
  }

  const emit = (patch = {}) => callbacks.onProgress?.({
    uploadId: state.uploadId,
    name: file.name,
    total: file.size,
    loaded: state.uploadedBytes,
    percent: file.size ? Math.min(99, Math.round((state.uploadedBytes / file.size) * 100)) : 0,
    status: state.status,
    speed: patch.speed || '--/s',
    ...patch,
  })

  async function ensureSession() {
    const stored = readStoredSession(key)
    if (stored?.uploadId) {
      try {
        const remote = await api.getUploadSession(stored.uploadId)
        const session = remote.session
        state.uploadId = session.upload_id
        state.chunkSize = session.chunk_size || state.chunkSize
        state.uploadedChunks = new Set(session.uploaded_chunks || [])
        state.uploadedBytes = Number(session.uploaded_bytes || 0)
        emit({ percent: file.size ? Math.round((state.uploadedBytes / file.size) * 100) : 0 })
        return session
      } catch {
        removeStoredSession(key)
      }
    }

    const created = await api.createUploadSession({
      filename: file.name,
      size: file.size,
      mime_type: file.type || null,
      chunk_size: state.chunkSize,
      scope: target.scope,
      parent_id: target.parentId,
      project_id: target.scope === 'project' ? Number(target.projectId) : undefined,
    })
    const session = created.session
    state.uploadId = session.upload_id
    state.chunkSize = session.chunk_size || state.chunkSize
    writeStoredSession(key, {
      uploadId: state.uploadId,
      name: file.name,
      size: file.size,
      parentId: target.parentId,
      scope: target.scope,
      projectId: target.projectId || null,
    })
    return session
  }

  async function start() {
    state.paused = false
    state.canceled = false
    state.status = 'uploading'
    emit({ status: 'default' })

    await ensureSession()
    const totalChunks = Math.ceil(file.size / state.chunkSize)

    for (let index = 0; index < totalChunks; index += 1) {
      if (state.canceled) throw makeError('UPLOAD_CANCELED', '上传已取消')
      if (state.paused) throw makeError('UPLOAD_PAUSED', '上传已暂停')
      if (state.uploadedChunks.has(index)) continue

      const startByte = index * state.chunkSize
      const endByte = Math.min(startByte + state.chunkSize, file.size)
      const blob = file.slice(startByte, endByte)
      const baseUploaded = startByte
      state.controller = new AbortController()
      state.lastUploadedBytes = state.uploadedBytes
      state.lastAt = performance.now()

      await api.uploadChunk(state.uploadId, index, blob, {
        signal: state.controller.signal,
        onUploadProgress: (event) => {
          const now = performance.now()
          const currentLoaded = baseUploaded + Number(event?.loaded || 0)
          const elapsed = Math.max(0.001, (now - state.lastAt) / 1000)
          const speed = formatUploadSpeed((currentLoaded - state.lastUploadedBytes) / elapsed)
          state.uploadedBytes = Math.min(currentLoaded, file.size)
          state.lastUploadedBytes = state.uploadedBytes
          state.lastAt = now
          emit({ speed, status: 'default' })
        },
      })

      state.uploadedChunks.add(index)
      state.uploadedBytes = Math.min(endByte, file.size)
      emit({ speed: '--/s', status: 'default' })
    }

    const completed = await api.completeUploadSession(state.uploadId)
    removeStoredSession(key)
    state.status = 'success'
    state.uploadedBytes = file.size
    emit({ percent: 100, loaded: file.size, status: 'success', speed: '完成' })
    callbacks.onComplete?.(completed)
    return completed
  }

  function pause() {
    if (state.status !== 'uploading') return
    state.paused = true
    state.status = 'paused'
    state.controller?.abort?.()
    emit({ status: 'warning', speed: '已暂停' })
  }

  async function resume() {
    if (state.status !== 'paused' && state.status !== 'error') return
    return start()
  }

  async function cancel() {
    state.canceled = true
    state.status = 'canceled'
    state.controller?.abort?.()
    if (state.uploadId) {
      try {
        await api.cancelUploadSession(state.uploadId)
      } catch {
        // The local cancel should still complete even if server cleanup already happened.
      }
    }
    removeStoredSession(key)
    emit({ status: 'error', speed: '已取消' })
  }

  return {
    get uploadId() {
      return state.uploadId
    },
    start,
    pause,
    resume,
    cancel,
  }
}
