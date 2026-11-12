import { useCallback, useState } from 'react'
import { Alert, Button, Card, Empty, Form, Input, List, Select, Space, Spin, Tag, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { careerApi } from '@/api/career'
import { applicationStages, careerWorkflow, type Application, type Resume, type Stage } from '@/api/careerWorkflow'
import { useCurrentJob } from './career/CurrentJob'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'

const { Paragraph, Text, Title } = Typography
const stages = Object.entries(applicationStages).map(([value, label]) => ({ value, label }))

function DraftForm({ jobId, draft, resumes, onSave }: {
  jobId: string
  draft?: Application
  resumes: Resume[]
  onSave: (saved: Application) => void
}) {
  const action = useCareerAction()
  const [form] = Form.useForm()
  const resumeId = Form.useWatch('resumeId', form)

  return (
    <Form form={form} layout="vertical" initialValues={{ resumeId: draft?.resumeId ?? undefined, answers: draft?.answers }}
      onFinish={(values: { resumeId?: string | null; answers?: string }) => action.run(async () => {
        const input = { resumeId: values.resumeId || null, answers: values.answers }
        const saved = draft
          ? await careerWorkflow.updateApplication(draft.id, { ...input, revision: draft.revision })
          : await careerWorkflow.createApplication({ ...input, jobId })
        onSave(saved)
      })}>
      <Form.Item name="resumeId" label="此岗位的简历版本">
        <Select allowClear placeholder="选择要使用的版本" options={resumes.filter((resume) => resume.jobId === jobId).map((resume) => ({
          value: resume.id, label: `${resume.jobTitle} · ${new Date(resume.createdAt).toLocaleString()}`,
        }))} />
      </Form.Item>
      <Form.Item name="answers" label="表单答案草稿">
        <Input.TextArea rows={6} maxLength={12000} showCount placeholder="例如到岗时间、求职动机、开放题答案" />
      </Form.Item>
      <Space wrap>
        <Tag color={resumeId ? 'success' : 'warning'}>{resumeId ? '已选简历' : '待选简历'}</Tag>
        <Button type="primary" htmlType="submit" loading={action.saving}>保存网申草稿</Button>
      </Space>
    </Form>
  )
}

export function ApplicationAssistantPage() {
  const [params, setParams] = useSearchParams()
  const { job: currentJob } = useCurrentJob()
  const jobId = currentJob?.id ?? params.get('job') ?? undefined
  const jobs = useCareerQuery(careerApi.jobs.list)
  const drafts = useCareerQuery(careerWorkflow.applications)
  const resumes = useCareerQuery(careerWorkflow.resumes)
  const draft = drafts.data?.find((item) => item.jobId === jobId)
  const job = jobs.data?.find((item) => item.id === jobId)
  const options = [
    ...(jobs.data ?? []).map((item) => ({ value: item.id, label: `${item.company} · ${item.title}` })),
    ...(drafts.data ?? []).filter((item) => !jobs.data?.some((row) => row.id === item.jobId))
      .map((item) => ({ value: item.jobId, label: `${item.company} · ${item.jobTitle}` })),
  ]

  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>网申助手</Title>
        <Paragraph type="secondary">核对招聘来源、简历版本和表单答案。完成招聘网站上的投递后，到看板记录进度。</Paragraph>
      </div>
      <Card title="准备申请材料" extra={<Link to="/career/applications">打开投递看板</Link>}>
        <Space direction="vertical" style={{ display: 'flex' }}>
          {[jobs, drafts, resumes].filter((query) => query.error).map((query, index) => (
            <Alert key={index} type="error" message={query.error} action={<Button onClick={query.retry}>重试</Button>} />
          ))}
          {currentJob ? <Text strong>{currentJob.company} · {currentJob.title}</Text> :
            <Select aria-label="选择申请岗位" value={jobId} options={options} placeholder="选择目标岗位"
              onChange={(value) => setParams({ job: value })} />}
          <Space wrap>
            <Link to="/career/jobs">管理岗位</Link>
            <Link to="/career/resume">生成简历版本</Link>
            {(job?.sourceUrl ?? draft?.sourceUrl)
              ? <Tag color="success">已记录招聘链接</Tag>
              : jobId && <Tag color="warning">待补招聘链接</Tag>}
            {draft && <Tag>{applicationStages[draft.stage]}</Tag>}
          </Space>
          {(job?.sourceUrl ?? draft?.sourceUrl) && <Typography.Link href={job?.sourceUrl ?? draft?.sourceUrl ?? undefined} target="_blank" rel="noopener noreferrer">打开招聘来源</Typography.Link>}
          {jobId && (job || draft) && drafts.data && resumes.data && (
            <DraftForm key={`${jobId}:${draft?.revision ?? 0}`} jobId={jobId} draft={draft} resumes={resumes.data} onSave={(saved) => {
              drafts.setData((items) => [saved, ...(items ?? []).filter((item) => item.id !== saved.id)])
            }} />
          )}
          {jobId && <Button type="link" onClick={drafts.retry}>刷新草稿</Button>}
        </Space>
      </Card>
    </Space>
  )
}

function StageEditor({ entry, onSave }: { entry: Application; onSave: (saved: Application) => void }) {
  const action = useCareerAction()
  const [form] = Form.useForm()
  const selectedStage = Form.useWatch('stage', form)
  const load = useCallback((signal: AbortSignal) => careerWorkflow.events(entry.id, signal), [entry.id])
  const history = useCareerQuery(load)
  return (
    <Space direction="vertical" style={{ display: 'flex' }}>
      <Form form={form} layout="vertical" initialValues={{ stage: entry.stage }}
        onFinish={(values: { stage: Stage; note?: string }) => action.run(async () => {
          const saved = await careerWorkflow.updateStage(entry.id, { ...values, revision: entry.revision })
          onSave(saved)
        })}>
        <Form.Item name="stage" label="实际投递阶段" rules={[{ required: true }]}>
          <Select options={stages} />
        </Form.Item>
        <Form.Item name="note" label="阶段备注"><Input maxLength={1000} /></Form.Item>
        <Button htmlType="submit" loading={action.saving} disabled={!selectedStage || selectedStage === entry.stage}>更新阶段</Button>
      </Form>
      <details>
        <summary>阶段历史</summary>
        {history.error && <Alert type="error" message={history.error} action={<Button onClick={history.retry}>重试</Button>} />}
        <List dataSource={history.data} loading={!history.data && !history.error} renderItem={(event) => (
          <List.Item>
            <Space wrap>
              <Tag>{applicationStages[event.stage]}</Tag>
              <Text>{new Date(event.createdAt).toLocaleString()}</Text>
              {event.note && <Text>{event.note}</Text>}
            </Space>
          </List.Item>
        )} />
      </details>
    </Space>
  )
}

export function ApplicationBoardPage() {
  const { job } = useCurrentJob()
  const entries = useCareerQuery(careerWorkflow.applications)
  const [stage, setStage] = useState<Stage>()
  const visible = entries.data?.filter((item) => (!stage || item.stage === stage) && (!job || item.jobId === job.id))

  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>投递看板</Title>
        <Paragraph type="secondary">按你在招聘网站看到的结果手动维护阶段，查看每次变更的时间和备注。</Paragraph>
      </div>
      <Space wrap>
        <Select aria-label="筛选投递阶段" options={stages} value={stage} allowClear placeholder="全部阶段" onChange={setStage} />
        <Button onClick={entries.retry}>刷新</Button>
        <Link to="/career/apply">准备网申草稿</Link>
      </Space>
      {entries.error && <Alert type="error" message={entries.error} action={<Button onClick={entries.retry}>重试</Button>} />}
      {!entries.data && !entries.error && <Spin />}
      {visible?.length === 0 && <Empty description="暂无该阶段的投递记录" />}
      {visible?.map((entry) => (
        <Card key={entry.id} title={`${entry.company} · ${entry.jobTitle}`} extra={<Tag>{applicationStages[entry.stage]}</Tag>}>
          <Link to={`/career/apply?job=${entry.jobId}`}>查看申请材料</Link>
          <StageEditor key={entry.revision} entry={entry}
            onSave={(saved) => entries.setData((items) => items?.map((item) => item.id === saved.id ? saved : item))} />
        </Card>
      ))}
    </Space>
  )
}
