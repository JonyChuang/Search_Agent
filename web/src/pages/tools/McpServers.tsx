import { useEffect, useState } from 'react'
import {
  Badge,
  Button,
  Card,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ApiOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import {
  mcpApi,
  type McpApproval,
  type McpAuthType,
  type McpPermission,
  type McpServer,
  type McpServerInput,
  type McpToolMeta,
  type McpTransport,
} from '@/api/mcp'

const { Text, Paragraph } = Typography

const STATUS_BADGE: Record<string, { status: 'success' | 'error' | 'default'; text: string }> = {
  ok: { status: 'success', text: '正常' },
  error: { status: 'error', text: '异常' },
  unknown: { status: 'default', text: '未测试' },
}

interface FormValues {
  name: string
  transport: McpTransport
  url: string
  auth_type: McpAuthType
  token?: string
  header?: string
  key?: string
}

export default function McpServers() {
  const [servers, setServers] = useState<McpServer[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<McpServer | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [form] = Form.useForm<FormValues>()
  const authType = Form.useWatch('auth_type', form)
  // 工具清单抽屉（默认关闭）
  const [toolsDrawer, setToolsDrawer] = useState<McpServer | null>(null)
  const [approvals, setApprovals] = useState<McpApproval[] | null>(null)

  const loadApprovals = async () => {
    try {
      setApprovals((await mcpApi.approvals()).data)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const decide = async (id: string, approved: boolean) => {
    setBusy(id)
    try {
      await mcpApi.decide(id, approved)
      message.success(approved ? '工具操作已完成' : '已拒绝工具操作')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(null)
      void loadApprovals()
    }
  }

  const changePermission = async (server: McpServer, tool: string, policy: McpPermission | 'none') => {
    const permissions = { ...server.tool_permissions }
    if (policy === 'none') delete permissions[tool]
    else permissions[tool] = policy
    setBusy(server.id)
    try {
      const { data } = await mcpApi.permissions(server.id, permissions)
      setToolsDrawer(data)
      setServers((prev) => prev.map((item) => item.id === data.id ? data : item))
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await mcpApi.list()
      setServers(data)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const openCreate = () => {
    setEditing(null)
    setModalOpen(true)
  }

  const openEdit = (s: McpServer) => {
    setEditing(s)
    setModalOpen(true)
  }

  // Modal 内容渲染完成后再回填表单，避免打开瞬间表单实例未就绪导致空白
  const onModalOpenChange = (open: boolean) => {
    if (!open) return
    if (editing) {
      form.setFieldsValue({
        name: editing.name,
        transport: editing.transport,
        url: editing.url,
        auth_type: editing.auth_type,
        token: undefined,
        header: undefined,
        key: undefined,
      })
    } else {
      form.resetFields()
      form.setFieldsValue({ transport: 'streamable_http', auth_type: 'none' })
    }
  }

  const buildPayload = (v: FormValues): McpServerInput => {
    let auth_config: Record<string, string> | null = null
    if (v.auth_type === 'bearer' && v.token) auth_config = { token: v.token }
    if (v.auth_type === 'api_key' && v.key)
      auth_config = { header: v.header || 'X-API-Key', key: v.key }
    return {
      name: v.name,
      transport: v.transport,
      url: v.url,
      auth_type: v.auth_type,
      auth_config,
    }
  }

  const onSubmit = async () => {
    const v = await form.validateFields()
    const payload = buildPayload(v)
    try {
      if (editing) {
        await mcpApi.update(editing.id, payload)
        message.success('已保存')
      } else {
        await mcpApi.create(payload)
        message.success('已添加')
      }
      setModalOpen(false)
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onTest = async (s: McpServer) => {
    setBusy(s.id)
    try {
      const { data } = await mcpApi.test(s.id)
      if (data.success) message.success(data.message)
      else message.error(data.message)
      load()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const onSync = async (s: McpServer) => {
    setBusy(s.id)
    try {
      await mcpApi.sync(s.id)
      message.success('已同步工具清单')
      load()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const onToggle = async (s: McpServer, enabled: boolean) => {
    try {
      await mcpApi.toggle(s.id, enabled)
      setServers((prev) =>
        prev.map((x) => (x.id === s.id ? { ...x, enabled } : x)),
      )
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onDelete = async (s: McpServer) => {
    try {
      await mcpApi.remove(s.id)
      message.success('已删除')
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const toolColumns = [
    {
      title: '执行权限',
      key: 'permission',
      render: (_: unknown, tool: McpToolMeta) => toolsDrawer && <Select
        value={toolsDrawer.tool_permissions?.[tool.name] ? 'confirm' : 'none'}
        disabled={busy === toolsDrawer.id}
        onChange={(policy: McpPermission | 'none') => void changePermission(toolsDrawer, tool.name, policy)}
        options={[{ value: 'none', label: '禁止' }, { value: 'confirm', label: '每次确认' }]}
      />,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 240,
      render: (name: string) => <Tag color="blue">{name}</Tag>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      render: (desc: string) =>
        desc ? (
          <Text style={{ fontSize: 13 }}>{desc}</Text>
        ) : (
          <Text type="secondary" style={{ fontSize: 13 }}>
            （无描述）
          </Text>
        ),
    },
  ]

  return (
    <Card
      className="mcp-servers-card"
      title={
        <Space>
          <ApiOutlined />
          MCP 服务
        </Space>
      }
      loading={loading}
      extra={
        <Space><Button onClick={() => void loadApprovals()}>待确认操作</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          添加服务
        </Button></Space>
      }
    >
      <Paragraph type="secondary" style={{ marginTop: -8 }}>
        同步工具后，在工具清单中授权。每次调用都需要在待确认区域核对参数并确认。
      </Paragraph>
      <Drawer title="待确认工具操作" open={approvals !== null} onClose={() => setApprovals(null)} width={560}>
        <Button onClick={() => void loadApprovals()}>刷新</Button>
        <List dataSource={approvals ?? []} locale={{ emptyText: '暂无待确认操作' }} renderItem={(item) => <List.Item>
          <Space direction="vertical" style={{ maxWidth: '100%' }}>
            <Text strong>{item.server} · {item.tool}</Text>
            <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(item.arguments, null, 2)}</pre>
            <Space>
              <Popconfirm title="确认执行此远程操作？" onConfirm={() => decide(item.id, true)}>
                <Button type="primary" disabled={busy === item.id}>确认执行</Button>
              </Popconfirm>
              <Button disabled={busy === item.id} onClick={() => void decide(item.id, false)}>拒绝</Button>
            </Space>
          </Space>
        </List.Item>} />
      </Drawer>
      {servers.length === 0 ? (
        <Empty description="暂无 MCP 服务" />
      ) : (
        <List
          itemLayout="vertical"
          dataSource={servers}
          renderItem={(s) => {
            const badge = STATUS_BADGE[s.status] || STATUS_BADGE.unknown
            const toolCount = s.tools_cache?.length ?? 0
            return (
              <List.Item
                actions={[
                  <Button
                    key="tools"
                    size="small"
                    icon={<UnorderedListOutlined />}
                    disabled={toolCount === 0}
                    onClick={() => setToolsDrawer(s)}
                  >
                    工具清单（{toolCount}）
                  </Button>,
                  <Button
                    key="test"
                    size="small"
                    icon={<ThunderboltOutlined />}
                    loading={busy === s.id}
                    onClick={() => onTest(s)}
                  >
                    测试连接
                  </Button>,
                  <Button
                    key="sync"
                    size="small"
                    icon={<SyncOutlined />}
                    loading={busy === s.id}
                    onClick={() => onSync(s)}
                  >
                    同步工具
                  </Button>,
                  <Button
                    key="edit"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => openEdit(s)}
                  >
                    编辑
                  </Button>,
                  <Popconfirm
                    key="del"
                    title="确认删除该 MCP 服务？"
                    onConfirm={() => onDelete(s)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />}>
                      删除
                    </Button>
                  </Popconfirm>,
                  <Switch
                    key="sw"
                    checked={s.enabled}
                    onChange={(v) => onToggle(s, v)}
                    checkedChildren="启用"
                    unCheckedChildren="停用"
                  />,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <Badge status={badge.status} text={s.name} />
                      <Tag>{s.transport === 'sse' ? 'SSE' : 'Streamable HTTP'}</Tag>
                      {s.auth_type !== 'none' && (
                        <Tag color="blue">
                          {s.auth_type === 'bearer' ? 'Bearer' : 'API Key'}
                        </Tag>
                      )}
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={2}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {s.url}
                      </Text>
                      {toolCount === 0 && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          尚未同步工具，点「同步工具」拉取清单。
                        </Text>
                      )}
                      {s.status === 'error' && s.last_error && (
                        <Text type="danger" style={{ fontSize: 12 }}>
                          {s.last_error}
                        </Text>
                      )}
                    </Space>
                  }
                />
              </List.Item>
            )
          }}
        />
      )}

      {/* 工具清单抽屉（默认关闭，点「工具清单」打开） */}
      <Drawer
        title={toolsDrawer ? `${toolsDrawer.name} · 工具清单` : '工具清单'}
        open={!!toolsDrawer}
        onClose={() => setToolsDrawer(null)}
        width={560}
      >
        <Table<McpToolMeta>
          rowKey="name"
          size="small"
          columns={toolColumns}
          dataSource={toolsDrawer?.tools_cache ?? []}
          pagination={false}
        />
      </Drawer>

      <Modal
        title={editing ? '编辑 MCP 服务' : '添加 MCP 服务'}
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => setModalOpen(false)}
        afterOpenChange={onModalOpenChange}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="服务名称"
            name="name"
            rules={[{ required: true, message: '请输入服务名称' }]}
            extra="用于区分不同服务，会作为工具名前缀"
          >
            <Input placeholder="例如：github-mcp" />
          </Form.Item>
          <Form.Item label="传输类型" name="transport" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'streamable_http', label: 'Streamable HTTP' },
                { value: 'sse', label: 'SSE' },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="服务地址 URL"
            name="url"
            rules={[{ required: true, message: '请输入服务地址' }]}
          >
            <Input placeholder="https://example.com/mcp" />
          </Form.Item>
          <Form.Item label="认证方式" name="auth_type" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'none', label: '无' },
                { value: 'bearer', label: 'Bearer Token' },
                { value: 'api_key', label: 'API Key（自定义请求头）' },
              ]}
            />
          </Form.Item>
          {authType === 'bearer' && (
            <Form.Item
              label="Token"
              name="token"
              extra={editing ? '留空表示不修改' : undefined}
              rules={editing ? [] : [{ required: true, message: '请输入 Token' }]}
            >
              <Input.Password placeholder="Bearer Token" />
            </Form.Item>
          )}
          {authType === 'api_key' && (
            <>
              <Form.Item label="请求头名称" name="header">
                <Input placeholder="X-API-Key" />
              </Form.Item>
              <Form.Item
                label="Key"
                name="key"
                extra={editing ? '留空表示不修改' : undefined}
                rules={editing ? [] : [{ required: true, message: '请输入 Key' }]}
              >
                <Input.Password placeholder="API Key" />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>
    </Card>
  )
}
