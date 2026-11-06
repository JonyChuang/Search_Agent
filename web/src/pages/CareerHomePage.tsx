import { Card, Col, Row, Space, Typography } from 'antd'
import { Link } from 'react-router-dom'

const { Paragraph, Title } = Typography

export default function CareerHomePage() {
  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>求职总览</Title>
        <Paragraph type="secondary">从整理真实经历和保存目标岗位开始。</Paragraph>
      </div>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12}>
          <Card title="简历与经历">
            <Paragraph>整理教育、科研、项目和实习经历，记录已核对的事实。</Paragraph>
            <Link to="/career/resume">打开经历档案</Link>
          </Card>
        </Col>
        <Col xs={24} sm={12}>
          <Card title="岗位与公司">
            <Paragraph>保存目标岗位的 JD，保留招聘来源和记录日期。</Paragraph>
            <Link to="/career/jobs">打开岗位记录</Link>
          </Card>
        </Col>
        <Col xs={24} sm={12}>
          <Card title="面试训练">
            <Paragraph>查看公开面经，按岗位方向刷题并复习错题。</Paragraph>
            <Space wrap>
              <Link to="/career/questions">打开面经与题库</Link>
              <Link to="/career/practice">打开刷题练习</Link>
              <Link to="/career/plan">生成训练计划</Link>
              <Link to="/career/interviews">开始模拟面试</Link>
            </Space>
          </Card>
        </Col>
        <Col xs={24} sm={12}>
          <Card title="申请与投递">
            <Paragraph>为岗位准备申请材料，记录实际投递阶段。</Paragraph>
            <Space wrap>
              <Link to="/career/apply">准备网申草稿</Link>
              <Link to="/career/applications">打开投递看板</Link>
            </Space>
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
