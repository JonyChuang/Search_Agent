import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Alert, App, Button, Input, InputNumber, Modal, Select, Spin, Tag } from 'antd'
import {
  ArrowRightOutlined, BankOutlined, CheckCircleOutlined, CheckOutlined, CopyOutlined, DownloadOutlined,
  ExclamationCircleOutlined, ExportOutlined, FileDoneOutlined, FilePdfOutlined, FileTextOutlined,
  FolderOpenOutlined, FormOutlined, GlobalOutlined, LinkOutlined, PlusOutlined, ProfileOutlined,
  RightOutlined, SaveOutlined, UploadOutlined,
} from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { applicationWorkspace, type ApplicationAnswers, type ApplicationQuestion, type ApplicationReceipt,
  type ApplicationWorkspaceState, type MaterialItem } from '@/api/applicationWorkspace'
import type { JobInput } from '@/api/career'
import { applicationStages, careerWorkflow, type Application, type Resume } from '@/api/careerWorkflow'
import { resumeStudio } from '@/api/resumeStudio'
import { copyText } from '@/utils/clipboard'
import { ResumeVersionPreview } from './ResumeStudio'
import { MaterialDialog, QuestionDialog, ReceiptDialog, webAddress } from './ApplicationMaterialDialogs'
import GreenhouseApplicationPanel, { supportsGreenhouse } from './GreenhouseApplicationPanel'
import { jobPath } from './paths'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'
import dashboard from './dashboard.module.css'
import styles from './applicationMaterials.module.css'

const suggestions: MaterialItem[] = [
  { id: '00000000-0000-0000-0000-000000000001', label: '成绩单', kind: 'FILE', required: false },
  { id: '00000000-0000-0000-0000-000000000002', label: '作品集或 GitHub 链接', kind: 'LINK', required: false },
]
const steps = ['核对岗位', '准备材料', '官网提交', '记录回执']
const dateFormat = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })

interface Props {
  jobId: string
  job?: JobInput
  resumes: Resume[]
  preferredResumeId?: string
  onSave: (saved: Application) => void
  onMakeResume: () => void
}

function Panel({ label, icon, action, children }: {
  label: string; icon: ReactNode; action?: ReactNode; children: ReactNode
}) {
  return <section className={styles.panel} aria-label={label}>
    <header className={styles.panelHead}><h2>{icon}{label}</h2>{action}</header>
    {children}
  </section>
}

function Editor({ initial, jobId, job, resumes, preferredResumeId, onSave, onMakeResume }: Props & {
  initial: ApplicationWorkspaceState
}) {
  const { message } = App.useApp()
  const action = useCareerAction()
  const [saved, setSaved] = useState(initial)
  const [form, setForm] = useState(initial.workspace.content.form)
  const [attachments, setAttachments] = useState(initial.workspace.content.attachments)
  const [legacy, setLegacy] = useState(initial.application?.answers ?? '')
  const [resumeId, setResumeId] = useState(preferredResumeId ?? initial.application?.resumeId ?? undefined)
  const [dirty, setDirty] = useState(Boolean(preferredResumeId && preferredResumeId !== initial.application?.resumeId))
  const [pending, setPending] = useState<Record<string, File>>({})
  const [materialDialog, setMaterialDialog] = useState<MaterialItem>()
  const [questionDialog, setQuestionDialog] = useState<ApplicationQuestion>()
  const [preview, setPreview] = useState(false)
  const [selectResume, setSelectResume] = useState(false)
  const [personal, setPersonal] = useState(false)
  const [receiptDialog, setReceiptDialog] = useState(false)

  useEffect(() => {
    if (preferredResumeId) {
      setResumeId(preferredResumeId)
      if (preferredResumeId !== initial.application?.resumeId) setDirty(true)
    }
  }, [preferredResumeId, initial.application?.resumeId])

  const entry = saved.application
  const source = webAddress(job ? job.sourceUrl : entry?.sourceUrl)
  const selectedResume = resumes.find((resume) => resume.id === resumeId)
  const hasAdvanced = entry && entry.stage !== 'DRAFT'
  const company = job?.company ?? entry?.company
  const title = job?.title ?? entry?.jobTitle
  const jobLabel = [company, title].filter(Boolean).join(' · ')
  const board = '/career/applications?' + new URLSearchParams({ job: jobId })
  const files = saved.workspace.files
  const allItems = [...attachments, ...suggestions.filter((suggestion) =>
    !attachments.some((item) => item.id === suggestion.id))]
  const fileAttached = (id?: string | null) => Boolean(id && (pending[id] || files.some((file) => file.id === id)))
  const missing = attachments.filter((item) => item.required &&
    (item.kind === 'FILE' ? !fileAttached(item.fileId) : !webAddress(item.url)))
  const hasAnswers = [form.name, form.phone, form.email, form.education, form.startDate, form.duration, form.motivation,
    legacy, ...form.questions.map((item) => item.answer)].some((item) => item?.trim()) || Boolean(form.weeklyDays)
  const missingAnswer = form.questions.some((item) => item.required && !item.answer?.trim())
  const checks = [
    { label: '招聘入口', ready: !!source, result: source ? '已记录' : '待补招聘链接' },
    { label: '简历版本', ready: !!selectedResume, result: selectedResume ? '已关联' : '待选择' },
    { label: '表单答案', ready: hasAnswers && !missingAnswer,
      result: missingAnswer ? '有岗位问题待填写' : hasAnswers ? '已填写' : '待填写' },
    { label: '岗位要求的附件', ready: missing.length === 0,
      result: missing.length ? '缺' + missing.map((item) => item.label).join('、')
        : attachments.some((item) => item.required) ? '已备齐' : '暂无已标记要求' },
  ]
  const ready = checks.filter((item) => item.ready).length
  const step = hasAdvanced ? 4 : receiptDialog ? 3 : !source ? 0 : ready === checks.length && !dirty && entry ? 2 : 1
  const availability = [form.weeklyDays ? `每周 ${form.weeklyDays} 天` : '', form.duration].filter(Boolean).join(' · ')

  function field<K extends keyof ApplicationAnswers>(key: K, value: ApplicationAnswers[K]) {
    setForm((previous) => ({ ...previous, [key]: value }))
    setDirty(true)
  }

  async function copy(value?: string | null) {
    if (value?.trim() && await copyText(value)) message.success('已复制')
    else message.error('复制失败，请手动选择文本')
  }

  function copyField(label: string, value?: string | null) {
    return <button type="button" className={styles.linkButton} aria-label={'复制' + label}
      disabled={!value?.trim()} onClick={() => void copy(value)}><CopyOutlined aria-hidden />复制</button>
  }

  function setAttachment(item: MaterialItem) {
    setAttachments((items) => items.some((value) => value.id === item.id)
      ? items.map((value) => value.id === item.id ? item : value) : [...items, item])
    setDirty(true)
  }

  function selectFile(item: MaterialItem, file?: File) {
    if (!file) return
    if (file.size === 0 || file.size > 10 * 1024 * 1024 || !/\.(pdf|jpe?g|png)$/i.test(file.name)) {
      message.error('请选择不超过 10 MB 的 PDF、JPG 或 PNG 文件')
      return
    }
    if (!item.fileId && attachments.filter((value) => value.fileId).length >= 6) {
      message.error('每份草稿最多保存 6 个文件')
      return
    }
    if (!attachments.some((value) => value.id === item.id) && attachments.length >= 12) {
      message.error('每份草稿最多保存 12 个附件项目')
      return
    }
    const id = crypto.randomUUID()
    setPending((previous) => {
      const next = { ...previous, [id]: file }
      if (item.fileId) delete next[item.fileId]
      return next
    })
    setAttachment({ ...item, fileId: id })
  }

  function removeAttachment(item: MaterialItem) {
    setAttachments((items) => items.filter((value) => value.id !== item.id))
    if (item.fileId) {
      const fileId = item.fileId
      setPending((previous) => {
        const next = { ...previous }
        delete next[fileId]
        return next
      })
    }
    setDirty(true)
    setMaterialDialog(undefined)
  }

  function importResume() {
    if (!selectedResume) return
    void action.run(async () => {
      const signal = new AbortController().signal
      const design = selectedResume.template
        ? await resumeStudio.composition(selectedResume.id, signal)
        : (await resumeStudio.profile(signal)).content
      const education = (selectedResume.template ? design.entries.filter((item) => item.kind === 'education')
        : selectedResume.evidence.filter((item) => item.type === 'education'))
        .map((item) => [item.organization, item.title, [item.startMonth, item.endMonth].filter(Boolean).join(' 至 ')]
          .filter(Boolean).join(' · ')).join('\n')
      if (!design.name && !design.phone && !design.email && !education) {
        message.info('所选简历暂没有可带入的信息，可以手动填写')
        return
      }
      setForm((previous) => ({
        ...previous, name: previous.name?.trim() || design.name, phone: previous.phone?.trim() || design.phone,
        email: previous.email?.trim() || design.email, education: previous.education?.trim() || education,
      }))
      setPersonal(true)
      setDirty(true)
      message.success('已带入可用资料，请核对后保存')
    })
  }

  async function saveDraft() {
    if (!dirty && entry) return entry
    const result = await action.submit(`application-workspace:${jobId}`, {
      revision: entry?.revision ?? 0, resumeId: resumeId ?? null, answers: legacy, content: { form, attachments },
    }, (input) => applicationWorkspace.save(jobId, input, pending))
    if (!result.application) throw new Error('服务未返回网申草稿，请重试')
    setSaved(result)
    setPending({})
    setDirty(false)
    onSave(result.application)
    return result.application
  }

  function recordReceipt(receipt: ApplicationReceipt, note?: string) {
    void action.run(async () => {
      const current = await saveDraft()
      const updated = await careerWorkflow.updateStage(current.id, { revision: current.revision, stage: 'SUBMITTED', receipt, note })
      setSaved((previous) => ({ ...previous, application: updated, receipt }))
      onSave(updated)
      setReceiptDialog(false)
      message.success('已记录投递回执')
    })
  }

  return <div className={styles.workspace}>
    <section className={styles.job} aria-label="投递岗位">
      <span className={styles.jobIcon}><BankOutlined aria-hidden /></span>
      <div><h2>{jobLabel}</h2><p><GlobalOutlined aria-hidden /> {source ? `招聘入口 · ${source.hostname}` : '待补招聘链接'}</p></div>
      <Tag color={hasAdvanced ? 'blue' : 'purple'}>{hasAdvanced ? applicationStages[entry.stage] : '待投递'}</Tag>
      <Link className={dashboard.button} to={job ? jobPath(jobId, 'details') : '/career/jobs'}>
        <ArrowRightOutlined aria-hidden />{source && job ? '查看岗位' : '管理岗位'}
      </Link>
    </section>
    <ol className={styles.steps} aria-label="网申准备进度">
      {steps.map((label, index) => <li key={label} data-step={index < step ? 'done' : index === step ? 'current' : 'next'}
        aria-current={index === step ? 'step' : undefined}>
        <span>{index < step ? <CheckOutlined aria-hidden /> : index + 1}</span><strong>{label}</strong>
        {index < steps.length - 1 && <RightOutlined aria-hidden />}
      </li>)}
    </ol>

    <fieldset className={styles.fieldset} disabled={action.saving}><div className={styles.grid}>
      <div className={styles.column}>
        <Panel label="简历与附件" icon={<FolderOpenOutlined aria-hidden />}
          action={<button type="button" className={styles.linkButton} disabled={action.saving || attachments.length >= 12}
            onClick={() => setMaterialDialog({ id: crypto.randomUUID(), kind: 'FILE', label: '', required: false })}>
            <PlusOutlined aria-hidden />添加其他附件</button>}>
          <div className={styles.fileList}>
            <div className={styles.fileRow + ' ' + styles.selectedFile}>
              <span className={styles.fileIcon + ' ' + styles.pdf}><FilePdfOutlined aria-hidden /></span>
              <div><strong>{selectedResume ? selectedResume.jobTitle + ' · 求职简历' : '岗位简历'}</strong>
                {selectedResume && <Tag color="success">已关联</Tag>}
                <p>{selectedResume ? `版本保存于 ${dateFormat.format(new Date(selectedResume.createdAt))}` : '请选择此岗位已保存的版本'}</p>
              </div>
              <div className={styles.rowActions}>
                {selectedResume && <button type="button" className={styles.linkButton} onClick={() => setPreview(true)}>预览</button>}
                <button type="button" className={dashboard.button} disabled={action.saving} onClick={() => setSelectResume(true)}>
                  {selectedResume ? '更换' : '选择简历'}
                </button>
              </div>
            </div>
            {allItems.map((item) => {
              const id = item.fileId ?? ''
              const local = pending[id]
              const file = files.find((value) => value.id === id)
              const link = webAddress(item.url)
              return <div className={styles.fileRow} key={item.id}>
                <span className={styles.fileIcon} data-missing={item.required && !fileAttached(id) && !link || undefined}>
                  {item.kind === 'FILE' ? <FileTextOutlined aria-hidden /> : <LinkOutlined aria-hidden />}
                </span>
                <div><strong>{item.label}</strong><Tag color={item.required ? 'gold' : undefined}>
                  {item.required ? '岗位要求' : '按岗位提供'}
                </Tag><p>{local ? local.name + ' · 待保存' : file?.name ?? link?.hostname ??
                  (item.kind === 'FILE' ? '待添加文件' : '待添加链接')}</p></div>
                <div className={styles.rowActions}>
                  {file && entry && <button type="button" className={styles.linkButton} disabled={action.saving}
                    onClick={() => void action.run(() => applicationWorkspace.download(entry.id, file))}>
                    <DownloadOutlined aria-hidden />下载</button>}
                  {link && <a className={styles.linkButton} href={link.href} target="_blank" rel="noreferrer">打开链接</a>}
                  {item.kind === 'FILE' && <label className={styles.upload + ' ' + dashboard.button}>
                    <UploadOutlined aria-hidden />{local || file ? '更换附件' : '添加附件'}
                    <input type="file" aria-label={`上传${item.label}`} accept=".pdf,.jpg,.jpeg,.png"
                      disabled={action.saving} onChange={(event) => {
                        selectFile(item, event.target.files?.[0])
                        event.target.value = ''
                      }} />
                  </label>}
                  <button type="button" className={styles.linkButton} disabled={action.saving}
                    aria-label={'编辑' + item.label} onClick={() => setMaterialDialog(item)}>
                    {item.kind === 'LINK' && !link ? '添加链接' : '编辑'}</button>
                </div>
              </div>
            })}
            <p className={styles.hint}>支持 PDF、JPG 和 PNG，单个文件最多 10 MB。按招聘页要求添加材料。</p>
          </div>
        </Panel>
        <Panel label="表单答案" icon={<FormOutlined aria-hidden />}
          action={<button type="button" className={styles.linkButton} disabled={action.saving || form.questions.length >= 12}
            onClick={() => setQuestionDialog({ id: crypto.randomUUID(), label: '', required: false })}>
            <PlusOutlined aria-hidden />添加岗位问题</button>}>
          <div className={styles.answers}>
            <div className={styles.personal}>
              <ProfileOutlined aria-hidden /><strong>个人信息与教育经历</strong>
              <div className={styles.rowActions}>
                <button className={styles.linkButton} type="button" disabled={!selectedResume || action.saving}
                  onClick={importResume}>从简历带入</button>
                <button className={styles.linkButton} type="button" aria-expanded={personal}
                  onClick={() => setPersonal(!personal)}>{personal ? '收起' : '核对并编辑'}</button>
              </div>
            </div>
            {personal && <div className={styles.personalFields}>
              <div className={styles.field}><label htmlFor="application-name">姓名</label>
                <div><Input id="application-name" value={form.name ?? ''} onChange={(e) => field('name', e.target.value)} maxLength={80} />
                  {copyField('姓名', form.name)}</div></div>
              <div className={styles.field}><label htmlFor="application-phone">手机号</label>
                <div><Input id="application-phone" type="tel" value={form.phone ?? ''}
                  onChange={(e) => field('phone', e.target.value)} maxLength={40} />{copyField('手机号', form.phone)}</div></div>
              <div className={styles.field}><label htmlFor="application-email">邮箱</label>
                <div><Input id="application-email" type="email" value={form.email ?? ''}
                  onChange={(e) => field('email', e.target.value)} maxLength={160} />{copyField('邮箱', form.email)}</div></div>
              <div className={styles.field + ' ' + styles.wide}><label htmlFor="application-education">教育经历</label>
                <div><Input.TextArea id="application-education" rows={2} value={form.education ?? ''}
                  onChange={(e) => field('education', e.target.value)} maxLength={2000} />{copyField('教育经历', form.education)}</div></div>
            </div>}
            <div className={styles.fieldPair}>
              <div className={styles.field}><label htmlFor="application-start-date">最早到岗时间</label>
                <div><Input id="application-start-date" type="date" value={form.startDate ?? ''}
                  onChange={(e) => field('startDate', e.target.value || null)} />{copyField('到岗时间', form.startDate)}</div></div>
              <fieldset className={styles.field}><legend>每周出勤 / 实习时长</legend><div>
                <InputNumber aria-label="每周出勤天数" min={1} max={7} precision={0} placeholder="天/周"
                  value={form.weeklyDays ?? null} onChange={(value) => field('weeklyDays', value)} />
                <Input aria-label="实习时长" value={form.duration ?? ''} placeholder="例如 4 个月"
                  onChange={(e) => field('duration', e.target.value)} maxLength={80} />
                {copyField('出勤与时长', availability)}
              </div></fieldset>
            </div>
            <div className={styles.field}><label htmlFor="application-motivation">求职动机</label>
              <div><Input.TextArea id="application-motivation" autoSize={{ minRows: 2, maxRows: 5 }}
                value={form.motivation ?? ''} onChange={(e) => field('motivation', e.target.value)}
                maxLength={2500} placeholder="按岗位要求准备一段回答" />{copyField('求职动机', form.motivation)}</div></div>
            {form.questions.map((question) => <div className={styles.question} key={question.id}>
              <div><strong>{question.label}</strong>{question.required && <Tag color="gold">岗位要求</Tag>}
                <p>{question.answer || '待填写答案'}</p></div>
              <div className={styles.rowActions}>
                <button type="button" className={styles.linkButton} onClick={() => setQuestionDialog(question)}>编辑</button>
                {copyField(question.label, question.answer)}
              </div>
            </div>)}
            <details className={styles.extra} open={legacy ? true : undefined}>
              <summary>{initial.application?.answers ? '原草稿补充' : '其他表单备注'}</summary>
              <Input.TextArea aria-label="其他表单备注" autoSize={{ minRows: 2, maxRows: 6 }} value={legacy}
                onChange={(e) => { setLegacy(e.target.value); setDirty(true) }} maxLength={12000} />
              {copyField('其他表单备注', legacy)}
            </details>
          </div>
        </Panel>
      </div>

      <aside className={styles.column} aria-label="投递前核对与回执">
        <section className={styles.checks} aria-label="投递前核对">
          <header><div><h2>投递前核对</h2><span><b>{ready}</b> / {checks.length} 项</span></div>
            <progress max={checks.length} value={ready} aria-label="投递前核对进度" /></header>
          <ul>{checks.map(({ label, ready, result }) => <li key={label} data-ready={ready}>
            {ready ? <CheckCircleOutlined aria-hidden /> : <ExclamationCircleOutlined aria-hidden />}
            <strong>{label}</strong><span>{result}</span></li>)}</ul>
          <p className={styles.hint}>实际必填项以招聘页面为准。</p>
        </section>
        {supportsGreenhouse(source) && !hasAdvanced && <Panel label="Greenhouse 官网填表" icon={<GlobalOutlined aria-hidden />}>
          <div className={styles.receipt}>
            <GreenhouseApplicationPanel applicationId={entry?.id} ready={!!selectedResume && !!form.email?.trim() && !action.saving}
              save={saveDraft} refresh={() => void action.run(async () => {
                const result = await applicationWorkspace.get(jobId)
                if (result.application?.stage === 'SUBMITTED') {
                  setSaved(result)
                  onSave(result.application)
                }
              })} />
          </div>
        </Panel>}
        <Panel label="投递回执" icon={<FileDoneOutlined aria-hidden />}>
          <div className={styles.receipt}>
            <Tag color={hasAdvanced ? 'success' : undefined}>{hasAdvanced ? applicationStages[entry.stage] : '待提交'}</Tag>
            {hasAdvanced && saved.receipt ? <>
              <p>投递时间 · {dateFormat.format(new Date(saved.receipt.submittedAt))}</p>
              {saved.receipt.applicationNumber && <p>申请编号 · {saved.receipt.applicationNumber}</p>}
            </> : !hasAdvanced && <p>官网确认提交后，可记录实际投递时间和申请编号。</p>}
            {hasAdvanced ? <Link className={styles.linkButton} to={board}>查看本岗位投递记录 <ArrowRightOutlined aria-hidden /></Link>
              : <button type="button" className={styles.linkButton} disabled={action.saving} onClick={() => setReceiptDialog(true)}>
                <ArrowRightOutlined aria-hidden />记录投递结果</button>}
          </div>
        </Panel>
      </aside>
    </div></fieldset>

    <footer className={styles.actions}>
      <span><SaveOutlined aria-hidden /> {dirty ? '网申草稿有未保存修改' : entry ? '网申材料已保存' : '网申草稿待保存'}</span>
      <div className={styles.rowActions}>
        <Button icon={<SaveOutlined />} loading={action.saving} onClick={() => void action.run(async () => {
          await saveDraft()
          message.success('已保存网申材料')
        })}>保存网申草稿</Button>
        {source ? <a className={dashboard.primary} href={source.href} target="_blank" rel="noreferrer">
          <ExportOutlined aria-hidden />打开招聘官网</a>
          : <Link className={dashboard.button} to={job ? jobPath(jobId, 'management') : '/career/jobs'}>
            <LinkOutlined aria-hidden />补充招聘链接</Link>}
      </div>
    </footer>

    {selectResume && <Modal open title="选择此岗位的简历版本" onCancel={() => setSelectResume(false)} footer={null}>
      <Select aria-label="此岗位的简历版本" allowClear value={resumeId} placeholder="选择已保存的简历版本"
        style={{ width: '100%' }} options={resumes.map((resume) => ({
          value: resume.id, label: resume.jobTitle + ' · ' + dateFormat.format(new Date(resume.createdAt)),
        }))} onChange={(value) => { setResumeId(value); setDirty(true); setSelectResume(false) }} />
      <Button type="link" onClick={() => { setSelectResume(false); onMakeResume() }}>前往简历制作</Button>
    </Modal>}
    {preview && selectedResume && <Modal open title="简历预览" width={920} footer={null} onCancel={() => setPreview(false)}>
      <ResumeVersionPreview id={selectedResume.id} version={selectedResume} onClose={() => setPreview(false)} />
    </Modal>}
    {materialDialog && <MaterialDialog item={materialDialog} existing={attachments.some((item) => item.id === materialDialog.id)}
      onClose={() => setMaterialDialog(undefined)} onSave={(item) => {
        if (!attachments.some((value) => value.id === item.id) && attachments.length >= 12) {
          message.error('每份草稿最多保存 12 个附件项目')
          return
        }
        setAttachment(item)
        setMaterialDialog(undefined)
      }} onRemove={() => removeAttachment(materialDialog)} />}
    {questionDialog && <QuestionDialog item={questionDialog} existing={form.questions.some((item) => item.id === questionDialog.id)}
      onClose={() => setQuestionDialog(undefined)} onSave={(item) => {
        field('questions', form.questions.some((value) => value.id === item.id)
          ? form.questions.map((value) => value.id === item.id ? item : value) : [...form.questions, item])
        setQuestionDialog(undefined)
      }} onRemove={() => {
        field('questions', form.questions.filter((item) => item.id !== questionDialog.id))
        setQuestionDialog(undefined)
      }} />}
    {receiptDialog && <ReceiptDialog saving={action.saving} onClose={() => {
      if (!action.saving) setReceiptDialog(false)
    }} onSave={recordReceipt} />}
  </div>
}

export default function ApplicationMaterialsEditor(props: Props) {
  const load = useCallback((signal: AbortSignal) => applicationWorkspace.get(props.jobId, signal), [props.jobId])
  const state = useCareerQuery(load)
  if (state.error) return <Alert type="error" showIcon message={state.error}
    action={<Button size="small" onClick={state.retry}>重试</Button>} />
  return state.data ? <Editor {...props} initial={state.data} /> : <Spin aria-label="正在读取申请材料" />
}
