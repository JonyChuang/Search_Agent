import { useCallback, useState } from 'react'
import { Alert, Button, Card, Empty, List, Space, Spin, Tabs, Tag, Typography } from 'antd'
import { Link as RouteLink, useSearchParams } from 'react-router-dom'
import { careerWorkflow } from '@/api/careerWorkflow'
import { practiceApi, type InterviewNote } from '@/api/practice'
import { useCurrentJob } from './career/CurrentJob'
import QuestionCatalog, { PracticeQuestionList } from './career/QuestionCatalog'
import TaskHistory from './career/TaskHistory'
import PreparationDocuments from './career/PreparationDocuments'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'
import { preparationPath } from './career/paths'

const { Paragraph, Text, Title, Link } = Typography

function InterviewNotes() {
  const { data, error, retry } = useCareerQuery(practiceApi.notes)
  if (error) return <Alert type="error" message={error} action={<Button onClick={retry}>重试</Button>} />
  if (!data) return <Spin />

  return <NoteList notes={data} />
}

function NoteList({ notes }: { notes: InterviewNote[] }) {
  return (
    <List
      dataSource={notes}
      rowKey="id"
      locale={{ emptyText: '暂时没有已整理的面经' }}
      renderItem={(note) => (
        <List.Item>
          <List.Item.Meta
            title={note.title}
            description={
              <>
                <Text type="secondary">{note.company} · {note.role} · 公开个人回顾</Text>
                <Paragraph style={{ marginBlock: 8 }}>{note.summary}</Paragraph>
                <Space wrap>
                  <Link href={note.sourceUrl} target="_blank" rel="noopener noreferrer">{note.sourceName}</Link>
                  <Text type="secondary">发布于 {note.publishedOn} · 整理于 {note.sourcedOn}</Text>
                </Space>
              </>
            }
          />
        </List.Item>
      )}
    />
  )
}

function JobRecommendations({ jobId }: { jobId: string }) {
  const load = useCallback((signal: AbortSignal) => practiceApi.recommendations(jobId, signal), [jobId])
  const { data, error, retry } = useCareerQuery(load)
  if (error) return <Alert type="error" message={error} action={<Button onClick={retry}>重试</Button>} />
  if (!data) return <Spin />
  if (!data.notes.length && !data.questions.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="公开资料库暂无匹配，可以联网查面经或生成岗位模拟题。" />
  }
  return (
    <>
      <Title level={4}>相关公开面经</Title>
      <NoteList notes={data.notes} />
      <Title level={4}>相关公开练习题</Title>
      <PracticeQuestionList questions={data.questions} jobId={jobId} />
    </>
  )
}

function JobPreparation({ jobId }: { jobId: string }) {
  const action = useCareerAction()
  const [refresh, setRefresh] = useState(0)
  const [documentIds, setDocumentIds] = useState<string[]>([])
  const [skillId, setSkillId] = useState<string>()
  return (
    <Space direction="vertical" style={{ display: 'flex' }}>
      <Paragraph>AI 根据岗位名称、JD 和能力标签生成开放式模拟题。作答后可获得逐题复盘。</Paragraph>
      <PreparationDocuments value={documentIds} onChange={setDocumentIds} skillId={skillId} onSkillChange={setSkillId} />
      <Button type="primary" loading={action.saving} onClick={() => action.run(async () => {
        await action.submit('preparation', { jobId, documentIds, skillId }, careerWorkflow.prepare)
        setRefresh((previous) => previous + 1)
      })}>生成岗位模拟题</Button>
      <TaskHistory key={refresh} kind="PREPARATION" jobId={jobId} render={(task) => task.result && (
        <>
          <Space wrap>
            <Text strong>建议准备的能力</Text>
            {task.result.skills?.map((skill) => <Tag key={skill}>{skill}</Tag>)}
          </Space>
          <List dataSource={task.result.openQuestions} renderItem={(question, index) => (
            <List.Item actions={[
              <RouteLink key="plan" to={preparationPath('plan', {
                job: jobId, source: task.id, question: `${task.id}-${index}`,
              })}>加入备考计划</RouteLink>,
              <RouteLink key="interview" to={preparationPath('interview', { job: jobId, question: `${task.id}-${index}` })}>开始作答</RouteLink>,
            ]}>
              <List.Item.Meta title={question.prompt} description={<Tag color="purple">AI 模拟 · {question.topic}</Tag>} />
            </List.Item>
          )} />
        </>
      )} />
    </Space>
  )
}

function JobDiscovery({ jobId }: { jobId: string }) {
  const action = useCareerAction()
  const [refresh, setRefresh] = useState(0)
  return (
    <Space direction="vertical" style={{ display: 'flex' }}>
      <Paragraph>用公司和岗位名称搜索公开网页。结果包含网页来源、摘要和检索时间，可打开原网页核对。</Paragraph>
      <Space wrap>
        <Button type="primary" loading={action.saving} onClick={() => action.run(async () => {
          await action.submit('discovery', { jobId }, careerWorkflow.discover)
          setRefresh((previous) => previous + 1)
        })}>联网查面经</Button>
        <RouteLink to="/settings/models">配置联网搜索</RouteLink>
      </Space>
      <TaskHistory key={refresh} kind="DISCOVERY" jobId={jobId} render={(task) => task.result && (
        <>
          {task.result.searchedAt && <Text type="secondary">检索于 {new Date(task.result.searchedAt).toLocaleString()}</Text>}
          <List dataSource={task.result.sources} rowKey={(source) => source.url}
            locale={{ emptyText: '本次未找到可展示的网页' }}
            renderItem={(source) => (
              <List.Item><List.Item.Meta title={
                <Link href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</Link>
              } description={source.snippet} /></List.Item>
            )} />
        </>
      )} />
    </Space>
  )
}

export default function ExperienceBankPage({ jobId }: { jobId?: string }) {
  const { loading } = useCurrentJob()
  const [params, setParams] = useSearchParams()
  const source = params.get('source')
  const active = source === 'notes' || (jobId && ['recommended', 'discovery', 'preparation'].includes(source ?? ''))
    ? source ?? 'questions' : 'questions'
  return (
      <Card>
        {loading ? <Spin /> : <Tabs activeKey={active} destroyOnHidden onChange={(key) => {
          const next = new URLSearchParams(params)
          next.set('source', key)
          setParams(next, { replace: true })
        }} items={[
          { key: 'questions', label: '公开题库', children: <QuestionCatalog jobId={jobId} /> },
          { key: 'notes', label: '公开面经', children: <InterviewNotes /> },
          ...(jobId ? [
            { key: 'recommended', label: '岗位推荐', children: <JobRecommendations jobId={jobId} /> },
            { key: 'discovery', label: '联网面经', children: <JobDiscovery jobId={jobId} /> },
            { key: 'preparation', label: 'AI 模拟题', children: <JobPreparation jobId={jobId} /> },
          ] : []),
        ]} />}
      </Card>
  )
}
