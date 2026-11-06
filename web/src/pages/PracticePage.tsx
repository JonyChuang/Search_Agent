import { useCallback, useState } from 'react'
import { Alert, Button, Card, Collapse, List, Radio, Space, Spin, Tabs, Tag, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { practiceApi, type Attempt, type Question, type Submission } from '@/api/practice'
import { useAuthStore } from '@/stores/authStore'
import QuestionCatalog, { practiceLink, roleLabel } from './career/QuestionCatalog'
import { useCareerQuery } from './career/useCareerQuery'

const { Paragraph, Text, Title } = Typography
const choices = ['A', 'B', 'C', 'D']

function Feedback({ attempt }: { attempt: Attempt }) {
  return (
    <Space direction="vertical">
      <Tag color={attempt.correct ? 'green' : 'volcano'}>{attempt.correct ? '回答正确' : '回答错误'}</Tag>
      <Text>你的选择 {attempt.answer} · {attempt.answerText}</Text>
      <Text>正确选项 {attempt.correctAnswer} · {attempt.correctAnswerText}</Text>
      <Text>{attempt.explanation}</Text>
      <Text type="secondary">题目版本 {attempt.questionVersion} · 评分版本 {attempt.gradingVersion}</Text>
    </Space>
  )
}

function AnswerForm({ question, storageKey }: { question: Question; storageKey: string }) {
  const [pending, setPending] = useState<Submission | undefined>(() => {
    const saved = sessionStorage.getItem(storageKey)
    return saved ? JSON.parse(saved) as Submission : undefined
  })
  const [answer, setAnswer] = useState(pending?.answer)
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<Attempt>()
  const [error, setError] = useState<string>()

  async function submit() {
    if (!answer || saving || result) return
    setSaving(true)
    setError(undefined)
    try {
      const submission = pending ?? {
        requestId: crypto.randomUUID(),
        questionId: question.id,
        questionVersion: question.version,
        answer,
      }
      sessionStorage.setItem(storageKey, JSON.stringify(submission))
      setPending(submission)
      const attempt = await practiceApi.submit(submission)
      sessionStorage.removeItem(storageKey)
      setResult(attempt)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '提交失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
      <Link to="/career/practice">返回选题</Link>
      <Space wrap>
        <Tag>{roleLabel(question.role)}</Tag>
        <Text type="secondary">{question.topic} · 单选题</Text>
      </Space>
      <Title level={4} style={{ margin: 0 }}>{question.prompt}</Title>
      <Radio.Group aria-label="作答选项" value={answer} disabled={!!pending || !!result || saving} onChange={(event) => setAnswer(event.target.value)}>
        <Space direction="vertical">
          {question.options.map((option, index) => (
            <Radio key={choices[index]} value={choices[index]}>{choices[index]} · {option}</Radio>
          ))}
        </Space>
      </Radio.Group>
      {error && <Alert type="error" message={error} showIcon />}
      {result ? (
        <>
          <Feedback attempt={result} />
          <Typography.Link href={question.sourceUrl} target="_blank" rel="noopener noreferrer">
            {question.sourceName}
          </Typography.Link>
          <Link to={result.correct ? '/career/practice' : '/career/practice?tab=wrong'}>
            {result.correct ? '继续选题' : '查看错题本'}
          </Link>
        </>
      ) : (
        <Button type="primary" loading={saving} disabled={!answer} onClick={submit}>
          {pending && !saving ? '重试提交' : '提交答案'}
        </Button>
      )}
    </Space>
  )
}

function SelectedQuestion({ id, version }: { id: string; version?: string }) {
  const userId = useAuthStore((state) => state.user?.id)
  const load = useCallback((signal: AbortSignal) => practiceApi.question(id, signal, version), [id, version])
  const { data, error, retry } = useCareerQuery(load)
  if (error) {
    return (
      <Space direction="vertical">
        <Alert type="error" message={error} action={<Button onClick={retry}>重试</Button>} />
        <Link to="/career/practice">返回选题</Link>
      </Space>
    )
  }
  if (!data || !userId) return <Spin />
  const storageKey = `career-attempt:${userId}:${data.id}:${data.version}`
  return <AnswerForm key={storageKey} storageKey={storageKey} question={data} />
}

function WrongQuestions() {
  const { data, error, retry } = useCareerQuery(practiceApi.wrongQuestions)
  if (error) return <Alert type="error" message={error} action={<Button onClick={retry}>重试</Button>} />
  if (!data) return <Spin />

  return (
    <List
      dataSource={data}
      rowKey="questionId"
      locale={{ emptyText: '还没有错题' }}
      renderItem={(question) => (
        <List.Item actions={[<Link key="review" to={practiceLink(question.questionId)}>重新作答</Link>]}>
          <List.Item.Meta
            title={question.prompt}
            description={
              <Space wrap>
                <Tag color={question.reviewed ? 'green' : 'orange'}>{question.reviewed ? '已复习' : '待复习'}</Tag>
                <Text type="secondary">{question.topic} · 答错 {question.wrongCount} 次</Text>
              </Space>
            }
          />
        </List.Item>
      )}
    />
  )
}

function HistoryPage({ page, onPage }: { page: number; onPage: (page: number) => void }) {
  const load = useCallback((signal: AbortSignal) => practiceApi.attempts(page, signal), [page])
  const { data, error, retry } = useCareerQuery(load)
  if (error) return <Alert type="error" message={error} action={<Button onClick={retry}>重试</Button>} />
  if (!data) return <Spin />

  return (
    <Space direction="vertical" style={{ display: 'flex' }}>
      {data.items.length ? (
        <Collapse items={data.items.map((attempt) => ({
          key: attempt.requestId,
          label: <>{attempt.prompt}<br /><Text type="secondary">{new Date(attempt.submittedAt).toLocaleString('zh-CN')}</Text></>,
          extra: <Tag color={attempt.correct ? 'green' : 'volcano'}>{attempt.correct ? '答对' : '答错'}</Tag>,
          children: <Feedback attempt={attempt} />,
        }))} />
      ) : <Text type="secondary">暂无作答记录</Text>}
      {(page > 1 || data.hasMore) && (
        <Space>
          <Button disabled={page === 1} onClick={() => onPage(page - 1)}>上一页</Button>
          <Text>第 {page} 页</Text>
          <Button disabled={!data.hasMore} onClick={() => onPage(page + 1)}>下一页</Button>
        </Space>
      )}
    </Space>
  )
}

export default function PracticePage() {
  const [params, setParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const version = params.get('version') ?? undefined
  const question = params.get('question')
  const tab = params.get('tab')
  const activeTab = tab === 'wrong' || tab === 'history' ? tab : 'practice'

  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>刷题练习</Title>
        <Paragraph type="secondary">按方向选题，提交后查看解析。答错的题目会进入错题本。</Paragraph>
      </div>
      <Card>
        <Tabs
          activeKey={activeTab}
          destroyOnHidden
          onChange={(key) => {
            setPage(1)
            setParams(key === 'practice' ? {} : { tab: key })
          }}
          items={[
            {
              key: 'practice',
              label: '选题作答',
              children: question ? <SelectedQuestion key={`${question}:${version}`} id={question} version={version} /> : <QuestionCatalog />,
            },
            { key: 'wrong', label: '错题本', children: <WrongQuestions /> },
            { key: 'history', label: '练习记录', children: <HistoryPage key={page} page={page} onPage={setPage} /> },
          ]}
        />
      </Card>
    </Space>
  )
}
