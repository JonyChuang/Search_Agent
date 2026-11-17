import { createPortal } from 'react-dom'
import { PrinterOutlined } from '@ant-design/icons'
import type { ResumeDesign, ResumeEntryKind, ResumeTemplate } from '@/api/resumeStudio'
import dashboard from './dashboard.module.css'
import styles from './ResumeStudio.module.css'

export const resumeTemplates: { id: ResumeTemplate; label: string; description: string; columns: 1 | 2 }[] = [
  { id: 'classic', label: '经典单栏', description: '通用岗位 · 清晰分区', columns: 1 },
  { id: 'tech', label: '技术简洁', description: '研发岗位 · 项目优先', columns: 1 },
  { id: 'campus', label: '校园招聘', description: '校招与实习 · 教育优先', columns: 1 },
  { id: 'modern', label: '现代双栏', description: '经历主栏 · 技能侧栏', columns: 2 },
  { id: 'academic', label: '研究生学术', description: '科研类岗位 · 学历与研究', columns: 1 },
  { id: 'mono', label: '黑白打印', description: '线下投递 · 灰度排版', columns: 1 },
]

export const entryLabels: Record<ResumeEntryKind, string> = {
  education: '教育经历', project: '项目经历', internship: '实习经历', award: '获奖情况', research: '科研经历',
}

type Section = ResumeEntryKind | 'skills'
const normalOrder: Section[] = ['education', 'project', 'research', 'internship', 'award', 'skills']
const orders: Partial<Record<ResumeTemplate, Section[]>> = {
  tech: ['project', 'internship', 'skills', 'research', 'education', 'award'],
  campus: ['education', 'internship', 'project', 'research', 'award', 'skills'],
  academic: ['education', 'research', 'project', 'award', 'skills', 'internship'],
  modern: ['project', 'internship', 'research', 'education'],
}

export function ResumePaper({ design }: { design: ResumeDesign }) {
  const { name, phone, email, targetRole, template, showPhoto, photo } = design
  const photoSource = showPhoto && photo && /^data:image\/(?:jpeg|png);base64,/.test(photo) ? photo : null
  const portrait = photoSource && <img className={styles.portrait} src={photoSource} alt="简历照片" />
  const identity = <div>
    <h2>{name.trim() || '姓名'}</h2>
    {targetRole && <p className={styles.paperRole}>{targetRole}</p>}
    {(phone || email) && <div className={styles.contact}>{phone && <span>{phone}</span>}{email && <span>{email}</span>}</div>}
  </div>

  function sections(order: Section[]) {
    return order.map((kind) => {
      if (kind === 'skills') {
        return design.skills.trim() && <section key={kind} className={styles.paperSection}><h3>专业技能</h3><p>{design.skills}</p></section>
      }
      const entries = design.entries.filter((item) => item.kind === kind && item.title.trim())
      if (!entries.length) return null
      return <section key={kind} className={styles.paperSection}>
        <h3>{entryLabels[kind]}</h3>
        {entries.map((item) => <div className={styles.paperEntry} key={item.id}>
          <div className={styles.entryHeading}>
            <strong>{[item.title, item.organization, item.role].filter(Boolean).join(' · ')}</strong>
            {(item.startMonth || item.endMonth) && <span>{[item.startMonth, item.endMonth].filter(Boolean)
              .map((month) => month.replace('-', '.')).join(' — ')}</span>}
          </div>
          {item.description && <p>{item.description}</p>}
        </div>)}
      </section>
    })
  }

  return <article className={styles.paper} data-template={template} aria-label="A4 简历预览">
    {template === 'modern' ? <div className={styles.paperColumns}>
      <aside className={styles.paperRail}>{portrait}{identity}{sections(['skills', 'award'])}</aside>
      <div className={styles.paperMain}>{sections(orders.modern ?? normalOrder)}</div>
    </div> : <div className={styles.paperInner}>
      <header className={styles.paperHeader}>{identity}{portrait}</header>
      {sections(orders[template] ?? normalOrder)}
    </div>}
  </article>
}

export function ResumePrint({ design }: { design: ResumeDesign }) {
  return <>
    <button type="button" className={dashboard.button} onClick={async () => {
      const sheet = document.querySelector('.' + styles.printRoot)
      await document.fonts.ready
      await Promise.all(Array.from(sheet?.querySelectorAll('img') ?? [], (image) => image.decode().catch(() => undefined)))
      window.print()
    }}><PrinterOutlined aria-hidden /> 打印 / 保存为 PDF</button>
    {createPortal(<div className={styles.printRoot}><ResumePaper design={design} /></div>, document.body)}
  </>
}

