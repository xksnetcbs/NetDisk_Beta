import { http } from './api'

export const terminalScheduleApi = {
  request(path = '', { method = 'GET', body, signal } = {}) {
    return http.request({ url: '/mobile/terminal/schedules' + path, method, data: body, signal, timeout: 60000 })
      .then(response => response.data).catch(error => {
        const detail = error?.response?.data
        error.message = typeof detail?.error === 'string' ? detail.error : detail?.error?.message || error.message
        throw error
      })
  },
}
