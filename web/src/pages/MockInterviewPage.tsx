import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, ConfigProvider, Empty, Select, Space, Spin, Tabs, Tag } from 'antd'
import {
  AimOutlined, ArrowRightOutlined, AudioOutlined, CalendarOutlined,
  EditOutlined, HistoryOutlined, MessageOutlined, SettingOutlined, VideoCameraOutlined,
} from '@ant-design/icons'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { interviewsApi, type InterviewMode, type InterviewSession, type InterviewSummary } from '@/api/interviews'
import { useCurrentJob } from './career/CurrentJob'
import { interviewTime, modeLabels, phaseLabels } from './career/interviewLabels'
import { interviewPath, preparationPath } from './career/paths'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'
import { openInterviewDevice, useInterviewCamera } from './career/useInterviewMedia'
import InterviewRoom, { CameraPreview } from './career/InterviewRoom'
import InterviewReview from './career/InterviewReview'
import styles from './career/interview.module.css'

const modes = [
  { value: 'VIDEO', Icon: VideoCameraOutlined, description: '摄像头自览 · 双向语音' },
  { value: 'VOICE', Icon: AudioOutlined, description: '仅使用麦克风' },
  { value: 'TEXT', Icon: EditOutlined, description: '键盘输入回答' },
] as const

const lengths = [
  { count: 3, title: '快速', time: '约 10 分钟' },
  { count: 5, title: '标准', time: '约 15–20 分钟' },
  { count: 8, title: '深入', time: '约 25 分钟' },
] as const

const phases = [
  { phase: 'WARMUP', Icon: MessageOutlined, description: '介绍与岗位相关的经历' },
  { phase: 'CORE', Icon: AimOutlined, description: '说明专业能力、行动和证据' },
  { phase: 'SCENARIO', Icon: CalendarOutlined, description: '讨论实际任务中的选择与取舍' },
] as const

function DeviceCheck({ mode }: { mode: 'VIDEO' | 'VOICE' }) {
  const camera = useInterviewCamera()
  const [mic, setMic] = useState<{ result: 'idle' | 'checking' | 'ready' | 'failed'; detail?: string }>({ result: 'idle' })

  async function checkMic() {
    setMic({ result: 'checking' })
    try {
      const stream = await openInterviewDevice('audio')
      stream.getTracks().forEach((track) => track.stop())
      setMic({ result: 'ready' })
    } catch (error) {
      setMic({ result: 'failed', detail: (error as Error).message })
    }
  }

  function check() {
    if (mode === 'VIDEO') void camera.enable()
    void checkMic()
  }

  const cameraStatus = camera.checking ? '检查中' : camera.stream ? '可用' : camera.error ? '不可用' : '待检查'
  const micStatus = { idle: '待检查', checking: '检查中', ready: '可用', failed: '不可用' }[mic.result]
  return (
    <Card className={styles.panel} title={<><VideoCameraOutlined /> 设备检查</>} extra={
      <Button size="small" loading={camera.checking || mic.result === 'checking'} onClick={check}>检查设备</Button>
    }>
      <div className={styles.devices}>
        {mode === 'VIDEO' && <div><span><VideoCameraOutlined /> 摄像头</span><small>{cameraStatus}</small></div>}
        <div><span><AudioOutlined /> 麦克风</span><small>{micStatus}</small></div>
      </div>
      {camera.stream && <CameraPreview className={styles.devicePreview} stream={camera.stream} />}
      {(camera.error || mic.detail) && <Alert type="warning" showIcon message={[camera.error, mic.detail].filter(Boolean).join(' ')} />}
      <p className={styles.deviceNote}>{mode === 'VIDEO' ? '摄像头仅本地自览。' : ''}语音由浏览器或已配置的语音识别服务转写。</p>
    </Card>
  )
}

function InterviewSetup({ jobId, resume }: { jobId?: string; resume?: InterviewSummary }) {
  const { jobs, error, loading, reload } = useCurrentJob()
  const [mode, setMode] = useState<InterviewMode>('VIDEO')
  const [count, setCount] = useState<number>(5)
  const [, setParams] = useSearchParams()
  const navigate = useNavigate()
  const action = useCareerAction()
  const selectedJob = jobs?.find((job) => job.id === jobId)
  const ModeIcon = modes.find((option) => option.value === mode)!.Icon
  const length = lengths.find((option) => option.count === count)!
  const scenarioCount = count === 8 ? 2 : 1
  const stageCounts = [1, count - scenarioCount - 1, scenarioCount]

  function start() {
    if (!selectedJob) return
    void action.run(async () => {
      const session = await action.submit('mock-interview-start', { jobId: selectedJob.id, mode, count }, interviewsApi.start)
      navigate(interviewPath({ session: session.summary.id }))
    })
  }

  return (
    <div className={styles.setupGrid}>
      <div className={styles.stack}>
        <Card className={styles.panel} title={<><SettingOutlined /> 面试设置</>} actions={[
          <div className={styles.setupFooter} key="start">
            <Button type="primary" icon={<ModeIcon />}
              disabled={!selectedJob} loading={action.saving} onClick={start}>开始{modeLabels[mode]}</Button>
          </div>,
        ]}>
          {error && <Alert type="error" message={error} action={<Button size="small" onClick={reload}>重试</Button>} />}
          <div className={styles.field}>
            <strong>目标岗位</strong>
            <Select aria-label="本场面试的目标岗位" showSearch optionFilterProp="label" placeholder="选择目标岗位" loading={loading}
              prefix={<AimOutlined />} value={selectedJob?.id} disabled={action.saving}
              options={jobs?.map((job) => ({ value: job.id, label: job.company + ' · ' + job.title }))}
              onChange={(value) => setParams({ job: value }, { replace: true })} />
            {!loading && !error && !selectedJob && <Link to="/career/jobs">{jobs?.length ? '管理岗位' : '添加目标岗位'}</Link>}
          </div>
          <div className={styles.field}>
            <strong id="interview-mode-label">面试方式</strong>
            <div role="group" aria-labelledby="interview-mode-label" className={styles.choices}>
              {modes.map(({ value, Icon, description }) => <button key={value} type="button" aria-pressed={mode === value}
                disabled={action.saving} onClick={() => setMode(value)}>
                <Icon /><strong>{modeLabels[value]}</strong><small>{description}</small>
              </button>)}
            </div>
          </div>
          <div className={styles.field}>
            <strong id="interview-count-label">题量</strong>
            <div role="group" aria-labelledby="interview-count-label" className={styles.choices}>
              {lengths.map((option) => <button key={option.count} type="button" aria-pressed={count === option.count}
                disabled={action.saving} onClick={() => setCount(option.count)}>
                <strong>{option.count} 道主问题</strong><small>{option.title} · {option.time}</small>
              </button>)}
            </div>
          </div>
          <Alert showIcon type="info" className={styles.setupHint}
            message="系统按岗位与环节随机抽题，开场后逐题展示。面试官会根据回答决定是否追问。" />
        </Card>
        {resume && <div className={styles.resume}>
          <HistoryOutlined />
          <div><strong>上次未完成的{modeLabels[resume.mode]}</strong>
            <small>{resume.job} · 已答 {resume.answered} / {resume.count} 道主问题</small></div>
          <Link to={interviewPath({ session: resume.id })}>打开面试 <ArrowRightOutlined /></Link>
        </div>}
      </div>
      <div className={styles.stack}>
        <Card className={`${styles.panel} ${styles.agenda}`} title={<><CalendarOutlined /> 本场安排</>}>
          <div className={styles.agendaStats}>
            <div><span>主问题</span><strong>{count} <small>道</small></strong></div>
            <div><span>预计时长</span><strong>{length.time.replace('约 ', '')}</strong></div>
          </div>
          <ul className={styles.agendaStages}>
            {phases.map(({ phase, Icon, description }, index) => <li key={phase}>
              <Icon /><div><strong>{phaseLabels[phase]}</strong><small>{description}</small></div>
              <span>{stageCounts[index]} 道</span>
            </li>)}
          </ul>
        </Card>
        {mode !== 'TEXT' && <DeviceCheck key={mode} mode={mode} />}
      </div>
    </div>
  )
}

function InterviewHistory({ records, error, reload, page, setPage }: {
  records?: { items: InterviewSummary[]; hasMore: boolean }
  error?: string
  reload: () => void
  page: number
  setPage: (page: number) => void
}) {
  return <Card className={styles.panel} title={<><HistoryOutlined /> 面试记录</>}>
    {error ? <Alert type="error" message={error} action={<Button onClick={reload}>重试</Button>} />
      : !records ? <Spin aria-label="正在读取面试记录" />
      : records.items.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有面试记录" />}
    <ul className={styles.history}>
      {records?.items.map((record) => <li key={record.id}>
        <div><strong>{record.job}</strong><small>{new Date(record.createdAt).toLocaleString('zh-CN')} · {modeLabels[record.mode]}</small></div>
        <small>{record.answered} / {record.count} 道 · {interviewTime(record.elapsedSeconds)}</small>
        <Tag color={record.status === 'FINISHED' ? 'purple' : 'default'}>
          {record.status === 'FINISHED' ? '已结束' : record.status === 'ACTIVE' ? '进行中' : '已暂停'}
        </Tag>
        <Link to={interviewPath({ session: record.id })}>{record.status === 'FINISHED' ? '查看复盘' : '打开面试'} <ArrowRightOutlined /></Link>
      </li>)}
    </ul>
    {(page > 1 || records?.hasMore) && <Space className={styles.pagination}>
      <Button size="small" disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</Button>
      <span>第 {page} 页</span>
      <Button size="small" disabled={!records?.hasMore} onClick={() => setPage(page + 1)}>下一页</Button>
    </Space>}
  </Card>
}

function InterviewLanding() {
  const [params, setParams] = useSearchParams()
  const { job, jobs } = useCurrentJob()
  const jobId = params.get('job') ?? job?.id ?? (jobs?.length === 1 ? jobs[0].id : undefined)
  const history = params.get('tab') === 'history'
  const [page, setPage] = useState(1)
  const load = useCallback((signal: AbortSignal) => interviewsApi.list(history ? page : 1, signal), [history, page])
  const records = useCareerQuery(load)
  const resume = records.data?.items.find((record) => record.status !== 'FINISHED' && record.jobId === jobId)
    ?? records.data?.items.find((record) => record.status !== 'FINISHED')
  return (
    <>
      <header className={styles.heading}>
        <div><h1>模拟面试</h1><p>按目标岗位完成一场多轮面试，结束后逐题回看。</p></div>
      </header>
      <Tabs className={styles.tabs} activeKey={history ? 'history' : 'setup'} onChange={(value) =>
        setParams({ ...(params.get('job') ? { job: params.get('job')! } : {}), ...(value === 'history' ? { tab: 'history' } : {}) })}
        items={[
          { key: 'setup', label: '开始面试', icon: <VideoCameraOutlined /> },
          { key: 'history', label: '面试记录', icon: <HistoryOutlined /> },
        ]} />
      {history ? <InterviewHistory records={records.data} error={records.error} reload={records.retry} page={page}
        setPage={(next) => { records.setData(undefined); setPage(next) }} /> : <InterviewSetup jobId={jobId} resume={resume} />}
    </>
  )
}

function InterviewSessionPage({ id }: { id: string }) {
  const load = useCallback((signal: AbortSignal) => interviewsApi.get(id, signal), [id])
  const query = useCareerQuery(load)
  const [connectionError, setConnectionError] = useState('')
  const session = query.data
  const pending = session?.pending
  const { setData } = query

  const update = useCallback((result: InterviewSession) => {
    setData((previous) => previous && previous.revision > result.revision ? previous : result)
  }, [setData])

  useEffect(() => {
    if (!pending?.id || pending.status === 'FAILED') return
    const controller = new AbortController()
    let timer: number
    async function poll() {
      try {
        const latest = await interviewsApi.get(id, controller.signal)
        if (controller.signal.aborted) return
        update(latest)
        setConnectionError('')
      } catch (failure) {
        if (!controller.signal.aborted) setConnectionError((failure as Error).message)
      }
      if (!controller.signal.aborted) timer = window.setTimeout(poll, 1500)
    }
    timer = window.setTimeout(poll, 700)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [id, pending?.id, pending?.status, pending?.generation, update])

  if (query.error && !session) return <Alert type="error" showIcon message={query.error} action={
    <Space><Button onClick={query.retry}>重试</Button><Link to={interviewPath()}>返回模拟面试</Link></Space>
  } />
  if (!session) return <Spin aria-label="正在读取面试进度" />
  return session.summary.status === 'FINISHED' ? <InterviewReview session={session} />
    : <InterviewRoom session={session} update={update} error={connectionError || query.error} reload={query.retry} />
}

export default function MockInterviewPage() {
  const [params] = useSearchParams()
  const id = params.get('session')
  if (params.has('question') && !id) {
    const values = Object.fromEntries(params)
    delete values.tab
    return <Navigate replace to={preparationPath('open', values)} />
  }
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#5142c7', borderRadius: 9 } }}>
      <main className={styles.page}>
        {id ? <InterviewSessionPage key={id} id={id} /> : <InterviewLanding />}
      </main>
    </ConfigProvider>
  )
}
