import axios from 'axios'

// 统一请求封装：baseURL=/api，返回体 { code, message, data }
// timeout 给到 5 分钟：上传大文件 + 转存 OSS 在低带宽下耗时长，避免前端过早 timeout。
// 普通接口正常都是秒级返回，不受影响。
const client = axios.create({
  baseURL: '/api',
  timeout: 300000,
})

function isCareerRequest(url?: string) {
  return url?.startsWith('/career/') ?? false
}

// 请求拦截：附带 token（账号体系阶段启用）
client.interceptors.request.use((config) => {
  if (isCareerRequest(config.url) && config.timeout === client.defaults.timeout) {
    config.timeout = 10000
  }
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：解包 { code, message, data }
client.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body.code !== 'undefined' && body.code !== 0) {
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    if (isCareerRequest(resp.config.url) && resp.config.url !== '/career/health'
        && (body?.code !== 0 || body.data === undefined)) {
      throw new Error('求职服务返回了无法识别的内容，请检查前端代理是否连接到 Java 后端。')
    }
    return body
  },
  async (error) => {
    if (error.response?.status === 401) {
      const currentToken = localStorage.getItem('access_token')
      const sentAuthorization = error.config?.headers?.get?.('Authorization')
      if (sentAuthorization && sentAuthorization !== `Bearer ${currentToken}`) {
        throw new Error('登录状态已更新，请重试。')
      }

      if (isCareerRequest(error.config?.url) && currentToken) {
        // 求职服务独立验签，只有 Comet 能确认当前会话是否已失效。
        try {
          await client.get('/auth/me', { timeout: 5000, signal: error.config.signal })
        } catch {
          throw new Error('暂时无法确认登录状态，请重试。')
        }
        throw new Error('求职服务未接受当前登录凭证。请检查 Java 与 Comet 的签名密钥和算法是否一致，再重试。')
      }

      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    if (isCareerRequest(error.config?.url)) {
      if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
        throw new Error('求职服务响应超时，请重试。若仍超时，请检查 Java 后端是否已启动。')
      }
      if (error.response?.status === 404 && !error.response.data?.message) {
        throw new Error('当前 Java 后端缺少此接口，请用最新代码重新启动后端。')
      }
    }
    const message =
      error.response?.data?.message || error.message || '网络错误'
    return Promise.reject(new Error(message))
  },
)

export default client
