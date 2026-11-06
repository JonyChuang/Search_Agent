import { Alert, Button, Card, List, Space, Spin, Tabs, Typography } from 'antd'
import { practiceApi } from '@/api/practice'
import QuestionCatalog from './career/QuestionCatalog'
import { useCareerQuery } from './career/useCareerQuery'

const { Paragraph, Text, Title, Link } = Typography

function InterviewNotes() {
  const { data, error, retry } = useCareerQuery(practiceApi.notes)
  if (error) return <Alert type="error" message={error} action={<Button onClick={retry}>重试</Button>} />
  if (!data) return <Spin />

  return (
    <List
      dataSource={data}
      rowKey="id"
      locale={{ emptyText: '暂时没有已整理的面经' }}
      renderItem={(note) => (
        <List.Item>
          <List.Item.Meta
            title={note.title}
            description={
              <>
                <Text type="secondary">{note.company} · {note.role} · 公开个人回顾</Text>
                <Paragraph style={{ marginBlock: 8 }}>{note.summary}</Paragraph>
                <Space wrap>
                  <Link href={note.sourceUrl} target="_blank" rel="noopener noreferrer">{note.sourceName}</Link>
                  <Text type="secondary">发布于 {note.publishedOn} · 整理于 {note.sourcedOn}</Text>
                </Space>
              </>
            }
          />
        </List.Item>
      )}
    />
  )
}

export default function ExperienceBankPage() {
  return (
    <Space direction="vertical" size="large" style={{ display: 'flex', maxWidth: 1000, marginInline: 'auto' }}>
      <div>
        <Title level={2}>面经与题库</Title>
        <Paragraph type="secondary">查看有来源的面试回顾，按目标岗位方向选择练习题。</Paragraph>
      </div>
      <Card>
        <Tabs items={[
          { key: 'questions', label: '题库', children: <QuestionCatalog /> },
          { key: 'notes', label: '公开面经', children: <InterviewNotes /> },
        ]} />
      </Card>
    </Space>
  )
}
