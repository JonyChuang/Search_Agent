import { useCallback, useState } from 'react'
import { Alert, Button, Card, Form, Select, Space, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { careerWorkflow } from '@/api/careerWorkflow'
import { useCurrentJob } from './career/CurrentJob'
import { practiceLink, roles } from './career/QuestionCatalog'
import PreparationDocuments from './career/PreparationDocuments'
import TaskHistory from './career/TaskHistory'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'
import { jobPath, preparationPath } from './career/paths'
import type { JobInput } from '@/api/career'

const { Paragraph, Title } = Typography

export default function TrainingPlanPage({ job }: { job?: JobInput & { id: string } }) {
  const { jobs, loading } = useCurrentJob()
  const [params] = useSearchParams()
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

  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <TrainingHistory key={trainingRefresh} jobId={job?.id} />
      <Card title="创建训练计划">
        {preparation.error && <Alert type="error" message={preparation.error} action={<Button onClick={preparation.retry}>重试</Button>} />}
        {source && preparation.data && !latest && <Alert type="warning" message="此岗位无法使用所选模拟题批次。"
          action={<Link to={preparationPath('plan', job ? { job: job.id } : undefined)}>继续使用最近题目</Link>} />}
        <Form layout="vertical" onFinish={(values: { jobId: string; role?: string }) => training.run(async () => {
          const input = job ? { jobId: job.id, preparationId: latest?.id, preferredQuestion } : values
          await training.submit('training', { ...input, documentIds, skillId }, careerWorkflow.training)
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
          <PreparationDocuments value={documentIds} onChange={setDocumentIds} skillId={skillId} onSkillChange={setSkillId} />
          <Space wrap>
            <Button htmlType="submit" type="primary" loading={training.saving}
              disabled={loading || !jobs?.length || (!!job && !preparation.data)
                || (!!source && !latest) || (!!preferredQuestion && !preferred)}>生成计划</Button>
            <Link to={preparationPath('library', job ? { job: job.id } : undefined)}>查看岗位题库</Link>
            <Link to="/career/resume">确认经历</Link>
            {job && <Link to={jobPath(job.id)}>公司调研</Link>}
            {job && <Link to={jobPath(job.id, 'memory')}>备考偏好</Link>}
          </Space>
        </Form>
      </Card>
    </Space>
  )
}

function TrainingHistory({ jobId }: { jobId?: string }) {
  const review = useCareerAction()
  const [, setParams] = useSearchParams()
  return <>
      <Title level={4} style={{ margin: 0 }}>训练计划</Title>
      <TaskHistory kind="TRAINING" jobId={jobId} render={(task) => task.result && (
        <>
          <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{task.result.analysis}</Paragraph>
          <ol>{task.result.steps?.map((step, index) => <li key={index}>{step}</li>)}</ol>
          <ul>{task.result.questions?.map((question) => (
            <li key={question.id}><Link to={question.kind === 'OPEN'
              ? preparationPath('interview', {
                question: question.id,
                ...(task.request.jobId ? { job: task.request.jobId } : {}),
              })
              : practiceLink(question.id, question.version, task.request.jobId)}>{question.prompt}</Link> · 版本 {question.version}</li>
          ))}</ul>
          <Button loading={review.saving} onClick={() => review.run(async () => {
            await review.submit('review', { planId: task.id }, careerWorkflow.review)
            setParams({ tab: 'review', ...(task.request.jobId ? { job: task.request.jobId } : {}) })
          })}>根据练习生成复习建议</Button>
        </>
      )} />
  </>
}
