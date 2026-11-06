import { App } from 'antd'
import { useRef, useState } from 'react'
import { useAuthStore } from '@/stores/authStore'

export function useCareerAction() {
  const { message } = App.useApp()
  const busy = useRef(false)
  const [saving, setSaving] = useState(false)
  const userId = useAuthStore((state) => state.user?.id)

  async function run(work: () => Promise<void>) {
    if (busy.current) return
    busy.current = true
    setSaving(true)
    try {
      await work()
    } catch (failure) {
      message.error(failure instanceof Error ? failure.message : '保存失败，请重试')
    } finally {
      busy.current = false
      setSaving(false)
    }
  }

  async function submit<T extends object, R>(kind: string, input: T, send: (body: T & { requestId: string }) => Promise<R>) {
    const key = `career-pending:${userId}:${kind}`
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(input)))
    const fingerprint = Array.from(new Uint8Array(digest)).join(',')
    const previous = JSON.parse(sessionStorage.getItem(key) ?? 'null') as { requestId: string; fingerprint: string } | null
    const requestId = previous?.fingerprint === fingerprint ? previous.requestId : crypto.randomUUID()
    sessionStorage.setItem(key, JSON.stringify({ fingerprint, requestId }))
    const result = await send({ ...input, requestId })
    sessionStorage.removeItem(key)
    return result
  }

  return { saving, run, submit }
}
