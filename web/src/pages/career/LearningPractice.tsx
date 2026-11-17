import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Empty, Input, List, Progress, Segmented, Select, Space, Spin, Tag, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { careerWorkflow, type CareerTask, type TaskReference } from '@/api/careerWorkflow'
import { learningApi } from '@/api/learning'
import { practiceApi } from '@/api/practice'
import { SelectedQuestion } from '../PracticePage'
import { OpenReviewDetails } from '../OpenQuestionPractice'
import PreparationDocuments from './PreparationDocuments'
import TaskDetails from './TaskDetails'
import TaskHistory from './TaskHistory'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'
import { preparationPath } from './paths'
import styles from './learning.module.css'

type Item = {
  id: string; version: number; topic: string; prompt: string; type: 'single' | 'open'
  sourceName?: string; sourceUrl?: string; recommended?: boolean; references?: TaskReference[] | null
}
const types = [{ value: 'all', label: '全部题型' }, { value: 'single', label: '单选题' }, { value: 'open', label: '开放题' }]

function useCatalog(jobId?: string) {
  const load = useCallback(async (signal: AbortSignal): Promise<Item[]> => {
    const [publicQuestions, recommended, personal] = await Promise.all([
      practiceApi.questions(undefined, signal),
      jobId ? practiceApi.recommendations(jobId, signal) : undefined,
      jobId ? learningApi.questions(jobId, signal) : [],
    ])
    const matches = new Set(recommended?.questions.map((q) => q.id))
    return [
      ...personal.map((item): Item => ({ ...item, type: 'open', recommended: true })),
      ...publicQuestions.map((item): Item => ({ ...item, type: 'single', recommended: matches.has(item.id) })),
    ].sort((a, b) => Number(b.recommended) - Number(a.recommended))
  }, [jobId])
  return useCareerQuery(load)
}

function QuestionList({ items, render }: { items: Item[]; render: (item: Item) => React.ReactNode }) {
  return <List dataSource={items} rowKey="id" size="small"
    locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无符合条件的题目" /> }}
    pagination={items.length > 8 ? { pageSize: 8, size: 'small', hideOnSinglePage: true } : false}
    renderItem={(item) => <List.Item actions={[render(item)]}>
      <List.Item.Meta title={item.prompt} description={<Space wrap size={[4, 4]}>
        <Tag color={item.type === 'open' ? 'purple' : 'blue'}>{item.type === 'open' ? '开放题' : '单选题'}</Tag>
        <Tag>{item.topic}</Tag>
        {item.recommended && <Tag color="green">岗位相关</Tag>}
        {item.sourceUrl ? <a href={item.sourceUrl} target="_blank" rel="noreferrer">{item.sourceName}</a> : <Tag>AI 模拟题</Tag>}
        {item.references?.map((ref) => <Typography.Text type="secondary" key={ref.id}>{ref.title}</Typography.Text>)}
      </Space>} />
    </List.Item>} />
}

const topicOptions = (items: Item[]) => [...new Set(items.map((item) => item.topic))].map((topic) => ({ value: topic, label: topic }))

export function LearningLibrary({ jobId }: { jobId?: string }) {
  const catalog = useCatalog(jobId)
  const [type, setType] = useState('all')
  const [topic, setTopic] = useState<string>()
  const [keyword, setKeyword] = useState('')
  const items = catalog.data ?? []
  const visible = items.filter((item) => (type === 'all' || type === item.type) && (!topic || topic === item.topic)
    && [item.prompt, item.topic].some((value) => value.toLowerCase().includes(keyword.trim().toLowerCase())))
  return <Card title="题库" extra={<Typography.Text type="secondary">提交后查看解析或参考思路</Typography.Text>}>
    <div className={styles.filters}>
      <Input.Search aria-label="搜索题目" placeholder="搜索题干或主题" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
      <Select aria-label="题库主题" allowClear placeholder="全部主题" options={topicOptions(items)} value={topic} onChange={setTopic} />
      <Select aria-label="题库题型" options={types} value={type} onChange={setType} />
    </div>
    {catalog.error ? <Alert type="error" message={catalog.error} action={<Button onClick={catalog.retry}>重试</Button>} />
      : !catalog.data ? <Spin /> : <QuestionList items={visible} render={(item) => <Link key="practice" to={preparationPath('practice', {
        question: item.id, version: String(item.version), kind: item.type, ...(jobId ? { job: jobId } : {}),
      })}>练这道</Link>} />}
  </Card>
}

function Generated({ onReady, count }: { onReady?: () => void; count: number }) {
  useEffect(() => { onReady?.() }, [onReady])
  return <Alert type="success" showIcon message={'已加入本岗位题库 · ' + count + ' 道开放题'} />
}

export function PreparationActions({ jobId, topic, purpose, initialDocument, onReady, renderNote }: {
  jobId: string; topic?: string; purpose?: 'NOTES'; initialDocument?: string; onReady?: () => void
  renderNote?: (task: CareerTask, index: number) => React.ReactNode
}) {
  const [documentIds, setDocumentIds] = useState<string[]>(initialDocument ? [initialDocument] : [])
  const [skillId, setSkillId] = useState<string>()
  const [taskId, setTaskId] = useState<string>()
  const action = useCareerAction()
  return <Space direction="vertical" className={styles.stack}>
    <PreparationDocuments value={documentIds} onChange={setDocumentIds} skillId={skillId} onSkillChange={setSkillId} />
    <Button type="primary" disabled={purpose === 'NOTES' && !documentIds.length} loading={action.saving} onClick={() => action.run(async () => {
      const task = await action.submit('prepare-' + (purpose ?? 'questions'), { jobId, documentIds, skillId, topic, purpose }, careerWorkflow.prepare)
      setTaskId(task.id)
    })}>{purpose === 'NOTES' ? '从所选资料整理面经' : 'AI 生成开放题'}</Button>
    {(taskId || purpose === 'NOTES') && <TaskHistory key={taskId ?? 'notes'} kind="PREPARATION" jobId={jobId}
      taskId={purpose === 'NOTES' ? undefined : taskId} content={purpose === 'NOTES' ? 'notes' : undefined}
      emptyText="暂无面经整理记录"
      renderTask={(task) => purpose === 'NOTES' ? <>
        {!task.result?.notes?.length ? <Alert type="info" message="所选资料中未找到明确的面试经历" /> :
          <List dataSource={task.result.notes} renderItem={(note, index) => <List.Item actions={[renderNote?.(task, index)]}>
            <List.Item.Meta title={note.title} description={<>{note.summary}<br />来源 · {task.references?.[note.reference - 1]?.title}</>} />
          </List.Item>} />}
        <TaskDetails task={task} />
      </> : <Generated onReady={onReady} count={task.result?.openQuestions?.length ?? 0} />} />}
  </Space>
}

function OpenAnswer({ item, jobId, onNext, requestId, previous }: {
  item: Item; jobId: string; onNext: () => void; requestId?: string; previous?: string | null
}) {
  const [answer, setAnswer] = useState('')
  const [taskId, setTaskId] = useState(previous ?? undefined)
  const action = useCareerAction()
  return <Space direction="vertical" className={styles.stack}>
    <Space wrap><Tag color="purple">开放题</Tag><Tag>{item.topic}</Tag></Space>
    <Typography.Title level={4} style={{ margin: 0 }}>{item.prompt}</Typography.Title>
    {!taskId ? <>
      <Input.TextArea aria-label="你的回答" placeholder="写下你的分析过程" rows={5} maxLength={6000} value={answer}
        onChange={(event) => setAnswer(event.target.value)} showCount />
      <Button type="primary" disabled={!answer.trim()} loading={action.saving} onClick={() => action.run(async () => {
        const input = { jobId, questionId: item.id, questionVersion: item.version, answer: answer.trim() }
        const task = requestId ? await careerWorkflow.interview({ ...input, requestId }) :
          await action.submit('open-practice', input, careerWorkflow.interview)
        setTaskId(task.id)
      })}>提交答案</Button>
    </> : <>
      <TaskHistory kind="INTERVIEW" jobId={jobId} taskId={taskId} render={OpenReviewDetails} />
      <Button type="primary" onClick={onNext}>继续练习</Button>
      <Link to={preparationPath('review', { job: jobId })}>在复盘中查看点评</Link>
    </>}
  </Space>
}

export default function LearningPractice({ jobId, description }: { jobId?: string; description?: string }) {
  const [params, setParams] = useSearchParams()
  const [type, setType] = useState('all')
  const [topic, setTopic] = useState<string>()
  const [size, setSize] = useState(3)
  const [onlyRecommended, setOnlyRecommended] = useState(true)
  const action = useCareerAction()
  const sessionId = params.get('session')
  const sessionLoader = useCallback((signal: AbortSignal) => sessionId ? practiceApi.session(sessionId, signal) : Promise.resolve(undefined), [sessionId])
  const session = useCareerQuery(sessionLoader)
  const active = session.data?.id === sessionId ? session.data : undefined
  const listLoader = useCallback((signal: AbortSignal) => practiceApi.sessions(signal, jobId), [jobId])
  const previous = useCareerQuery(listLoader)
  const document = params.get('prepDocument') ?? undefined
  const [generator, setGenerator] = useState(Boolean(document))
  const catalog = useCatalog(jobId)
  const direct = params.get('question')
  const directOpen = params.get('kind') === 'open' ? direct : null
  const loadQuestion = useCallback((signal: AbortSignal) => directOpen && jobId ? learningApi.question(jobId, directOpen, signal)
    : Promise.resolve(undefined), [jobId, directOpen])
  const linked = useCareerQuery(loadQuestion)
  const items = catalog.data ?? []
  const activeOpen: Item | undefined = linked.data?.id === directOpen ? { ...linked.data, type: 'open' } : undefined
  const selected = direct ? items.find((item) => item.id === direct) ?? activeOpen : undefined
  const scope = jobId ? { job: jobId } : undefined
  const complete = useCallback(() => {
    setType('open')
    catalog.retry()
  }, [catalog.retry])

  function reset() {
    setParams({ tab: 'practice', ...scope })
    previous.retry()
  }

  if (sessionId && !active) return session.error ? <Alert type="error" message={session.error}
    action={<Button onClick={reset}>返回练习设置</Button>} /> : <Spin />
  if (active && !active.current) return <Card title="本组练习完成">
    <Space wrap><Typography.Text>已提交 {active.total} 道题</Typography.Text>
      <Button onClick={reset}>再练一组</Button><Link to={preparationPath('review', scope)}>查看复盘与错题</Link></Space>
  </Card>
  if (active?.current) {
    const current = active.current
    const job = active.jobId ?? undefined
    const next = () => void action.run(async () => session.setData(await practiceApi.advance(active)))
    return <Card title={'第 ' + (active.position + 1) + ' / ' + active.total + ' 题'} extra={<Button onClick={reset}>保存进度并退出</Button>}>
      <Progress percent={Math.round(active.position / active.total * 100)} showInfo={false} />
      {current.type === 'SINGLE' ? <SelectedQuestion key={active.answerRequestId} id={current.id} version={String(current.version)}
        previous={active.attempt} requestId={active.answerRequestId ?? undefined} jobId={job} onNext={next} /> :
        job && <OpenAnswer key={active.answerRequestId} item={{ ...current, type: 'open' }} jobId={job}
          previous={active.taskId} requestId={active.answerRequestId ?? undefined} onNext={next} />}
    </Card>
  }
  if (direct) {
    const directVersion = params.get('version') ?? undefined
    const objective = selected?.type === 'single' || (direct && !selected && params.get('kind') !== 'open')
    return <Card title="单题练习" extra={<Button onClick={reset}>返回练习设置</Button>}>
      {objective ? <SelectedQuestion key={direct} id={direct} version={directVersion} jobId={jobId} />
        : selected && jobId ? <OpenAnswer key={selected.id} item={selected} jobId={jobId} onNext={reset} />
        : directOpen && !jobId ? <Alert type="info" message="请先选择题目所属的岗位" />
        : directOpen && linked.error ? <Alert type="error" message={linked.error} action={<Button onClick={linked.retry}>重试</Button>} />
        : catalog.error ? <Alert type="error" message={catalog.error} action={<Button onClick={catalog.retry}>重试</Button>} />
        : !catalog.data || directOpen && !linked.data ? <Spin /> : <Empty description="当前岗位没有这道题" />}
    </Card>
  }

  const recommendedAvailable = items.some((item) => item.recommended)
  const base = jobId && onlyRecommended && recommendedAvailable ? items.filter((item) => item.recommended) : items
  const topics = topicOptions(base)
  const selectedTopic = topics.some((item) => item.value === topic) ? topic : undefined
  const visible = base.filter((item) => (!selectedTopic || selectedTopic === item.topic) && (type === 'all' || type === item.type))
  const count = Math.min(size, visible.length)
  const begin = (items: Item[]) => void action.run(async () => {
    const questions = items.map(({ id, version, type }) => ({ id, version, type: type === 'single' ? 'SINGLE' as const : 'OPEN' as const }))
    const created = await action.submit('practice-session', { jobId, questions }, practiceApi.createSession)
    session.setData(created)
    setParams({ tab: 'practice', ...scope, session: created.id })
  })

  return <div className={styles.layout}>
    <div className={styles.stack}>
      {!!previous.data?.length && <Card title="继续未完成的练习"><List dataSource={previous.data} size="small" rowKey="id"
        renderItem={(item) => <List.Item actions={[<Link key="continue" to={preparationPath('practice', { ...scope, session: item.id })}>继续</Link>]}>
          第 {item.position + 1} / {item.total} 题 · {item.prompt}
        </List.Item>} /></Card>}
      <Card title="岗位专项练习" extra={<Link to={preparationPath('practice', { ...scope, mode: 'judge' })}>编程与 SQL</Link>}>
        <div className={styles.filters}>
          <Select aria-label="练习主题" showSearch allowClear placeholder="全部主题" options={topics} value={selectedTopic} onChange={setTopic} />
          <Select aria-label="练习题型" options={types} value={type} onChange={setType} />
          {jobId && <Segmented aria-label="练习范围" value={onlyRecommended ? 'job' : 'all'} onChange={(value) => setOnlyRecommended(value === 'job')}
            options={[{ value: 'job', label: '岗位推荐' }, { value: 'all', label: '全部题目' }]} />}
        </div>
        {jobId && catalog.data && onlyRecommended && !recommendedAvailable && <Typography.Text type="secondary">
          暂无匹配岗位的题目，已显示公开题库。可按岗位生成开放题。
        </Typography.Text>}
      </Card>
      <Card title="可练题目" extra={catalog.data && <Typography.Text type="secondary">{visible.length} 道</Typography.Text>}>
        {catalog.error ? <Alert type="error" message={catalog.error} action={<Button onClick={catalog.retry}>重试</Button>} />
          : !catalog.data ? <Spin /> : <QuestionList items={visible} render={(item) => <Button type="link" key="practice" onClick={() => begin([item])}>作答</Button>} />}
      </Card>
    </div>
    <div className={styles.stack}>
      <Card title="本次练习">
        <Space direction="vertical" className={styles.stack}>
          <Typography.Text>{selectedTopic ?? '全部主题'} · {types.find((item) => item.value === type)?.label}</Typography.Text>
          <Select aria-label="练习题量" value={size} onChange={setSize} options={[3, 5, 10].map((value) => ({ value, label: value + ' 道' }))} />
          <Typography.Text type="secondary">本次可练 {count} 道</Typography.Text>
          <Button type="primary" disabled={!count} loading={action.saving} onClick={() => begin(visible.slice(0, count))}>开始练习</Button>
        </Space>
      </Card>
      {jobId && <Card title="根据岗位要求出题">
        {description && <Typography.Paragraph ellipsis={{ rows: 3, expandable: 'collapsible' }}>{description}</Typography.Paragraph>}
        {generator ? <PreparationActions jobId={jobId} topic={selectedTopic} initialDocument={document} onReady={complete} />
          : <Button onClick={() => setGenerator(true)}>选择资料并生成</Button>}
      </Card>}
      {document && !jobId && <Alert type="info" message="请先在页面顶部选择岗位，再使用所选资料出题" />}
    </div>
  </div>
}

