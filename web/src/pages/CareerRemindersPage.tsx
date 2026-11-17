import { useState } from 'react'
import { Alert, Button, Checkbox, Form, Input, List, Modal, Popconfirm, Select, Space, Spin, Tag } from 'antd'
import { Link } from 'react-router-dom'
import { remindersApi, type CareerReminder, type ReminderInput, type ReminderType } from '@/api/careerReminders'
import { useCurrentJob } from './career/CurrentJob'
import { applicationPath, interviewPath, preparationPath } from './career/paths'
import { useCareerAction } from './career/useCareerAction'
import { useCareerQuery } from './career/useCareerQuery'
import styles from './career/dashboard.module.css'

const types = { REVIEW: '复习提醒', INTERVIEW: '面试提醒', APPLICATION: '投递截止提醒' }
const delivery: Record<string, string> = {
  READY: '待推送', SENDING: '正在推送', SENT: '已推送', UNDELIVERED: '未送达', UNKNOWN: '推送结果待核对',
}
const options = Object.entries(types).map(([value, label]) => ({ value, label }))

function Editor({ item, onDone, close }: { item?: CareerReminder; onDone: () => void; close: () => void }) {
  const { jobs, job } = useCurrentJob()
  const [form] = Form.useForm<ReminderInput>()
  const action = useCareerAction()
  const date = item && new Date(item.dueAt)
  const time = date && new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
  return <Modal open title={item ? '编辑提醒' : '添加提醒'} onCancel={close} onOk={() => form.submit()}
    okText="保存提醒" cancelText="取消" confirmLoading={action.saving}>
    <Form form={form} layout="vertical" initialValues={{ jobId: item?.jobId ?? job?.id, type: item?.type ?? 'REVIEW',
      title: item?.title, dueAt: time, externalDelivery: item?.externalDelivery ?? false }} onFinish={(values) => action.run(async () => {
        const reminder = { ...values, dueAt: new Date(values.dueAt).toISOString() }
        if (item) await remindersApi.edit(item, reminder)
        else await action.submit('career-reminder', { reminder }, remindersApi.create)
        onDone()
      })}>
      <Form.Item name="jobId" label="关联岗位">
        <Select allowClear options={jobs?.map(value => ({ label: value.company + ' · ' + value.title, value: value.id }))} />
      </Form.Item>
      <Form.Item name="type" label="提醒类型" rules={[{ required: true }]}><Select options={options} /></Form.Item>
      <Form.Item name="title" label="提醒内容" rules={[{ required: true, whitespace: true }]}><Input maxLength={160} /></Form.Item>
      <Form.Item name="dueAt" label="提醒时间（本机时区）" rules={[{ required: true }]}><Input type="datetime-local" /></Form.Item>
      <Form.Item name="externalDelivery" valuePropName="checked"><Checkbox>到时通过已启用的消息渠道推送</Checkbox></Form.Item>
    </Form>
  </Modal>
}

const format = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
function entryPoint(type: ReminderType, jobId?: string | null) {
  const values = jobId ? { job: jobId } : undefined
  if (type === 'REVIEW') return preparationPath('review', values)
  if (type === 'INTERVIEW') return interviewPath(values)
  return applicationPath(jobId ?? undefined)
}

export default function CareerRemindersPage() {
  const reminders = useCareerQuery(remindersApi.list)
  const { jobs } = useCurrentJob()
  const [editor, setEditor] = useState<CareerReminder | true>()
  const action = useCareerAction()
  const refresh = () => {
    setEditor(undefined)
    reminders.retry()
    window.dispatchEvent(new Event('career-reminders-changed'))
  }
  return <div className={styles.page}>
    <header className={styles.pageHead}>
      <div><h1>计划与提醒</h1><p>安排复习、面试和投递截止提醒。</p></div>
      <Button type="primary" onClick={() => setEditor(true)}>添加提醒</Button>
    </header>
    {reminders.error ? <Alert showIcon type="error" message={reminders.error} action={<Button onClick={reminders.retry}>重试</Button>} />
      : !reminders.data ? <Spin /> : <List dataSource={reminders.data} rowKey="id" locale={{ emptyText: '暂无提醒' }}
        renderItem={(item) => {
          const job = jobs?.find((value) => value.id === item.jobId)
          return <List.Item actions={item.status === 'PENDING' ? [
            <Link key="go" to={entryPoint(item.type, item.jobId)}>查看</Link>,
            <Button type="link" key="edit" disabled={['SENDING', 'UNKNOWN'].includes(item.deliveryState)} onClick={() => setEditor(item)}>编辑</Button>,
            <Button type="link" key="done" disabled={action.saving} onClick={() => action.run(async () => {
              await remindersApi.change(item, 'DONE')
              refresh()
            })}>标记完成</Button>,
            <Popconfirm title="取消这条提醒？" key="cancel" onConfirm={() => action.run(async () => {
              await remindersApi.change(item, 'CANCELLED')
              refresh()
            })}><Button type="link" danger disabled={action.saving}>取消</Button></Popconfirm>,
          ] : []}>
            <List.Item.Meta title={item.title} description={<Space wrap>
              <Tag>{types[item.type]}</Tag>
              <Tag color={item.due ? 'orange' : undefined}>{item.due ? '已到时间' :
                item.status === 'DONE' ? '已完成' : item.status === 'CANCELLED' ? '已取消' : '待提醒'}</Tag>
              <span>{format.format(new Date(item.dueAt))}</span>
              {item.externalDelivery && item.status === 'PENDING' && <Tag>{delivery[item.deliveryState] ?? '应用内提醒'}</Tag>}
              {job && <span>{job.company} · {job.title}</span>}
            </Space>} />
          </List.Item>
        }} />}
    {editor && <Editor item={editor === true ? undefined : editor} onDone={refresh} close={() => setEditor(undefined)} />}
  </div>
}

