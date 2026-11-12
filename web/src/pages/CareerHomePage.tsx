import { useCallback, type ReactNode } from 'react'
import {
  ArrowDownOutlined, ArrowRightOutlined, AuditOutlined, BookOutlined, CheckOutlined,
  CommentOutlined, CompassOutlined, FileDoneOutlined, FileSearchOutlined, FileTextOutlined,
  FlagOutlined, FundOutlined, ReadOutlined, ReloadOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { careerApi } from '@/api/career'
import { applicationStages, careerWorkflow, type Stage } from '@/api/careerWorkflow'
import { modelApi } from '@/api/models'
import { practiceApi } from '@/api/practice'
import { useAuthStore } from '@/stores/authStore'
import { useCurrentJob } from './career/CurrentJob'
import { useCareerQuery } from './career/useCareerQuery'
import styles from './CareerHomePage.module.css'

const stageColors: Record<Stage, string> = {
  DRAFT: '#717b96', SUBMITTED: '#5554d8', SCREENING: '#2b74c8', INTERVIEW: '#986218',
  OFFER: '#147d68', REJECTED: '#b85161', WITHDRAWN: '#645d78',
}
const stages = Object.keys(applicationStages) as Stage[]

const features = [
  { title: '求职助手', copy: '和 AI 讨论岗位、材料与准备方向', to: '/chat', icon: CommentOutlined, tone: 'violet' },
  { title: '简历与经历', copy: '归档真实经历，生成岗位简历', to: '/career/resume', icon: FileTextOutlined, tone: 'blue' },
  { title: '岗位与公司', copy: '收藏目标岗位，整理招聘信息', to: '/career/jobs', icon: FileSearchOutlined, tone: 'teal' },
  { title: '我的资料', copy: '集中管理文档和网页资料', to: '/knowledge', icon: BookOutlined, tone: 'amber' },
  { title: '面经与题库', copy: '阅读公开面经，按岗位方向找题', to: '/career/questions', icon: ReadOutlined, tone: 'blue' },
  { title: '刷题练习', copy: '即时查看判分，回顾做错的题', to: '/career/practice', icon: AuditOutlined, tone: 'teal' },
  { title: '岗位训练计划', copy: '结合岗位要求安排选题和复习', to: '/career/plan', icon: ThunderboltOutlined, tone: 'violet' },
  { title: '模拟面试', copy: '练习一道岗位问答，获得复盘', to: '/career/interviews', icon: CompassOutlined, tone: 'amber' },
  { title: '网申助手', copy: '关联简历版本，整理申请答案', to: '/career/apply', icon: FileDoneOutlined, tone: 'violet' },
  { title: '投递看板', copy: '维护实际投递阶段，回看记录', to: '/career/applications', icon: FundOutlined, tone: 'blue' },
] as const

async function loadChatModels(signal: AbortSignal) {
  return (await modelApi.list('chat', signal)).data
}

function HeroArtwork() {
  return (
    <div className={styles.artwork} aria-hidden="true">
      <svg viewBox="0 0 440 248" fill="none">
        <circle cx="251" cy="120" r="105" />
        <circle cx="251" cy="120" r="77" />
        <path d="M30 205C97 205 99 166 150 159S223 149 251 120 310 72 398 57" strokeDasharray="4 8" />
        <path d="M151 159C197 155 224 147 251 120S310 72 350 68" className={styles.routeLine} />
        <path d="M367 107h20m-10-10v20M77 65h14m-7-7v14M291 211h12m-6-6v12" />
        <circle cx="32" cy="205" r="3" /><circle cx="398" cy="57" r="3" />
      </svg>
      <span className={`${styles.artNode} ${styles.artStart}`}><FileSearchOutlined /></span>
      <span className={`${styles.artNode} ${styles.artCenter}`}><CompassOutlined /></span>
      <span className={`${styles.artNode} ${styles.artFinish}`}><FlagOutlined /></span>
      <span className={styles.artCaption}>目标岗位 · 定向训练 · 投递跟进</span>
    </div>
  )
}

function OverviewCard({ title, eyebrow, icon, children }: {
  title: string; eyebrow: string; icon: ReactNode; children: ReactNode
}) {
  return (
    <section className={styles.overviewCard} aria-label={title}>
      <div className={styles.chartHeading}>
        <span className={`${styles.iconBox} ${styles.blue}`}>{icon}</span>
        <div><h3>{title}</h3><p>{eyebrow}</p></div>
      </div>
      {children}
    </section>
  )
}

export default function CareerHomePage() {
  const nickname = useAuthStore((state) => state.user?.nickname)
  const { job, jobs } = useCurrentJob()
  const jobId = job?.id
  const experiences = useCareerQuery(careerApi.experiences.list)
  const models = useCareerQuery(loadChatModels)
  const loadRecentPractice = useCallback((signal: AbortSignal) => practiceApi.attempts(1, signal, jobId), [jobId])
  const practice = useCareerQuery(loadRecentPractice)
  const loadRecentInterviews = useCallback((signal: AbortSignal) =>
    jobId ? careerWorkflow.tasks('INTERVIEW', 1, signal, jobId) : Promise.resolve(undefined), [jobId])
  const interviews = useCareerQuery(loadRecentInterviews)
  const applications = useCareerQuery(careerWorkflow.applications)
  const visibleApplications = applications.data?.filter((entry) => !jobId || entry.jobId === jobId)

  const confirmed = experiences.data?.filter((entry) => entry.confirmed).length
  const model = models.data?.find((entry) => entry.is_default) ?? models.data?.[0]
  const attempts = practice.data?.items
  const correct = attempts?.filter((attempt) => attempt.correct).length ?? 0
  const completedInterviews = interviews.data?.items.filter((task) => task.status === 'SUCCEEDED').length ?? 0
  const distribution = stages.map((stage) => ({
    stage, count: visibleApplications?.filter((entry) => entry.stage === stage).length ?? 0,
  })).filter(({ count }) => count > 0)

  const steps = [
    { title: '确认一段经历', copy: '整理项目、科研或实习经历，留作简历依据。', to: '/career/resume',
      action: '整理经历', done: confirmed === undefined ? undefined : confirmed > 0, error: experiences.error },
    { title: '选择目标岗位', copy: '选中一份岗位，查看匹配的面经和练习。', to: '/career/jobs',
      action: jobs?.length ? '选择岗位' : '添加岗位', done: jobs && !!job },
    { title: '配置 AI 教练', copy: '启用对话模型的工具调用，开始定向训练。', to: '/settings/models',
      action: '配置模型', done: models.data && !!model?.capability?.includes('function_call'), error: models.error },
    { title: '完成首道练习', copy: '选一道岗位方向的题，看看自己的掌握情况。', to: job ? '/career/questions' : '/career/practice',
      action: '开始练习', done: completedInterviews > 0 || (attempts && (!job || interviews.data) && attempts.length > 0),
      error: practice.error || interviews.error },
  ]
  const next = steps.find((step) => step.done === false)
  const knownSteps = steps.every((step) => step.done !== undefined)
  const completed = steps.filter((step) => step.done).length
  const failedQueries = [experiences, models, practice, interviews, applications].filter((query) => query.error)

  return (
    <div className={styles.home}>
      <header className={styles.hero}>
        <div className={styles.heroCopy}>
          <div className={styles.heroLabel}><CompassOutlined /> Search Agent <span /> 求职工作台</div>
          <h1>求职总览</h1>
          <p>{job ? `当前准备 ${job.company} · ${job.title}` : `${nickname?.trim() ? `你好，${nickname.trim()}。` : ''}把目标岗位变成具体的准备计划。从整理经历、练习面试到跟进投递，每一步都有记录。`}</p>
          <div className={styles.heroActions}>
            <Link className={styles.primary} to={next?.to ?? '/career/plan'}>{next?.action ?? '查看训练计划'} <ArrowRightOutlined /></Link>
            <a className={styles.secondary} href="#career-features">浏览功能 <ArrowDownOutlined /></a>
          </div>
        </div>
        <HeroArtwork />
      </header>

      <section className={`${styles.panel} ${styles.setupPanel}`} aria-labelledby="career-start-title">
        <div className={styles.sectionHeading}>
          <div><h2 id="career-start-title">开始求职准备</h2><p>从这些小步骤开始，建立你的第一份求职记录。</p></div>
          <div className={styles.setupProgress} aria-live="polite">
            <span>{knownSteps ? <><b>{completed} / {steps.length}</b> 已完成</> : steps.some((step) => step.error) ? '进度暂未读全' : '正在读取进度'}</span>
            <div aria-hidden="true">{steps.map((step) => <i key={step.title} className={step.done ? styles.filled : undefined} />)}</div>
          </div>
        </div>
        <ol className={styles.steps}>
          {steps.map((step, index) => (
            <li key={step.title}>
              <Link to={step.to} className={`${styles.step} ${step === next ? styles.currentStep : ''} ${step.done ? styles.doneStep : ''}`}>
                <span className={styles.stepNumber} aria-hidden="true">{step.done ? <CheckOutlined /> : `0${index + 1}`}</span>
                <div><h3>{step.title}</h3><p>{step.copy}</p></div>
                <span className={styles.stepAction}>{step.done ? '已完成' : step.action}<ArrowRightOutlined /></span>
              </Link>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="career-progress-title">
        <div className={`${styles.sectionHeading} ${styles.outerHeading}`}>
          <div><h2 id="career-progress-title">我的求职进展</h2><p>{job ? `显示 ${job.title} 的练习和投递记录。` : '显示全部练习和投递记录。'}</p></div>
          {failedQueries.length > 0 && <button type="button" className={styles.retry} onClick={() => failedQueries.forEach(({ retry }) => retry())}><ReloadOutlined /> 重试读取数据</button>}
        </div>
        <div className={styles.overviewGrid}>
          <OverviewCard title="最近练习" eyebrow={job ? '当前岗位的刷题和面试' : '最近 20 次作答'} icon={<AuditOutlined />}>
            {attempts?.length ? (
              <>
                <div className={styles.chartTotal}><strong>{Math.round(correct / attempts.length * 100)}%</strong><span>正确率 · {attempts.length} 次作答</span></div>
                <div className={styles.practiceBar} aria-hidden="true">
                  {attempts.slice().reverse().map((attempt) => <i key={attempt.requestId} className={attempt.correct ? styles.correct : styles.incorrect} />)}
                </div>
                <div className={styles.legend}><span><i className={styles.correct} />答对 <b>{correct}</b></span><span><i className={styles.incorrect} />答错 <b>{attempts.length - correct}</b></span></div>
              </>
            ) : !completedInterviews && <p className={styles.chartEmpty} role="status">
              {practice.error || interviews.error ? '练习记录暂时无法读取。'
                : attempts && (!job || interviews.data) ? '还没有练习记录，完成第一道题后可查看表现。' : '正在读取练习记录…'}
            </p>}
            {completedInterviews > 0 && <Link className={styles.chartLink} to="/career/interviews">
              最近完成 {completedInterviews} 次模拟面试 <ArrowRightOutlined />
            </Link>}
            <Link className={styles.chartLink} to="/career/practice">前往刷题练习 <ArrowRightOutlined /></Link>
          </OverviewCard>
          <OverviewCard title="投递阶段" eyebrow="按当前阶段统计，含草稿" icon={<FundOutlined />}>
            {visibleApplications?.length ? (
              <>
                <div className={styles.chartTotal}><strong>{visibleApplications.length}</strong><span>条申请记录</span></div>
                <div className={styles.stageBar} aria-hidden="true">
                  {distribution.map(({ stage, count }) => <i key={stage} style={{ flex: count, backgroundColor: stageColors[stage] }} />)}
                </div>
                <div className={styles.legend}>{distribution.map(({ stage, count }) => <span key={stage}><i style={{ backgroundColor: stageColors[stage] }} />{applicationStages[stage]} <b>{count}</b></span>)}</div>
              </>
            ) : <p className={styles.chartEmpty} role="status">{applications.error ? '申请记录暂时无法读取。' : applications.data ? '还没有申请记录，可以先为目标岗位保存一份网申草稿。' : '正在读取申请记录…'}</p>}
            {visibleApplications?.length ? <Link className={styles.chartLink} to="/career/applications">查看投递看板 <ArrowRightOutlined /></Link> : <Link className={styles.chartLink} to="/career/apply">前往网申助手 <ArrowRightOutlined /></Link>}
          </OverviewCard>
        </div>
      </section>

      <section className={`${styles.panel} ${styles.featuresPanel}`} id="career-features" aria-labelledby="career-features-title">
        <div className={styles.sectionHeading}><div><h2 id="career-features-title">功能一览</h2><p>按你的准备节奏，直接进入需要的工具。</p></div></div>
        <div className={styles.features}>
          {features.map(({ title, copy, to, icon: Icon, tone }) => (
            <Link to={to} className={styles.feature} key={to}>
              <span className={`${styles.iconBox} ${styles[tone]}`} aria-hidden="true"><Icon /></span>
              <div><h3>{title}</h3><p>{copy}</p></div>
              <ArrowRightOutlined className={styles.featureArrow} aria-hidden="true" />
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}
