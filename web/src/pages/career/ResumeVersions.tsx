import { createPortal } from 'react-dom'
import { PrinterOutlined } from '@ant-design/icons'
import type { Resume } from '@/api/careerWorkflow'
import dashboard from './dashboard.module.css'
import './resume-print.css'

export function LegacyResumeContent({ resume, print = false }: { resume: Resume; print?: boolean }) {
  return <article className={print ? 'career-print-sheet' : 'career-resume-preview'}>
    <h2>岗位简历草稿</h2>
    <p>{[resume.company, resume.jobTitle].filter(Boolean).join(' · ')}</p>
    {resume.evidence.map((item) => <section key={item.id}>
      <h3>{item.title}</h3>
      <p>{[item.organization, [item.startMonth, item.endMonth].filter(Boolean).join(' 至 ')].filter(Boolean).join(' · ')}</p>
      <p>{item.description}</p>
      {!print && item.sourceNote && <small>事实依据 · {item.sourceNote}</small>}
    </section>)}
  </article>
}

export function LegacyResumePrint({ resume }: { resume: Resume }) {
  return <>
    <button type="button" className={dashboard.button} onClick={() => window.print()}>
      <PrinterOutlined aria-hidden /> 打印 / 保存为 PDF
    </button>
    {createPortal(<LegacyResumeContent resume={resume} print />, document.body)}
  </>
}
