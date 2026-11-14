import { useCallback } from 'react'
import { Alert, Button, Card, List, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { researchApi } from '@/api/research'
import type { TaskKind } from '@/api/careerWorkflow'
import { jobPath } from './paths'
import TaskHistory from './TaskHistory'
import { useCareerQuery } from './useCareerQuery'

const taskTypes: { kind: TaskKind; title: string }[] = [
  { kind: 'TRAINING', title: '备考计划' },
  { kind: 'INTERVIEW', title: '模拟面试' },
  { kind: 'REVIEW', title: '复习建议' },
  { kind: 'PREPARATION', title: '岗位模拟题' },
  { kind: 'DISCOVERY', title: '联网面经' },
]

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
      <Space wrap aria-label="备考任务类型">
        {taskTypes.map(({ kind, title }) => kind === selected.kind
          ? <Typography.Text strong key={kind}>{title}</Typography.Text>
          : <Link key={kind} to={jobId ? jobPath(jobId, 'tasks', { kind }) : `/career/tasks?kind=${kind}`}>{title}</Link>)}
      </Space>
      <TaskHistory key={`${jobId}:${selected.kind}`} kind={selected.kind} jobId={jobId} />
    </Space>
  )
}
