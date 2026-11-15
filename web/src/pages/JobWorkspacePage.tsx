import { Alert, Button, Card, Descriptions, Spin, Tabs, Typography } from 'antd'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useState } from 'react'
import ResearchPage from './ResearchPage'
import { CurrentJobSelect, useCurrentJob } from './career/CurrentJob'
import CareerTaskRecords from './career/CareerTaskRecords'
import JobPreparationMemory from './career/JobPreparationMemory'
import { jobPath, preparationPath } from './career/paths'
import WorkspaceHero from './career/WorkspaceHero'
import JobResearchSidebar from './career/JobResearchSidebar'
import JobManagement from './career/JobManagement'
import styles from './career/workspace.module.css'

const { Paragraph } = Typography

export default function JobWorkspacePage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { jobs, loading, error, reload, job: activeJob, select, saving } = useCurrentJob()
  const job = jobId ? jobs?.find((entry) => entry.id === jobId) : activeJob
  const requested = params.get('tab')
  const tab = requested && ['management', 'research', 'details', 'memory', 'tasks'].includes(requested)
    ? requested
    : jobId ? 'research' : 'management'
  const [historyRevision, setHistoryRevision] = useState(0)

  function changeTab(key: string) {
    const next = new URLSearchParams(params)
    next.set('tab', key)
    if (!jobId && job && key !== 'management') navigate(jobPath(job.id, key, Object.fromEntries(next)))
    else setParams(next)
  }

  const scopedJob = tab !== 'management' ? job : undefined
  const jobRequired = loading ? <Spin aria-label="正在读取岗位" /> : <Alert
    showIcon
    type={error ? 'error' : 'info'}
    message={error || (jobId ? '岗位不存在或不可访问。' : '请先在岗位管理中选择一个岗位。')}
    action={error ? <Button onClick={reload}>重试</Button> : <Link to="/career/jobs">打开岗位管理</Link>}
  />

  return (
    <div className={styles.workspace}>
      {scopedJob ? <WorkspaceHero section={<Link to="/career/jobs">岗位与公司</Link>} title={scopedJob.title}
        description={[scopedJob.company, scopedJob.location].filter(Boolean).join(' · ')} actions={<>
          <strong>{activeJob?.id === scopedJob.id ? '当前目标岗位' : '已保存岗位'}</strong>
          <Link to={preparationPath('plan', { job: scopedJob.id })}>打开备考中心</Link>
          {activeJob?.id !== scopedJob.id
            && <Button size="small" loading={saving} onClick={() => select(scopedJob.id)}>设为当前目标</Button>}
        </>} /> : <WorkspaceHero section="求职准备" title="岗位与公司"
        description="管理已保存的招聘信息，围绕具体岗位发起公司调研。" actions={<>
          <small>当前目标岗位</small>
          <CurrentJobSelect inHero />
        </>} />}
      <Tabs className={styles.tabs} activeKey={tab} onChange={changeTab} destroyOnHidden items={[
        { key: 'management', label: '岗位管理', children: <JobManagement /> },
        { key: 'research', label: '公司调研', children: job ? <div className={styles.grid}>
          <ResearchPage key={job.id} jobId={job.id} onHistoryChange={() => setHistoryRevision((previous) => previous + 1)} />
          <JobResearchSidebar key={`${job.id}:${historyRevision}`} jobId={job.id} />
        </div> : jobRequired },
        { key: 'details', label: '招聘信息', children: job ? <Card>
          <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{job.description}</Paragraph>
          <Descriptions column={1} items={[
            { key: 'source', label: '招聘来源', children: job.sourceUrl
              ? <Typography.Link href={job.sourceUrl} target="_blank" rel="noopener noreferrer">{job.sourceName}</Typography.Link>
              : job.sourceName },
            { key: 'date', label: '记录日期', children: job.sourcedOn },
            ...(job.skills ? [{ key: 'skills', label: '技能要求', children: job.skills }] : []),
          ]} />
        </Card> : jobRequired },
        { key: 'memory', label: '求职记忆', children: job ? <Card title="岗位备考偏好"
          extra={<Link to="/career/memory?tab=graph">查看全局记忆与关系图谱</Link>}>
          <JobPreparationMemory jobId={job.id} />
        </Card> : jobRequired },
        { key: 'tasks', label: '任务记录', children: job
          ? <CareerTaskRecords jobId={job.id} kind={params.get('kind') ?? ''} /> : jobRequired },
      ]} />
      {tab === 'tasks' && job && <Link to={jobPath(job.id)}>返回公司调研</Link>}
    </div>
  )
}
