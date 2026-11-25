import { useCallback, useRef, useState, type ReactNode } from 'react'
import { Alert, Button } from 'antd'
import {
  AimOutlined, ArrowRightOutlined, ArrowUpOutlined, CheckOutlined, CommentOutlined,
  FileDoneOutlined, FileSearchOutlined, FileTextOutlined, FlagOutlined, FundOutlined,
  PlusOutlined, ReadOutlined, RightOutlined,
} from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import { careerApi } from '@/api/career'
import { careerWorkflow } from '@/api/careerWorkflow'
import { modelApi } from '@/api/models'
import { practiceApi } from '@/api/practice'
import { useCurrentJob } from './career/CurrentJob'
import { withJobContext } from './career/jobContext'
import { jobPath, newJobPath, preparationPath, resumeStudioPath } from './career/paths'
import { trainingQuestionPath } from './career/TrainingPlanCard'
import { useCareerQuery } from './career/useCareerQuery'
import { useTrainingProgress } from './career/useTrainingProgress'
import dashboard from './career/dashboard.module.css'
import styles from './CareerHomePage.module.css'

const suggestions = [
  { label: '分析岗位要求', prompt: '请帮我分析这个岗位的核心要求和准备重点。', Icon: FileSearchOutlined },
  { label: '准备面试问题', prompt: '请根据这个岗位列出值得准备的面试问题。', Icon: CommentOutlined },
  { label: '梳理项目经历', prompt: '请引导我梳理适合这个岗位的项目经历。', Icon: FileTextOutlined },
]

async function loadChatModels(signal: AbortSignal) {
  return (await modelApi.list('chat', signal)).data
}

function Metric({ title, value, note, icon, tone, to }: {
  title: string; value?: string | number; note: string; icon: ReactNode; tone: string; to: string
}) {
  return <Link className={styles.metric} to={to}>
    <div className={styles.metricTitle}><span className={styles.metricIcon} data-tone={tone}>{icon}</span>
      {title}<RightOutlined className={styles.metricArrow} aria-hidden /></div>
    <p className={styles.metricValue}><strong>{value ?? '—'}</strong><span>{note}</span></p>
  </Link>
}

function CareerAssistant() {
  const { job, loading } = useCurrentJob()
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState('')
  const input = useRef<HTMLTextAreaElement>(null)

  return <section className={styles.panel} aria-labelledby="overview-assistant">
    <header className={styles.panelHead}>
      <h2 id="overview-assistant"><span className={styles.metricIcon}><CommentOutlined aria-hidden /></span>求职助手</h2>
      <Link to="/chat" className={styles.panelLink}>打开对话 <RightOutlined aria-hidden /></Link>
    </header>
    <p className={styles.assistantCopy}>围绕岗位要求准备面试，或梳理真实经历。</p>
    <form className={styles.composer} onSubmit={(event) => {
      event.preventDefault()
      const text = prompt.trim()
      if (text && !loading) navigate('/chat', { state: { careerPrompt: job ? withJobContext(job, text) : text } })
    }}>
      <textarea ref={input} aria-label="向求职助手提问" value={prompt} rows={2}
        placeholder={job ? '想为这个岗位准备什么？' : '想为求职准备什么？'}
        onChange={(event) => setPrompt(event.target.value)} />
      <div className={styles.composerActions}>
        {job ? <span className={styles.context} title={job.company + ' · ' + job.title}>
          <AimOutlined aria-hidden /> 当前岗位
        </span> : <span />}
        <button type="submit" className={dashboard.primary} disabled={!prompt.trim() || loading} aria-label="发送问题">
          <ArrowUpOutlined aria-hidden />
        </button>
      </div>
    </form>
    <div className={styles.suggestions}>
      {suggestions.map(({ label, prompt: suggestion, Icon }) => (
        <button key={label} type="button" onClick={() => { setPrompt(suggestion); input.current?.focus() }}>
          <Icon aria-hidden /> {label}
        </button>
      ))}
    </div>
  </section>
}

export default function CareerHomePage() {
  const target = useCurrentJob()
  const { job } = target
  const jobId = job?.id
  const scope = jobId ? { job: jobId } : undefined
  const planPath = preparationPath('plan', scope)
  const reviewPath = preparationPath('review', { ...scope, section: 'history' })
  const loadTraining = useCallback((signal: AbortSignal) => jobId
    ? careerWorkflow.tasks('TRAINING', 1, signal, jobId) : Promise.resolve(undefined), [jobId])
  const loadPractice = useCallback((signal: AbortSignal) => target.loading || target.error
    ? Promise.resolve(undefined) : practiceApi.attempts(1, signal, jobId), [target.loading, target.error, jobId])
  const training = useCareerQuery(loadTraining)
  const practice = useCareerQuery(loadPractice)
  const experiences = useCareerQuery(careerApi.experiences.list)
  const applications = useCareerQuery(careerWorkflow.applications)
  const models = useCareerQuery(loadChatModels)
  const tasks = training.data?.items
  const plan = tasks?.find((task) => task.status === 'SUCCEEDED' && task.result)
  const progress = useTrainingProgress(plan)
  const { completed, hasProgress, questions, next } = progress
  const planDone = hasProgress && questions.length > 0 && completed === questions.length
  const planRunning = tasks?.some(({ status }) => status === 'QUEUED' || status === 'RUNNING')
  const model = models.data?.find((entry) => entry.is_default) ?? models.data?.[0]
  const needsModel = !!models.data && !model?.capability?.includes('function_call')
  const attempts = practice.data?.items
  const correct = attempts?.filter((attempt) => attempt.correct).length
  const confirmed = experiences.data?.filter((entry) => entry.confirmed).length
  const progressText = hasProgress && questions.length ? completed + ' / ' + questions.length : undefined
  const failures = [training, practice, experiences, applications, progress].filter(({ error }) => error)

  function nextAction() {
    if (target.loading) return { title: '正在读取当前岗位', note: '', label: '查看岗位', to: '/career/jobs' }
    if (!job) return { title: '选定目标岗位', note: '从已有岗位中选择目标，或添加一份招聘信息。', label: '查看岗位', to: '/career/jobs' }
    if (next) return { title: '继续岗位训练', note: next.prompt, label: '继续练习', to: trainingQuestionPath(next, jobId) }
    if (planDone) return { title: '复盘岗位训练', note: '本轮计划已完成，回看作答记录和复习建议。', label: '查看复盘', to: preparationPath('review', scope) }
    if (planRunning && !plan) return { title: '查看计划生成进度', note: '打开备考中心查看任务状态。', label: '查看训练计划', to: planPath }
    if (plan || !tasks) return { title: '查看岗位训练', note: '打开备考中心查看计划和练习记录。', label: '查看训练计划', to: planPath }
    if (needsModel) return { title: '配置训练模型', note: '为对话模型启用工具调用后，即可生成岗位训练计划。', label: '配置模型', to: '/settings/models' }
    return { title: '制定岗位训练计划', note: '从备考中心查看题库和岗位训练计划。', label: '打开备考计划', to: planPath }
  }
  const action = nextAction()

  const steps = [
    { title: '选定目标岗位', note: job ? job.company + ' · ' + job.title : '保存并选中一份招聘信息',
      done: !!job, to: job ? jobPath(job.id, 'details') : '/career/jobs', action: '选择岗位' },
    { title: '确认简历素材', note: confirmed === undefined ? '整理项目、科研或实习经历' : '已确认 ' + confirmed + ' 条经历',
      done: !!confirmed, to: resumeStudioPath, action: '整理经历' },
    { title: '生成岗位训练计划', note: plan?.result?.skills?.join(' · ') || (plan ? '计划已保存' : '从岗位要求出发安排练习'),
      done: !!plan, to: planPath, action: '查看计划' },
    { title: '完成本轮训练', note: progressText ? '已完成 ' + progressText + ' 题' : '完成计划内的练习',
      done: planDone, to: planDone ? preparationPath('review', scope) : next ? trainingQuestionPath(next, jobId) : planPath,
      action: next ? '继续练习' : '查看计划' },
  ]
  const currentStep = next ? steps[3] : steps.find((step) => !step.done)
  const stepsLoaded = !target.loading && !target.error && confirmed !== undefined
    && (!job || (tasks && (!questions.length || hasProgress)))

  return <div className={dashboard.page}>
    <header className={dashboard.pageHead}>
      <div><h1>求职总览</h1><p>查看当前岗位的备考进度和下一步安排。</p></div>
      <Link className={dashboard.button} to={newJobPath}><PlusOutlined aria-hidden /> 添加岗位</Link>
    </header>
    {(target.error || failures.length > 0) && <Alert type="warning" showIcon
      message={target.error || '部分求职进度暂时无法读取。'}
      action={<Button size="small" onClick={() => {
        if (target.error) target.reload()
        failures.forEach(({ retry }) => retry())
      }}>重试</Button>} />}
    {models.error && <Alert type="warning" showIcon
      message="暂时无法读取模型配置。"
      action={<Button size="small" onClick={models.retry}>重试</Button>} />}
    <section className={styles.hero} aria-labelledby="overview-next">
      <div className={styles.orbit} aria-hidden="true" />
      <div className={styles.heroCopy}>
        <div className={styles.eyebrow}><FlagOutlined aria-hidden /> 下一步</div>
        <h2 id="overview-next">{action.title}</h2>
        {action.note && <p className={styles.nextNote}>{action.note}</p>}
        <div className={styles.heroActions}>
          <Link className={styles.continue} to={action.to}><ArrowRightOutlined aria-hidden /> {action.label}</Link>
          {job && action.to !== planPath && <Link className={styles.secondary} to={planPath}>查看训练计划</Link>}
        </div>
      </div>
      <div className={styles.focus}>
        <header><span>当前目标岗位</span>
          {job && <Link to={jobPath(job.id, 'details')}>岗位详情 <RightOutlined aria-hidden /></Link>}
        </header>
        {job ? <>
          <div className={styles.focusJob}>
            <span aria-hidden="true">{Array.from(job.company.trim())[0]?.toUpperCase() || <AimOutlined />}</span>
            <div><h3>{job.title}</h3><p>{job.company}</p></div>
          </div>
          <div className={styles.progressLabel}>
            <span>训练计划进度</span><strong>{progressText ?? (progress.error || training.error ? '读取失败' : planRunning && !plan ? '生成中' : questions.length ? '读取中…' : plan ? '已生成' : tasks ? '暂无计划' : '读取中…')}</strong>
          </div>
          {progressText && <progress className={styles.progress} value={completed} max={questions.length} aria-label="训练计划进度" />}
        </> : <p className={styles.focusEmpty}>{target.loading ? '正在读取岗位…' : '尚未选定岗位'}</p>}
      </div>
    </section>
    <section className={styles.metrics} aria-label="求职进度数据">
      <Metric title="最近练习" value={attempts?.length} note={job ? '次作答 · 当前岗位' : '次作答 · 全部岗位'}
        to={reviewPath} tone="violet" icon={<ReadOutlined aria-hidden />} />
      <Metric title="练习正确率" value={attempts?.length && correct !== undefined ? Math.round(correct / attempts.length * 100) + '%' : undefined}
        note={attempts?.length ? '答对 ' + correct + ' / ' + attempts.length + ' 题' : '最近作答'}
        to={reviewPath} tone="green" icon={<AimOutlined aria-hidden />} />
      <Metric title="已确认经历" value={confirmed} note="条可用于备考" to={resumeStudioPath} tone="sky" icon={<FileDoneOutlined aria-hidden />} />
      <Metric title="申请记录" value={applications.data?.length} note="条 · 全部岗位，含草稿" to="/career/applications" tone="amber" icon={<FundOutlined aria-hidden />} />
    </section>
    <div className={styles.lower}>
      <section className={styles.panel} aria-labelledby="overview-checklist">
        <header className={styles.panelHead}>
          <h2 id="overview-checklist">岗位准备清单</h2>
          {stepsLoaded && <p>{steps.filter((step) => step.done).length} / {steps.length} 已完成</p>}
        </header>
        <ul className={styles.checklist}>
          {steps.map((step) => <li key={step.title}>
            <Link to={step.to} className={styles.step} data-current={currentStep === step || undefined}>
              <span className={styles.stepIcon} data-done={step.done || undefined} aria-hidden="true">
                {step.done ? <CheckOutlined /> : <i />}
              </span>
              <span className={styles.stepText}><strong>{step.title}</strong><small>{step.note}</small></span>
              {step.done ? <span className={styles.done}>已完成</span> : <span className={styles.stepAction}>
                {step.action} <RightOutlined aria-hidden />
              </span>}
            </Link>
          </li>)}
        </ul>
      </section>
      <CareerAssistant />
    </div>
  </div>
}
