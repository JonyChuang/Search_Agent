import { useCallback, useState } from 'react'
import { Alert, Button, Card, Form, Input, Select, Space, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { careerWorkflow, type CareerTask } from '@/api/careerWorkflow'
import { practiceApi } from '@/api/practice'
import { useCurrentJob } from './career/CurrentJob'
import { roles } from './career/QuestionCatalog'
import TaskHistory from './career/TaskHistory'
import PreparationDocuments from './career/PreparationDocuments'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'
import { preparationPath } from './career/paths'

const { Paragraph, Text, Title } = Typography

function InterviewForm({ jobId, initialQuestion }: { jobId?: string; initialQuestion?: string }) {
  const [, setSearchParams] = useSearchParams()
  const library = preparationPath('library', jobId ? { job: jobId, source: 'preparation' } : undefined)
  const [form] = Form.useForm()
  const [role, setRole] = useState('backend')
  const load = useCallback(async (signal: AbortSignal) => {
    if (!jobId) return (await practiceApi.questions(role, signal)).map((item) => ({ ...item, source: '公开题库' }))
    const preparationId = initialQuestion?.match(/^([0-9a-f-]{36})-[0-4]$/)?.[1]
    const [recommendations, recent, linked] = await Promise.all([
      practiceApi.recommendations(jobId, signal),
      careerWorkflow.tasks('PREPARATION', 1, signal, jobId),
      preparationId ? careerWorkflow.task(preparationId, signal) : undefined,
    ])
    const preparations = linked && !recent.items.some((item) => item.id === linked.id) ? [linked, ...recent.items] : recent.items
    const simulated = preparations.filter((item) => item.kind === 'PREPARATION' && item.request.jobId === jobId)
      .flatMap((item) => item.result?.openQuestions?.map((question, index) => ({
        ...question, id: `${item.id}-${index}`, version: 1, source: 'AI 模拟',
      })) ?? [])
    return [...simulated, ...recommendations.questions.map((item) => ({ ...item, source: '公开题库' }))]
  }, [jobId, role, initialQuestion])
  const { jobs, loading } = useCurrentJob()
  const questions = useCareerQuery(load)
  const questionId = Form.useWatch('questionId', form)
  const question = questions.data?.find((item) => item.id === questionId)
  const action = useCareerAction()
  const [documentIds, setDocumentIds] = useState<string[]>([])
  const [skillId, setSkillId] = useState<string>()

  return (
    <>
      <Card title="开放题练习">
        {questions.error && <Alert type="error" message={questions.error} action={<Button onClick={questions.retry}>重试</Button>} />}
        {questions.data?.length === 0 && <Alert type="info" message="当前岗位暂无可作答的题目"
          action={<Link to={library}>生成岗位模拟题</Link>} />}
        <Form form={form} layout="vertical" initialValues={{ questionId: initialQuestion }} onFinish={(values: { jobId: string; answer: string }) => action.run(async () => {
          if (!question) return
          await action.submit('interview', {
            jobId: jobId ?? values.jobId, answer: values.answer.trim(), questionId: question.id, questionVersion: question.version,
            documentIds,
            skillId,
          }, careerWorkflow.interview)
          form.resetFields(['answer'])
          setSearchParams({ tab: 'review', job: jobId ?? values.jobId })
        })}>
          {!jobId && <>
            <Form.Item name="jobId" label="本次面试岗位" rules={[{ required: true }]}>
              <Select loading={loading} options={jobs?.map((job) => ({ value: job.id, label: `${job.company} · ${job.title}` }))} />
            </Form.Item>
            <Form.Item label="公开题库方向">
              <Select value={role} options={Object.entries(roles).map(([value, label]) => ({ value, label }))} onChange={(value) => {
                form.resetFields(['questionId', 'answer'])
                questions.setData(undefined)
                setRole(value)
              }} />
            </Form.Item>
          </>}
          <Form.Item name="questionId" label="面试题" rules={[{ required: true }]}>
            <Select loading={!questions.data && !questions.error} options={questions.data?.map((item) => ({
              value: item.id, label: `${jobId ? `${item.source} · ` : ''}${item.topic} · ${item.prompt}`,
            }))} />
          </Form.Item>
          {question && <Paragraph strong>{question.prompt}</Paragraph>}
          <Form.Item name="answer" label="你的回答" rules={[{ required: true, whitespace: true }]}>
            <Input.TextArea rows={5} maxLength={6000} showCount />
          </Form.Item>
          <PreparationDocuments value={documentIds} onChange={setDocumentIds} skillId={skillId} onSkillChange={setSkillId} />
          <Space wrap>
            <Button htmlType="submit" type="primary" disabled={!question || !jobs?.length} loading={action.saving}>提交并生成复盘</Button>
            <Link to={library}>查看岗位题库</Link>
          </Space>
        </Form>
      </Card>
    </>
  )
}

export function OpenReviewDetails(task: CareerTask) {
  const detail = task.interview
  if (!detail) return null
  return <>
    <Paragraph strong style={{ overflowWrap: 'anywhere' }}>{detail.prompt}</Paragraph>
    <Paragraph type="secondary">
      题目版本 {task.request.questionVersion} · 评分版本 {detail.gradingVersion}
      {detail.sourceUrl && <> · <Typography.Link href={detail.sourceUrl} target="_blank" rel="noreferrer">题目来源</Typography.Link></>}
    </Paragraph>
    <Text strong>你的回答</Text>
    <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{detail.answer}</Paragraph>
    {!!detail.rubric?.length && <details><summary>评分要点</summary><ul>{detail.rubric.map((point, index) => <li key={index}>{point}</li>)}</ul></details>}
    {detail.referenceAnswer && <details><summary>参考思路</summary>
      <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{detail.referenceAnswer}</Paragraph></details>}
  </>
}

export function OpenQuestionHistory({ jobId }: { jobId?: string }) {
  return (
    <>
      <Title level={4} style={{ margin: 0 }}>开放题练习复盘</Title>
      <TaskHistory key={jobId} kind="INTERVIEW" jobId={jobId} emptyText="暂无开放题作答记录"
        collapseLabel={(task) => <>
          <Paragraph strong ellipsis={{ rows: 2 }} style={{ margin: 0, overflowWrap: 'anywhere' }}>
            {task.interview?.prompt || '开放题作答'}
          </Paragraph>
          <Text type="secondary">{new Date(task.createdAt).toLocaleString('zh-CN')}</Text>
        </>} render={OpenReviewDetails} />
    </>
  )
}

export default function OpenQuestionPractice() {
  const [params] = useSearchParams()
  const { job } = useCurrentJob()
  const linkedJob = params.get('job') ?? undefined
  const jobId = linkedJob ?? job?.id
  const initialQuestion = params.get('question') ?? undefined
  return (
    <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
      <Text type="secondary">选择一道开放题作答，提交后查看点评。</Text>
      <InterviewForm key={`${jobId}:${initialQuestion}`} jobId={jobId} initialQuestion={initialQuestion} />
    </Space>
  )
}
