import { useState } from 'react'
import { Button, Drawer, Form, Input, InputNumber, Popconfirm, Space, message } from 'antd'
import { careerContextApi, type CareerContextState } from '@/api/chat'

const fallbackFields = ['求职目标', '复习顺序', '截止时间']

export default function CareerContextButton({ conversation, job }: { conversation: string; job: string }) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<CareerContextState>()
  const [target, setTarget] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm<Record<string, string>>()
  const fields = state?.constraint_types ?? fallbackFields

  function fill(data: CareerContextState) {
    setState(data)
    setTarget(null)
    form.setFieldsValue(Object.fromEntries((data.constraint_types ?? fallbackFields)
      .map((name) => [name, data.state[name]?.[1] ?? ''])))
  }

  async function load() {
    setOpen(true)
    setBusy(true)
    try {
      fill((await careerContextApi.read(conversation, job)).data)
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function save(values?: Record<string, string>) {
    if (!state) return
    const edits = values && Object.fromEntries(fields
      .filter((name) => (values[name]?.trim() ?? '') !== (state.state[name]?.[1] ?? '')
        || state.constraints?.some((item) => item.field === name && !item.confirmed))
      .map((name) => [name, values[name]?.trim() || null]))
    if (!target && (!edits || !Object.keys(edits).length)) return
    setBusy(true)
    try {
      const body = values ? { fields: edits, time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone }
        : { rollback_to: target ?? undefined }
      fill((await careerContextApi.save(conversation, job, { expected_version: state.version, ...body })).data)
      message.success('岗位上下文已更新')
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return <>
    <Button size="small" onClick={() => void load()}>上下文约束</Button>
    <Drawer title="岗位上下文约束" open={open} onClose={() => setOpen(false)} forceRender>
      {state?.job_facts?.location && <p>岗位实际地点 {state.job_facts.location}（来自岗位记录）</p>}
      <Form form={form} layout="vertical" disabled={busy || !state} onFinish={(values) => void save(values)}>
        {fields.map((name) => {
          const constraint = state?.constraints?.find((item) => item.field === name)
          const hint = constraint?.normalizedValue ? `固定截止日期 ${constraint.normalizedValue}`
            : constraint?.confirmed === false ? name === '截止时间' ? '请保存以确认截止日期。' : '来自历史消息，保存可确认。' : undefined
          return <Form.Item key={name} label={name} name={name} extra={hint}>
            <Input.TextArea maxLength={500} autoSize={{ minRows: 2 }} />
          </Form.Item>
        })}
        <Space>
          <Button type="primary" htmlType="submit" loading={busy}>保存约束</Button>
          <Button onClick={() => void load()}>刷新版本</Button>
          {state && <span>当前版本 {state.version}</span>}
        </Space>
      </Form>
      {!!state && state.version > 1 && <Space style={{ marginTop: 16 }}>
        <InputNumber aria-label="回滚目标版本" min={1} max={state.version - 1} precision={0} value={target}
          onChange={setTarget} />
        <Popconfirm title={`恢复第 ${target} 版约束？`} onConfirm={() => save()} disabled={!target || busy}>
          <Button disabled={!target || busy}>回滚</Button>
        </Popconfirm>
      </Space>}
    </Drawer>
  </>
}
