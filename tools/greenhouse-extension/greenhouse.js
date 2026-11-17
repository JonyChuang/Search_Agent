// Runs in the selected tab. Keep this function self-contained for Chrome scripting.
export function greenhousePage(target, action, ticket, resume) {
  const expected = new URL(target)
  const current = new URL(location.href)
  const path = (address) => address.pathname.replace(/\/$/, '')
  if (current.origin !== expected.origin || path(current) !== path(expected)) {
    throw new Error('请切换到这份凭证对应的 Greenhouse 岗位页面。')
  }
  const clean = (value) => value.replace(/\s+/g, ' ').trim().replace(/\s*\*$/, '').toLowerCase()
  const buttons = () => [...document.querySelectorAll('button, input[type="submit"]')].filter((button) =>
    button.getClientRects().length && clean(button instanceof HTMLInputElement ? button.value : button.textContent) === 'submit application')
  if (action === 'VERIFY') {
    const success = [...document.querySelectorAll('main h1, main h2, [role="alert"], h1')]
      .some((element) => element.getClientRects().length && [
        'thank you for applying', 'thank you for applying!', 'application submitted', 'application submitted!',
        'your application has been submitted', 'your application has been submitted.',
      ].includes(clean(element.textContent)))
    if (!success || buttons().length) throw new Error('暂未读到此岗位的官网确认。请查看官网或邮件后回网申助手记录结果。')
    return { url: current.origin + path(current) }
  }
  const submit = buttons()
  if (submit.length !== 1 || submit[0].disabled || submit[0].getAttribute('aria-disabled') === 'true') {
    throw new Error('没有找到可用的申请提交按钮，请打开完整的岗位申请表。')
  }
  if (action === 'CHECK' || action === 'CLICK') {
    const form = submit[0].form ?? submit[0].closest('form')
    if (form && !form.reportValidity()) throw new Error('请补全官网标记的必填项，再提交。')
    if (action === 'CLICK') submit[0].click()
    return { url: current.origin + path(current) }
  }
  const typed = []
  const locate = (key, label, selector = 'input, textarea') => {
    const direct = key && (document.getElementById(key) || document.querySelector(`[name="${key}"]`))
    if (direct?.matches(selector)) return direct
    const matches = [...document.querySelectorAll('label')].filter((item) => clean(item.textContent) === clean(label))
    return matches.length === 1 && matches[0].control?.matches(selector) ? matches[0].control : undefined
  }
  const setText = (key, label, value) => {
    if (typeof value !== 'string' || !value.trim()) return
    const control = locate(key, label, 'input:not([type]), input[type=text], input[type=email], input[type=tel], textarea')
    if (!control || control.value || control.disabled || control.readOnly || !control.getClientRects().length) return
    const type = control instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement
    Object.getOwnPropertyDescriptor(type.prototype, 'value').set.call(control, value)
    control.dispatchEvent(new Event('input', { bubbles: true }))
    control.dispatchEvent(new Event('change', { bubbles: true }))
    typed.push(label)
  }
  setText('first_name', 'First Name', ticket.firstName)
  setText('last_name', 'Last Name', ticket.lastName)
  setText('email', 'Email', ticket.answers.email)
  setText('phone', 'Phone', ticket.answers.phone)
  if (resume) {
    const field = locate('resume', 'Resume/CV', 'input[type=file]')
    if (!field || field.disabled) throw new Error('请在官网简历选项点击 Attach，打开上传控件后重试。')
    if (!field.files.length) {
      const transfer = new DataTransfer()
      transfer.items.add(new File([Uint8Array.from(atob(resume.base64), (char) => char.charCodeAt(0))], resume.name,
        { type: 'application/pdf' }))
      field.files = transfer.files
      field.dispatchEvent(new Event('change', { bubbles: true }))
      typed.push('简历 PDF')
    }
  }
  return { url: current.origin + path(current), typed }
}

export function parsePacket(contents) {
  const packet = JSON.parse(contents)
  const server = new URL(packet.server)
  const ticket = packet.ticket
  const target = new URL(ticket.target)
  if (server.origin !== packet.server || !(server.protocol === 'https:' ||
      (server.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(server.hostname))) ||
      target.origin !== 'https://job-boards.greenhouse.io' ||
      !/^\/[a-zA-Z0-9_-]{1,100}\/jobs\/\d{1,20}\/?$/.test(target.pathname) ||
      !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(ticket.id) ||
      !/^[a-zA-Z0-9_-]{43}$/.test(ticket.token) || !(Date.parse(ticket.expiresAt) > Date.now()) ||
      typeof ticket.firstName !== 'string' || typeof ticket.lastName !== 'string' || typeof ticket.answers?.email !== 'string') {
    throw new Error('凭证不完整或已过期，请从网申助手重新下载。')
  }
  return { server, ticket }
}
