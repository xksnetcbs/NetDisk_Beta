import { inject, onBeforeUnmount, shallowReactive, type InjectionKey, type Ref } from 'vue'

export interface InfoCenterRuntime {
  request: <T>(path: string, options?: { signal?: AbortSignal; method?: string; body?: object }) => Promise<T>
  blob: (id: number, kind: 'file' | 'media', signal?: AbortSignal) => Promise<Blob>
  refreshUnread: () => Promise<unknown>
  markRead: (chat: string, uid: string) => Promise<unknown>
  unreadByChat: Ref<Record<string, number>>
  openLink?: (path: string) => void
  sendNetdisk?: (chat: string, body: object) => Promise<{ status: string }>
  scheduleRequest?: (path: string, options?: { method?: string; body?: object; signal?: AbortSignal }) => Promise<any>
  theme?: Ref<string>
}

export const INFOCENTER_RUNTIME: InjectionKey<InfoCenterRuntime> = Symbol('infocenter-runtime')

export function useInfoCenterRuntime() {
  return inject(INFOCENTER_RUNTIME, null)
}

export function useAuthenticatedMedia(runtime: InfoCenterRuntime | null) {
  const urls = shallowReactive(new Map<number, string>())
  const pending = new Map<number, AbortController>()
  let disposed = false
  function mediaUrl(id: number) {
    if (!runtime) return `/api/messages/${id}/media`
    if (!urls.has(id) && !pending.has(id) && !disposed) {
      const controller = new AbortController()
      pending.set(id, controller)
      runtime.blob(id, 'media', controller.signal).then(blob => {
        if (!disposed) urls.set(id, URL.createObjectURL(blob))
      }).catch(() => {
        // Polling/retrying the view may request a media file again after recovery.
      }).finally(() => pending.delete(id))
    }
    return urls.get(id)
  }
  onBeforeUnmount(() => {
    disposed = true
    pending.forEach(controller => controller.abort())
    urls.forEach(url => URL.revokeObjectURL(url))
  })
  return mediaUrl
}
