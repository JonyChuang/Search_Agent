import { Button, Card, Form, Input, Space, Typography } from 'antd'
import { FileSearchOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import styles from './workspace.module.css'

const examples = [
  ['产品与团队', '比较公司的主要产品线和团队职责。优先查近一年官网资料，为每条结论附上来源。'],
  ['岗位匹配', '结合岗位 JD，找出主要工作和作品集或项目经历中值得展示的能力。标出待核实的信息。'],
  ['面试准备', '查看近一年的公开面经。结合岗位 JD 列出准备重点，并注明面经的来源和发布时间。'],
]

export default function CompanyResearchForm({ topic, onChange, onSubmit }: {
  topic: string; onChange: (topic: string) => void; onSubmit: () => void
}) {
  return (
    <Card className={styles.panel}>
      <div className={styles.researchIntro} style={{ marginBottom: 16 }}>
        <span className={styles.itemIcon}><FileSearchOutlined /></span>
        <div>
          <h2 className={styles.sectionTitle}>发起公司调研</h2>
          <p className={styles.muted}>调研会参考当前公司的信息和岗位 JD。</p>
        </div>
      </div>
      <Form layout="vertical" onFinish={onSubmit}>
        <Form.Item label="你想调研什么？" htmlFor="company-research-topic"
          extra={<div id="company-research-hint" className={styles.researchHint}>
            <Typography.Text type="secondary">可指定时间范围、优先来源和希望得到的结果。</Typography.Text>
            <Typography.Text type="secondary">{topic.length} / 2000</Typography.Text>
          </div>}>
          <Input.TextArea id="company-research-topic" value={topic} onChange={(event) => onChange(event.target.value)}
            aria-describedby="company-research-hint" rows={4} maxLength={2000} required
            placeholder="例如：比较公司的两条产品线，判断哪个团队更适合服务设计实习。优先查近一年的公司官网。" />
        </Form.Item>
        <Space wrap style={{ marginBottom: 16 }}>
          {examples.map(([label, example]) => (
            <Button key={label} size="small" disabled={topic.includes(example) || topic.trim().length + example.length + 1 > 2000}
              onClick={() => onChange([topic.trim(), example].filter(Boolean).join('\n'))}>
              + {label}
            </Button>
          ))}
        </Space>
        <div>
          <Space wrap>
            <Button className={styles.primary} type="primary" icon={<FileSearchOutlined />}
              htmlType="submit" disabled={!topic.trim()}>发起调研</Button>
            <Link to="/settings/models">模型与联网配置</Link>
          </Space>
        </div>
      </Form>
    </Card>
  )
}
