import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Input, List, Segmented, Space, Spin, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import client from '@/api/client'
import { preparationPath } from './paths'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'

type Reply<T> = { code: number; message?: string; data: T }
type Problem = { id: string; version: number; kind: 'PYTHON' | 'SQL'; topic: string; prompt: string; starter: string }
type Result = { id: string; problemId: string; version: number; status: string; passed: number; createdAt: string }
const base = '/career/judge'
const labels: Record<string, string> = { QUEUED: '等待判题', RUNNING: '判题中', ACCEPTED: '通过', WRONG_ANSWER: '答案错误',
  TIME_LIMIT: '运行超时', COMPILE_ERROR: '编译失败', RUNTIME_ERROR: '运行错误', SYSTEM_ERROR: '判题服务异常' }
const load = async (signal: AbortSignal) => (await client.get<unknown, Reply<{ available: boolean; problems: Problem[] }>>(
  base + '/problems', { signal })).data
const pending = (value?: Result) => value && ['QUEUED','RUNNING'].includes(value.status)

function JudgeEditor({ problem, jobId, available, results, saved }: {
  problem: Problem; jobId?: string; available: boolean; results?: Result[]; saved: () => void
}) {
  const action = useCareerAction()
  const [source, setSource] = useState(problem.starter)
  const [submitted, setSubmitted] = useState<Result>()
  const result = results?.find((item) => item.id === submitted?.id) ?? submitted
  return <Space direction="vertical" style={{ display: 'flex' }}>
    <Typography.Title level={4} style={{ margin: 0 }}>{problem.topic}</Typography.Title>
    <Typography.Paragraph>{problem.prompt}</Typography.Paragraph>
    <Input.TextArea aria-label={problem.kind === 'SQL' ? 'SQL 作答' : 'Python 作答'} rows={12} value={source} maxLength={16000}
      onChange={(event) => setSource(event.target.value)} style={{ fontFamily: 'monospace' }} spellCheck={false} />
    <Button type="primary" loading={action.saving} disabled={!available || !source.trim() || !!pending(result)}
      onClick={() => action.run(async () => {
        const attempt = await action.submit('judge', { jobId, problemId: problem.id, version: problem.version, source },
          async (input) => (await client.post<unknown, Reply<Result>>(base + '/submissions', input)).data)
        setSubmitted(attempt)
        saved()
      })}>提交判题</Button>
    {result && <Tag>{labels[result.status]}</Tag>}
  </Space>
}

export default function JudgeWorkspace({ jobId }: { jobId?: string }) {
  const bank = useCareerQuery(load)
  const [language, setLanguage] = useState<'PYTHON' | 'SQL'>('PYTHON')
  const [selected, setSelected] = useState<string>()
  const action = useCareerAction()
  const history = useCareerQuery(useCallback(async (signal: AbortSignal) =>
    (await client.get<unknown, Reply<Result[]>>(base + '/submissions', { signal, params: { jobId } })).data, [jobId]))
  const inProgress = history.data?.some(pending)
  useEffect(() => {
    if (!inProgress || history.error) return
    const timeout = window.setTimeout(history.retry, 1500)
    return () => window.clearTimeout(timeout)
  }, [inProgress, history.data, history.retry, history.error])
  const problems = bank.data?.problems.filter((item) => item.kind === language)
  const problem = problems?.find((item) => item.id === selected) ?? problems?.[0]
  return <Card title="编程与 SQL 练习" extra={<Link to={preparationPath('practice', jobId ? { job: jobId } : undefined)}>返回专项练习</Link>}>
    <Space direction="vertical" style={{ display: 'flex' }}>
      <Segmented value={language} onChange={setLanguage} options={[
        { value: 'PYTHON', label: 'Python' }, { value: 'SQL', label: 'SQL' },
      ]} />
      {bank.error ? <Alert type="error" message={bank.error} action={<Button onClick={bank.retry}>重试</Button>} /> :
        !bank.data ? <Spin /> : <>
          {!bank.data.available && <Alert type="info" message="部署者配置判题服务后即可提交" />}
          {!!problems?.length && <Segmented value={problem?.id} onChange={setSelected}
            options={problems.map((item) => ({ label: item.topic, value: item.id }))} />}
          {problem && <JudgeEditor key={problem.id + ':' + problem.version} problem={problem} jobId={jobId} available={bank.data.available}
            results={history.data} saved={history.retry} />}
        </>}
      <Typography.Title level={5}>判题记录</Typography.Title>
      {history.error ? <Alert type="error" message={history.error} action={<Button onClick={history.retry}>重试</Button>} /> :
        <List dataSource={history.data} rowKey="id" locale={{ emptyText: '暂无提交' }} renderItem={(item) => <List.Item actions={
          item.status === 'SYSTEM_ERROR' ? [<Button key="retry" disabled={action.saving} onClick={() => action.run(async () => {
            await client.post(base + '/submissions/' + item.id + '/retry')
            history.retry()
          })}>重试判题</Button>] : []}>
          <List.Item.Meta title={bank.data?.problems.find((value) => value.id === item.problemId)?.topic ?? item.problemId}
            description={'第 ' + item.version + ' 版 · 通过 ' + item.passed + ' 个用例'} />
          <Tag color={item.status === 'ACCEPTED' ? 'green' : pending(item) ? 'processing' : 'orange'}>{labels[item.status] ?? item.status}</Tag>
        </List.Item>} />}
    </Space>
  </Card>
}

