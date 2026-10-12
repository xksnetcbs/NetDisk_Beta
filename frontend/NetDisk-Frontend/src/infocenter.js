import { http } from './api'

function content(response) { return response.data }
function connectionError(error) {
  const detail = error?.response?.data
  const message = typeof detail?.error === 'string' ? detail.error : detail?.error?.message || detail?.msg
  if (message) error.message = message
  throw error
}

export const infoCenterApi = {
  request(path, { signal, method = 'GET', body } = {}) {
    return http.request({ url: '/infocenter/desktop' + path, method, data: body, signal, timeout: 60000 })
      .then(content).catch(connectionError)
  },
  unread() {
    return http.get('/infocenter/terminal/unread').then(content).catch(connectionError)
  },
  markRead(chat, uid) {
    return http.post('/infocenter/terminal/conversations/read', { chat_id: chat, through_uid: uid })
      .then(content).catch(connectionError)
  },
  blob(id, kind, signal) {
    return http.get(`/infocenter/desktop/messages/${Number(id)}/${kind}`, {
      responseType: 'blob', signal, timeout: 120000,
    }).then(content).catch(connectionError)
  },
  sendNetdisk(chat, body) {
    return http.post('/infocenter/netdisk/conversations/' + encodeURIComponent(chat) + '/send', body)
      .then(content).catch(connectionError)
  },
}
