import { useState } from 'react'
import { Checkbox, Empty, Form, Input, Modal, Tag } from 'antd'
import { careerApi, type CareerProfile, type ExperienceInput } from '@/api/career'
import type { ResumeEntry } from '@/api/resumeStudio'
import { entryLabels } from './ResumePaper'
import { useCareerAction } from './useCareerAction'
import styles from './ResumeStudio.module.css'

export type ArchivedExperience = ExperienceInput & { id: string }

export function importExperience(item: ArchivedExperience): ResumeEntry {
  return {
    id: item.id, kind: item.type, title: item.title, organization: item.organization ?? '', role: '',
    startMonth: item.startMonth?.slice(0, 7) ?? '', endMonth: item.endMonth?.slice(0, 7) ?? '',
    description: item.description, sourceNote: item.sourceNote ?? null,
  }
}

export function experienceMatches(entry: ResumeEntry, fact: ArchivedExperience) {
  const description = entry.role.trim() ? '担任角色：' + entry.role.trim() + '\n' + entry.description.trim() : entry.description.trim()
  return entry.kind === fact.type && entry.title.trim() === fact.title && entry.organization.trim() === (fact.organization ?? '')
    && entry.startMonth === (fact.startMonth ?? '') && entry.endMonth === (fact.endMonth ?? '')
    && description === fact.description && (entry.sourceNote?.trim() ?? '') === (fact.sourceNote ?? '')
}

export function ExperienceImport({ entries, remaining, onClose, onImport }: {
  entries: ArchivedExperience[]; remaining: number; onClose: () => void; onImport: (entries: ResumeEntry[]) => void
}) {
  const [selected, setSelected] = useState<string[]>([])
  return <Modal open title="导入已有经历" onCancel={onClose} okText="导入所选" cancelText="取消"
    okButtonProps={{ disabled: !selected.length || selected.length > remaining }}
    onOk={() => onImport(entries.filter((entry) => selected.includes(entry.id)).map(importExperience))}>
    {!entries.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有可导入的经历" /> : <>
      <p className={styles.importHint}>本次最多还可添加 {remaining} 条经历。</p>
      <Checkbox.Group className={styles.importOptions} value={selected} onChange={setSelected}>
        {entries.map((entry) => <Checkbox key={entry.id} value={entry.id}>
          {entry.title} <Tag>{entryLabels[entry.type]}</Tag>
          <Tag color={entry.confirmed ? 'success' : 'default'}>{entry.confirmed ? '已确认' : '待核对'}</Tag>
        </Checkbox>)}
      </Checkbox.Group>
    </>}
  </Modal>
}

export function CareerPreferences({ profile, onSave, onClose }: {
  profile: CareerProfile | null; onSave: (value: CareerProfile) => void; onClose: () => void
}) {
  const [form] = Form.useForm<CareerProfile>()
  const action = useCareerAction()
  return <Modal open title="求职档案" cancelText="取消" okText="保存求职档案" confirmLoading={action.saving}
    onCancel={onClose} onOk={() => form.submit()}>
    <Form<CareerProfile> form={form} layout="vertical" initialValues={profile ?? undefined} disabled={action.saving}
      onFinish={(values) => action.run(async () => {
        const saved = await careerApi.saveProfile({
          targetRole: profile?.targetRole ?? null,
          graduationMonth: values.graduationMonth || null,
          preferences: values.preferences?.trim() || null,
        })
        onSave(saved)
        onClose()
      })}>
      <Form.Item name="graduationMonth" label="毕业月份"><Input type="month" /></Form.Item>
      <Form.Item name="preferences" label="求职偏好">
        <Input.TextArea rows={3} maxLength={2000} placeholder="例如期望城市、行业或岗位方向" />
      </Form.Item>
    </Form>
  </Modal>
}
