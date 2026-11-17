import { useState } from 'react'
import { Alert, Button, Descriptions, Input, Modal, Segmented, Select, Space, Typography, message } from 'antd'
import { skillApi, type PackagePreview, type Skill } from '@/api/skills'

export default function SkillPackageModal({ skill, close, saved }: { skill?: Skill; close: () => void; saved: () => void }) {
  const origin = skill?.package?.versions.find((item) => item.version === skill.package?.activeVersion)
  const [mode, setMode] = useState(origin?.commit ? 'repo' : 'file')
  const [repository, setRepository] = useState(origin?.commit ? origin.source : '')
  const [commit, setCommit] = useState('')
  const [file, setFile] = useState<File>()
  const [preview, setPreview] = useState<PackagePreview>()
  const [rollback, setRollback] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  function request() {
    const body = new FormData()
    if (skill) body.set('skill_id', skill.id)
    if (mode === 'file' && file) body.set('file', file)
    if (mode === 'repo') {
      body.set('repository', repository.trim())
      body.set('commit', commit.trim())
    }
    return body
  }

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(undefined)
    try { await action() }
    catch (failure) { setError(failure instanceof Error ? failure.message : '操作失败，请重试') }
    finally { setBusy(false) }
  }

  const done = () => { message.success('技能包版本已保存'); saved(); close() }
  return <Modal open title={skill ? '管理技能包版本' : '导入技能包'} onCancel={close} closable={!busy}
    maskClosable={!busy} keyboard={!busy} footer={null}>
    <Space direction="vertical" style={{ width: '100%' }}>
      {skill?.package && <Space wrap>
        <Typography.Text>当前版本 {skill.package.activeVersion}</Typography.Text>
        <Select aria-label="选择旧版本" placeholder="选择旧版本" value={rollback} disabled={busy}
          onChange={setRollback} options={skill.package.versions.filter((item) => item.version !== skill.package?.activeVersion)
            .map((item) => ({ label: item.version, value: item.version }))} />
        <Button disabled={!rollback || busy} onClick={() => run(async () => {
          if (rollback) await skillApi.rollback(skill.id, rollback)
          done()
        })}>切换到旧版本</Button>
      </Space>}
      <Segmented disabled={busy || !!origin} value={mode} onChange={(value) => { setPreview(undefined); setMode(value) }}
        options={[{ label: '本地 ZIP', value: 'file' }, { label: 'GitHub 仓库', value: 'repo' }]} />
      {mode === 'file' ? <input aria-label="选择技能包文件" type="file" accept=".zip" disabled={busy}
        onChange={(event) => { setPreview(undefined); setFile(event.target.files?.[0]) }} /> : <>
        <Input aria-label="仓库地址" placeholder="https://github.com/作者/仓库" value={repository}
          disabled={busy || !!origin} onChange={(event) => { setPreview(undefined); setRepository(event.target.value) }} />
        <Input aria-label="提交编号" placeholder="40 位 Git 提交编号" value={commit} disabled={busy}
          onChange={(event) => { setPreview(undefined); setCommit(event.target.value) }} />
      </>}
      {error && <Alert type="error" message={error} />}
      {!preview && <Button loading={busy} disabled={mode === 'file' ? !file : !repository.trim() || !commit.trim()}
        onClick={() => run(async () => setPreview((await skillApi.previewPackage(request())).data))}>预览技能包</Button>}
      {preview && <>
        <Descriptions column={1} size="small" items={[
          { key: 'name', label: '技能', children: preview.manifest.name },
          { key: 'version', label: '版本', children: preview.previousVersion ?
            preview.previousVersion + ' → ' + preview.manifest.version : preview.manifest.version },
          { key: 'tools', label: '所需只读工具', children: preview.manifest.tools.join('、') || '无' },
          { key: 'references', label: '参考资料', children: preview.references.join('、') || '无' },
        ]} />
        <details><summary>查看技能说明</summary>
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', maxHeight: 260, overflow: 'auto' }}>{preview.prompt}</Typography.Paragraph>
        </details>
        {preview.previousPrompt !== undefined && <>
          <details><summary>查看旧版技能说明</summary>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', maxHeight: 260, overflow: 'auto' }}>{preview.previousPrompt}</Typography.Paragraph>
          </details>
          {preview.localPromptEdited && <Alert type="info" message="已编辑的本地提示词会保留" />}
        </>}
        {!!preview.unavailable.length && <Alert type="warning" message={'请先配置并启用：' + preview.unavailable.join('、')} />}
        <Button type="primary" loading={busy} disabled={!!preview.unavailable.length} onClick={() => run(async () => {
          const body = request()
          body.set('digest', preview.digest)
          await skillApi.installPackage(body)
          done()
        })}>{skill ? '应用新版本' : '安装技能包'}</Button>
      </>}
    </Space>
  </Modal>
}

