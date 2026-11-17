import { useCallback, useState } from 'react'
import { Alert, App, Button, Card, Form, Input, List, Modal, Popconfirm, Segmented, Select, Space, Spin, Tag } from 'antd'
import { contentReview, type ReviewContent, type ReviewDraft, type ReviewKind, type ReviewStatus } from '@/api/contentReview'
import { practiceApi } from '@/api/practice'
import { roles } from './QuestionCatalog'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'

const statusLabels = { DRAFT: '待审核', PUBLISHED: '已发布', DISMISSED: '已驳回' }
const choices = ['A', 'B', 'C', 'D']
const required = [{ required: true, message: '请填写此项' }]

function DraftEditor({ draft, kind, onClose, onSaved }: {
  draft?: ReviewDraft; kind: ReviewKind; onClose: () => void; onSaved: () => void
}) {
  const [form] = Form.useForm<ReviewContent>()
  const action = useCareerAction()
  const question = kind === 'QUESTION'
  const catalog = useCareerQuery(useCallback((signal: AbortSignal) => question && !draft ? practiceApi.questions(undefined, signal)
    : Promise.resolve([]), [question, draft]))
  return <Modal open title={draft ? '编辑审核草稿' : question ? '新增单选题草稿' : '新增面经草稿'}
    onCancel={onClose} onOk={() => form.submit()} okText="保存草稿" cancelText="取消" confirmLoading={action.saving}>
    <Form form={form} layout="vertical" disabled={action.saving} initialValues={draft?.content}
      onFinish={(values) => action.run(async () => {
        await contentReview.save(kind, { ...values, targetId: draft ? draft.content.targetId : values.targetId }, draft)
        onSaved()
      })}>
      {question ? <>
        {!draft && <Form.Item name="targetId" label="修订现有题目（可选）">
          <Select allowClear showSearch optionFilterProp="label" loading={!catalog.data && !catalog.error}
            options={catalog.data?.map((item) => ({ value: item.id, label: item.prompt }))} />
        </Form.Item>}
        {draft?.baseVersion != null && <Alert message={'基于已发布第 ' + draft.baseVersion + ' 版修订'} type="info" />}
        <Form.Item name="role" label="岗位方向" rules={required}><Select options={Object.entries(roles).map(([value, label]) => ({ value, label }))} /></Form.Item>
        <Form.Item name="topic" label="主题" rules={required}><Input maxLength={80} /></Form.Item>
      </> : <>
        <Form.Item name="company" label="公司" rules={required}><Input maxLength={160} /></Form.Item>
        <Form.Item name="role" label="岗位" rules={required}><Input maxLength={24} /></Form.Item>
        <Form.Item name="publishedOn" label="原文发布日期" rules={required}><Input type="date" /></Form.Item>
      </>}
      <Form.Item name="title" label={question ? '题干' : '标题'} rules={required}><Input maxLength={question ? 1000 : 160} /></Form.Item>
      {question && <>
        {choices.map((choice, index) => <Form.Item key={choice} name={['options', index]} label={'选项 ' + choice} rules={required}><Input maxLength={500} /></Form.Item>)}
        <Form.Item name="correctAnswer" label="正确选项" rules={required}><Select options={choices.map((value) => ({ value, label: value }))} /></Form.Item>
      </>}
      <Form.Item name="explanation" label={question ? '解析' : '核对后的面经摘要'} rules={required}><Input.TextArea rows={4} maxLength={6000} /></Form.Item>
      <Form.Item name="sourceName" label="来源名称" rules={required}><Input maxLength={160} /></Form.Item>
      <Form.Item name="sourceUrl" label="公开来源链接" rules={required}><Input type="url" maxLength={2048} /></Form.Item>
    </Form>
  </Modal>
}

export default function PublicLearningReview() {
  const [status, setStatus] = useState<ReviewStatus>('DRAFT')
  const [page, setPage] = useState(1)
  const [editor, setEditor] = useState<{ kind: ReviewKind; draft?: ReviewDraft }>()
  const load = useCallback((signal: AbortSignal) => contentReview.list(status, page, signal), [status, page])
  const drafts = useCareerQuery(load)
  const feeds = useCareerQuery(contentReview.feeds)
  const action = useCareerAction()
  const { message } = App.useApp()

  function navigate(value: ReviewStatus, next: number) {
    drafts.setData(undefined)
    setStatus(value)
    setPage(next)
  }

  function review(draft: ReviewDraft, decision: 'publish' | 'dismiss') {
    void action.run(async () => {
      await contentReview.review(draft, decision)
      drafts.retry()
      message.success(decision === 'publish' ? '已发布公开内容' : '已驳回草稿')
    })
  }

  return <Card title="公开内容审核">
    <Space direction="vertical" style={{ display: 'flex' }}>
      <Space wrap>
        <Button onClick={() => setEditor({ kind: 'QUESTION' })}>新增或修订单选题</Button>
        <Button onClick={() => setEditor({ kind: 'NOTE' })}>新增面经</Button>
        <Button disabled={!feeds.data} loading={action.saving} onClick={() => action.run(async () => {
          const result = await contentReview.refresh()
          drafts.retry()
          message.info(result.busy ? '正在检查公开来源，稍后刷新列表' :
            '已检查 ' + result.succeeded + ' 个来源' + (result.failed ? '，' + result.failed + ' 个来源读取失败' : ''))
        })}>检查公开来源</Button>
        {feeds.data === 0 && <small>暂无配置的公开订阅来源</small>}
      </Space>
      <Segmented value={status} onChange={(value) => navigate(value, 1)}
        options={Object.entries(statusLabels).map(([value, label]) => ({ value: value as ReviewStatus, label }))} />
      {drafts.error ? <Alert type="error" message={drafts.error} action={<Button onClick={drafts.retry}>重试</Button>} />
        : !drafts.data ? <Spin /> : <List rowKey="id" dataSource={drafts.data.items} locale={{ emptyText: '当前没有记录' }}
          renderItem={(draft) => <List.Item actions={draft.status === 'DRAFT' ? [
            <Button type="link" key="edit" onClick={() => setEditor({ draft, kind: draft.kind })}>编辑</Button>,
            <Popconfirm title="已核对出处和内容，发布给所有用户？" key="publish" onConfirm={() => review(draft, 'publish')}>
              <Button type="link" disabled={action.saving}>发布</Button>
            </Popconfirm>,
            <Popconfirm title="驳回此候选？" key="dismiss" onConfirm={() => review(draft, 'dismiss')}>
              <Button type="link" danger disabled={action.saving}>驳回</Button>
            </Popconfirm>,
          ] : undefined}>
            <List.Item.Meta title={<><Tag>{draft.kind === 'NOTE' ? '面经' : '单选题'}</Tag>{draft.content.title}</>}
              description={<Space wrap><a href={draft.content.sourceUrl} target="_blank" rel="noreferrer">{draft.content.sourceName}</a>
                {draft.baseVersion != null && <span>修订第 {draft.baseVersion} 版</span>}
                {!draft.content.explanation && <span>待补充核对后的摘要</span>}</Space>} />
          </List.Item>} />}
      {(page > 1 || drafts.data?.hasMore) && <Space>
        <Button disabled={page === 1} onClick={() => navigate(status, page - 1)}>上一页</Button>
        <Button disabled={!drafts.data?.hasMore} onClick={() => navigate(status, page + 1)}>下一页</Button>
      </Space>}
    </Space>
    {editor && <DraftEditor {...editor} onClose={() => setEditor(undefined)} onSaved={() => {
      setEditor(undefined)
      if (status === 'DRAFT' && page === 1) drafts.retry()
      else navigate('DRAFT', 1)
    }} />}
  </Card>
}

