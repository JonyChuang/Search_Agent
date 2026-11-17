import { Avatar, Badge, Button, ConfigProvider, Drawer, Dropdown, Input, Layout, Menu, Select, message } from 'antd'
import {
  AimOutlined,
  AppstoreOutlined,
  BellOutlined,
  BookOutlined,
  CommentOutlined,
  CompassOutlined,
  ClockCircleOutlined,
  ClusterOutlined,
  HistoryOutlined,
  FileSearchOutlined,
  FormOutlined,
  FundOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoreOutlined,
  PlusOutlined,
  ReadOutlined,
  RightOutlined,
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
  UpOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useChatHeaderStore } from '@/stores/chatHeaderStore'
import { useGroupHeaderStore } from '@/stores/groupHeaderStore'
import { agentTaskApi } from '@/api/agentTask'
import { remindersApi } from '@/api/careerReminders'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import MusicPlayer from '@/components/MusicPlayer'
import logo from '@/images/logo.png'
import { CurrentJobProvider, CurrentJobSelect, useCurrentJob } from '@/pages/career/CurrentJob'
import styles from './MainLayout.module.css'

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
    ],
  },
  {
    type: 'group' as const,
    label: '面试备考',
    children: [
      { key: '/career/preparation', icon: <ReadOutlined />, label: '备考中心' },
      { key: '/career/interviews', icon: <VideoCameraOutlined />, label: '模拟面试' },
    ],
  },
  {
    type: 'group' as const,
    label: '求职进展',
    children: [
      { key: '/career/apply', icon: <FormOutlined />, label: '网申助手' },
      { key: '/career/applications', icon: <FundOutlined />, label: '投递看板' },
      { key: '/career/reminders', icon: <FormOutlined />, label: '计划与提醒' },
    ],
  },
  {
    type: 'group' as const,
    label: '个人工作区',
    children: [
      { key: '/knowledge', icon: <BookOutlined />, label: '我的资料' },
      { key: '/career/memory', icon: <ClusterOutlined />, label: '求职记忆' },
      { key: '/career/tasks', icon: <HistoryOutlined />, label: '任务中心' },
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

const sidebarTheme = {
  components: {
    Menu: {
      itemBg: 'transparent',
      itemColor: '#47506a',
      itemSelectedBg: '#ece9ff',
      itemSelectedColor: '#4736b6',
      itemHoverBg: '#f0eff8',
      itemHoverColor: '#423782',
      itemHeight: 29,
      itemMarginInline: 0,
      itemMarginBlock: 1,
      groupTitleColor: '#676f85',
      groupTitleFontSize: 11,
      subMenuItemBg: 'transparent',
      fontSize: 13,
    },
  },
}

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
  const { job, jobs } = useCurrentJob()
  const [params, setParams] = useSearchParams()
  const boardPage = location.pathname === '/career/applications'
  const applyPage = location.pathname === '/career/apply'
  const interviewPage = location.pathname === '/career/interviews'
  const dashboardPage = boardPage || applyPage || interviewPage || location.pathname === '/'
  const boardJobId = params.get('job')
  const scopedJob = boardJobId ?? (applyPage ? job?.id ?? 'general' : '')
  const workspaceTitle = boardPage ? '投递看板' : applyPage ? '网申助手' : interviewPage ? '模拟面试' : '求职总览'
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
  const [dueReminders, setDueReminders] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    const refresh = () => remindersApi.count(controller.signal).then(setDueReminders).catch(() => {})
    void refresh()
    const timer = window.setInterval(refresh, 60_000)
    window.addEventListener('career-reminders-changed', refresh)
    return () => {
      controller.abort()
      window.clearInterval(timer)
      window.removeEventListener('career-reminders-changed', refresh)
    }
  }, [])
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

  const accountItems = [
    { key: 'profile', icon: <UserOutlined />, label: '个人中心', onClick: () => navigate('/profile') },
    { key: 'comet-workspace', icon: <AppstoreOutlined />, label: 'Comet 工作台', onClick: () => navigate('/workspace') },
    { type: 'divider' as const },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: onLogout },
  ]
  const accountName = user?.nickname || user?.username || '用户'
  const account = (mini: boolean, inSidebar: boolean) => (
    <Dropdown menu={{ items: accountItems }} trigger={['click']} placement={inSidebar ? 'topLeft' : 'bottomRight'}>
      <button type="button" aria-label="账户菜单" className={inSidebar ? styles.account : styles.headerAccount}
        data-mini={mini || undefined} data-immersive={immersive || undefined}>
        {user?.avatar
          ? <AuthenticatedImage src={user.avatar} alt="" className={styles.avatar} />
          : <Avatar size={32} className={styles.avatar}>{Array.from(accountName)[0]?.toUpperCase() || <UserOutlined />}</Avatar>}
        {!mini && <><span className={styles.accountName}>{accountName}</span>{inSidebar && <UpOutlined aria-hidden />}</>}
      </button>
    </Dropdown>
  )

  // logo 头部（桌面 Sider 与移动抽屉共用）
  const brand = (mini: boolean) => (
    <Link to="/" className={styles.brand} data-mini={mini || undefined} data-immersive={immersive || undefined}
      aria-label="Search Agent 求职总览">
      {immersive ? <img src={logo} alt="" className={styles.brandMark} />
        : <span className={styles.brandMark}><CompassOutlined aria-hidden /></span>}
      {!mini && <span><strong>Search Agent</strong>{!immersive && <small>求职工作台</small>}</span>}
    </Link>
  )

  const navMenu = (mini: boolean) => {
    // 给「定时任务」注入未读红点（不改全局静态 menuItems）
    const items = menuItems.map((group) =>
      'children' in group
        ? {
            ...group,
            children: group.children.map((it) => {
              const count = it.key === '/agent-tasks' ? unreadTasks : it.key === '/career/reminders' ? dueReminders : 0
              return count > 0 && !mini
                ? {
                    ...it,
                    label: (
                      <Badge count={count} size="small" offset={[10, 0]}>
                        <span>{it.label}</span>
                      </Badge>
                    ),
                  }
                : it
            }),
          }
        : group,
    )
    const menu = (
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
        className={!immersive ? styles.nav : undefined}
        style={{ borderInlineEnd: 'none', background: 'transparent' }}
      />
    )
    return immersive ? menu : <ConfigProvider theme={sidebarTheme}>{menu}</ConfigProvider>
  }

  return (
    <Layout
      style={{ height: '100%', overflow: 'hidden' }}
      className={`app-shell${immersive ? ' immersive-layout' : ''}`}
    >
      {/* 桌面端：常驻可折叠侧边栏 */}
      {!isMobile && (
        <Sider
          width={immersive ? 236 : 224}
          collapsible
          collapsed={collapsed}
          trigger={null}
          collapsedWidth={72}
          style={{
            borderInlineEnd: immersive
              ? '1px solid rgba(255,255,255,0.08)'
              : '1px solid #e5e7f1',
            background: immersive
              ? 'linear-gradient(180deg, #141633 0%, #0c0d18 100%)'
              : '#fafaff',
            transition: 'background 0.4s',
          }}
        >
          {brand(collapsed)}
          <div className="app-shell-sider-menu">
            {navMenu(collapsed)}
          </div>
          {!immersive && account(collapsed, true)}
        </Sider>
      )}

      {/* 移动端：抽屉式侧边栏 */}
      {isMobile && (
        <Drawer
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          width={224}
          closable={false}
          styles={{
            body: { padding: 0, display: 'flex', flexDirection: 'column', height: '100%' },
            content: immersive
              ? { background: 'linear-gradient(180deg, #141633 0%, #0c0d18 100%)' }
              : { background: '#fafaff' },
          }}
        >
          {brand(false)}
          <div className="app-shell-sider-menu">
            {navMenu(false)}
          </div>
          {!immersive && account(false, true)}
        </Drawer>
      )}

      <Layout
        className="app-shell-main"
        style={{
          background: immersive ? '#0b0c16' : undefined,
          transition: 'background 0.4s',
        }}
      >
        {dashboardPage ? <Header className={styles.dashboardHeader}>
          <div className={styles.headerStart}>
            <button type="button" className={styles.navToggle} aria-label="菜单" aria-expanded={isMobile ? drawerOpen : !collapsed}
              onClick={() => isMobile ? setDrawerOpen(true) : setCollapsed((value) => !value)}>
              {isMobile || collapsed ? <MenuUnfoldOutlined aria-hidden /> : <MenuFoldOutlined aria-hidden />}
            </button>
            <div className={styles.crumb} aria-label="当前位置">
              <span>{boardPage ? <FundOutlined aria-hidden /> : applyPage ? <FormOutlined aria-hidden />
                : interviewPage ? <ReadOutlined aria-hidden /> : <AppstoreOutlined aria-hidden />}
                {boardPage || applyPage ? '求职进展' : interviewPage ? '面试备考' : '工作台'}</span>
              <RightOutlined aria-hidden />
              <strong>{workspaceTitle}</strong>
            </div>
          </div>
          <div className={styles.headerEnd}>
            {(!interviewPage || !params.has('session')) && <div className={styles.jobFilter} data-all-jobs={boardPage && !boardJobId || undefined}>
              {boardPage || applyPage ? <Select aria-label={applyPage ? '选择申请岗位' : '筛选投递岗位'}
                prefix={<AimOutlined aria-hidden />} value={scopedJob}
                options={[
                  applyPage ? { value: 'general', label: '通用简历 · 不绑定岗位' } : { value: '', label: '全部岗位' },
                  ...(jobs ?? []).map((item) => ({ value: item.id, label: item.company + ' · ' + item.title })),
                  ...(boardJobId && boardJobId !== 'general' && !jobs?.some((item) => item.id === boardJobId)
                    ? [{ value: boardJobId, label: '历史岗位' }] : []),
                ]}
                optionFilterProp="label" showSearch popupMatchSelectWidth={false}
                onChange={(value) => {
                  const next = new URLSearchParams(params)
                  if (value) next.set('job', value)
                  else next.delete('job')
                  if (applyPage) {
                    next.delete('version')
                    next.delete('resume')
                  }
                  setParams(next)
                }} /> : <CurrentJobSelect inHeader />}
            </div>}
            <Link to="/settings/notify" className={styles.notification} title="消息推送" aria-label="消息推送">
              <BellOutlined aria-hidden />
            </Link>
          </div>
        </Header> : <Header
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

          {(isMobile || immersive) && account(isMobile, false)}
        </Header>}
        <Content
          className={dashboardPage ? 'app-shell-content ' + styles.dashboardContent : 'app-shell-content'}
          style={dashboardPage ? undefined : { padding: isMobile ? 14 : 24 }}
        >
          {careerPage && !dashboardPage && !jobWorkspace
            && !['/career/jobs', '/career/preparation', '/career/apply'].includes(location.pathname)
            && <CurrentJobSelect maxWidth={1000} />}
          <Outlet key={careerPage && !jobWorkspace && !boardPage && !applyPage && !interviewPage ? job?.id : undefined} />
        </Content>
      </Layout>
      {immersive && <MusicPlayer />}
    </Layout>
  )
}
