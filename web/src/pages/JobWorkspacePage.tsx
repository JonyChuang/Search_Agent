import { Alert, Button, Card, Descriptions, Spin, Tabs, Typography } from 'antd'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useState } from 'react'
import ResearchPage from './ResearchPage'
import { useCurrentJob } from './career/CurrentJob'
import CareerTaskRecords from './career/CareerTaskRecords'
import JobPreparationMemory from './career/JobPreparationMemory'
import { jobPath, preparationPath } from './career/paths'
import WorkspaceHero from './career/WorkspaceHero'
import JobResearchSidebar from './career/JobResearchSidebar'
import styles from './career/workspace.module.css'

const { Paragraph } = Typography

export default function JobWorkspacePage() {
  const { jobId } = useParams()
  const [params, setParams] = useSearchParams()
  const { jobs, loading, error, reload, job: activeJob, select, saving } = useCurrentJob()
  const job = jobs?.find((entry) => entry.id === jobId)
  const requested = params.get('tab')
  const tab = requested === 'memory' || requested === 'tasks' || requested === 'details' ? requested : 'research'
  const reportId = params.get('report')
  const [historyRevision, setHistoryRevision] = useState(0)

  if (loading) return <Spin aria-label="正在读取岗位" />
  if (!job) return <Alert type={error ? 'error' : 'warning'} message={error || '岗位不存在或不可访问。'}
    action={error ? <Button onClick={reload}>重试</Button> : <Link to="/career/jobs">返回岗位与公司</Link>} />

  return (
    <div className={styles.workspace}>
      <WorkspaceHero section={<Link to="/career/jobs">岗位与公司</Link>} title={job.title}
        description={[job.company, job.location].filter(Boolean).join(' · ')} actions={<>
          <strong>{activeJob?.id === job.id ? '当前目标岗位' : '已保存岗位'}</strong>
          <Link to={preparationPath('plan', { job: job.id })}>打开备考中心</Link>
          {activeJob?.id !== job.id && <Button size="small" loading={saving} onClick={() => select(job.id)}>设为当前目标</Button>}
        </>} />
      <Tabs className={styles.tabs} activeKey={tab} onChange={(key) => setParams({
        tab: key, ...(reportId ? { report: reportId } : {}),
      })} destroyOnHidden items={[
        { key: 'research', label: '公司调研', children: <div className={styles.grid}>
          <ResearchPage key={job.id} jobId={job.id} onHistoryChange={() => setHistoryRevision((previous) => previous + 1)} />
          <JobResearchSidebar key={`${job.id}:${historyRevision}`} jobId={job.id} />
        </div> },
        { key: 'details', label: '招聘信息', children: <Card>
          <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{job.description}</Paragraph>
          <Descriptions column={1} items={[
            { key: 'source', label: '招聘来源', children: job.sourceUrl
              ? <Typography.Link href={job.sourceUrl} target="_blank" rel="noopener noreferrer">{job.sourceName}</Typography.Link>
              : job.sourceName },
            { key: 'date', label: '记录日期', children: job.sourcedOn },
            ...(job.skills ? [{ key: 'skills', label: '技能要求', children: job.skills }] : []),
          ]} />
        </Card> },
        { key: 'memory', label: '求职记忆', children: <Card title="岗位备考偏好"
          extra={<Link to="/career/memory?tab=graph">查看全局记忆与关系图谱</Link>}>
          <JobPreparationMemory jobId={job.id} />
        </Card> },
        { key: 'tasks', label: '任务记录', children: <CareerTaskRecords jobId={job.id} kind={params.get('kind') ?? ''} /> },
      ]} />
      {tab === 'tasks' && <Link to={jobPath(job.id)}>返回公司调研</Link>}
    </div>
  )
}
