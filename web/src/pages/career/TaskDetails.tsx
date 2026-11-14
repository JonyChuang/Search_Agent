import { useCallback, useState } from 'react'
import { Alert, Button, List, Modal, Space, Typography } from 'antd'
import { FileTextOutlined } from '@ant-design/icons'
import { documentApi, type DocumentPreview } from '@/api/documents'
import { careerWorkflow, type CareerTask } from '@/api/careerWorkflow'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'
import styles from './workspace.module.css'

const stepLabels: Record<string, string> = {
  assemble_context: '装配备考上下文',
  list_training_questions: '读取候选题',
  create_training_plan: '生成训练计划',
  preparation: '生成岗位模拟题',
  interview: '生成面试复盘',
  review: '生成复习建议',
  discovery: '联网查面经',
}

function Events({ id }: { id: string }) {
  const load = useCallback((signal: AbortSignal) => careerWorkflow.taskEvents(id, signal), [id])
  const events = useCareerQuery(load)
  if (events.error) return <Alert type="error" message={events.error} action={<Button onClick={events.retry}>重试</Button>} />
  return <List size="small" loading={!events.data} dataSource={events.data} locale={{ emptyText: '暂无执行记录' }}
    rowKey={(item) => `${item.generation}:${item.sequenceNo}`} renderItem={(item) => (
      <List.Item>
        第 {item.generation} 次执行 · {stepLabels[item.step] ?? item.step} · {item.outcome === 'succeeded' ? '完成' : '失败'}
        {' · '}{(item.elapsedMs / 1000).toFixed(2)} 秒
        {item.inputTokens !== null && ` · 输入 ${item.inputTokens} tokens`}
        {item.outputTokens !== null && ` · 输出 ${item.outputTokens} tokens`}
      </List.Item>
    )} />
}

export default function TaskDetails({ task, referenceList = false }: { task: CareerTask; referenceList?: boolean }) {
  const [preview, setPreview] = useState<DocumentPreview>()
  const [trace, setTrace] = useState(false)
  const action = useCareerAction()
  const openReference = (id: string) => action.run(async () => {
    setPreview((await documentApi.preview(id)).data)
  })
  return (
    <Space direction="vertical" style={{ display: 'flex' }}>
      {!!task.references?.length && (referenceList ? (
        <ul className={styles.items}>
          {task.references.map((ref) => <li key={ref.id}>
            <span className={styles.itemIcon}><FileTextOutlined /></span>
            <div className={styles.itemBody}><strong>{ref.title}</strong><p className={styles.muted}>我的资料</p></div>
            <Button size="small" type="link" loading={action.saving} onClick={() => openReference(ref.id)}>查看引用</Button>
          </li>)}
        </ul>
      ) : (
        <Space wrap>
          <Typography.Text type="secondary">本次备考资料</Typography.Text>
          {task.references.map((ref, i) => (
            <Button key={ref.id} type="link" size="small" loading={action.saving}
              onClick={() => openReference(ref.id)}>[资料{i + 1}] {ref.title}</Button>
          ))}
        </Space>
      ))}
      {!referenceList && task.generation > 0 && <Button type="link" size="small" onClick={() => setTrace(true)}>执行记录</Button>}
      <Modal open={!!preview} title={preview?.file_name} footer={null} onCancel={() => setPreview(undefined)} width={760}>
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', maxHeight: '65vh', overflow: 'auto' }}>
          {preview?.content}
        </Typography.Paragraph>
        {preview?.truncated && <Typography.Text type="secondary">原文预览已截断。</Typography.Text>}
      </Modal>
      <Modal open={trace} title="Agent 执行记录" footer={null} onCancel={() => setTrace(false)} width={680}>
        {trace && <Events id={task.id} />}
      </Modal>
    </Space>
  )
}
