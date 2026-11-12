import { useCallback, useState } from 'react'
import { Alert, Button, Card, Form, Input, Select, Space, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { careerWorkflow } from '@/api/careerWorkflow'
import { practiceApi } from '@/api/practice'
import { useCurrentJob } from './career/CurrentJob'
import { roles } from './career/QuestionCatalog'
import TaskHistory from './career/TaskHistory'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'

const { Paragraph, Text, Title } = Typography

function InterviewForm({ jobId, initialQuestion }: { jobId?: string; initialQuestion?: string }) {
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
  const [refresh, setRefresh] = useState(0)

  return (
    <>
      <Card title="开始一轮面试">
        {questions.error && <Alert type="error" message={questions.error} action={<Button onClick={questions.retry}>重试</Button>} />}
        {questions.data?.length === 0 && <Alert type="info" message="当前岗位暂无可作答的题目"
          action={<Link to="/career/questions">生成岗位模拟题</Link>} />}
        <Form form={form} layout="vertical" initialValues={{ questionId: initialQuestion }} onFinish={(values: { jobId: string; answer: string }) => action.run(async () => {
          if (!question) return
          await action.submit('interview', {
            jobId: jobId ?? values.jobId, answer: values.answer.trim(), questionId: question.id, questionVersion: question.version,
          }, careerWorkflow.interview)
          form.resetFields(['answer'])
          setRefresh((n) => n + 1)
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
          <Space wrap>
            <Button htmlType="submit" type="primary" disabled={!question || !jobs?.length} loading={action.saving}>提交并生成复盘</Button>
            <Link to="/career/questions">查看岗位题库</Link>
          </Space>
        </Form>
      </Card>
      <Title level={3}>面试记录</Title>
      <TaskHistory key={refresh} kind="INTERVIEW" jobId={jobId} render={(task) => task.interview && (
        <>
          <Paragraph strong>{task.interview.prompt}</Paragraph>
          <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{task.interview.answer}</Paragraph>
          <Paragraph type="secondary">
            题目版本 {task.request.questionVersion} · 评分版本 {task.interview.gradingVersion}
            {task.interview.sourceUrl && <> · <Typography.Link href={task.interview.sourceUrl} target="_blank" rel="noreferrer">题目来源</Typography.Link></>}
          </Paragraph>
        </>
      )} />
    </>
  )
}

export default function MockInterviewPage() {
  const [params] = useSearchParams()
  const { job } = useCurrentJob()
  const linkedJob = params.get('job') ?? undefined
  const jobId = job?.id ?? linkedJob
  const initialQuestion = linkedJob === jobId ? params.get('question') ?? undefined : undefined
  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>模拟面试</Title>
        <Text type="secondary">围绕目标岗位完成一道题，用自己的话回答，再查看面试复盘。</Text>
      </div>
      <InterviewForm key={`${jobId}:${initialQuestion}`} jobId={jobId} initialQuestion={initialQuestion} />
    </Space>
  )
}
