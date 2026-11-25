import { useCallback } from 'react'
import { Alert, Button, Card, Collapse, List, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { researchApi } from '@/api/research'
import client from '@/api/client'
import type { TaskKind } from '@/api/careerWorkflow'
import { jobPath } from './paths'
import TaskHistory from './TaskHistory'
import { useCareerQuery } from './useCareerQuery'

const taskTypes: { kind: TaskKind; title: string }[] = [
  { kind: 'TRAINING', title: '备考计划' },
  { kind: 'INTERVIEW', title: '开放题练习' },
  { kind: 'REVIEW', title: '复习建议' },
  { kind: 'PREPARATION', title: '岗位模拟题' },
  { kind: 'DISCOVERY', title: '联网面经' },
]

type Metric = { kind: string; status: string; taskCount: number; recordedSteps: number; stepMilliseconds: number;
  measuredInputs: number; inputTokens: number; outputTokens: number;
  failedSteps?: number; resumedTasks?: number; adaptedPlans?: number }

function TaskMetrics({ jobId }: { jobId?: string }) {
  const load = useCallback(async (signal: AbortSignal) => (await client.get<unknown, { data: Metric[] }>(
    '/career/task-metrics', { params: { jobId }, signal })).data, [jobId])
  const query = useCareerQuery(load)
  if (query.error) return <Alert type="error" message={query.error} action={<Button onClick={query.retry}>重试</Button>} />
  const items = query.data ?? []
  const sum = (key: Exclude<keyof Metric, 'kind' | 'status'>) =>
    items.reduce((total, item) => total + (item[key] ?? 0), 0)
  const stateCount = (state: string) => items.filter((item) => item.status === state).reduce((total, item) => total + item.taskCount, 0)
  return query.data ? <Space wrap>
    <Tag>共 {sum('taskCount')} 项</Tag><Tag color="success">完成 {stateCount('SUCCEEDED')}</Tag>
    <Tag color="error">失败 {stateCount('FAILED')}</Tag><Tag>取消 {stateCount('CANCELLED')}</Tag>
    <Tag>记录 {sum('recordedSteps')} 个执行步骤</Tag>
    {!!sum('failedSteps') && <Tag>失败步骤 {sum('failedSteps')}</Tag>}
    {!!sum('resumedTasks') && <Tag>从检查点继续 {sum('resumedTasks')} 项</Tag>}
    {!!sum('adaptedPlans') && <Tag>根据练习反馈安排新题 {sum('adaptedPlans')} 份</Tag>}
    {!!sum('measuredInputs') && <Tag>已计量 Token · 输入 {sum('inputTokens')} / 输出 {sum('outputTokens')}</Tag>}
    <Button size="small" onClick={query.retry}>刷新</Button>
  </Space> : <Typography.Text type="secondary">正在读取运行统计</Typography.Text>
}

function CompanyResearchRecords({ jobId }: { jobId: string }) {
  const load = useCallback(async () => (await researchApi.list(1, 10, jobId)).data.items, [jobId])
  const { data, error, retry } = useCareerQuery(load)
  return (
    <Card title="最近公司调研" extra={<Link to={jobPath(jobId)}>所有调研报告</Link>}>
      {error ? <Alert type="error" message={error} action={<Button onClick={retry}>重试</Button>} /> :
        <List loading={!data} size="small" dataSource={data} rowKey="id"
          locale={{ emptyText: '暂无调研任务' }} renderItem={(item) => (
            <List.Item actions={[<Link key="report" to={jobPath(jobId, 'research', { report: item.id })}>查看调研</Link>]}>
              <List.Item.Meta title={item.title || item.topic}
                description={item.created_at && new Date(item.created_at).toLocaleString('zh-CN')} />
              {item.status === 'done' ? <Tag color="success">已完成</Tag>
                : item.status === 'failed' ? <Tag color="error">失败</Tag>
                : <Tag color="processing">进行中</Tag>}
            </List.Item>
          )} />}
    </Card>
  )
}

export default function CareerTaskRecords({ jobId, kind }: { jobId?: string; kind: string }) {
  const selected = taskTypes.find((item) => item.kind === kind) ?? taskTypes[0]
  return (
    <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
      {jobId && <CompanyResearchRecords jobId={jobId} />}
      <Collapse size="small" items={[{ key: 'metrics', label: '最近 30 天的运行统计', children: <TaskMetrics key={jobId} jobId={jobId} /> }]} />
      <Space wrap aria-label="备考任务类型">
        {taskTypes.map(({ kind, title }) => kind === selected.kind
          ? <Typography.Text strong key={kind}>{title}</Typography.Text>
          : <Link key={kind} to={jobId ? jobPath(jobId, 'tasks', { kind }) : `/career/tasks?kind=${kind}`}>{title}</Link>)}
      </Space>
      <TaskHistory key={`${jobId}:${selected.kind}`} kind={selected.kind} jobId={jobId} />
    </Space>
  )
}
