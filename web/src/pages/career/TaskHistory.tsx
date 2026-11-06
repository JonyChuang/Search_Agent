import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Alert, Button, Card, Empty, Space, Spin, Tag, Typography } from 'antd'
import { careerWorkflow, type CareerTask, type TaskKind } from '@/api/careerWorkflow'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'

const { Paragraph, Text } = Typography
const status = {
  QUEUED: { label: '待执行', color: 'default' },
  RUNNING: { label: '运行中', color: 'processing' },
  SUCCEEDED: { label: '已完成', color: 'success' },
  FAILED: { label: '失败', color: 'error' },
}

export default function TaskHistory({ kind, render }: { kind: TaskKind; render?: (task: CareerTask) => ReactNode }) {
  const [page, setPage] = useState(1)
  const load = useCallback((signal: AbortSignal) => careerWorkflow.tasks(kind, page, signal), [kind, page])
  const { data, error, retry, setData } = useCareerQuery(load)
  const active = data?.items.some((task) => task.status === 'QUEUED' || task.status === 'RUNNING')
  const action = useCareerAction()

  useEffect(() => {
    if (!active || error) return
    const request = new AbortController()
    const timer = window.setTimeout(() => {
      load(request.signal).then(
        (result) => { if (!request.signal.aborted) setData(result) },
        () => { if (!request.signal.aborted) retry() },
      )
    }, 2000)
    return () => {
      clearTimeout(timer)
      request.abort()
    }
  }, [active, data, error, load, retry, setData])

  function changePage(next: number) {
    setData(undefined)
    setPage(next)
  }

  if (error) return <Alert type="error" message={error} action={<Button onClick={retry}>重试读取</Button>} />
  if (!data) return <Spin />
  if (!data.items.length) return <Empty description="暂无任务" />
  return (
    <Space direction="vertical" style={{ display: 'flex' }}>
      {data.items.map((task) => (
        <Card key={task.id} size="small" title={task.job} extra={<Tag color={status[task.status].color}>{status[task.status].label}</Tag>}>
          <Paragraph type="secondary">创建于 {new Date(task.createdAt).toLocaleString()} · 执行次数 {task.generation}</Paragraph>
          {task.error && <Alert type="error" message={task.error} action={
            <Button loading={action.saving} onClick={() => action.run(async () => {
              await careerWorkflow.retry(task.id)
              retry()
            })}>重试执行</Button>
          } />}
          {render?.(task)}
          {task.result?.feedback && <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{task.result.feedback}</Paragraph>}
        </Card>
      ))}
      <Space>
        <Button disabled={page === 1} onClick={() => changePage(page - 1)}>上一页</Button>
        <Text>第 {page} 页</Text>
        <Button disabled={!data.hasMore} onClick={() => changePage(page + 1)}>下一页</Button>
      </Space>
    </Space>
  )
}
