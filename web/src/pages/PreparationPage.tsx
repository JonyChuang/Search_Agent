import { Alert, Space, Spin, Tabs, Typography } from 'antd'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { CurrentJobSelect, useCurrentJob } from './career/CurrentJob'
import { jobPath, preparationPath } from './career/paths'
import TaskHistory from './career/TaskHistory'
import ExperienceBankPage from './ExperienceBankPage'
import MockInterviewPage, { InterviewHistory } from './MockInterviewPage'
import PracticePage from './PracticePage'
import TrainingPlanPage from './TrainingPlanPage'
import WorkspaceHero from './career/WorkspaceHero'
import styles from './career/workspace.module.css'

export function LegacyPreparationLink({ page }: { page: 'questions' | 'practice' | 'plan' | 'interviews' }) {
  const [params] = useSearchParams()
  const values = Object.fromEntries(params)
  delete values.tab
  const section = params.get('tab')
  if (page === 'practice' && (section === 'wrong' || section === 'history')) {
    return <Navigate replace to={preparationPath('review', { ...values, section })} />
  }
  const tab = { questions: 'library', practice: params.has('question') ? 'practice' : 'library', plan: 'plan', interviews: 'interview' }[page]
  return <Navigate replace to={preparationPath(tab, values)} />
}

export default function PreparationPage() {
  const [params, setParams] = useSearchParams()
  const { job: currentJob, jobs, loading, error } = useCurrentJob()
  const requestedJobId = params.get('job')
  const job = requestedJobId ? jobs?.find((entry) => entry.id === requestedJobId) : currentJob
  const tab = params.get('tab')
  const active = tab && ['library', 'practice', 'interview', 'review'].includes(tab) ? tab : 'plan'
  const practiceTab = active === 'interview' ? 'interview' : 'practice'
  const scope = job ? { job: job.id } : undefined

  return (
    <div className={styles.workspace}>
      <WorkspaceHero section="面试备考" title="备考中心"
        description="继续当前岗位的训练，或从面经与题库添加下一项练习。" actions={<>
          <small>{requestedJobId && requestedJobId !== currentJob?.id ? '本页备考岗位' : '当前目标岗位'}</small>
          {requestedJobId && requestedJobId !== currentJob?.id && job
            ? <><strong>{job.company} · {job.title}</strong><Link to={preparationPath(active)}>切回当前目标</Link></>
            : <CurrentJobSelect inHero />}
          <Link to={job ? jobPath(job.id) : '/career/jobs'}>{job ? '查看岗位详情' : '管理岗位'}</Link>
        </>} />
      {loading ? <Spin aria-label="正在读取岗位" /> : requestedJobId && !job ? (
        <Alert type="warning" message={error || '链接中的岗位不存在或不可访问。'}
          action={<Link to={preparationPath(active)}>返回当前岗位</Link>} />
      ) : <Tabs className={styles.tabs} activeKey={active === 'interview' ? 'practice' : active} destroyOnHidden
        onChange={(key) => setParams({ tab: key, ...(requestedJobId ? { job: requestedJobId } : {}) })}
        items={[
          { key: 'plan', label: '备考计划', children: <TrainingPlanPage
            key={`${job?.id}:${params.get('document')}:${params.get('source')}:${params.get('question')}`} job={job} /> },
          { key: 'library', label: '面经与题库', children: <ExperienceBankPage key={job?.id} jobId={job?.id} /> },
          { key: 'practice', label: '开始练习', children: <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
            <Space wrap>
              {practiceTab === 'practice' ? <Typography.Text strong>客观题练习</Typography.Text>
                : <Link to={preparationPath('practice', scope)}>客观题练习</Link>}
              {practiceTab === 'interview' ? <Typography.Text strong>模拟面试</Typography.Text>
                : <Link to={preparationPath('interview', scope)}>模拟面试</Link>}
            </Space>
            {practiceTab === 'interview' ? <MockInterviewPage /> : <PracticePage />}
          </Space> },
          { key: 'review', label: '复盘与错题', children: <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
            <PracticePage review key={job?.id} />
            <InterviewHistory jobId={job?.id} />
            <Typography.Title level={4} style={{ margin: 0 }}>计划复习建议</Typography.Title>
            <TaskHistory key={job?.id} kind="REVIEW" jobId={job?.id} />
          </Space> },
        ]} />}
    </div>
  )
}
