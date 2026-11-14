import { useCallback, useState } from 'react'
import { Alert, Button, List, Select, Space, Spin, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { practiceApi } from '@/api/practice'
import { useCareerQuery } from './useCareerQuery'
import { preparationPath } from './paths'

export const roles: Record<string, string> = { backend: '后端开发', algorithm: '算法', llm: '大模型应用' }

export function roleLabel(role: string) {
  return roles[role] ?? role
}

export function practiceLink(questionId: string, version?: number, jobId?: string) {
  return preparationPath('practice', {
    question: questionId,
    ...(version ? { version: String(version) } : {}),
    ...(jobId ? { job: jobId } : {}),
  })
}

export function PracticeQuestionList({ questions, jobId }: { questions: Awaited<ReturnType<typeof practiceApi.questions>>; jobId?: string }) {
  return (
    <List
      dataSource={questions}
      rowKey="id"
      locale={{ emptyText: '这个岗位方向暂时没有题目' }}
      renderItem={(question) => (
        <List.Item actions={[<Link key="practice" to={practiceLink(question.id, question.version, jobId)}>开始作答</Link>]}>
          <List.Item.Meta
            title={question.prompt}
            description={
              <Space wrap>
                <Tag>{roleLabel(question.role)}</Tag>
                <Typography.Text type="secondary">{question.topic}</Typography.Text>
                <Typography.Link href={question.sourceUrl} target="_blank" rel="noopener noreferrer">
                  {question.sourceName}
                </Typography.Link>
                <Typography.Text type="secondary">核对于 {question.sourcedOn}</Typography.Text>
              </Space>
            }
          />
        </List.Item>
      )}
    />
  )
}

function Questions({ role, jobId }: { role?: string; jobId?: string }) {
  const load = useCallback((signal: AbortSignal) => practiceApi.questions(role, signal), [role])
  const { data, error, retry } = useCareerQuery(load)
  if (error) return <Alert type="error" message={error} action={<Button onClick={retry}>重试</Button>} />
  if (!data) return <Spin />

  return <PracticeQuestionList questions={data} jobId={jobId} />
}

export default function QuestionCatalog({ jobId }: { jobId?: string }) {
  const [role, setRole] = useState<string>()

  return (
    <>
      <Select
        aria-label="岗位方向"
        placeholder="全部岗位方向"
        allowClear
        value={role}
        onChange={setRole}
        options={Object.entries(roles).map(([value, label]) => ({ value, label }))}
        style={{ width: 200 }}
      />
      <Questions key={role ?? 'all'} role={role} jobId={jobId} />
    </>
  )
}
