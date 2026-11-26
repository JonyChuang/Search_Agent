import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Checkbox, Collapse, DatePicker, Form, InputNumber, Select, Space, Typography } from 'antd'
import type { Dayjs } from 'dayjs'
import { Link, useSearchParams } from 'react-router-dom'
import { careerWorkflow } from '@/api/careerWorkflow'
import { useCurrentJob } from './career/CurrentJob'
import { roles } from './career/QuestionCatalog'
import PreparationDocuments from './career/PreparationDocuments'
import TaskHistory from './career/TaskHistory'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'
import { jobPath, preparationPath, resumeStudioPath } from './career/paths'
import type { JobInput } from '@/api/career'
import TrainingPlanCard from './career/TrainingPlanCard'
import PreparationSidebar, { LatestReview } from './career/PreparationSidebar'
import styles from './career/workspace.module.css'

const { Paragraph } = Typography

interface PlanForm {
  jobId: string
  role?: string
  questionCount?: number | null
  deadline?: Dayjs | null
  prioritySkills?: string[]
  strictOrder?: boolean
  excludeCompleted?: boolean
}

export default function TrainingPlanPage({ job }: { job?: JobInput & { id: string } }) {
  const { jobs, loading } = useCurrentJob()
  const [params] = useSearchParams()
  const planId = params.get('plan') ?? undefined
  const sourceId = params.get('source')
  const source = sourceId && /^[0-9a-f-]{36}$/.test(sourceId) ? sourceId : undefined
  const loadPreparation = useCallback((signal: AbortSignal) =>
    job ? Promise.all([
      careerWorkflow.tasks('PREPARATION', 1, signal, job.id),
      source ? careerWorkflow.task(source, signal) : undefined,
    ]) : Promise.resolve(undefined), [job, source])
  const preparation = useCareerQuery(loadPreparation)
  const linked = preparation.data?.[1]
  const latest = source ? linked?.kind === 'PREPARATION' && linked.status === 'SUCCEEDED' && linked.request.jobId === job?.id
    ? linked : undefined : preparation.data?.[0].items.find((item) => item.status === 'SUCCEEDED')
  const preferredQuestion = source ? params.get('question') ?? undefined : undefined
  const preferred = latest?.result?.openQuestions?.find((_, index) => `${source}-${index}` === preferredQuestion)
  const [trainingRefresh, refreshTraining] = useState(0)
  const linkedDocument = params.get('document')
  const [documentIds, setDocumentIds] = useState<string[]>(linkedDocument && /^[0-9a-f-]{36}$/.test(linkedDocument)
    ? [linkedDocument] : [])
  const [skillId, setSkillId] = useState<string>()
  const training = useCareerAction()
  const fromInterview = params.get('create') === '1'
  const restart = params.get('restart')
  const showCreateFirst = Boolean(linkedDocument || source || fromInterview || restart)
  const [createOpen, setCreateOpen] = useState(showCreateFirst)
  useEffect(() => { if (restart) setCreateOpen(true) }, [restart])

  const createPanel = <Collapse activeKey={createOpen ? ['create'] : []} onChange={(keys) => setCreateOpen(keys.includes('create'))}
    items={[{ key: 'create', label: '创建训练计划', children: <>
        {preparation.error && <Alert type="error" message={preparation.error} action={<Button onClick={preparation.retry}>重试</Button>} />}
        {source && preparation.data && !latest && <Alert type="warning" message="此岗位无法使用所选模拟题批次。"
          action={<Link to={preparationPath('plan', job ? { job: job.id } : undefined)}>继续使用最近题目</Link>} />}
        {fromInterview && <Alert type="info" showIcon message="新计划会参考本岗位近期的多轮面试点评。" />}
        <Form layout="vertical" onFinish={(values: PlanForm) => training.run(async () => {
          const input = job ? { jobId: job.id, preparationId: latest?.id, preferredQuestion }
            : { jobId: values.jobId, role: values.role }
          const { questionCount, deadline, prioritySkills, excludeCompleted, strictOrder } = values
          const requirements = questionCount || deadline || prioritySkills?.length || excludeCompleted ? {
            questionCount: questionCount ?? undefined,
            deadline: deadline?.format('YYYY-MM-DD'),
            prioritySkills: prioritySkills?.length ? prioritySkills : undefined,
            orderMode: strictOrder && prioritySkills?.length ? ('STRICT_PHASE_ORDER' as const) : undefined,
            excludeCompleted: excludeCompleted || undefined,
            timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          } : undefined
          const restartTaskId = restart && /^[0-9a-f-]{36}$/.test(restart) ? restart : undefined
          await training.submit('training', { ...input, documentIds, skillId, requirements, restartTaskId }, careerWorkflow.training)
          setCreateOpen(false)
          refreshTraining((n) => n + 1)
        })}>
          {preferred && <Alert type="info" message="本次计划将包含所选题目" description={preferred.prompt} style={{ marginBottom: 12 }} />}
          {preferredQuestion && !preferred && latest && <Alert type="warning" message="所选题目已不可用。"
            action={<Link to={preparationPath('library', job ? { job: job.id, source: 'preparation' } : undefined)}>返回模拟题</Link>} />}
          {job ? <Paragraph>
            {job.company} · {job.title}。{latest
              ? source ? '将从相关公开题和所选批次的模拟题中选题。' : '将从相关公开题和最近生成的模拟题中选题。'
              : '将从相关公开题中选题。'}
          </Paragraph> : <>
            <Form.Item name="jobId" label="本次训练岗位" rules={[{ required: true }]}>
              <Select loading={loading} options={jobs?.map((item) => ({
                value: item.id, label: `${item.company} · ${item.title}`,
              }))} />
            </Form.Item>
            <Form.Item name="role" label="题库方向" rules={[{ required: true }]}>
              <Select options={Object.entries(roles).map(([value, label]) => ({ value, label }))} />
            </Form.Item>
          </>}
          <Space wrap align="start">
            <Form.Item name="questionCount" label="题目数量">
              <InputNumber min={1} max={8} precision={0} placeholder="自动安排" />
            </Form.Item>
            <Form.Item name="deadline" label="截止日期">
              <DatePicker placeholder="选择日期" />
            </Form.Item>
          </Space>
          <Form.Item name="prioritySkills" label="优先复习技能">
            <Select mode="tags" maxCount={8} tokenSeparators={[',', '，']} placeholder="按复习顺序输入技能并按回车" />
          </Form.Item>
          <Form.Item name="strictOrder" valuePropName="checked">
            <Checkbox>每项优先技能学完后再进入下一项</Checkbox>
          </Form.Item>
          <Form.Item name="excludeCompleted" valuePropName="checked">
            <Checkbox>排除已完成的题目</Checkbox>
          </Form.Item>
          <PreparationDocuments value={documentIds} onChange={setDocumentIds} skillId={skillId} onSkillChange={setSkillId} />
          <Space wrap>
            <Button htmlType="submit" type="primary" loading={training.saving}
              disabled={loading || !jobs?.length || (!!job && !preparation.data)
                || (!!source && !latest) || (!!preferredQuestion && !preferred)}>生成计划</Button>
            <Link to={preparationPath('library', job ? { job: job.id } : undefined)}>查看岗位题库</Link>
            <Link to={resumeStudioPath}>确认经历</Link>
            {job && <Link to={jobPath(job.id)}>公司调研</Link>}
            {job && <Link to={jobPath(job.id, 'memory')}>备考偏好</Link>}
          </Space>
        </Form>
    </> }]} />

  return (
    <TaskHistory refresh={trainingRefresh} kind="TRAINING" jobId={job?.id} taskId={planId}
      emptyText="还没有训练计划。可创建计划，或先从面经与题库选题。"
      renderTask={(task, featured) => featured ? <TrainingPlanCard task={task} /> : <Collapse size="small" ghost items={[{
        key: task.id,
        label: `历史计划 · ${new Date(task.createdAt).toLocaleString('zh-CN')}`,
        children: <TrainingPlanCard task={task} />,
      }]} />}
      layout={(history, tasks) => <div className={styles.grid}>
        <div className={styles.stack}>
          {planId && <Link to={preparationPath('plan', job ? { job: job.id } : undefined)}>查看此岗位的全部备考计划</Link>}
          {showCreateFirst && createPanel}
          {history}
          <LatestReview jobId={job?.id} />
          {!showCreateFirst && !planId && createPanel}
        </div>
        <PreparationSidebar jobId={job?.id} plan={tasks.find((task) => task.status === 'SUCCEEDED')} />
      </div>} />
  )
}
