import { useState } from 'react'
import { AppstoreOutlined, ArrowLeftOutlined, CheckOutlined, FileTextOutlined, InfoCircleOutlined } from '@ant-design/icons'
import type { ResumeDesign, ResumeEntryKind, ResumeTemplate } from '@/api/resumeStudio'
import { ResumePaper, resumeTemplates } from './ResumePaper'
import dashboard from './dashboard.module.css'
import styles from './ResumeStudio.module.css'

const exampleEntries: [ResumeEntryKind, string, string, string, string, string][] = [
  ['education', '计算机技术 · 硕士', '江宁理工大学', '2024-09', '2027-06', '方向为信息检索与自然语言处理。'],
  ['project', '检索问答助手', '', '2026-03', '2026-07', '实现资料分块与混合检索，保留回答对应的原文链接。\n整理问答样例，用于检索回归检查。'],
  ['internship', '后端开发实习生', '远山网络', '2025-07', '2025-09', '参与任务管理接口开发，补充分页和参数校验。'],
  ['research', '中文检索实验', '', '2025-10', '2026-01', '对比关键词检索与向量检索的结果。'],
  ['award', '研究生学业奖学金', '', '2025-11', '', ''],
]
const example: ResumeDesign = {
  name: '林予安', phone: '138 **** 0126', email: 'lin.yuan@example.com', targetRole: 'Agent 开发实习生',
  skills: 'Java、Python、Spring Boot、MySQL、Git', showPhoto: false, photo: null, template: 'classic',
  entries: exampleEntries.map(([kind, title, organization, startMonth, endMonth, description], index) =>
    ({ id: String(index), kind, title, organization, role: '', startMonth, endMonth, description })),
}

export default function ResumeTemplates({ design, onApply, onClose }: {
  design: ResumeDesign; onApply: (template: ResumeTemplate, showPhoto: boolean) => void; onClose: () => void
}) {
  const [selected, select] = useState(design.template)
  const [filter, setFilter] = useState<0 | 1 | 2>(0)
  const [showPhoto, setShowPhoto] = useState(design.showPhoto)
  const hasContent = Boolean(design.name.trim() || design.entries.some((entry) => entry.title.trim()))
  const preview = { ...(hasContent ? design : example), template: selected, showPhoto }

  return <div className={styles.galleryScreen} data-resume-gallery>
    <header className={styles.galleryTitle}>
      <div><h2>简历模板</h2><p>用同一份资料比较不同排版。</p></div>
      <button type="button" className={dashboard.button} onClick={onClose}><ArrowLeftOutlined aria-hidden /> 返回简历制作</button>
    </header>
    <div className={styles.gallery}>
      <section className={styles.panel} aria-labelledby="resume-template-gallery">
        <header className={styles.panelHead}>
          <h3 id="resume-template-gallery"><AppstoreOutlined aria-hidden /> 选择模板</h3>
          <div className={styles.templateFilters} role="group" aria-label="筛选版式">
            {([0, 1, 2] as const).map((value) => <button key={value} type="button" aria-pressed={filter === value}
              onClick={() => {
                setFilter(value)
                if (value && !resumeTemplates.some((item) => item.id === selected && item.columns === value)) {
                  select(resumeTemplates.find((item) => item.columns === value)!.id)
                }
              }}>{['全部', '单栏', '双栏'][value]}</button>)}
          </div>
        </header>
        <div className={styles.tiles}>
          {resumeTemplates.filter((item) => !filter || item.columns === filter).map((item) => (
            <button type="button" key={item.id} className={styles.tile} aria-pressed={selected === item.id} onClick={() => select(item.id)}>
              <span className={styles.tileThumb} data-layout={item.id} aria-hidden="true">
                <ResumePaper design={{ ...example, template: item.id }} />
              </span>
              {selected === item.id && <span className={styles.tileCheck}><CheckOutlined aria-hidden /></span>}
              <span className={styles.tileLabel}><strong>{item.label}</strong><small>{item.description}</small></span>
            </button>
          ))}
        </div>
        <footer className={styles.panelFoot}><span><InfoCircleOutlined aria-hidden /> 切换模板会沿用已填写的资料和经历。</span></footer>
      </section>
      <section className={styles.panel} aria-labelledby="resume-template-preview">
        <header className={styles.panelHead}>
          <h3 id="resume-template-preview"><FileTextOutlined aria-hidden /> {hasContent ? '简历预览' : '示例简历'}</h3>
          <span className={styles.paperMeta}>{resumeTemplates.find((item) => item.id === selected)?.label} · A4</span>
        </header>
        <div className={styles.previewSurface}><ResumePaper design={preview} /></div>
        <footer className={styles.panelFoot}>
          <label className={styles.check}><input type="checkbox" disabled={!design.photo} checked={showPhoto}
            onChange={(event) => setShowPhoto(event.target.checked)} /> 在简历中显示照片</label>
          <button type="button" className={dashboard.primary} onClick={() => onApply(selected, showPhoto)}>
            <CheckOutlined aria-hidden /> 使用此模板
          </button>
        </footer>
      </section>
    </div>
  </div>
}

