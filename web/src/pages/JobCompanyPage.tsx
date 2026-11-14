import { Button, Card, Col, Form, Input, Row, Space, Tag, Typography } from 'antd'
import { ArrowRightOutlined, FileSearchOutlined, ReadOutlined } from '@ant-design/icons'
import { Link as RouteLink } from 'react-router-dom'
import { careerApi, type JobInput } from '@/api/career'
import CareerRecordList from './career/CareerRecordList'
import { CurrentJobSelect, useCurrentJob } from './career/CurrentJob'
import { jobPath, preparationPath } from './career/paths'
import WorkspaceHero from './career/WorkspaceHero'
import styles from './career/workspace.module.css'

const { Link, Paragraph, Text } = Typography

export default function JobCompanyPage() {
  const target = useCurrentJob()
  return (
    <div className={styles.workspace}>
      <WorkspaceHero section="求职准备" title="岗位与公司"
        description="管理已保存的招聘信息，围绕具体岗位发起公司调研。" actions={<>
          <small>当前目标岗位</small>
          <CurrentJobSelect inHero />
        </>} />
      <div className={styles.grid}>
      <CareerRecordList<JobInput>
        label="岗位"
        api={careerApi.jobs}
        onChange={target.reload}
        defaults={() => ({ sourcedOn: new Date().toLocaleDateString('sv-SE') })}
        normalize={(values) => ({
          company: values.company.trim(),
          title: values.title.trim(),
          location: values.location?.trim() || null,
          description: values.description.trim(),
          sourceName: values.sourceName.trim(),
          sourceUrl: values.sourceUrl?.trim() || null,
          sourcedOn: values.sourcedOn,
          skills: values.skills?.trim() || null,
        })}
        render={(entry) => (
          <article className={styles.record}>
            <div className={styles.row}>
              <div>
                <h2 className={styles.sectionTitle}><RouteLink to={jobPath(entry.id)}>{entry.title}</RouteLink></h2>
                <p className={styles.muted}>{[entry.company, entry.location].filter(Boolean).join(' · ')}</p>
              </div>
              {target.job?.id === entry.id ? <Tag color="purple">当前目标</Tag>
                : <Button size="small" loading={target.saving} onClick={() => target.select(entry.id)}>设为当前目标</Button>}
            </div>
            <Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', marginBlock: 12 }} ellipsis={{ rows: 2, expandable: true }}>
              {entry.description}
            </Paragraph>
            <Space wrap>
              <RouteLink to={jobPath(entry.id)} className={styles.primaryLink}>公司调研 <ArrowRightOutlined aria-hidden /></RouteLink>
              <RouteLink to={jobPath(entry.id, 'details')}>查看招聘信息</RouteLink>
            </Space>
            <Space wrap style={{ display: 'flex', marginTop: 8 }}>
              {entry.sourceUrl
                ? <Link href={entry.sourceUrl} target="_blank" rel="noopener noreferrer">{entry.sourceName}</Link>
                : <Text>{entry.sourceName}</Text>}
              <Text type="secondary">记录于 {entry.sourcedOn}</Text>
            </Space>
          </article>
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
        <Form.Item name="skills" label="已确认技能">
          <Input maxLength={1000} placeholder="例如访谈、可用性测试、数据分析" />
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
        <aside className={styles.stack} aria-label="当前岗位的下一步">
          {target.job && <Card className={styles.panel}>
            <div className={styles.stack}>
              <h2 className={styles.sectionTitle}>当前岗位的下一步</h2>
              <p className={styles.muted}>{target.job.company} · {target.job.title}</p>
              <RouteLink to={jobPath(target.job.id)}><FileSearchOutlined /> 发起公司调研</RouteLink>
              <RouteLink to={preparationPath('plan', { job: target.job.id })}><ReadOutlined /> 查看备考计划</RouteLink>
            </div>
          </Card>}
        </aside>
      </div>
    </div>
  )
}
