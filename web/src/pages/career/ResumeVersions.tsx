import { useCallback, useState } from 'react'
import { createPortal } from 'react-dom'
import { Alert, Button, Card, Empty, Form, Select, Space, Spin, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { careerApi } from '@/api/career'
import { careerWorkflow, type Resume } from '@/api/careerWorkflow'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'
import './resume-print.css'

const { Paragraph, Text } = Typography

function ResumeContent({ resume, print = false }: { resume: Resume; print?: boolean }) {
  return (
    <article className={print ? 'career-print-sheet' : 'career-resume-preview'}>
      <h2>岗位简历草稿</h2>
      <p>{resume.company} · {resume.jobTitle}</p>
      {resume.evidence.map((item) => (
        <section key={item.id}>
          <h3>{item.title}</h3>
          <p>{[item.organization, [item.startMonth, item.endMonth].filter(Boolean).join(' 至 ')].filter(Boolean).join(' · ')}</p>
          <p>{item.description}</p>
          {!print && item.sourceNote && <Text type="secondary">事实依据 · {item.sourceNote}</Text>}
        </section>
      ))}
    </article>
  )
}

export default function ResumeVersions({ experienceRevision }: { experienceRevision: number }) {
  const jobs = useCareerQuery(careerApi.jobs.list)
  const loadExperiences = useCallback((signal: AbortSignal) => careerApi.experiences.list(signal), [experienceRevision])
  const experiences = useCareerQuery(loadExperiences)
  const resumes = useCareerQuery(careerWorkflow.resumes)
  const [form] = Form.useForm()
  const [selectedId, setSelectedId] = useState<string>()
  const jobId = Form.useWatch('jobId', form)
  const job = jobs.data?.find((item) => item.id === jobId)
  const confirmed = experiences.data?.filter((item) => item.confirmed)
  const selected = resumes.data?.find((item) => item.id === selectedId) ?? resumes.data?.[0]
  const action = useCareerAction()

  return (
    <Card title="岗位简历版本" extra={<Link to="/career/jobs">管理岗位</Link>}>
      <Space direction="vertical" style={{ display: 'flex' }}>
        <Paragraph type="secondary">对照岗位描述，选择相关的已确认经历。按选择顺序生成草稿，保存后可以打印为 PDF。</Paragraph>
        {[jobs, experiences, resumes].filter((query) => query.error).map((query, index) => (
          <Alert key={index} type="error" message={query.error} action={<Button onClick={query.retry}>重试</Button>} />
        ))}
        <Form form={form} layout="vertical" onFinish={(values: { jobId: string; experienceIds: string[] }) => action.run(async () => {
          const result = await action.submit('resume', values, careerWorkflow.generate)
          setSelectedId(result.id)
          resumes.retry()
        })}>
          <Form.Item name="jobId" label="定制岗位" rules={[{ required: true }]}>
            <Select options={jobs.data?.map((item) => ({ value: item.id, label: `${item.company} · ${item.title}` }))} />
          </Form.Item>
          {job && (
            <details style={{ marginBottom: 12 }}>
              <summary>查看岗位描述</summary>
              <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{job.description}</Paragraph>
            </details>
          )}
          <Form.Item name="experienceIds" label="已确认经历" rules={[{ required: true, type: 'array', min: 1, max: 12 }]}>
            <Select mode="multiple" maxCount={12} options={confirmed?.map((item) => ({ value: item.id, label: item.title }))} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={action.saving} disabled={!jobs.data?.length || !confirmed?.length}>
            生成并保存版本
          </Button>
          {experiences.data && !confirmed?.length && <Paragraph type="secondary">请先在本页经历列表确认相关事实。</Paragraph>}
        </Form>
        {!resumes.data && !resumes.error && <Spin />}
        {resumes.data?.length === 0 && <Empty description="暂无简历版本" />}
        {selected && (
          <>
            <Space wrap>
              <Select aria-label="查看简历版本" value={selected.id} onChange={setSelectedId} options={resumes.data?.map((item) => ({
                value: item.id, label: `${item.company} · ${item.jobTitle} · ${new Date(item.createdAt).toLocaleString()}`,
              }))} />
              <Button onClick={() => window.print()}>打印或保存为 PDF</Button>
            </Space>
            <ResumeContent resume={selected} />
            {createPortal(<ResumeContent resume={selected} print />, document.body)}
          </>
        )}
      </Space>
    </Card>
  )
}
