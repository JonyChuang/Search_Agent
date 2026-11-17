import { useCallback, useEffect, useState } from 'react'
import { Button, Input, Modal, Space, Tag } from 'antd'
import client from '@/api/client'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'

type Reply<T> = { data: T }
type Ticket = { id: string; token: string; target: string; expiresAt: string }
const statuses: Record<string, string> = {
  NONE: '待准备', PREPARED: '凭证已生成', NEEDS_USER: '待官网核对和提交',
  VERIFYING: '待核对官网结果', CONFIRMED: '已记录回执', RELEASED: '已确认未投递',
}
const endpoint = (id: string) => '/career/application-browser/applications/' + id

export function supportsGreenhouse(source?: URL | null) {
  return source?.origin === 'https://job-boards.greenhouse.io' &&
    /^\/[a-zA-Z0-9_-]{1,100}\/jobs\/\d{1,20}\/?$/.test(source.pathname)
}

export default function GreenhouseApplicationPanel({ applicationId, ready, save, refresh }: {
  applicationId?: string; ready: boolean; save: () => Promise<{ id: string }>; refresh: () => void
}) {
  const action = useCareerAction()
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [release, setRelease] = useState(false)
  const status = useCareerQuery(useCallback(async (signal: AbortSignal) => applicationId ?
    (await client.get<unknown, Reply<string>>(endpoint(applicationId) + '/status', { signal })).data : 'NONE', [applicationId]))
  useEffect(() => {
    if (!['PREPARED', 'NEEDS_USER', 'VERIFYING'].includes(status.data ?? '') || status.error) return
    const timer = window.setInterval(status.retry, 4000)
    return () => window.clearInterval(timer)
  }, [status.data, status.error, status.retry])

  async function download() {
    const application = await save()
    const ticket = (await client.post<unknown, Reply<Ticket>>(endpoint(application.id) + '/ticket', {
      firstName: firstName.trim(), lastName: lastName.trim(),
    })).data
    const contents = JSON.stringify({ server: window.location.origin, ticket })
    const href = URL.createObjectURL(new Blob([contents], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = href
    link.download = 'greenhouse-application.json'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(href), 1000)
    status.retry()
  }

  const locked = status.data === 'VERIFYING' || status.data === 'CONFIRMED'
  return <Space direction="vertical" size={9} style={{ width: '100%' }}>
    <Tag color={status.data === 'VERIFYING' ? 'gold' : 'purple'}>{statuses[status.data ?? 'NONE']}</Tag>
    <p>在 Chrome 或 Edge 加载项目中的 Greenhouse 扩展。打开招聘页面后，在扩展中导入凭证和本次投递的简历 PDF。</p>
    {!locked && <>
      <Input aria-label="官网填写的名" placeholder="名" maxLength={80} value={firstName} onChange={(event) => setFirstName(event.target.value)} />
      <Input aria-label="官网填写的姓" placeholder="姓" maxLength={80} value={lastName} onChange={(event) => setLastName(event.target.value)} />
      <Button disabled={!ready || !firstName.trim() || !lastName.trim()} loading={action.saving}
        onClick={() => void action.run(download)}>下载填表凭证</Button>
    </>}
    {status.error && <div role="alert">{status.error}</div>}
    {applicationId && <Button onClick={() => { status.retry(); refresh() }}>刷新官网回执</Button>}
    {status.data === 'VERIFYING' && <Button type="link" onClick={() => setRelease(true)}>官网确认未投递</Button>}
    {release && <Modal open title="官网已确认未收到申请？" onCancel={() => setRelease(false)} confirmLoading={action.saving}
      okText="确认未投递" onOk={() => void action.run(async () => {
        if (!applicationId) return
        await client.post(endpoint(applicationId) + '/release')
        setRelease(false)
        status.retry()
      })}>
      <p>仅在招聘页面明确显示提交失败，且确认官网未收到申请时使用。操作后可以重新编辑材料和准备投递。</p>
    </Modal>}
  </Space>
}
