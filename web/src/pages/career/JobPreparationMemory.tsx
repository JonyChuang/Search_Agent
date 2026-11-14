import { useCallback } from 'react'
import { Alert, Button, Form, Input, Spin } from 'antd'
import { careerWorkflow } from '@/api/careerWorkflow'
import { useCareerQuery } from './useCareerQuery'
import { useCareerAction } from './useCareerAction'

export default function JobPreparationMemory({ jobId }: { jobId: string }) {
  const load = useCallback((signal: AbortSignal) => careerWorkflow.memory(jobId, signal), [jobId])
  const memory = useCareerQuery(load)
  const action = useCareerAction()
  if (memory.error) return <Alert type="error" message={memory.error} action={<Button onClick={memory.retry}>重试</Button>} />
  if (!memory.data) return <Spin aria-label="正在读取备考偏好" />
  const entry = memory.data
  return (
    <Form key={entry.revision} layout="vertical" initialValues={{ notes: entry.notes ?? '' }}
      onFinish={({ notes }: { notes: string }) => action.run(async () => {
        memory.setData(await careerWorkflow.saveMemory(jobId, { revision: entry.revision, notes: notes.trim() || null }))
      })}>
      <Form.Item label="跨任务备考偏好" name="notes" extra="适用于该岗位后续创建的训练和模拟面试。清空后保存可撤销。">
        <Input.TextArea rows={2} maxLength={3000} placeholder="例如每天准备 30 分钟，优先练习项目追问" />
      </Form.Item>
      <Button htmlType="submit" loading={action.saving}>保存备考偏好</Button>
      <Button type="link" onClick={memory.retry}>重新读取</Button>
    </Form>
  )
}
