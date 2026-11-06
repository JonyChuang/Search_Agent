import { Col, Form, Input, Row, Space, Typography } from 'antd'
import { careerApi, type JobInput } from '@/api/career'
import CareerRecordList from './career/CareerRecordList'

const { Link, Paragraph, Text, Title } = Typography

export default function JobCompanyPage() {
  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>岗位与公司</Title>
        <Paragraph type="secondary">手动录入目标岗位的招聘描述、来源和记录日期，方便后续准备。</Paragraph>
      </div>
      <CareerRecordList<JobInput>
        label="岗位"
        api={careerApi.jobs}
        defaults={() => ({ sourcedOn: new Date().toLocaleDateString('sv-SE') })}
        normalize={(values) => ({
          company: values.company.trim(),
          title: values.title.trim(),
          location: values.location?.trim() || null,
          description: values.description.trim(),
          sourceName: values.sourceName.trim(),
          sourceUrl: values.sourceUrl?.trim() || null,
          sourcedOn: values.sourcedOn,
        })}
        render={(entry) => (
          <>
            <Text strong>{entry.title}</Text>
            <Paragraph type="secondary">{[entry.company, entry.location].filter(Boolean).join(' · ')}</Paragraph>
            <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }} ellipsis={{ rows: 4, expandable: true }}>
              {entry.description}
            </Paragraph>
            <Space wrap>
              {entry.sourceUrl
                ? <Link href={entry.sourceUrl} target="_blank" rel="noopener noreferrer">{entry.sourceName}</Link>
                : <Text>{entry.sourceName}</Text>}
              <Text type="secondary">记录于 {entry.sourcedOn}</Text>
            </Space>
          </>
        )}
      >
        <Row gutter={16}>
          <Col xs={24} sm={12}>
            <Form.Item name="company" label="公司" rules={[{ required: true, whitespace: true }]}>
              <Input maxLength={160} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="title" label="岗位" rules={[{ required: true, whitespace: true }]}>
              <Input maxLength={160} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="location" label="工作地点"><Input maxLength={160} /></Form.Item>
        <Form.Item name="description" label="岗位描述（JD）" rules={[{ required: true, whitespace: true }]}>
          <Input.TextArea rows={5} maxLength={40000} />
        </Form.Item>
        <Row gutter={16}>
          <Col xs={24} sm={12}>
            <Form.Item name="sourceName" label="招聘来源" rules={[{ required: true, whitespace: true }]}>
              <Input maxLength={160} placeholder="例如公司招聘官网或校招宣讲" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="sourcedOn" label="来源记录日期" rules={[{ required: true }]}>
              <Input type="date" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="sourceUrl" label="来源链接"><Input type="url" maxLength={2048} /></Form.Item>
      </CareerRecordList>
    </Space>
  )
}
