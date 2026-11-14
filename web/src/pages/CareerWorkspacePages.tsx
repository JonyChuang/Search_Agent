import { Card, Space, Tabs, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import GraphPage from './GraphPage'
import MemoryPage from './MemoryPage'
import TracesPage from './TracesPage'
import CareerTaskRecords from './career/CareerTaskRecords'
import { useCurrentJob } from './career/CurrentJob'
import { jobPath } from './career/paths'

const { Title, Paragraph } = Typography

export function CareerMemoryPage() {
  const [params, setParams] = useSearchParams()
  const { job } = useCurrentJob()
  return (
    <Space direction="vertical" size="middle" style={{ display: 'flex', maxWidth: 1100, marginInline: 'auto' }}>
      <div>
        <Title level={2} style={{ marginBottom: 6 }}>求职记忆</Title>
        <Paragraph type="secondary">回查对话中形成的记忆、来源与实体关系。</Paragraph>
        {job && <Link to={jobPath(job.id, 'memory')}>编辑当前岗位的备考偏好</Link>}
      </div>
      <Tabs activeKey={params.get('tab') === 'graph' ? 'graph' : 'memory'} destroyOnHidden
        onChange={(tab) => setParams({ tab })} items={[
          { key: 'memory', label: '我的记忆', children: <MemoryPage embedded /> },
          { key: 'graph', label: '关系图谱', children: <GraphPage /> },
        ]} />
    </Space>
  )
}

export function CareerTasksPage() {
  const [params, setParams] = useSearchParams()
  const { job } = useCurrentJob()
  const tab = params.has('task_id') || params.has('trace_id') || params.get('tab') === 'traces' ? 'traces' : 'tasks'
  return (
    <Space direction="vertical" size="middle" style={{ display: 'flex', maxWidth: 1100, marginInline: 'auto' }}>
      <div>
        <Title level={2} style={{ marginBottom: 6 }}>任务记录</Title>
        {job && <Link to={jobPath(job.id, 'tasks')}>只看当前岗位的任务</Link>}
      </div>
      <Tabs activeKey={tab} destroyOnHidden onChange={(key) => setParams({ tab: key })} items={[
        { key: 'tasks', label: '备考任务', children: <Card>
          <CareerTaskRecords kind={params.get('kind') ?? ''} />
        </Card> },
        { key: 'traces', label: '执行轨迹', children: <TracesPage embedded /> },
      ]} />
    </Space>
  )
}
