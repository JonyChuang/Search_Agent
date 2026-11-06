import { useCallback, useState } from 'react'
import { Alert, Button, Card, Form, Input, Select, Space, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { careerApi } from '@/api/career'
import { careerWorkflow } from '@/api/careerWorkflow'
import { practiceApi } from '@/api/practice'
import { roles } from './career/QuestionCatalog'
import TaskHistory from './career/TaskHistory'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'

const { Paragraph, Text, Title } = Typography

function InterviewForm() {
  const [form] = Form.useForm()
  const [role, setRole] = useState('backend')
  const load = useCallback((signal: AbortSignal) => practiceApi.questions(role, signal), [role])
  const jobs = useCareerQuery(careerApi.jobs.list)
  const questions = useCareerQuery(load)
  const questionId = Form.useWatch('questionId', form)
  const question = questions.data?.find((item) => item.role === role && item.id === questionId)
  const action = useCareerAction()
  const [refresh, setRefresh] = useState(0)

  return (
    <>
      <Card title="开始一轮面试">
        {jobs.error && <Alert type="error" message={jobs.error} action={<Button onClick={jobs.retry}>重试</Button>} />}
        {questions.error && <Alert type="error" message={questions.error} action={<Button onClick={questions.retry}>重试</Button>} />}
        <Form form={form} layout="vertical" onFinish={(values: { jobId: string; answer: string }) => action.run(async () => {
          if (!question) return
          await action.submit('interview', {
            jobId: values.jobId, answer: values.answer.trim(), questionId: question.id, questionVersion: question.version,
          }, careerWorkflow.interview)
          form.resetFields(['answer'])
          setRefresh((n) => n + 1)
        })}>
          <Form.Item name="jobId" label="目标岗位" rules={[{ required: true }]}>
            <Select loading={!jobs.data && !jobs.error} options={jobs.data?.map((job) => ({
              value: job.id, label: `${job.company} · ${job.title}`,
            }))} />
          </Form.Item>
          <Form.Item label="题库方向">
            <Select value={role} options={Object.entries(roles).map(([value, label]) => ({ value, label }))} onChange={(value) => {
              form.resetFields(['questionId', 'answer'])
              questions.setData(undefined)
              setRole(value)
            }} />
          </Form.Item>
          <Form.Item name="questionId" label="面试题" rules={[{ required: true }]}>
            <Select loading={!questions.data && !questions.error} options={questions.data?.map((item) => ({
              value: item.id, label: `${item.topic} · ${item.prompt}`,
            }))} />
          </Form.Item>
          {question && <Paragraph strong>{question.prompt}</Paragraph>}
          <Form.Item name="answer" label="你的回答" rules={[{ required: true, whitespace: true }]}>
            <Input.TextArea rows={5} maxLength={6000} showCount />
          </Form.Item>
          <Space wrap>
            <Button htmlType="submit" type="primary" disabled={!question || !jobs.data?.length} loading={action.saving}>提交并生成复盘</Button>
            <Link to="/career/jobs">管理岗位</Link>
          </Space>
        </Form>
      </Card>
      <Title level={3}>面试记录</Title>
      <TaskHistory key={refresh} kind="INTERVIEW" render={(task) => task.interview && (
        <>
          <Paragraph strong>{task.interview.prompt}</Paragraph>
          <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{task.interview.answer}</Paragraph>
          <Paragraph type="secondary">
            题目版本 {task.request.questionVersion} · 题库评分版本 {task.interview.gradingVersion}
            {task.interview.sourceUrl && <> · <Typography.Link href={task.interview.sourceUrl} target="_blank" rel="noreferrer">题目来源</Typography.Link></>}
          </Paragraph>
        </>
      )} />
    </>
  )
}

export default function MockInterviewPage() {
  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>模拟面试</Title>
        <Text type="secondary">围绕目标岗位完成一道题，用自己的话回答，再查看面试复盘。</Text>
      </div>
      <InterviewForm />
    </Space>
  )
}
