import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Alert, Button, Card, Empty, Space, Spin, Tag, Typography } from 'antd'
import { careerWorkflow, type CareerTask, type TaskKind } from '@/api/careerWorkflow'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'
import TaskDetails from './TaskDetails'

const { Paragraph, Text } = Typography
const status = {
  QUEUED: { label: '待执行', color: 'default' },
  RUNNING: { label: '运行中', color: 'processing' },
  SUCCEEDED: { label: '已完成', color: 'success' },
  FAILED: { label: '失败', color: 'error' },
}
const trainingStepLabels = {
  FIND_QUESTIONS: '待查题',
  GENERATE_PLAN: '题目已保存 · 待生成计划',
  SAVE_PLAN: '计划草稿已保存 · 待确认结果',
  COMPLETE: '计划已保存',
}

export default function TaskHistory({ kind, jobId, render, renderTask, layout, emptyText = '暂无任务', refresh = 0 }: {
  kind: TaskKind; jobId?: string; render?: (task: CareerTask) => ReactNode
  renderTask?: (task: CareerTask, featured: boolean) => ReactNode
  layout?: (history: ReactNode, items: CareerTask[]) => ReactNode
  emptyText?: string
  refresh?: number
}) {
  const [page, setPage] = useState(1)
  const load = useCallback((signal: AbortSignal) => careerWorkflow.tasks(kind, page, signal, jobId), [kind, page, jobId])
  const { data, error, retry, setData } = useCareerQuery(load)
  const active = data?.items.some((task) => task.status === 'QUEUED' || task.status === 'RUNNING')
  const action = useCareerAction()
  useEffect(() => {
    if (refresh) {
      setPage(1)
      retry()
    }
  }, [refresh, retry])

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

  const featured = data?.items.find((task) => task.status === 'SUCCEEDED' && task.result)
  const history = error ? <Alert type="error" message={error} action={<Button onClick={retry}>重试读取</Button>} />
    : !data ? <Spin />
    : !data.items.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />
    : (
    <Space direction="vertical" style={{ display: 'flex' }}>
      {data.items.map((task) => renderTask && task.status === 'SUCCEEDED' && task.result
        ? <div key={task.id}>{renderTask(task, task.id === featured?.id)}</div> : (
        <Card key={task.id} size="small" title={task.job} extra={<Tag color={status[task.status].color}>{status[task.status].label}</Tag>}>
          <Paragraph type="secondary">
            创建于 {new Date(task.createdAt).toLocaleString()} · 执行次数 {task.generation}
            {task.trainingStep && ` · ${trainingStepLabels[task.trainingStep]}`}
          </Paragraph>
          {task.error && <Alert type="error" message={task.error} action={
            <Button loading={action.saving} onClick={() => action.run(async () => {
              await careerWorkflow.retry(task.id)
              retry()
            })}>重试执行</Button>
          } />}
          {render?.(task)}
          {task.result?.feedback && <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{task.result.feedback}</Paragraph>}
          <TaskDetails task={task} />
        </Card>
      ))}
      {(page > 1 || data.hasMore) && <Space>
        <Button disabled={page === 1} onClick={() => changePage(page - 1)}>上一页</Button>
        <Text>第 {page} 页</Text>
        <Button disabled={!data.hasMore} onClick={() => changePage(page + 1)}>下一页</Button>
      </Space>}
    </Space>
  )
  return layout ? layout(history, data?.items ?? []) : history
}
