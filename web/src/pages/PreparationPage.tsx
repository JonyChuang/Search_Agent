import { Alert, Button, Space, Spin, Tabs, Typography } from 'antd'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { careerWorkflow, type CareerTask } from '@/api/careerWorkflow'
import { CurrentJobSelect, useCurrentJob } from './career/CurrentJob'
import { interviewPath, jobPath, preparationPath } from './career/paths'
import TaskHistory from './career/TaskHistory'
import ExperienceBankPage from './ExperienceBankPage'
import OpenQuestionPractice, { OpenQuestionHistory } from './OpenQuestionPractice'
import PracticePage from './PracticePage'
import TrainingPlanPage from './TrainingPlanPage'
import WorkspaceHero from './career/WorkspaceHero'
import LearningPractice from './career/LearningPractice'
import JudgeWorkspace from './career/JudgeWorkspace'
import { useCareerAction } from './career/useCareerAction'
import styles from './career/workspace.module.css'

function RevisePlan({ jobId, review }: { jobId: string; review: CareerTask }) {
  const action = useCareerAction()
  const navigate = useNavigate()
  const previousPlanId = review.request.planId
  if (review.status !== 'SUCCEEDED' || !previousPlanId) return null
  return <Button size="small" loading={action.saving} onClick={() => void action.run(async () => {
    const updated = await action.submit('revise-training', { jobId, previousPlanId, reviewTaskId: review.id }, careerWorkflow.training)
    navigate(preparationPath('plan', { job: jobId, plan: updated.id }))
  })}>根据这份建议创建新版计划</Button>
}

export function LegacyPreparationLink({ page }: { page: 'questions' | 'practice' | 'plan' }) {
  const [params] = useSearchParams()
  const values = Object.fromEntries(params)
  delete values.tab
  const section = params.get('tab')
  if (page === 'practice' && (section === 'wrong' || section === 'history')) {
    return <Navigate replace to={preparationPath('review', { ...values, section })} />
  }
  const tab = { questions: 'library', practice: params.has('question') ? 'practice' : 'library', plan: 'plan' }[page]
  return <Navigate replace to={preparationPath(tab, values)} />
}

export default function PreparationPage() {
  const [params, setParams] = useSearchParams()
  const { job: currentJob, jobs, loading, error } = useCurrentJob()
  const requestedJobId = params.get('job')
  const job = requestedJobId ? jobs?.find((entry) => entry.id === requestedJobId) : currentJob
  const tab = params.get('tab')
  const active = tab && ['library', 'practice', 'open', 'review'].includes(tab) ? tab : 'plan'
  if (tab === 'interview') {
    const values = Object.fromEntries(params)
    delete values.tab
    return <Navigate replace to={params.has('question') ? preparationPath('open', values) : interviewPath(values)} />
  }

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
      ) : <Tabs className={styles.tabs} activeKey={active === 'open' ? 'practice' : active} destroyOnHidden
        onChange={(key) => setParams({ tab: key, ...(requestedJobId ? { job: requestedJobId } : {}) })}
        items={[
          { key: 'plan', label: '备考计划', children: <TrainingPlanPage
            key={`${job?.id}:${params.get('document')}:${params.get('source')}:${params.get('question')}:${params.get('plan')}:${params.get('create')}`} job={job} /> },
          { key: 'library', label: '面经与题库', children: <ExperienceBankPage key={job?.id} jobId={job?.id} /> },
          { key: 'practice', label: '开始练习', children: active === 'open' ? <OpenQuestionPractice />
            : params.get('mode') === 'judge' ? <JudgeWorkspace key={job?.id} jobId={job?.id} />
            : <LearningPractice key={job?.id} jobId={job?.id} description={job?.description} /> },
          { key: 'review', label: '复盘与错题', children: <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
            <PracticePage review key={job?.id} />
            <OpenQuestionHistory jobId={job?.id} />
            <Typography.Title level={4} style={{ margin: 0 }}>计划复习建议</Typography.Title>
            <TaskHistory key={job?.id} kind="REVIEW" jobId={job?.id} render={job ? (review) => <RevisePlan jobId={job.id} review={review} /> : undefined} />
          </Space> },
        ]} />}
    </div>
  )
}
