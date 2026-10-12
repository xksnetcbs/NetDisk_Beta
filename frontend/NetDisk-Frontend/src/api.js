import axios from 'axios'
import { useAuthStore } from './stores/auth'

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 30000,
  withCredentials: true,
})

const UPLOAD_TIMEOUT = 2 * 60 * 60 * 1000
const DOWNLOAD_TIMEOUT = 2 * 60 * 60 * 1000
let refreshPromise = null

http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token && !config.skipAuthToken) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

http.interceptors.response.use(
  (resp) => resp,
  async (err) => {
    const status = err?.response?.status
    const config = err?.config
    if (status === 401 && config && !config.skipAuthRefresh && !config.authRetried) {
      const auth = useAuthStore()
      // A late response may use the old access token after another request renewed it.
      const sentToken = config.headers?.Authorization
      if (auth.token && sentToken !== `Bearer ${auth.token}`) {
        config.authRetried = true
        return http(config)
      }
      try {
        await restoreSession()
        config.authRetried = true
        return http(config)
      } catch (refreshError) {
        return Promise.reject(refreshError)
      }
    }
    if (status === 401 && config?.authRetried) {
      useAuthStore().clearSession()
    }
    return Promise.reject(err)
  },
)

export function unwrap(resp) {
  const data = resp?.data
  if (!data?.ok) {
    const e = new Error(data?.error?.message || '请求失败')
    e.code = data?.error?.code || 'UNKNOWN'
    e.status = resp?.status
    throw e
  }
  return data.data
}

export function restoreSession() {
  const auth = useAuthStore()
  if (auth.signedOut) return Promise.reject(new Error('已退出登录'))
  if (refreshPromise) return refreshPromise
  const version = auth.sessionVersion
  refreshPromise = http
    .post('/auth/refresh', null, {
      skipAuthRefresh: true,
      skipAuthToken: true,
      headers: { 'X-DCP-Session': '1' },
    })
    .then(unwrap)
    .then((data) => {
      if (version !== auth.sessionVersion || auth.signedOut) throw new Error('登录状态已改变')
      auth.setSession(data)
      return data
    })
    .catch((err) => {
      if (version === auth.sessionVersion && [401, 403].includes(err?.response?.status || err?.status)) {
        auth.clearSession()
      }
      throw err
    })
    .finally(() => {
      refreshPromise = null
    })
  return refreshPromise
}

const PUBLIC_AUTH_REQUEST = { skipAuthRefresh: true, skipAuthToken: true }

export const api = {
  bootstrap: (payload) => http.post('/auth/bootstrap', payload, PUBLIC_AUTH_REQUEST).then(unwrap),
  login: (payload) => http.post('/auth/login', payload, PUBLIC_AUTH_REQUEST).then(unwrap),
  register: (payload) => http.post('/auth/register', payload, PUBLIC_AUTH_REQUEST).then(unwrap),
  logout: () => http.post('/auth/logout', null, {
    ...PUBLIC_AUTH_REQUEST,
    headers: { 'X-DCP-Session': '1' },
  }).then(unwrap),
  me: () => http.get('/auth/me').then(unwrap),
  changePassword: (payload) => http.post('/auth/change-password', payload).then(unwrap),

  listUsers: (params) => http.get('/users', { params }).then(unwrap),
  searchUsers: (params) => http.get('/users/search', { params }).then(unwrap),
  createUser: (payload) => http.post('/users', payload).then(unwrap),
  patchUser: (id, payload) => http.patch(`/users/${id}`, payload).then(unwrap),

  listProjects: (params) => http.get('/projects', { params }).then(unwrap),
  createProject: (payload) => http.post('/projects', payload).then(unwrap),
  getProject: (id) => http.get(`/projects/${id}`).then(unwrap),
  patchProject: (id, payload) => http.patch(`/projects/${id}`, payload).then(unwrap),
  archiveProject: (id) => http.post(`/projects/${id}/archive`).then(unwrap),
  unarchiveProject: (id) => http.post(`/projects/${id}/unarchive`).then(unwrap),

  projectManageOverview: (projectId) => http.get(`/projects/${projectId}/manage/overview`).then(unwrap),
  projectManageUsers: ( projectId) => http.get(`/projects/${projectId}/manage/users`).then(unwrap),

  listProjectMembers: (projectId) => http.get(`/projects/${projectId}/members`).then(unwrap),
  addProjectMember: (projectId, payload) => http.post(`/projects/${projectId}/members`, payload).then(unwrap),
  patchProjectMember: (projectId, userId, payload) => http.patch(`/projects/${projectId}/members/${userId}`, payload).then(unwrap),
  removeProjectMember: (projectId, userId) => http.delete(`/projects/${projectId}/members/${userId}`).then(unwrap),

  getProjectSettings: (projectId) => http.get(`/projects/${projectId}/settings`).then(unwrap),
  patchProjectSettings: (projectId, payload) => http.patch(`/projects/${projectId}/settings`, payload).then(unwrap),
  getProjectWorkflow: (projectId) => http.get(`/projects/${projectId}/workflow`).then(unwrap),
  putProjectWorkflow: (projectId, payload) => http.put(`/projects/${projectId}/workflow`, payload).then(unwrap),
  listProjectGroupMessages: (projectId) => http.get(`/projects/${projectId}/group-messages`).then(unwrap),
  sendProjectGroupMessage: (projectId, payload) => http.post(`/projects/${projectId}/group-messages`, payload).then(unwrap),

  listTasks: (projectId, params) => http.get(`/projects/${projectId}/tasks`, { params }).then(unwrap),
  createTask: (projectId, payload) => http.post(`/projects/${projectId}/tasks`, payload).then(unwrap),
  getTask: (taskId) => http.get(`/tasks/${taskId}`).then(unwrap),
  patchTask: (taskId, payload) => http.patch(`/tasks/${taskId}`, payload).then(unwrap),
  deleteTask: (taskId) => http.delete(`/tasks/${taskId}`).then(unwrap),
  takeTask: (taskId) => http.post(`/tasks/${taskId}/take`).then(unwrap),
  rejectTask: (taskId) => http.post(`/tasks/${taskId}/reject`).then(unwrap),
  listTaskComments: (taskId) => http.get(`/tasks/${taskId}/comments`).then(unwrap),
  createTaskComment: (taskId, payload) => http.post(`/tasks/${taskId}/comments`, payload).then(unwrap),
  addTaskAttachment: (taskId, payload) => http.post(`/tasks/${taskId}/attachments`, payload).then(unwrap),
  removeTaskAttachment: (taskId, fileId) => http.delete(`/tasks/${taskId}/attachments/${fileId}`).then(unwrap),

  filesRoot: (params) => http.get('/files/root', { params }).then(unwrap),
  filesList: (params) => http.get('/files', { params }).then(unwrap),
  createFolder: (payload) => http.post('/files/folders', payload).then(unwrap),
  uploadFile: (formData, config = {}) =>
    http
      .post('/files/upload', formData, {
        timeout: UPLOAD_TIMEOUT,
        ...config,
        headers: { 'Content-Type': 'multipart/form-data', ...(config.headers || {}) },
      })
      .then(unwrap),
  createUploadSession: (payload) =>
    http.post('/files/upload-sessions', payload, { timeout: UPLOAD_TIMEOUT }).then(unwrap),
  getUploadSession: (uploadId) =>
    http.get(`/files/upload-sessions/${uploadId}`, { timeout: UPLOAD_TIMEOUT }).then(unwrap),
  uploadChunk: (uploadId, index, blob, config = {}) =>
    http
      .put(`/files/upload-sessions/${uploadId}/chunks/${index}`, blob, {
        timeout: UPLOAD_TIMEOUT,
        ...config,
        headers: { 'Content-Type': 'application/octet-stream', ...(config.headers || {}) },
      })
      .then(unwrap),
  completeUploadSession: (uploadId) =>
    http.post(`/files/upload-sessions/${uploadId}/complete`, null, { timeout: UPLOAD_TIMEOUT }).then(unwrap),
  cancelUploadSession: (uploadId) =>
    http.delete(`/files/upload-sessions/${uploadId}`, { timeout: UPLOAD_TIMEOUT }).then(unwrap),
  linkFile: (payload) => http.post('/files/link', payload).then(unwrap),
  replaceFile: (fileId, formData) =>
    http
      .post(`/files/${fileId}/replace`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: UPLOAD_TIMEOUT,
      })
      .then(unwrap),
  downloadFile: (fileId) =>
    http.get(`/files/${fileId}/download`, { responseType: 'blob', timeout: DOWNLOAD_TIMEOUT }),
  createFolderZipTask: (folderId) => http.post(`/files/${folderId}/zip-tasks`).then(unwrap),
  getFolderZipTask: (taskId) => http.get(`/files/zip-tasks/${taskId}`).then(unwrap),
  downloadFolderZipTask: (taskId) =>
    http.get(`/files/zip-tasks/${taskId}/download`, { responseType: 'blob', timeout: DOWNLOAD_TIMEOUT }),
  filePreviewUrl: (fileId) => {
    const auth = useAuthStore()
    const base = String(http.defaults.baseURL || '/api').replace(/\/$/, '')
    return `${base}/files/${fileId}/preview?token=${encodeURIComponent(auth.token || '')}`
  },
  patchFileNode: (fileId, payload) => http.patch(`/files/${fileId}`, payload).then(unwrap),
  deleteFileNode: (fileId) => http.delete(`/files/${fileId}`).then(unwrap),

  listCalendarEvents: (params) => http.get('/calendar/events', { params }).then(unwrap),
  createCalendarEvent: (payload) => http.post('/calendar/events', payload).then(unwrap),
  patchCalendarEvent: (id, payload) => http.patch(`/calendar/events/${id}`, payload).then(unwrap),
  deleteCalendarEvent: (id) => http.delete(`/calendar/events/${id}`).then(unwrap),

  listThreads: () => http.get('/inbox/threads').then(unwrap),
  createThread: (payload) => http.post('/inbox/threads', payload).then(unwrap),
  listMessages: (threadId) => http.get(`/inbox/threads/${threadId}/messages`).then(unwrap),
  sendMessage: (threadId, payload) => http.post(`/inbox/threads/${threadId}/messages`, payload).then(unwrap),
  readThread: (threadId) => http.post(`/inbox/threads/${threadId}/read`).then(unwrap),

  listNotifications: (params) => http.get('/notifications', { params }).then(unwrap),
  readNotification: (id) => http.post(`/notifications/${id}/read`).then(unwrap),
  readAllNotifications: () => http.post('/notifications/read-all').then(unwrap),

  adminOverview: () => http.get('/admin/overview').then(unwrap),
  adminProjects: () => http.get('/admin/projects').then(unwrap),
  adminStorage: () => http.get('/admin/storage').then(unwrap),
  adminInviteCodes: () => http.get('/admin/invite-codes').then(unwrap),
  createInviteCode: (payload) => http.post('/admin/invite-codes', payload).then(unwrap),
  patchInviteCode: (inviteId, payload) => http.patch(`/admin/invite-codes/${inviteId}`, payload).then(unwrap),
  activateUser: (userId) => http.post(`/admin/users/${userId}/activate`).then(unwrap),
  adminUsers: (params) => http.get('/admin/users', { params }).then(unwrap),
  adminDisableUser: (userId) => http.post(`/admin/users/${userId}/disable`).then(unwrap),
  adminEnableUser: (userId) => http.post(`/admin/users/${userId}/enable`).then(unwrap),
  adminSetSuperAdmin: (userId) => http.post(`/admin/users/${userId}/set-super-admin`).then(unwrap),
  adminSetUser: (userId) => http.post(`/admin/users/${userId}/set-user`).then(unwrap),
  adminDeleteUser: (userId) => http.delete(`/admin/users/${userId}`).then(unwrap),
}
