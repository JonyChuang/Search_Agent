import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Empty, Form, Input, Modal, Select, Spin, Tag } from 'antd'
import { EditOutlined, FileTextOutlined, FilterOutlined, FolderOpenOutlined, FormOutlined, FundOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { Link, useSearchParams } from 'react-router-dom'
import { applicationWorkspace } from '@/api/applicationWorkspace'
import { applicationStages, careerWorkflow, type Application, type Resume, type Stage } from '@/api/careerWorkflow'
import ApplicationMaterialsEditor from './career/ApplicationMaterialsEditor'
import { webAddress } from './career/ApplicationMaterialDialogs'
import { useCurrentJob } from './career/CurrentJob'
import { applicationPath, resumeDesignPath } from './career/paths'
import ResumeStudio, { ResumeVersionPreview } from './career/ResumeStudio'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'
import dashboard from './career/dashboard.module.css'
import styles from './CareerApplicationsPage.module.css'

const allStages = Object.keys(applicationStages) as Stage[]
const stages = allStages.map((value) => ({ value, label: applicationStages[value] }))

export function ApplicationAssistantPage() {
  const [params, setParams] = useSearchParams()
  const { job: currentJob, jobs } = useCurrentJob()
  const requestedJob = params.get('job')
  const jobId = requestedJob === 'general' ? undefined : requestedJob ?? currentJob?.id
  const drafts = useCareerQuery(careerWorkflow.applications)
  const resumes = useCareerQuery(careerWorkflow.resumes)
  const draft = drafts.data?.find((item) => item.jobId === jobId)
  const job = jobs?.find((item) => item.id === jobId)
  const sourceUrl = job ? job.sourceUrl : draft?.sourceUrl
  const materialsTab = params.get('tab') === 'materials'
  const versionId = materialsTab ? null : params.get('version')
  const version = resumes.data?.find((item) => item.id === versionId)
  const linkedVersion = resumes.data?.find((item) => item.id === params.get('resume') && item.jobId === jobId)
  const editing = !materialsTab && !versionId
  const [visitedEditor, setVisitedEditor] = useState(editing)
  const [visitedMaterials, setVisitedMaterials] = useState(materialsTab)

  useEffect(() => {
    if (editing) setVisitedEditor(true)
  }, [editing])
  useEffect(() => {
    if (materialsTab) setVisitedMaterials(true)
  }, [materialsTab])

  function changeTab(tab: 'studio' | 'materials', resume?: string) {
    const next = new URLSearchParams(params)
    next.set('tab', tab)
    next.delete('version')
    if (resume) next.set('resume', resume)
    else next.delete('resume')
    setParams(next)
  }

  function openVersion(value: Resume) {
    setParams({ job: value.jobId ?? 'general', version: value.id })
  }

  return <div className={dashboard.page + ' ' + styles.assistantPage}>
    <header className={dashboard.pageHead + ' ' + styles.assistantHead}>
      <div><h1>网申助手</h1><p>{materialsTab ? '为目标岗位准备简历、附件和表单答案。' : '为目标岗位制作简历，准备线上或线下投递。'}</p></div>
      <Link to="/career/applications" className={dashboard.button}><FundOutlined aria-hidden /> 投递看板</Link>
    </header>
    <div className={styles.assistantTabs} role="group" aria-label="网申助手功能">
      <button type="button" aria-pressed={!materialsTab} onClick={() => changeTab('studio')}>
        <FileTextOutlined aria-hidden /> 简历制作
      </button>
      <button type="button" aria-pressed={materialsTab} onClick={() => changeTab('materials', linkedVersion?.id)}>
        <FolderOpenOutlined aria-hidden /> 网申材料
      </button>
    </div>
    {resumes.error && <Alert type="error" message={resumes.error}
      action={<Button size="small" onClick={resumes.retry}>重试</Button>} />}
    {(visitedEditor || editing) && <div hidden={!editing} data-studio-active={editing || undefined}>
      <ResumeStudio active={editing} jobId={jobId} jobTitle={job?.title}
        sourceUrl={sourceUrl} versions={resumes.data ?? []}
        onOpenVersion={(id) => {
          const selected = resumes.data?.find((item) => item.id === id)
          if (selected) openVersion(selected)
        }}
        onGenerated={(saved) => {
          resumes.setData((items) => [saved, ...(items ?? []).filter((item) => item.id !== saved.id)])
          openVersion(saved)
        }} />
    </div>}
    {versionId && !resumes.data && !resumes.error && <Spin aria-label="正在读取简历版本" />}
    {versionId && resumes.data && <ResumeVersionPreview key={versionId} id={versionId} version={version} sourceUrl={sourceUrl}
      onClose={() => changeTab('studio')}
      onUse={version?.jobId && version.jobId === jobId ? () => changeTab('materials', version.id) : undefined} />}
    {(visitedMaterials || materialsTab) && <div hidden={!materialsTab}>
      {!jobId ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请在页面顶部选择投递岗位" />
        : resumes.data ? <ApplicationMaterialsEditor key={jobId} jobId={jobId} job={job}
          resumes={resumes.data.filter((item) => item.jobId === jobId)}
          preferredResumeId={linkedVersion?.id} onMakeResume={() => changeTab('studio')}
          onSave={(saved) => {
            drafts.setData((items) => [saved, ...(items ?? []).filter((item) => item.id !== saved.id)])
            if (linkedVersion) changeTab('materials')
          }} />
          : !resumes.error && <Spin aria-label="正在读取简历版本" />}
    </div>}
  </div>
}

const closedStages: Stage[] = ['OFFER', 'REJECTED', 'WITHDRAWN']
const views = [
  { key: 'all', label: '全部记录', matches: () => true },
  { key: 'active', label: '进行中', matches: (stage: Stage) => stage !== 'DRAFT' && !closedStages.includes(stage) },
  { key: 'closed', label: '结果已出', matches: (stage: Stage) => closedStages.includes(stage) },
]

const shortDate = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric' })
const fullDate = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })

function CompanyMark({ company }: { company: string }) {
  return <span className={styles.companyMark} aria-hidden="true">{Array.from(company.trim())[0]?.toUpperCase() || '·'}</span>
}

function StageLabel({ stage }: { stage: Stage }) {
  return <span className={styles.stageLabel} data-stage={stage}>
    <span className={styles.dot} aria-hidden="true" /> {applicationStages[stage]}
  </span>
}

function StageEditor({ entry, onClose, onSave }: {
  entry: Application; onClose: () => void; onSave: (saved: Application) => void
}) {
  const action = useCareerAction()
  const [form] = Form.useForm()
  const selectedStage = Form.useWatch('stage', form)
  return <Modal open title="更新实际投递阶段" onCancel={onClose} onOk={() => form.submit()}
    okText="保存阶段" cancelText="取消" confirmLoading={action.saving}
    closable={!action.saving} keyboard={!action.saving} maskClosable={!action.saving}
    cancelButtonProps={{ disabled: action.saving }}
    okButtonProps={{ disabled: !selectedStage || selectedStage === entry.stage }}>
    <Form form={form} layout="vertical" disabled={action.saving} initialValues={{ stage: entry.stage }}
      onFinish={(values: { stage: Stage; note?: string }) => action.run(async () => {
        const saved = await careerWorkflow.updateStage(entry.id, { ...values, revision: entry.revision })
        onSave(saved)
      })}>
      <Form.Item name="stage" label="实际投递阶段" rules={[{ required: true }]}>
        <Select options={stages} />
      </Form.Item>
      {selectedStage === 'SUBMITTED' && <Alert showIcon type="info" message={
        entry.resumeId ? '将记下当前选用的简历版本、附件和表单答案。' : '当前未选简历，历史将记录附件和表单答案。'
      } />}
      <Form.Item name="note" label="阶段备注"><Input.TextArea rows={3} maxLength={1000} /></Form.Item>
    </Form>
  </Modal>
}

function ApplicationHistory({ id, jobId }: { id: string; jobId: string }) {
  const load = useCallback((signal: AbortSignal) => careerWorkflow.events(id, signal), [id])
  const history = useCareerQuery(load)
  const action = useCareerAction()
  return <div className={styles.history} aria-live="polite">
    <h2>阶段历史</h2>
    {history.error ? <Alert type="error" message={history.error}
      action={<Button size="small" onClick={history.retry}>重试</Button>} />
      : !history.data ? <Spin size="small" aria-label="正在读取阶段历史" />
      : !history.data.length ? <p className={styles.emptyHistory}>暂无阶段记录</p>
      : <ol>
        {history.data.map((event, index) => <li key={event.createdAt + ':' + index}>
          <time dateTime={event.createdAt}>{fullDate.format(new Date(event.createdAt))}</time>
          {event.eventType === 'MATERIALS_UPDATED' ? <Tag>调整材料</Tag> : <StageLabel stage={event.stage} />}
          {event.note && <span className={styles.note}>{event.note}</span>}
          {event.receipt && <div className={styles.materialHistory}>
            <p>实际投递时间 · {fullDate.format(new Date(event.receipt.submittedAt))}</p>
            {event.receipt.applicationNumber && <p>申请编号 · {event.receipt.applicationNumber}</p>}
          </div>}
          {event.materials && <details className={styles.materialHistory}>
            <summary>{event.eventType === 'MATERIALS_UPDATED' ? '更新后的材料' : '标记已投递时的材料'}</summary>
            {event.materials.resumeId ? <Link to={resumeDesignPath(event.materials.resumeId, jobId)}>
              {event.materials.resumeTitle || '查看简历版本'}
              {event.materials.resumeCreatedAt && ' · ' + fullDate.format(new Date(event.materials.resumeCreatedAt))}
            </Link> : <span>当时未关联简历</span>}
            {event.materials.answers && <p className={styles.note}>{event.materials.answers}</p>}
            {event.materials.workspace && <div className={styles.snapshot}>
              {Object.entries({
                姓名: event.materials.workspace.content.form.name,
                手机号: event.materials.workspace.content.form.phone,
                邮箱: event.materials.workspace.content.form.email,
                教育经历: event.materials.workspace.content.form.education,
                最早到岗: event.materials.workspace.content.form.startDate,
                每周出勤: event.materials.workspace.content.form.weeklyDays,
                实习时长: event.materials.workspace.content.form.duration,
                求职动机: event.materials.workspace.content.form.motivation,
              }).filter(([, value]) => value).map(([label, value]) =>
                <p key={label} className={styles.note}><strong>{label}</strong> · {value}</p>)}
              {event.materials.workspace.content.form.questions.filter((question) => question.answer)
                .map((question) => <p className={styles.note} key={question.id}><strong>{question.label}</strong> · {question.answer}</p>)}
              {event.materials.workspace.content.attachments.map((item) => {
                const file = event.materials?.workspace?.files.find((value) => value.id === item.fileId)
                const url = webAddress(item.url)
                return file ? <p className={styles.note} key={item.id}>
                  <strong>{item.label}</strong> · {file.name}{' '}
                  <button type="button" className={dashboard.button} disabled={action.saving}
                    onClick={() => void action.run(() => applicationWorkspace.download(id, file))}>下载</button>
                </p>
                  : url ? <p key={item.id}><a href={url.href} target="_blank" rel="noreferrer">{item.label}</a></p> : null
              })}
            </div>}
          </details>}
        </li>)}
      </ol>}
  </div>
}

export function ApplicationBoardPage() {
  const [params, setParams] = useSearchParams()
  const entries = useCareerQuery(careerWorkflow.applications)
  const [selectedId, setSelectedId] = useState<string>()
  const [editing, setEditing] = useState(false)
  const [historyRefresh, setHistoryRefresh] = useState(0)
  const jobId = params.get('job')
  const stage = allStages.find((value) => value === params.get('stage'))
  const view = views.find(({ key }) => key === params.get('view')) ?? views[0]
  const scoped = entries.data?.filter((entry) => !jobId || entry.jobId === jobId)
  const drafts = scoped?.filter((entry) => entry.stage === 'DRAFT').length ?? 0
  const visible = scoped?.filter((entry) => view.matches(entry.stage) && (!stage || entry.stage === stage))
  const selected = visible?.find((entry) => entry.id === selectedId) ?? visible?.[0]
  const columns = allStages.filter((item) => stage
    ? item === stage
    : view.matches(item) && (item !== 'REJECTED' && item !== 'WITHDRAWN' || visible?.some((entry) => entry.stage === item)))

  function filter(viewKey: string, value?: Stage) {
    const next = new URLSearchParams(params)
    if (viewKey === 'all') next.delete('view')
    else next.set('view', viewKey)
    if (value) next.set('stage', value)
    else next.delete('stage')
    setParams(next)
  }

  function saveStage(saved: Application) {
    entries.setData((items) => items && [saved, ...items.filter((item) => item.id !== saved.id)])
    setSelectedId(saved.id)
    setEditing(false)
    if (!view.matches(saved.stage) || (stage && stage !== saved.stage)) filter('all')
  }

  return <div className={dashboard.page}>
    <header className={dashboard.pageHead}>
      <div><h1>投递看板</h1><p>查看各岗位的申请进度和阶段记录。</p></div>
      <Link className={dashboard.primary} to={applicationPath(jobId ?? undefined)}><PlusOutlined aria-hidden /> 准备网申草稿</Link>
    </header>
    {drafts > 0 && <section className={styles.summary} aria-label="待处理的网申草稿">
      <span className={styles.summaryIcon}><FormOutlined aria-hidden /></span>
      <div><strong>{drafts} 份网申草稿待处理</strong><p>核对简历和表单答案，在招聘网站完成投递后更新阶段。</p></div>
      <button type="button" className={dashboard.button} onClick={() => filter('all', 'DRAFT')}>查看草稿</button>
    </section>}
    {entries.error && <Alert type="error" showIcon message={entries.error}
      action={<Button size="small" onClick={entries.retry}>重试</Button>} />}
    <section className={styles.board} aria-label="按阶段查看申请">
      <header className={styles.toolbar}>
        <div className={styles.views} role="group" aria-label="投递记录范围">
          {views.map((item) => <button type="button" key={item.key}
            aria-pressed={view.key === item.key && !stage} onClick={() => filter(item.key)}>
            {item.label} {scoped && <span>{scoped.filter((entry) => item.matches(entry.stage)).length}</span>}
          </button>)}
        </div>
        <div className={styles.filters}>
          <FilterOutlined aria-hidden />
          <Select<Stage | 'ALL'> size="small" aria-label="筛选投递阶段" value={stage ?? 'ALL'}
            options={[{ value: 'ALL', label: '全部阶段' }, ...stages]}
            onChange={(value) => filter('all', value === 'ALL' ? undefined : value)} />
          <button type="button" className={dashboard.button} aria-label="刷新投递记录" onClick={() => {
            entries.retry()
            setHistoryRefresh((value) => value + 1)
          }}><ReloadOutlined aria-hidden /></button>
        </div>
      </header>
      {!visible && !entries.error && <div className={styles.boardStatus}><Spin aria-label="正在读取投递记录" /></div>}
      {visible?.length === 0 && <Empty className={styles.boardStatus} image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={entries.data?.length ? '当前筛选范围内暂无投递记录' : '还没有投递记录，可以先准备一份网申草稿。'} />}
      {!!visible?.length && <div className={styles.columns} role="region" aria-label="投递阶段列" tabIndex={0}>
        {columns.map((column) => {
          const items = visible.filter((entry) => entry.stage === column)
          return <section className={styles.column} key={column} data-stage={column} aria-label={applicationStages[column]}>
            <header className={styles.columnHead}>
              <span className={styles.dot} aria-hidden="true" /><h2>{applicationStages[column]}</h2>
              <span className={styles.count}>{items.length}</span>
            </header>
            {items.map((entry) => <button type="button" className={styles.application} key={entry.id}
              aria-pressed={entry.id === selected?.id} onClick={() => setSelectedId(entry.id)}>
              <span className={styles.company}><CompanyMark company={entry.company} />{entry.company}</span>
              <strong>{entry.jobTitle}</strong>
              <span className={styles.applicationMeta}>
                <span className={styles.material}>{entry.resumeId ? '已关联简历' : '待选简历'}</span>
                {entry.updatedAt && <time dateTime={entry.updatedAt} title={'更新于 ' + fullDate.format(new Date(entry.updatedAt))}>
                  {shortDate.format(new Date(entry.updatedAt))}
                </time>}
              </span>
            </button>)}
            {items.length === 0 && <p className={styles.emptyColumn}>暂无记录</p>}
          </section>
        })}
      </div>}
    </section>
    {selected && <section className={styles.inspect} aria-label="所选申请记录">
      <div className={styles.inspectMain}>
        <header>
          <CompanyMark company={selected.company} />
          <div><h2>{selected.jobTitle}</h2><p>{selected.company}</p></div>
          <StageLabel stage={selected.stage} />
        </header>
        <div className={styles.inspectActions}>
          <Link className={dashboard.button} to={applicationPath(selected.jobId)}>
            <FileTextOutlined aria-hidden /> 查看申请材料
          </Link>
          <button type="button" className={dashboard.primary} onClick={() => setEditing(true)}>
            <EditOutlined aria-hidden /> 更新阶段
          </button>
        </div>
      </div>
      <ApplicationHistory key={[selected.id, selected.revision, historyRefresh].join(':')} id={selected.id} jobId={selected.jobId} />
      {editing && <StageEditor key={selected.id + ':' + selected.revision} entry={selected}
        onClose={() => setEditing(false)} onSave={saveStage} />}
    </section>}
  </div>
}
