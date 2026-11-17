import { useCallback, useRef, useState } from 'react'
import { Alert, App, Button, Empty, Modal, Select, Spin } from 'antd'
import {
  AppstoreOutlined, ArrowLeftOutlined, CheckCircleOutlined, DeleteOutlined, ExpandOutlined,
  ExportOutlined, FileTextOutlined, ImportOutlined, PlusOutlined, ProfileOutlined, ThunderboltOutlined, UploadOutlined, UserOutlined,
} from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { careerApi } from '@/api/career'
import type { Resume } from '@/api/careerWorkflow'
import { resumeStudio, type ResumeEntry, type ResumeEntryKind, type ResumeProfile } from '@/api/resumeStudio'
import { entryLabels, ResumePaper, ResumePrint, resumeTemplates } from './ResumePaper'
import ResumeTemplates from './ResumeTemplates'
import { CareerPreferences, experienceMatches, ExperienceImport } from './ResumeProfileTools'
import { LegacyResumeContent, LegacyResumePrint } from './ResumeVersions'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'
import dashboard from './dashboard.module.css'
import styles from './ResumeStudio.module.css'

const kindOrder: ResumeEntryKind[] = ['education', 'project', 'internship', 'award', 'research']
const titleLabels: Record<ResumeEntryKind, string> = {
  education: '专业与学位', project: '项目名称', internship: '实习岗位', award: '奖项名称', research: '科研课题',
}

interface StudioProps {
  active: boolean
  jobId?: string
  jobTitle?: string
  sourceUrl?: string | null
  versions: Resume[]
  onGenerated: (version: Resume) => void
  onOpenVersion: (id: string) => void
}

function Field({ label, value, onChange, maxLength, type, wide, placeholder }: {
  label: string; value: string; onChange: (value: string) => void; maxLength?: number
  type?: 'email' | 'tel' | 'month'; wide?: boolean; placeholder?: string
}) {
  return <label className={styles.field} data-wide={wide || undefined}>
    <span>{label}</span><input type={type ?? 'text'} value={value} maxLength={maxLength} placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)} />
  </label>
}

async function preparePhoto(file: File) {
  if (!['image/jpeg', 'image/png'].includes(file.type) || file.size > 10 * 1024 * 1024) {
    throw new Error('请选择不超过 10 MB 的 JPG 或 PNG 照片')
  }
  const bitmap = await createImageBitmap(file).catch(() => { throw new Error('无法读取这张照片，请重新选择') })
  try {
    const scale = Math.min(1, 640 / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('无法处理这张照片，请重新选择')
    context.fillStyle = '#fff'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL('image/jpeg', 0.87)
  } finally {
    bitmap.close()
  }
}

function blankEntry(kind: ResumeEntryKind): ResumeEntry {
  return { id: crypto.randomUUID(), kind, title: '', organization: '', role: '', startMonth: '', endMonth: '', description: '' }
}

function EntryFields({ entry, onChange }: { entry: ResumeEntry; onChange: (entry: ResumeEntry) => void }) {
  function field(label: string, key: 'title' | 'organization' | 'role' | 'startMonth' | 'endMonth', type?: 'month') {
    return <Field label={label} value={entry[key]} maxLength={160} type={type}
      onChange={(value) => onChange({ ...entry, [key]: value })} />
  }
  const kind = entry.kind
  return <div className={styles.entryForm}>
    <div className={styles.fields}>
      {field(titleLabels[kind], 'title')}
      {field(kind === 'education' ? '学校' : kind === 'award' ? '颁发机构' : '单位或组织', 'organization')}
      {(kind === 'project' || kind === 'research') && field('担任角色', 'role')}
      {field(kind === 'award' ? '获奖月份' : '开始月份', 'startMonth', 'month')}
      {kind !== 'award' && field('结束月份', 'endMonth', 'month')}
    </div>
    <label className={styles.field}>
      <span>{kind === 'project' ? '项目描述' : kind === 'research' ? '研究内容与贡献' : '经历描述'}</span>
      <textarea rows={3} maxLength={12000} value={entry.description}
        placeholder="写下你实际负责的内容、采取的行动及成果。"
        onChange={(event) => onChange({ ...entry, description: event.target.value })} />
    </label>
  </div>
}

function RecruitingLink({ sourceUrl, jobId }: { sourceUrl?: string | null; jobId?: string }) {
  if (sourceUrl && /^https?:\/\//i.test(sourceUrl)) {
    return <a className={styles.online} href={sourceUrl} target="_blank" rel="noopener noreferrer">
      <ExportOutlined aria-hidden /> 前往线上投递
    </a>
  }
  return jobId ? <Link className={styles.online} to="/career/jobs"><ExportOutlined aria-hidden /> 补充招聘链接</Link> : null
}

function ResumeEditor({ initial, preferences, active, jobId, jobTitle, sourceUrl, versions, onGenerated, onOpenVersion }:
  StudioProps & { initial: ResumeProfile; preferences: ReturnType<typeof useCareerQuery<Awaited<ReturnType<typeof careerApi.profile>>>> }) {
  const { message } = App.useApp()
  const [saved, setSaved] = useState(initial)
  const [design, setDesign] = useState(() => !initial.revision && !initial.content.targetRole && preferences.data?.targetRole
    ? { ...initial.content, targetRole: preferences.data.targetRole } : initial.content)
  const [kind, setKind] = useState<ResumeEntryKind>('education')
  const [entryId, setEntryId] = useState<string>()
  const [gallery, setGallery] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [preferencesOpen, setPreferencesOpen] = useState(false)
  const action = useCareerAction()
  const experiences = useCareerQuery(careerApi.experiences.list)
  const fileInput = useRef<HTMLInputElement>(null)
  const entries = design.entries.filter((item) => item.kind === kind)
  const entry = entries.find((item) => item.id === entryId) ?? entries[0]
  const facts = experiences.data ?? []
  const fact = facts.find((item) => item.id === entry?.id)
  const importable = facts.filter((item) => !design.entries.some((current) => current.id === item.id))
  const factIsCurrent = !!(entry && fact?.confirmed
    && experienceMatches({ ...entry, sourceNote: entry.sourceNote ?? fact.sourceNote }, fact))
  const dirty = design !== saved.content
  const busy = action.saving || uploading
  const preview = { ...design, targetRole: design.targetRole || jobTitle || '' }
  const hasPrintableContent = Boolean(design.name.trim() && design.entries.some((item) => item.title.trim()))
  const selectedTemplate = resumeTemplates.find((item) => item.id === design.template)

  async function persist(confirmExperienceId?: string) {
    if (!dirty && saved.revision && !confirmExperienceId) return saved
    const content = {
      ...design, name: design.name.trim(), phone: design.phone.trim(), email: design.email.trim(),
      targetRole: design.targetRole.trim(), skills: design.skills.trim(),
      entries: design.entries.map((item) => ({
        ...item, title: item.title.trim(), organization: item.organization.trim(), role: item.role.trim(),
        description: item.description.trim(),
        sourceNote: item.sourceNote?.trim() ?? facts.find((candidate) => candidate.id === item.id)?.sourceNote ?? null,
      })),
    }
    if (content.entries.some((item) => !item.title)) throw new Error('请为每条经历填写名称')
    const result = await resumeStudio.save({ revision: saved.revision, content, confirmExperienceId })
    setSaved(result)
    setDesign(result.content)
    return result
  }

  function importExperiences(copied: ResumeEntry[]) {
    if (!copied.length) return
    setDesign((current) => ({ ...current, entries: [...current.entries, ...copied] }))
    setKind(copied[0].kind)
    setEntryId(copied[0].id)
    setImportOpen(false)
  }

  function changeField(key: 'name' | 'phone' | 'email' | 'targetRole' | 'skills', value: string) {
    setDesign((current) => ({ ...current, [key]: value }))
  }

  function addEntry() {
    const next = blankEntry(kind)
    setDesign((current) => ({ ...current, entries: [...current.entries, next] }))
    setEntryId(next.id)
  }

  if (gallery) return <ResumeTemplates design={preview} onClose={() => setGallery(false)}
    onApply={(template, showPhoto) => {
      setDesign((current) => ({ ...current, template, showPhoto }))
      setGallery(false)
    }} />

  return <>
    <div className={styles.studio}>
      <section className={styles.panel} aria-labelledby="resume-studio-profile">
        <header className={styles.panelHead}>
          <h2 id="resume-studio-profile"><ProfileOutlined aria-hidden /> 简历资料</h2>
          <div className={styles.actions}>
            <button type="button" className={dashboard.button} disabled={busy} onClick={() => setPreferencesOpen(true)}>求职档案</button>
            <button type="button" className={dashboard.button} disabled={busy || !experiences.data} onClick={() => setImportOpen(true)}>
              <ImportOutlined aria-hidden /> 导入已有经历
            </button>
          </div>
        </header>
        <fieldset disabled={busy} className={styles.form}>
          {experiences.error && <Alert type="warning" message="暂时无法读取已有经历"
            action={<Button size="small" onClick={experiences.retry}>重试</Button>} />}
          <h3>基本信息</h3>
          <div className={styles.fields}>
            <Field label="姓名" value={design.name} maxLength={80} onChange={(value) => changeField('name', value)} />
            <Field label="手机" value={design.phone} maxLength={40} type="tel" onChange={(value) => changeField('phone', value)} />
            <Field label="邮箱" value={design.email} maxLength={160} type="email" onChange={(value) => changeField('email', value)} />
            <Field label="求职方向" value={design.targetRole} placeholder={jobTitle} maxLength={160}
              onChange={(value) => changeField('targetRole', value)} />
            <Field wide label="专业技能" value={design.skills} maxLength={1000} onChange={(value) => changeField('skills', value)} />
          </div>
          <div className={styles.photoRow}>
            {design.photo ? <img src={design.photo} alt="已上传的简历照片" /> : <span className={styles.photoPlaceholder}><UserOutlined aria-hidden /></span>}
            <div><strong>简历照片</strong><small>选填 · JPG 或 PNG</small></div>
            <input ref={fileInput} type="file" accept="image/jpeg,image/png" aria-label="上传简历照片" hidden
              onChange={async (event) => {
                const file = event.currentTarget.files?.[0]
                event.currentTarget.value = ''
                if (!file) return
                setUploading(true)
                try {
                  const photo = await preparePhoto(file)
                  setDesign((current) => ({ ...current, photo }))
                } catch (error) {
                  message.error(error instanceof Error ? error.message : '照片读取失败')
                } finally {
                  setUploading(false)
                }
              }} />
            <button type="button" className={dashboard.button} onClick={() => fileInput.current?.click()}>
              <UploadOutlined aria-hidden /> {uploading ? '读取照片中' : design.photo ? '更换照片' : '上传照片'}
            </button>
            {design.photo && <>
              <button type="button" className={styles.iconButton} aria-label="移除照片"
                onClick={() => setDesign((current) => ({ ...current, photo: null }))}><DeleteOutlined aria-hidden /></button>
              <label className={styles.check}><input type="checkbox" checked={design.showPhoto}
                onChange={(event) => setDesign((current) => ({ ...current, showPhoto: event.target.checked }))} /> 在简历中显示</label>
            </>}
          </div>
          <section className={styles.experience} aria-labelledby="resume-experience">
            <h3 id="resume-experience">个人经历</h3>
            <div className={styles.kinds} role="group" aria-label="经历类别">
              {kindOrder.map((value) => <button key={value} type="button" aria-pressed={kind === value}
                onClick={() => { setKind(value); setEntryId(undefined) }}>
                {entryLabels[value]} <small>{design.entries.filter((item) => item.kind === value).length}</small>
              </button>)}
            </div>
            {entries.length > 1 && <Select aria-label="选择编辑的经历" className={styles.entrySelect} value={entry?.id}
              options={entries.map((item) => ({ label: item.title || '未命名经历', value: item.id }))}
              onChange={setEntryId} />}
            {entry ? <>
              <EntryFields key={entry.id} entry={entry} onChange={(next) => setDesign((current) => ({
                ...current, entries: current.entries.map((item) => item.id === next.id ? next : item),
              }))} />
              {entry.kind !== 'award' && <div className={styles.factBox}>
                <label className={styles.field}>
                  <span>事实依据（选填）</span>
                  <input maxLength={500} value={entry.sourceNote ?? fact?.sourceNote ?? ''}
                    placeholder="例如项目文档或实习记录"
                    onChange={(event) => {
                      const sourceNote = event.target.value
                      setDesign((current) => ({ ...current, entries: current.entries.map((item) =>
                        item.id === entry.id ? { ...item, sourceNote } : item) }))
                    }} />
                </label>
                <div className={styles.factActions}>
                  <span>{factIsCurrent ? '已确认，供备考使用' : fact?.confirmed ? '备考仍使用上次确认的内容' : '核对后可用于备考'}</span>
                  <div className={styles.actions}>
                    {fact?.confirmed && <button className={dashboard.button} type="button" disabled={busy} onClick={() => action.run(async () => {
                      const { id, ...input } = fact
                      const updated = await careerApi.experiences.save(id, { ...input, confirmed: false })
                      experiences.setData((items) => items?.map((item) => item.id === id ? updated : item))
                    })}>取消确认</button>}
                    {!factIsCurrent && <button className={dashboard.button} type="button" disabled={busy || !entry.title.trim() || !entry.description.trim()}
                      onClick={() => action.run(async () => {
                        await persist(entry.id)
                        experiences.retry()
                        message.success('已确认经历，可用于备考')
                      })}>{fact?.confirmed ? '确认更新' : '确认并用于备考'}</button>}
                  </div>
                </div>
              </div>}
              <div className={styles.entryActions}>
                <button type="button" onClick={addEntry} disabled={design.entries.length >= 40}><PlusOutlined aria-hidden /> 添加{entryLabels[kind]}</button>
                <button type="button" onClick={() => setDesign((current) => ({
                  ...current, entries: current.entries.filter((item) => item.id !== entry.id),
                }))}><DeleteOutlined aria-hidden /> 移出简历</button>
              </div>
            </> : <button type="button" className={styles.addEmpty} disabled={design.entries.length >= 40} onClick={addEntry}>
              <PlusOutlined aria-hidden /> 添加{entryLabels[kind]}
            </button>}
          </section>
        </fieldset>
        <footer className={styles.panelFoot}>
          <span role="status">{dirty ? '资料有未保存修改' : saved.revision > 0 ? <><CheckCircleOutlined aria-hidden /> 资料草稿已保存</> : '填写资料后可生成简历'}</span>
          <div className={styles.actions}>
            <button type="button" className={dashboard.button} disabled={busy || !dirty} onClick={() => action.run(async () => { await persist() })}>保存资料</button>
            <button type="button" className={dashboard.primary} disabled={busy || !hasPrintableContent} onClick={() => action.run(async () => {
              const profile = await persist()
              const version = await action.submit('resume-studio', { jobId: jobId ?? null, revision: profile.revision }, resumeStudio.generate)
              onGenerated(version)
              message.success('已生成简历版本')
            })}><ThunderboltOutlined aria-hidden /> 生成简历</button>
          </div>
        </footer>
      </section>
      <section className={styles.panel} aria-labelledby="resume-studio-preview">
        <header className={styles.panelHead}>
          <h2 id="resume-studio-preview"><FileTextOutlined aria-hidden /> 简历预览</h2>
          <div className={styles.actions}>
            <span className={styles.paperMeta}>A4</span>
            <button type="button" className={dashboard.button} onClick={() => setExpanded(true)}><ExpandOutlined aria-hidden /> 放大预览</button>
          </div>
        </header>
        <div className={styles.templateBar}>
          <div><strong>{selectedTemplate?.label}</strong><small>{selectedTemplate?.description}</small></div>
          <button type="button" className={dashboard.button} disabled={busy} onClick={() => setGallery(true)}><AppstoreOutlined aria-hidden /> 更换模板</button>
        </div>
        <div className={styles.previewSurface}><ResumePaper design={preview} /></div>
        <footer className={styles.panelFoot}>
          {versions.length ? <Select size="small" aria-label="查看历史简历版本" placeholder="查看历史版本" className={styles.versionSelect}
            options={versions.map((item) => ({ label: item.jobTitle + ' · ' + new Date(item.createdAt).toLocaleString('zh-CN'), value: item.id }))}
            onChange={onOpenVersion} /> : <span />}
          <div className={styles.actions}>
            {active && hasPrintableContent && <ResumePrint design={preview} />}
            <RecruitingLink sourceUrl={sourceUrl} jobId={jobId} />
          </div>
        </footer>
      </section>
    </div>
    {active && importOpen && <ExperienceImport entries={importable} remaining={40 - design.entries.length}
      onClose={() => setImportOpen(false)} onImport={importExperiences} />}
    {active && preferencesOpen && (preferences.data !== undefined
      ? <CareerPreferences profile={preferences.data} onSave={preferences.setData} onClose={() => setPreferencesOpen(false)} />
      : <Modal open title="求职档案" footer={null} onCancel={() => setPreferencesOpen(false)}>
        {preferences.error ? <Alert type="error" message={preferences.error}
          action={<Button onClick={preferences.retry}>重试</Button>} /> : <Spin aria-label="正在读取求职档案" />}
      </Modal>)}
    {active && expanded && <Modal open title="A4 简历预览" onCancel={() => setExpanded(false)} footer={null} width={760}>
      <div className={styles.previewSurface}><ResumePaper design={preview} /></div>
    </Modal>}
  </>
}

export default function ResumeStudio(props: StudioProps) {
  const profile = useCareerQuery(resumeStudio.profile)
  const preferences = useCareerQuery(careerApi.profile)
  if (profile.error) return <Alert type="error" showIcon message={profile.error} action={<Button onClick={profile.retry}>重试</Button>} />
  return profile.data && (profile.data.revision || preferences.data !== undefined || preferences.error)
    ? <ResumeEditor {...props} initial={profile.data} preferences={preferences} /> : <Spin aria-label="正在读取简历资料" />
}

interface PreviewProps {
  id: string; version?: Resume; sourceUrl?: string | null; onClose: () => void; onUse?: () => void
}

export function ResumeVersionPreview(props: PreviewProps) {
  const { version, sourceUrl, onClose, onUse } = props
  if (!version || version.template) return <ComposedResumePreview {...props} />
  return <section className={styles.panel} aria-label="历史简历版本">
    <header className={styles.panelHead}>
      <h2><FileTextOutlined aria-hidden /> {version.jobTitle}</h2>
      <button type="button" className={dashboard.button} onClick={onClose}><ArrowLeftOutlined aria-hidden /> 返回简历制作</button>
    </header>
    <div className={styles.legacyPreview}><LegacyResumeContent resume={version} /></div>
    <footer className={styles.panelFoot}>
      <span>已保存的历史版本</span>
      <div className={styles.actions}>
        <LegacyResumePrint resume={version} />
        <RecruitingLink sourceUrl={sourceUrl} jobId={version.jobId ?? undefined} />
        {onUse && <button type="button" className={dashboard.primary} onClick={onUse}>用于网申</button>}
      </div>
    </footer>
  </section>
}

function ComposedResumePreview({ id, version, sourceUrl, onClose, onUse }: PreviewProps) {
  const load = useCallback((signal: AbortSignal) => resumeStudio.composition(id, signal), [id])
  const composition = useCareerQuery(load)
  const design = composition.data
  return <section className={styles.panel} aria-labelledby="generated-resume-preview">
    <header className={styles.panelHead}>
      <h2 id="generated-resume-preview"><FileTextOutlined aria-hidden /> {version?.jobTitle ?? '已保存简历'}</h2>
      <button type="button" className={dashboard.button} onClick={onClose}><ArrowLeftOutlined aria-hidden /> 返回简历制作</button>
    </header>
    {composition.error ? <Alert type="error" showIcon message={composition.error}
      action={<Button onClick={composition.retry}>重试</Button>} />
      : design ? <div className={styles.previewSurface}><ResumePaper design={design} /></div>
        : <Empty description={<Spin aria-label="正在读取简历版本" />} />}
    {design && <footer className={styles.panelFoot}>
      <span className={styles.paperMeta}>A4 · {resumeTemplates.find((item) => item.id === design.template)?.label}</span>
      <div className={styles.actions}>
        <ResumePrint design={design} />
        <RecruitingLink sourceUrl={sourceUrl} jobId={version?.jobId ?? undefined} />
        {onUse && <button type="button" className={dashboard.primary} onClick={onUse}>用于网申</button>}
      </div>
    </footer>}
  </section>
}

