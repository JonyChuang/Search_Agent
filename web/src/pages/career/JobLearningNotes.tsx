import { useCallback, useState } from 'react'
import { Alert, App, Button, Empty, List, Modal, Space, Spin, Typography } from 'antd'
import { useSearchParams } from 'react-router-dom'
import type { CareerTask } from '@/api/careerWorkflow'
import { documentApi, type DocumentPreview } from '@/api/documents'
import { learningApi } from '@/api/learning'
import { PreparationActions } from './LearningPractice'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'

export function SaveLearningNote({ jobId, task, index, onSaved }: {
  jobId: string; task: CareerTask; index: number; onSaved?: () => void
}) {
  const [saved, setSaved] = useState(false)
  const action = useCareerAction()
  const { message } = App.useApp()
  return <Button type="link" disabled={saved} loading={action.saving} onClick={() => action.run(async () => {
    await learningApi.saveNote(jobId, task, index)
    setSaved(true)
    onSaved?.()
    message.success('已保存到本岗位的我的面经')
  })}>{saved ? '已保存' : '保存到本岗位'}</Button>
}

export default function JobLearningNotes({ jobId }: { jobId: string }) {
  const [params] = useSearchParams()
  const document = params.get('prepDocument') ?? undefined
  const load = useCallback((signal: AbortSignal) => learningApi.notes(jobId, signal), [jobId])
  const list = useCareerQuery(load)
  const action = useCareerAction()
  const [preview, setPreview] = useState<DocumentPreview>()
  const [showSources, setShowSources] = useState(Boolean(document))
  return <Space direction="vertical" style={{ display: 'flex' }}>
    <Button onClick={() => setShowSources(!showSources)} aria-expanded={showSources}>从我的资料整理面经</Button>
    {showSources && <PreparationActions jobId={jobId} purpose="NOTES" initialDocument={document} renderNote={(task, index) =>
      <SaveLearningNote key={task.id + ':' + index} jobId={jobId} task={task} index={index} onSaved={list.retry} />} />}
    {list.error ? <Alert type="error" message={list.error} action={<Button onClick={list.retry}>重试</Button>} /> :
      !list.data ? <Spin /> : <List dataSource={list.data} rowKey="sourceKey"
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本岗位还没有保存的面经" /> }}
        renderItem={(note) => <List.Item>
          <List.Item.Meta title={note.title} description={<>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{note.summary}</Typography.Paragraph>
            <Space wrap>
              {note.sourceUrl && <a href={note.sourceUrl} target="_blank" rel="noreferrer">查看联网原文</a>}
              {note.documentId && <Button type="link" size="small" loading={action.saving} onClick={() => action.run(async () => {
                if (note.documentId) setPreview((await documentApi.preview(note.documentId)).data)
              })}>{note.documentTitle || '查看原资料'}</Button>}
              <Typography.Text type="secondary">{new Date(note.collectedAt).toLocaleString('zh-CN')} · {note.documentId ? '个人资料整理' : '联网面经'}</Typography.Text>
            </Space>
          </>} />
        </List.Item>} />}
    <Modal open={!!preview} title={preview?.file_name} onCancel={() => setPreview(undefined)} footer={null}>
      <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', maxHeight: '65vh', overflow: 'auto' }}>{preview?.content}</Typography.Paragraph>
      {preview?.truncated && <Typography.Text type="secondary">仅显示原资料的部分内容</Typography.Text>}
    </Modal>
  </Space>
}

