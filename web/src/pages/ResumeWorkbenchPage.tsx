import { Alert, Button, Card, Checkbox, Col, Form, Input, Row, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { useState } from 'react'
import { careerApi, type CareerProfile, type ExperienceInput, type ExperienceType } from '@/api/career'
import CareerRecordList from './career/CareerRecordList'
import ResumeVersions from './career/ResumeVersions'
import { useCareerQuery } from './career/useCareerQuery'

const { Paragraph, Text, Title } = Typography

const experienceTypes: Record<ExperienceType, string> = {
  education: '教育',
  research: '科研',
  project: '项目',
  internship: '实习',
}

function ProfileCard() {
  const { data, setData, error, retry } = useCareerQuery(careerApi.profile)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string>()

  async function save(values: CareerProfile) {
    setSaving(true)
    setSaveError(undefined)
    try {
      const profile = await careerApi.saveProfile({
        targetRole: values.targetRole?.trim() || null,
        graduationMonth: values.graduationMonth || null,
        preferences: values.preferences?.trim() || null,
      })
      setData(profile)
      message.success('求职档案已保存')
    } catch (failure) {
      setSaveError((failure as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="求职档案">
      {error ? (
        <Alert type="error" showIcon message={error} action={<Button onClick={retry}>重试</Button>} />
      ) : data === undefined ? (
        <Spin aria-label="正在加载求职档案" />
      ) : (
        <Form<CareerProfile> layout="vertical" initialValues={data ?? {}} onFinish={save} disabled={saving}>
          {data === null && <Paragraph type="secondary">尚未填写求职档案。</Paragraph>}
          {saveError && <Alert type="error" showIcon message={saveError} style={{ marginBottom: 16 }} />}
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item name="targetRole" label="求职目标"><Input maxLength={160} /></Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item name="graduationMonth" label="毕业月份"><Input type="month" /></Form.Item>
            </Col>
          </Row>
          <Form.Item name="preferences" label="求职偏好">
            <Input.TextArea rows={2} maxLength={2000} placeholder="例如期望城市、行业或岗位方向" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving}>保存求职档案</Button>
        </Form>
      )}
    </Card>
  )
}

export default function ResumeWorkbenchPage() {
  const [experienceRevision, setExperienceRevision] = useState(0)
  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>简历与经历</Title>
        <Paragraph type="secondary">保存你的求职目标与实际经历，并标记已经核对的事实。</Paragraph>
      </div>
      <ProfileCard />
      <CareerRecordList<ExperienceInput>
        label="经历"
        api={careerApi.experiences}
        onChange={() => setExperienceRevision((value) => value + 1)}
        defaults={() => ({ type: 'education', confirmed: false })}
        normalize={(values) => ({
          type: values.type,
          title: values.title.trim(),
          organization: values.organization?.trim() || null,
          startMonth: values.startMonth || null,
          endMonth: values.endMonth || null,
          description: values.description.trim(),
          sourceNote: values.sourceNote?.trim() || null,
          confirmed: values.confirmed,
        })}
        render={(entry) => (
          <>
            <Space wrap>
              <Text strong>{entry.title}</Text>
              <Tag>{experienceTypes[entry.type]}</Tag>
              <Tag color={entry.confirmed ? 'success' : 'default'}>{entry.confirmed ? '已确认' : '待确认'}</Tag>
            </Space>
            {(entry.organization || entry.startMonth || entry.endMonth) && (
              <Paragraph type="secondary">
                {[entry.organization, [entry.startMonth, entry.endMonth].filter(Boolean).join(' 至 ')].filter(Boolean).join(' · ')}
              </Paragraph>
            )}
            <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }} ellipsis={{ rows: 4, expandable: true }}>
              {entry.description}
            </Paragraph>
            {entry.sourceNote && <Text type="secondary">事实依据 · {entry.sourceNote}</Text>}
          </>
        )}
      >
        <Form.Item name="type" label="类型" rules={[{ required: true }]}>
          <Select options={Object.entries(experienceTypes).map(([value, label]) => ({ value, label }))} />
        </Form.Item>
        <Form.Item name="title" label="经历名称" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={160} />
        </Form.Item>
        <Form.Item name="organization" label="学校或组织"><Input maxLength={160} /></Form.Item>
        <Row gutter={16}>
          <Col xs={24} sm={12}>
            <Form.Item name="startMonth" label="起始月份"><Input type="month" /></Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="endMonth" label="结束月份" dependencies={['startMonth']} rules={[
              ({ getFieldValue }) => ({
                validator: (_, end) => {
                  const start = getFieldValue('startMonth')
                  return !start || !end || end >= start
                    ? Promise.resolve()
                    : Promise.reject(new Error('结束月份应晚于或等于起始月份'))
                },
              }),
            ]}>
              <Input type="month" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="description" label="经历内容" rules={[{ required: true, whitespace: true }]}>
          <Input.TextArea rows={4} maxLength={12000} />
        </Form.Item>
        <Form.Item name="sourceNote" label="事实依据">
          <Input.TextArea rows={2} maxLength={500} placeholder="例如原始材料名称或核对记录" />
        </Form.Item>
        <Form.Item name="confirmed" valuePropName="checked">
          <Checkbox>我已核对这条经历</Checkbox>
        </Form.Item>
      </CareerRecordList>
      <ResumeVersions experienceRevision={experienceRevision} />
    </Space>
  )
}
