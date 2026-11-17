import { greenhousePage, parsePacket } from './greenhouse.js'

const input = document.querySelector('#ticket')
const file = document.querySelector('#resume')
const origin = document.querySelector('#origin')
const result = document.querySelector('#result')
const buttons = [...document.querySelectorAll('button')]
let packet
let busy = false

const update = () => buttons.forEach((button) => { button.disabled = busy || !packet })
input.addEventListener('change', async () => {
  packet = undefined
  busy = true
  update()
  try {
    if (input.files[0]?.size > 150_000) throw new Error('请选用网申助手下载的凭证。')
    packet = parsePacket(await input.files[0].text())
    origin.textContent = `凭证来源 ${packet.server.origin}`
    result.textContent = ''
  } catch (error) {
    origin.textContent = ''
    result.textContent = error instanceof SyntaxError || error instanceof TypeError ? '无法读取凭证文件。' : error.message
  } finally {
    busy = false
    update()
  }
})

async function call(action, url) {
  const endpoint = new URL(`/api/career/application-browser/runs/${packet.ticket.id}/event`, packet.server)
  const response = await fetch(endpoint, {
    method: 'POST', credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(8000),
    headers: { 'Content-Type': 'application/json', 'X-Application-Run': packet.ticket.token },
    body: JSON.stringify({ action, url }),
  })
  const data = await response.json()
  if (!response.ok || data.code !== 0) throw new Error(data.message ?? '无法更新投递状态，请回网申助手核对。')
  return data.data
}

async function execute(action, run) {
  if (busy || !packet) return
  busy = true
  input.disabled = file.disabled = true
  update()
  result.textContent = '处理中…'
  try {
    // Request optional access from this user gesture and only for the packet's server host.
    const granted = await chrome.permissions.request({ origins: [`${packet.server.protocol}//${packet.server.hostname}/*`] })
    if (!granted) throw new Error('需要连接凭证来源，才能核对投递状态。')
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true })
    if (tab?.id == null) throw new Error('请打开本次申请的岗位页面。')
    const script = async (command, resume) => {
      const [evaluation] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: greenhousePage,
        args: [packet.ticket.target, command, command === 'FILL' ? packet.ticket : null, resume ?? null] })
      if (!evaluation?.result) throw new Error('请在对应的岗位页面打开助手，并检查页面提示。')
      if (evaluation.result.error) throw new Error(evaluation.result.error)
      return evaluation.result
    }
    result.textContent = await run(script)
  } catch (error) {
    result.textContent = `${error.message}${action === 'submit' ? '\n如果官网可能已收到申请，请先核对回执。' : ''}`
  } finally {
    busy = false
    input.disabled = file.disabled = false
    update()
  }
}

document.querySelector('#fill').addEventListener('click', () => execute('fill', async (script) => {
  const pdf = file.files[0]
  if (!pdf || pdf.size > 4_000_000 || !(await pdf.slice(0, 5).text()).startsWith('%PDF-')) {
    throw new Error('请选择不超过 4 MB 的简历 PDF。')
  }
  const base64 = await new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1])
    reader.onerror = () => reject(new Error('无法读取简历 PDF。'))
    reader.readAsDataURL(pdf)
  })
  await call('REVIEW', packet.ticket.target)
  const filled = await script('FILL', { name: pdf.name, base64 })
  return (filled.typed.length ? `已填写 ${filled.typed.join('、')}。` : '表单已有内容，请核对。') + '\n检查官网的必填项和附件后，可提交申请。'
}))

document.querySelector('#submit').addEventListener('click', () => execute('submit', async (script) => {
  const checked = await script('CHECK')
  if (await call('PERMIT', checked.url) !== 'VERIFYING') throw new Error('无法取得本次提交许可。')
  await script('CLICK')
  return '请查看官网结果。出现确认页面后，点击读取官网回执。'
}))

document.querySelector('#verify').addEventListener('click', () => execute('verify', async (script) => {
  const receipt = await script('VERIFY')
  await call('CONFIRM', receipt.url)
  return '已同步官网确认。返回网申助手刷新即可查看。'
}))
