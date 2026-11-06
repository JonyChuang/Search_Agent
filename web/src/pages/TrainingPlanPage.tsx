import { useState } from 'react'
import { Alert, Button, Card, Form, Select, Space, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { careerApi } from '@/api/career'
import { careerWorkflow } from '@/api/careerWorkflow'
import { practiceLink, roles } from './career/QuestionCatalog'
import TaskHistory from './career/TaskHistory'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'

const { Paragraph, Title } = Typography

export default function TrainingPlanPage() {
  const jobs = useCareerQuery(careerApi.jobs.list)
  const [trainingRefresh, refreshTraining] = useState(0)
  const [reviewRefresh, refreshReview] = useState(0)
  const training = useCareerAction()
  const review = useCareerAction()

  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>岗位训练计划</Title>
        <Paragraph type="secondary">Agent 根据目标岗位和已确认的经历选题。完成计划里的练习后，可生成复习建议。</Paragraph>
      </div>
      <Card title="创建训练计划">
        {jobs.error && <Alert type="error" message={jobs.error} action={<Button onClick={jobs.retry}>重试</Button>} />}
        <Form layout="vertical" onFinish={(values: { jobId: string; role: string }) => training.run(async () => {
          await training.submit('training', values, careerWorkflow.training)
          refreshTraining((n) => n + 1)
        })}>
          <Form.Item name="jobId" label="目标岗位" rules={[{ required: true }]}>
            <Select loading={!jobs.data && !jobs.error} options={jobs.data?.map((job) => ({
              value: job.id, label: `${job.company} · ${job.title}`,
            }))} />
          </Form.Item>
          <Form.Item name="role" label="题库方向" rules={[{ required: true }]}>
            <Select options={Object.entries(roles).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Space wrap>
            <Button htmlType="submit" type="primary" loading={training.saving} disabled={!jobs.data?.length}>生成计划</Button>
            <Link to="/career/jobs">管理岗位</Link>
            <Link to="/career/resume">确认经历</Link>
          </Space>
        </Form>
      </Card>
      <Title level={3}>训练计划</Title>
      <TaskHistory key={trainingRefresh} kind="TRAINING" render={(task) => task.result && (
        <>
          <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{task.result.analysis}</Paragraph>
          <ol>{task.result.steps?.map((step, index) => <li key={index}>{step}</li>)}</ol>
          <ul>{task.result.questions?.map((question) => (
            <li key={question.id}><Link to={practiceLink(question.id, question.version)}>{question.prompt}</Link> · 版本 {question.version}</li>
          ))}</ul>
          <Button loading={review.saving} onClick={() => review.run(async () => {
            await review.submit('review', { planId: task.id }, careerWorkflow.review)
            refreshReview((n) => n + 1)
          })}>根据练习生成复习建议</Button>
        </>
      )} />
      <Title level={3}>复习建议</Title>
      <TaskHistory key={reviewRefresh} kind="REVIEW" />
    </Space>
  )
}
