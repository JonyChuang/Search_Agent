import { Button, Checkbox, Form, Input, Modal, Select } from 'antd'
import type { ApplicationQuestion, ApplicationReceipt, MaterialItem } from '@/api/applicationWorkspace'

export function webAddress(value?: string | null): URL | undefined {
  try {
    const url = new URL(value?.trim() ?? '')
    if ((url.protocol === 'https:' || url.protocol === 'http:') && !url.username && !url.password) return url
  } catch {
    return undefined
  }
}

export function MaterialDialog({ item, existing, onClose, onSave, onRemove }: {
  item: MaterialItem
  existing: boolean
  onClose: () => void
  onSave: (item: MaterialItem) => void
  onRemove: () => void
}) {
  const [form] = Form.useForm<MaterialItem>()
  const kind = Form.useWatch('kind', form) ?? item.kind
  return <Modal open title={existing ? '编辑附件项目' : '添加附件项目'} onCancel={onClose}
    footer={[
      existing && <Button danger key="remove" onClick={onRemove}>移除此项目</Button>,
      <Button key="cancel" onClick={onClose}>取消</Button>,
      <Button type="primary" key="ok" onClick={() => form.submit()}>保存项目</Button>,
    ]}>
    <Form form={form} layout="vertical" initialValues={item} onFinish={(values) => onSave({
      ...item, ...values, label: values.label.trim(), url: kind === 'LINK' ? webAddress(values.url)?.href ?? null : null,
    })}>
      <Form.Item name="label" label="材料名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={100} /></Form.Item>
      <Form.Item name="kind" label="类型" rules={[{ required: true }]}>
        <Select disabled={existing} options={[{ value: 'FILE', label: '文件附件' }, { value: 'LINK', label: '链接' }]} />
      </Form.Item>
      {kind === 'LINK' && <Form.Item name="url" label="链接" rules={[{
        validator: (_, value: string | undefined) => !value?.trim() || webAddress(value) ? Promise.resolve()
          : Promise.reject(new Error('请输入 HTTP 或 HTTPS 链接')),
      }]}><Input maxLength={2048} placeholder="https://" /></Form.Item>}
      <Form.Item name="required" valuePropName="checked"><Checkbox>招聘页面要求提供</Checkbox></Form.Item>
    </Form>
  </Modal>
}

export function QuestionDialog({ item, existing, onClose, onSave, onRemove }: {
  item: ApplicationQuestion
  existing: boolean
  onClose: () => void
  onSave: (item: ApplicationQuestion) => void
  onRemove: () => void
}) {
  const [form] = Form.useForm<ApplicationQuestion>()
  return <Modal open title={existing ? '编辑岗位问题' : '添加岗位问题'} onCancel={onClose}
    footer={[
      existing && <Button danger key="remove" onClick={onRemove}>移除此题</Button>,
      <Button key="cancel" onClick={onClose}>取消</Button>,
      <Button type="primary" key="ok" onClick={() => form.submit()}>保存答案</Button>,
    ]}>
    <Form form={form} layout="vertical" initialValues={item}
      onFinish={(values) => onSave({ ...item, ...values, label: values.label.trim() })}>
      <Form.Item name="label" label="招聘页面上的问题" rules={[{ required: true, whitespace: true }]}><Input maxLength={160} /></Form.Item>
      <Form.Item name="answer" label="答案草稿"><Input.TextArea rows={4} maxLength={2500} showCount /></Form.Item>
      <Form.Item name="required" valuePropName="checked"><Checkbox>招聘页面要求填写</Checkbox></Form.Item>
    </Form>
  </Modal>
}

export function ReceiptDialog({ saving, onClose, onSave }: {
  saving: boolean
  onClose: () => void
  onSave: (receipt: ApplicationReceipt, note?: string) => void
}) {
  const [form] = Form.useForm<{ submittedAt: string; applicationNumber?: string; note?: string; confirmed: boolean }>()
  const time = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
  return <Modal open title="记录投递回执" okText="记录为已投递" cancelText="取消" confirmLoading={saving}
    onCancel={onClose} onOk={() => form.submit()} closable={!saving} maskClosable={!saving} keyboard={!saving}>
    <Form form={form} layout="vertical" disabled={saving} initialValues={{ submittedAt: time, confirmed: false }}
      onFinish={({ submittedAt, applicationNumber, note }) => onSave({
        submittedAt: new Date(submittedAt).toISOString(), applicationNumber: applicationNumber?.trim() || null,
      }, note?.trim())}>
      <Form.Item name="submittedAt" label="实际投递时间" rules={[{ required: true }]}><Input type="datetime-local" /></Form.Item>
      <Form.Item name="applicationNumber" label="申请编号（如有）"><Input maxLength={160} /></Form.Item>
      <Form.Item name="note" label="回执备注"><Input.TextArea rows={2} maxLength={1000} placeholder="例如已收到确认邮件" /></Form.Item>
      <Form.Item name="confirmed" valuePropName="checked" rules={[{
        validator: (_, value: boolean) => value ? Promise.resolve() : Promise.reject(new Error('请先确认招聘网站已受理申请')),
      }]}><Checkbox>我已在招聘官网确认投递成功</Checkbox></Form.Item>
    </Form>
  </Modal>
}
