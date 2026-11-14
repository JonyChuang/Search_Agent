import { Avatar, Badge, Button, Drawer, Dropdown, Input, Layout, Menu, Space, message } from 'antd'
import {
  AppstoreOutlined,
  BellOutlined,
  BookOutlined,
  CommentOutlined,
  ClockCircleOutlined,
  ClusterOutlined,
  HistoryOutlined,
  FileTextOutlined,
  FileSearchOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoreOutlined,
  PlusOutlined,
  ReadOutlined,
  RobotOutlined,
  SearchOutlined,
  SettingOutlined,
  ShareAltOutlined,
  StarOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  UserOutlined,
  UsergroupAddOutlined,
} from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useChatHeaderStore } from '@/stores/chatHeaderStore'
import { useGroupHeaderStore } from '@/stores/groupHeaderStore'
import { agentTaskApi } from '@/api/agentTask'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import MusicPlayer from '@/components/MusicPlayer'
import logo from '@/images/logo.png'
import { CurrentJobProvider, CurrentJobSelect, useCurrentJob } from '@/pages/career/CurrentJob'

const { Sider, Content, Header } = Layout

// 分组导航：按职责归类，分组标题灰色小字，更清晰
const menuItems = [
  {
    type: 'group' as const,
    label: '工作台',
    children: [
      { key: '/', icon: <AppstoreOutlined />, label: '求职总览' },
      { key: '/chat', icon: <CommentOutlined />, label: '求职助手' },
    ],
  },
  {
    type: 'group' as const,
    label: '求职准备',
    children: [
      { key: '/career/jobs', icon: <FileSearchOutlined />, label: '岗位与公司' },
      { key: '/career/resume', icon: <FileTextOutlined />, label: '简历与经历' },
    ],
  },
  {
    type: 'group' as const,
    label: '面试备考',
    children: [
      { key: '/career/preparation', icon: <ReadOutlined />, label: '备考中心' },
    ],
  },
  {
    type: 'group' as const,
    label: '求职进展',
    children: [
      { key: '/career/apply', label: '网申助手' },
      { key: '/career/applications', label: '投递看板' },
    ],
  },
  {
    type: 'group' as const,
    label: '个人工作区',
    children: [
      { key: '/knowledge', icon: <BookOutlined />, label: '我的资料' },
      { key: '/career/memory', icon: <ClusterOutlined />, label: '求职记忆' },
      { key: '/career/tasks', icon: <HistoryOutlined />, label: '任务记录' },
      { key: '/search', icon: <SearchOutlined />, label: '全局搜索' },
      { key: '/favorites', icon: <StarOutlined />, label: '收藏夹' },
      { key: '/agent-tasks', icon: <ClockCircleOutlined />, label: '定时任务' },
    ],
  },
  {
    key: 'settings',
    icon: <SettingOutlined />,
    label: '设置',
    children: [
      { key: '/settings/models', icon: <SettingOutlined />, label: '模型配置' },
      { key: '/settings/agent', icon: <RobotOutlined />, label: '角色配置' },
      { key: '/settings/skills', icon: <ThunderboltOutlined />, label: '技能中心' },
      { key: '/settings/tools', icon: <ToolOutlined />, label: '工具配置' },
      { key: '/settings/notify', icon: <BellOutlined />, label: '消息推送' },
    ],
  },
]

// 小屏（手机/窄平板）检测：≤768px 走抽屉式侧边栏
function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= 768,
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return isMobile
}

export default function MainLayout() {
  const userId = useAuthStore((state) => state.user?.id)
  return <CurrentJobProvider key={userId}><MainLayoutContent /></CurrentJobProvider>
}

function MainLayoutContent() {
  const navigate = useNavigate()
  const location = useLocation()
  const { job } = useCurrentJob()
  const careerPage = location.pathname === '/' || location.pathname.startsWith('/career/')
  const jobWorkspace = location.pathname.startsWith('/career/jobs/')
  const menuKey = jobWorkspace ? '/career/jobs'
    : location.pathname.startsWith('/knowledge-bases/') ? '/knowledge'
    : location.pathname
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const isMobile = useIsMobile()
  // 聊天页注册的顶栏操作（手机端聊天页用它替代搜索框，合并成一行）
  const chatHeaderActive = useChatHeaderStore((s) => s.active)
  const chatOpenHistory = useChatHeaderStore((s) => s.openHistory)
  const chatNewChat = useChatHeaderStore((s) => s.newChat)
  const chatOpenShare = useChatHeaderStore((s) => s.openShare)
  const chatCanShare = useChatHeaderStore((s) => s.canShare)
  const showChatHeader = isMobile && chatHeaderActive && location.pathname === '/chat'

  // 群聊页注册的顶栏操作（手机端群聊页用它替代搜索框 + 替代群聊自己的标题栏）
  const groupHeaderActive = useGroupHeaderStore((s) => s.active)
  const groupTitle = useGroupHeaderStore((s) => s.title)
  const groupOpenList = useGroupHeaderStore((s) => s.openList)
  const groupOpenInvite = useGroupHeaderStore((s) => s.openInvite)
  const groupOpenShare = useGroupHeaderStore((s) => s.openShare)
  const groupCanShare = useGroupHeaderStore((s) => s.canShare)
  const groupMoreItems = useGroupHeaderStore((s) => s.moreItems)
  const showGroupHeader =
    isMobile && groupHeaderActive && location.pathname === '/group-chat'

  // 桌面端：侧边栏折叠（窄条）；移动端：抽屉开关
  const [collapsed, setCollapsed] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(true)

  // 切换路由后自动关闭移动端抽屉
  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

  // 定时任务未读红点：轮询 + 路由切换时刷新（离开任务页 mark-seen 后归零）
  const [unreadTasks, setUnreadTasks] = useState(0)
  useEffect(() => {
    let alive = true
    const fetchUnread = () => {
      agentTaskApi
        .unreadCount()
        .then(({ data }) => {
          if (alive) setUnreadTasks(data.count)
        })
        .catch(() => {})
    }
    fetchUnread()
    const timer = window.setInterval(fetchUnread, 60000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [location.pathname])

  // 音乐页沉浸式深色主题：进入 /music 整体变深色霓虹，离开自动恢复
  const immersive = location.pathname === '/music'

  // 主壳挂载时锁死 html/body 滚动（比 :has 更稳），卸载后恢复登录/分享页整页滚动
  useEffect(() => {
    const root = document.documentElement
    root.classList.add('app-shell-active')
    return () => root.classList.remove('app-shell-active')
  }, [])

  const onLogout = async () => {
    await logout()
    message.success('已退出登录')
    navigate('/login', { replace: true })
  }

  // logo 头部（桌面 Sider 与移动抽屉共用）
  const brand = (mini: boolean) => (
    <div
      style={{
        height: 64,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        paddingInline: mini ? 0 : 20,
        justifyContent: mini ? 'center' : 'flex-start',
        color: immersive ? '#fff' : '#171719',
        overflow: 'hidden',
      }}
    >
      <img
        src={logo}
        alt="彗记"
        style={{ width: 36, height: 36, borderRadius: 9, objectFit: 'cover', flexShrink: 0 }}
      />
      {!mini && (
        <span style={{ fontWeight: 600, fontSize: 19, whiteSpace: 'nowrap' }}>Search Agent</span>
      )}
    </div>
  )

  const navMenu = (mini: boolean) => {
    // 给「定时任务」注入未读红点（不改全局静态 menuItems）
    const items = menuItems.map((group) =>
      'children' in group
        ? {
            ...group,
            children: group.children.map((it) =>
              it.key === '/agent-tasks' && unreadTasks > 0 && !mini
                ? {
                    ...it,
                    label: (
                      <Badge count={unreadTasks} size="small" offset={[10, 0]}>
                        <span>{it.label}</span>
                      </Badge>
                    ),
                  }
                : it,
            ),
          }
        : group,
    )
    return (
      <Menu
        mode="inline"
        theme={immersive ? 'dark' : 'light'}
        inlineCollapsed={mini}
        openKeys={mini ? undefined : settingsOpen ? ['settings'] : []}
        onOpenChange={(keys) => {
          if (!mini) setSettingsOpen(keys.includes('settings'))
        }}
        selectedKeys={[menuKey]}
        items={items}
        onClick={({ key }) => navigate(key)}
        style={{ borderInlineEnd: 'none', background: 'transparent' }}
      />
    )
  }

  return (
    <Layout
      style={{ height: '100%', overflow: 'hidden' }}
      className={`app-shell${immersive ? ' immersive-layout' : ''}`}
    >
      {/* 桌面端：常驻可折叠侧边栏 */}
      {!isMobile && (
        <Sider
          width={236}
          collapsible
          collapsed={collapsed}
          trigger={null}
          collapsedWidth={72}
          style={{
            borderInlineEnd: immersive
              ? '1px solid rgba(255,255,255,0.08)'
              : '1px solid #f0f0f0',
            background: immersive
              ? 'linear-gradient(180deg, #141633 0%, #0c0d18 100%)'
              : undefined,
            transition: 'background 0.4s',
          }}
        >
          {brand(collapsed)}
          <div className="app-shell-sider-menu" style={{ paddingBottom: 12 }}>
            {navMenu(collapsed)}
          </div>
        </Sider>
      )}

      {/* 移动端：抽屉式侧边栏 */}
      {isMobile && (
        <Drawer
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          width={236}
          closable={false}
          styles={{
            body: { padding: 0, display: 'flex', flexDirection: 'column', height: '100%' },
            content: immersive
              ? { background: 'linear-gradient(180deg, #141633 0%, #0c0d18 100%)' }
              : undefined,
          }}
        >
          {brand(false)}
          <div className="app-shell-sider-menu" style={{ paddingBottom: 12 }}>
            {navMenu(false)}
          </div>
        </Drawer>
      )}

      <Layout
        className="app-shell-main"
        style={{
          background: immersive ? '#0b0c16' : undefined,
          transition: 'background 0.4s',
        }}
      >
        <Header
          style={{
            flexShrink: 0,
            paddingInline: isMobile ? 12 : 24,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
            borderBottom: immersive
              ? '1px solid rgba(255,255,255,0.08)'
              : '1px solid #f0f0f0',
            background: immersive ? 'rgba(18,20,40,0.8)' : undefined,
            backdropFilter: immersive ? 'blur(10px)' : undefined,
            transition: 'background 0.4s',
          }}
        >
          <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center' }}>
            <Button
              type="text"
              aria-label="菜单"
              icon={
                isMobile ? (
                  <MenuUnfoldOutlined />
                ) : collapsed ? (
                  <MenuUnfoldOutlined />
                ) : (
                  <MenuFoldOutlined />
                )
              }
              onClick={() =>
                isMobile ? setDrawerOpen(true) : setCollapsed((c) => !c)
              }
              style={{ color: immersive ? '#fff' : undefined, fontSize: 18 }}
            />
          </div>

          {/* 中间区：手机端聊天页显示「会话 / 新对话」，群聊页显示群控制，其余页面显示搜索框 */}
          {showChatHeader ? (
            <div
              style={{
                flex: 1,
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                gap: 8,
                minWidth: 0,
                padding: '0 8px',
              }}
            >
              <Button
                type="text"
                icon={<HistoryOutlined />}
                onClick={() => chatOpenHistory?.()}
              >
                会话
              </Button>
              <Button
                type="text"
                icon={<PlusOutlined />}
                onClick={() => chatNewChat?.()}
              >
                新对话
              </Button>
              {chatCanShare && (
                <Button
                  type="text"
                  icon={<ShareAltOutlined />}
                  onClick={() => chatOpenShare?.()}
                >
                  分享
                </Button>
              )}
            </div>
          ) : showGroupHeader ? (
            <div
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                minWidth: 0,
                padding: '0 4px',
              }}
            >
              <Button
                type="text"
                icon={<TeamOutlined />}
                onClick={() => groupOpenList?.()}
                style={{ flexShrink: 0 }}
              />
              <span
                style={{
                  flex: 1,
                  minWidth: 0,
                  fontWeight: 600,
                  fontSize: 15,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {groupTitle || '群聊'}
              </span>
              <Button
                type="text"
                icon={<UsergroupAddOutlined />}
                onClick={() => groupOpenInvite?.()}
                style={{ flexShrink: 0 }}
              />
              {groupCanShare && (
                <Button
                  type="text"
                  icon={<ShareAltOutlined />}
                  onClick={() => groupOpenShare?.()}
                  style={{ flexShrink: 0 }}
                />
              )}
              {groupMoreItems && groupMoreItems.length > 0 && (
                <Dropdown trigger={['click']} menu={{ items: groupMoreItems }}>
                  <Button type="text" icon={<MoreOutlined />} style={{ flexShrink: 0 }} />
                </Dropdown>
              )}
            </div>
          ) : (
            <div
              style={{
                flex: 1,
                display: 'flex',
                justifyContent: 'center',
                minWidth: 0,
                padding: isMobile ? '0 8px' : '0 16px',
              }}
            >
              <Input
                className={`top-search${immersive ? ' top-search--dark' : ''}`}
                prefix={<SearchOutlined style={{ color: '#98A2B3' }} />}
                placeholder={isMobile ? '搜索…' : '搜索文档、图片、记忆…'}
                allowClear
                style={{ width: '100%', maxWidth: 560 }}
                onPressEnter={(e) => {
                  const q = (e.target as HTMLInputElement).value.trim()
                  if (q) navigate(`/search?q=${encodeURIComponent(q)}`)
                }}
              />
            </div>
          )}

          <Dropdown
            menu={{
              items: [
                {
                  key: 'profile',
                  icon: <UserOutlined />,
                  label: '个人中心',
                  onClick: () => navigate('/profile'),
                },
                {
                  key: 'comet-workspace',
                  icon: <AppstoreOutlined />,
                  label: 'Comet 工作台',
                  onClick: () => navigate('/workspace'),
                },
                { type: 'divider' },
                {
                  key: 'logout',
                  icon: <LogoutOutlined />,
                  label: '退出登录',
                  onClick: onLogout,
                },
              ],
            }}
          >
            <Space align="center" style={{ cursor: 'pointer', flexShrink: 0 }}>
              {user?.avatar ? (
                <AuthenticatedImage
                    src={user.avatar}
                    alt="头像"
                    style={{
                      width: 30,
                      height: 30,
                      borderRadius: '50%',
                      objectFit: 'cover',
                      display: 'block',
                    }}
                  />
                ) : (
                  <Avatar size={30} style={{ background: '#155EEF' }}>
                    {user?.username?.[0]?.toUpperCase() ?? <UserOutlined />}
                  </Avatar>
                )}
                {!isMobile && (
                  <span style={{ fontWeight: 500, color: immersive ? '#fff' : undefined }}>
                    {user?.nickname || user?.username || '用户'}
                  </span>
                )}
              </Space>
            </Dropdown>
          </Header>
          <Content
            className="app-shell-content"
            style={{
              padding: isMobile ? 14 : 24,
            }}
          >
            {careerPage && !jobWorkspace && !['/career/jobs', '/career/preparation'].includes(location.pathname)
              && <CurrentJobSelect maxWidth={location.pathname === '/' ? 1280 : 1000} />}
            <Outlet key={careerPage && !jobWorkspace ? job?.id : undefined} />
          </Content>
        </Layout>
        {immersive && <MusicPlayer />}
      </Layout>
    )
  }
