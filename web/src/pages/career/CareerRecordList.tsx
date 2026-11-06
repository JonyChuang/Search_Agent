import type { ReactNode } from 'react'
import { Alert, Button, Card, Empty, Form, List, Modal, Popconfirm, Spin, message } from 'antd'
import { useState } from 'react'
import type { CareerRecords } from '@/api/career'
import { useCareerQuery } from './useCareerQuery'

interface Props<T> {
  label: string
  api: CareerRecords<T>
  defaults: () => Partial<T>
  normalize: (values: T) => T
  onChange?: () => void
  children: ReactNode
  render: (entry: T) => ReactNode
}

export default function CareerRecordList<T extends object>({
  label, api, defaults, normalize, children, render, onChange,
}: Props<T>) {
  const { data, setData, error, retry } = useCareerQuery(api.list)
  const [editor, setEditor] = useState<{ id?: string; values: Partial<T> }>()
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [saveError, setSaveError] = useState<string>()

  function openEditor(entry?: T & { id: string }) {
    setSaveError(undefined)
    setEditor(entry ? { id: entry.id, values: entry } : { values: defaults() })
  }

  async function save(values: T) {
    setSaving(true)
    setSaveError(undefined)
    try {
      const entry = await api.save(editor?.id, normalize(values))
      setData((current) => editor?.id
        ? current?.map((row) => row.id === entry.id ? entry : row)
        : [entry, ...(current ?? [])])
      setEditor(undefined)
      onChange?.()
      message.success('已保存')
    } catch (failure) {
      setSaveError((failure as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function remove(id: string) {
    setDeleting(true)
    try {
      await api.remove(id)
      setData((current) => current?.filter((row) => row.id !== id))
      onChange?.()
      message.success('已删除')
    } catch (failure) {
      message.error((failure as Error).message)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Card
      title={label}
      extra={<Button type="primary" disabled={!data || deleting} onClick={() => openEditor()}>新增{label}</Button>}
    >
      {error ? (
        <Alert type="error" showIcon message={error} action={<Button onClick={retry}>重试</Button>} />
      ) : data === undefined ? (
        <Spin aria-label={`正在加载${label}`} />
      ) : (
        <List
          itemLayout="vertical"
          dataSource={data}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`还没有${label}记录`} /> }}
          renderItem={(entry) => (
            <List.Item
              key={entry.id}
              actions={[
                <Button key="edit" type="link" disabled={deleting} onClick={() => openEditor(entry)}>编辑</Button>,
                <Popconfirm
                  key="delete"
                  title={`删除这条${label}？`}
                  okText="删除"
                  cancelText="取消"
                  onConfirm={() => remove(entry.id)}
                  disabled={deleting}
                >
                  <Button type="link" danger disabled={deleting}>删除</Button>
                </Popconfirm>,
              ]}
            >
              {render(entry)}
            </List.Item>
          )}
        />
      )}
      {editor && (
        <Modal
          open
          title={`${editor.id ? '编辑' : '新增'}${label}`}
          onCancel={() => setEditor(undefined)}
          closable={!saving}
          keyboard={!saving}
          maskClosable={!saving}
          footer={null}
        >
          <Form<T> layout="vertical" initialValues={editor.values} onFinish={save} disabled={saving}>
            {saveError && <Alert type="error" showIcon message={saveError} style={{ marginBottom: 16 }} />}
            {children}
            <Button type="primary" htmlType="submit" loading={saving}>保存{label}</Button>
          </Form>
        </Modal>
      )}
    </Card>
  )
}
