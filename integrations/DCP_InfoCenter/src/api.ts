export async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch('/api' + path, { signal, cache: 'no-store' })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    if (data.device_required) location.replace('/')
    throw new Error(data.error || (response.status === 401 ? '连接凭据无效，请检查本地 .env.local' : `服务器连接失败 (${response.status})`))
  }
  return response.json()
}
export function fileUrl(id: number) { return `/api/messages/${id}/file` }
export function mediaUrl(id: number) { return `/api/messages/${id}/media` }
export function formatSize(bytes: number) {
  if (!bytes) return '大小未知'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
export function timeLabel(value: number, full = false) {
  return new Intl.DateTimeFormat('zh-CN', { ...(full ? { year: 'numeric', month: '2-digit', day: '2-digit' } as const : { month: 'numeric', day: 'numeric' } as const), hour: '2-digit', minute: '2-digit', hour12: false }).format(value * 1000)
}
