import { Alert, Button, Select, Space, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { documentApi } from '@/api/documents'
import { skillApi } from '@/api/skills'
import { useCareerQuery } from './useCareerQuery'

async function loadDocuments(signal: AbortSignal) {
  const { data } = await documentApi.list(1, 100, undefined, undefined, signal)
  const pages = await Promise.all(Array.from({ length: Math.ceil(data.total / data.page_size) - 1 }, (_, i) =>
    documentApi.list(i + 2, 100, undefined, undefined, signal)))
  return [...data.items, ...pages.flatMap((page) => page.data.items)]
}

async function loadSkills(signal: AbortSignal) {
  return (await skillApi.list(signal)).data.filter((item) => item.enabled)
}

export default function PreparationDocuments({ value, onChange, skillId, onSkillChange }: {
  value?: string[]; onChange: (value: string[]) => void; skillId?: string; onSkillChange: (id?: string) => void
}) {
  const documents = useCareerQuery(loadDocuments)
  const skills = useCareerQuery(loadSkills)
  return (
    <Space direction="vertical" style={{ display: 'flex', marginBottom: 12 }}>
      <Select mode="multiple" maxCount={3} value={value} onChange={onChange} optionFilterProp="label"
        loading={!documents.data && !documents.error} aria-label="备考参考资料"
        placeholder="选择备考参考资料（最多 3 份）"
        options={documents.data?.map((doc) => ({ value: doc.id, label: doc.file_name }))}
        notFoundContent="暂无资料" style={{ width: '100%' }} />
      <Typography.Text type="secondary">所选资料的相关摘录会发给当前模型用于本次备考。</Typography.Text>
      <Link to="/knowledge">管理我的资料</Link>
      <Select value={skillId} onChange={onSkillChange} allowClear optionFilterProp="label" showSearch
        loading={!skills.data && !skills.error} aria-label="备考技能"
        placeholder="可选备考技能" options={skills.data?.map((skill) => ({ value: skill.id, label: skill.name }))}
        notFoundContent="暂无启用的技能" style={{ width: '100%' }} />
      {documents.error && <Alert type="error" message={documents.error}
        action={<Button onClick={documents.retry}>重试读取</Button>} />}
      {skills.error && <Alert type="error" message={skills.error}
        action={<Button onClick={skills.retry}>重试读取技能</Button>} />}
    </Space>
  )
}
