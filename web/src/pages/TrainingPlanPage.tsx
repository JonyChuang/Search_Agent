import { useCallback, useState } from 'react'
import { Alert, Button, Card, Form, Select, Space, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { careerWorkflow } from '@/api/careerWorkflow'
import { useCurrentJob } from './career/CurrentJob'
import { practiceLink, roles } from './career/QuestionCatalog'
import PreparationDocuments from './career/PreparationDocuments'
import JobPreparationMemory from './career/JobPreparationMemory'
import TaskHistory from './career/TaskHistory'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'

const { Paragraph, Title } = Typography

export default function TrainingPlanPage() {
  const { job, jobs, loading } = useCurrentJob()
  const [params] = useSearchParams()
  const loadPreparation = useCallback((signal: AbortSignal) =>
    job ? careerWorkflow.tasks('PREPARATION', 1, signal, job.id) : Promise.resolve(undefined), [job])
  const preparation = useCareerQuery(loadPreparation)
  const latest = preparation.data?.items.find((item) => item.status === 'SUCCEEDED')
  const [trainingRefresh, refreshTraining] = useState(0)
  const [reviewRefresh, refreshReview] = useState(0)
  const linkedDocument = params.get('document')
  const [documentIds, setDocumentIds] = useState<string[]>(linkedDocument && /^[0-9a-f-]{36}$/.test(linkedDocument)
    ? [linkedDocument] : [])
  const [skillId, setSkillId] = useState<string>()
  const training = useCareerAction()
  const review = useCareerAction()

  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>岗位训练计划</Title>
        <Paragraph type="secondary">Agent 根据目标岗位和已确认的经历选题。完成计划里的练习后，可生成复习建议。</Paragraph>
      </div>
      <Card title="创建训练计划">
        {preparation.error && <Alert type="error" message={preparation.error} action={<Button onClick={preparation.retry}>重试</Button>} />}
        <Form layout="vertical" onFinish={(values: { jobId: string; role?: string }) => training.run(async () => {
          const input = job ? { jobId: job.id, preparationId: latest?.id } : values
          await training.submit('training', { ...input, documentIds, skillId }, careerWorkflow.training)
          refreshTraining((n) => n + 1)
        })}>
          {job ? <Paragraph>
            {job.company} · {job.title}。{latest ? '将从相关公开题和最近生成的模拟题中选题。' : '将从相关公开题中选题。'}
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
              disabled={loading || !jobs?.length || (!!job && !preparation.data)}>生成计划</Button>
            <Link to="/career/questions">查看岗位题库</Link>
            <Link to="/career/resume">确认经历</Link>
          </Space>
        </Form>
      </Card>
      {job && <Card size="small"><JobPreparationMemory jobId={job.id} /></Card>}
      <Title level={3}>训练计划</Title>
      <TaskHistory key={trainingRefresh} kind="TRAINING" jobId={job?.id} render={(task) => task.result && (
        <>
          <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{task.result.analysis}</Paragraph>
          <ol>{task.result.steps?.map((step, index) => <li key={index}>{step}</li>)}</ol>
          <ul>{task.result.questions?.map((question) => (
            <li key={question.id}><Link to={question.kind === 'OPEN'
              ? `/career/interviews?job=${task.request.jobId}&question=${question.id}`
              : practiceLink(question.id, question.version, task.request.jobId)}>{question.prompt}</Link> · 版本 {question.version}</li>
          ))}</ul>
          <Button loading={review.saving} onClick={() => review.run(async () => {
            await review.submit('review', { planId: task.id }, careerWorkflow.review)
            refreshReview((n) => n + 1)
          })}>根据练习生成复习建议</Button>
        </>
      )} />
      <Title level={3}>复习建议</Title>
      <TaskHistory key={reviewRefresh} kind="REVIEW" jobId={job?.id} />
    </Space>
  )
}
