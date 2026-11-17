import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Input, Space, Tag } from 'antd'
import {
  AimOutlined, ArrowRightOutlined, AudioMutedOutlined, AudioOutlined, CheckCircleOutlined, ClockCircleOutlined, EditOutlined,
  FileTextOutlined, LogoutOutlined, PauseCircleOutlined, PlayCircleOutlined, ReloadOutlined, RobotOutlined, VideoCameraOutlined,
} from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { interviewsApi, type InterviewSession, type InterviewStatus } from '@/api/interviews'
import { interviewTime, modeLabels, phaseLabels } from './interviewLabels'
import { interviewPath } from './paths'
import { useCareerAction } from './useCareerAction'
import { useInterviewCamera, useInterviewVoice } from './useInterviewMedia'
import styles from './interview.module.css'

export function CameraPreview({ stream, className }: { stream: MediaStream; className?: string }) {
  const video = useRef<HTMLVideoElement>(null)
  useEffect(() => {
    if (video.current) video.current.srcObject = stream
  }, [stream])
  return <video ref={video} className={className} autoPlay playsInline muted aria-label="本地摄像头自览" />
}

function useQuestionAudio(prompt: string, enabled: boolean) {
  const current = useRef<SpeechSynthesisUtterance>()
  const [speaking, setSpeaking] = useState(false)
  const [error, setError] = useState('')
  const available = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window

  const stop = useCallback(() => {
    if (!current.current) return
    current.current = undefined
    window.speechSynthesis.cancel()
  }, [])

  const play = useCallback(() => {
    if (!enabled || !available) return
    stop()
    const utterance = new SpeechSynthesisUtterance(prompt)
    utterance.lang = 'zh-CN'
    utterance.rate = 0.95
    const chineseVoice = window.speechSynthesis.getVoices().find((voice) => voice.lang.toLowerCase().startsWith('zh'))
    if (chineseVoice) utterance.voice = chineseVoice
    current.current = utterance
    setError('')
    setSpeaking(true)
    utterance.onend = () => {
      if (current.current !== utterance) return
      current.current = undefined
      setSpeaking(false)
    }
    utterance.onerror = () => {
      if (current.current !== utterance) return
      current.current = undefined
      setSpeaking(false)
      setError('题目语音播放失败，可点击重播或阅读文字。')
    }
    window.speechSynthesis.speak(utterance)
  }, [available, enabled, prompt, stop])

  useEffect(() => {
    setSpeaking(false)
    setError('')
    if (!available || !enabled) return
    const timer = window.setTimeout(play, 200)
    return () => { window.clearTimeout(timer); stop() }
  }, [available, enabled, play, stop])

  return { available, speaking, play, error }
}

type Controls = {
  session: InterviewSession
  camera: ReturnType<typeof useInterviewCamera>
  saving: boolean
  onAnswer: (answer: string) => void
  onFinish: () => void
  onResume: () => void
}

function AnswerTurn({ session, camera, saving, onAnswer, onFinish, onResume }: Controls) {
  const [answer, setAnswer] = useState('')
  const [captions, setCaptions] = useState(true)
  const [typing, setTyping] = useState(false)
  const scroll = useRef<HTMLDivElement>(null)
  const active = session.summary.status === 'ACTIVE'
  const current = session.current!
  const video = session.summary.mode === 'VIDEO'
  const voiceMode = session.summary.mode !== 'TEXT' && !typing
  const waiting = !!session.pending
  const enabled = active && !waiting
  const audio = useQuestionAudio(current.prompt, enabled && voiceMode)
  const append = useCallback((value: string) => {
    setAnswer((previous) => [previous.trimEnd(), value.trim()].filter(Boolean).join(' ').slice(0, 4000))
  }, [])
  const voice = useInterviewVoice(enabled && voiceMode, append)
  const recording = voice.status === 'listening'
  const voiceBusy = voice.status !== 'idle'
  const statusText = !active ? '面试已暂停' : waiting ? '回答已保存' : audio.speaking ? '面试官正在提问'
    : recording ? '正在回答' : '等你回答'
  const voiceStatus = { idle: '开始回答', starting: '正在开启', listening: '结束录音', processing: '正在转写' }[voice.status]

  useEffect(() => {
    const panel = scroll.current
    if (panel) panel.scrollTop = panel.scrollHeight
  }, [session.transcript.length, answer, voice.interim, captions])

  return (
    <div className={`${styles.roomGrid} ${!captions ? styles.roomWide : ''}`}>
      <section className={styles.room} aria-label="面试间">
        <div className={styles.roomStatus}>
          <span><i data-active={active} /> {statusText}</span>
          {video && <span>摄像头仅本地自览</span>}
        </div>
        {active && session.summary.mode !== 'TEXT' && <div className={`${styles.media} ${!video ? styles.voiceOnly : ''}`}>
          {video && <div className={styles.selfView}>
            {camera.stream ? <CameraPreview stream={camera.stream} /> : <div>
              <VideoCameraOutlined /><span>{camera.checking ? '正在打开摄像头' : '摄像头已关闭'}</span>
            </div>}
            <small><VideoCameraOutlined /> 你 · 本地画面</small>
          </div>}
          <div className={styles.interviewer}>
            <small>AI 面试官</small>
            <div className={styles.orb} data-speaking={audio.speaking}><RobotOutlined /></div>
            <span>{waiting ? '正在处理你的回答' : audio.speaking ? '正在提问' : recording ? '正在听你回答' : '等待你的回答'}</span>
            {audio.available && voiceMode && <Button size="small" ghost icon={<PlayCircleOutlined />}
              disabled={waiting || voiceBusy || audio.speaking} onClick={audio.play}>播放题目</Button>}
          </div>
        </div>}
        <div className={styles.question} aria-live="polite">
          <small>{current.followUp ? '当前追问' : phaseLabels[current.phase]}</small>
          <h2>{current.prompt}</h2>
        </div>
        {!active ? <div className={styles.pause}>
          <PauseCircleOutlined /><p>进度已保存，可以随时继续这一题。</p>
          <Button type="primary" icon={<PlayCircleOutlined aria-hidden />} loading={saving} onClick={onResume}>继续面试</Button>
          {!waiting && <Button ghost danger disabled={saving} onClick={onFinish}>结束面试</Button>}
        </div> : <>
          {enabled && (typing || session.summary.mode === 'TEXT' || answer) && <Input.TextArea
            aria-label="你的回答" placeholder="输入或修正本题回答"
            value={answer} maxLength={4000} autoSize={{ minRows: 2, maxRows: 5 }}
            onChange={(event) => setAnswer(event.target.value)} showCount />}
          {enabled && [camera.error, audio.error, voice.error].filter(Boolean).map((error) =>
            <Alert key={error} type="warning" showIcon message={error} />)}
          <div className={styles.roomControls}>
            <Space wrap size={6}>
              {voiceMode && <Button ghost icon={recording ? <AudioMutedOutlined /> : <AudioOutlined />}
                loading={voice.status === 'starting' || voice.status === 'processing'}
                disabled={!enabled || audio.speaking || saving} onClick={voice.toggle}>{voiceStatus}</Button>}
              {video && <Button ghost icon={<VideoCameraOutlined />} loading={camera.checking}
                onClick={() => camera.stream ? camera.disable() : void camera.enable()}>{camera.stream ? '关闭摄像头' : '开启摄像头'}</Button>}
              <Button ghost icon={<FileTextOutlined />} aria-pressed={captions} onClick={() => setCaptions(!captions)}>
                {captions ? '隐藏转写' : '显示转写'}
              </Button>
              {session.summary.mode !== 'TEXT' && <Button ghost icon={<EditOutlined />} disabled={waiting || voiceBusy}
                onClick={() => setTyping(!typing)}>{typing ? '切回语音' : '切换文字'}</Button>}
              {voiceMode && voice.browserAvailable && (voice.error || voice.serverMode) && <Button ghost
                disabled={!enabled || voiceBusy} onClick={() => voice.setServerMode(!voice.serverMode)}>
                {voice.serverMode ? '使用实时转写' : '使用服务转写'}
              </Button>}
            </Space>
            <Space wrap size={6}>
              <Button danger ghost icon={<LogoutOutlined />} disabled={waiting || saving} onClick={onFinish}>结束面试</Button>
              <Button type="primary" icon={<ArrowRightOutlined />} loading={saving}
                disabled={!enabled || voiceBusy || audio.speaking || !answer.trim()} onClick={() => onAnswer(answer.trim())}>完成回答</Button>
            </Space>
          </div>
        </>}
      </section>
      {captions && <aside className={styles.transcript} aria-label="面试转写">
        <header><h2><FileTextOutlined /> {session.summary.mode === 'TEXT' ? '面试对话' : '实时转写'}</h2></header>
        <div className={styles.transcriptBody} ref={scroll}>
          {session.transcript.map((line, index) => <div key={index} className={styles.dialogue}>
            <div><strong>AI 面试官 · {line.followUp ? '追问' : '主问题'}</strong><p>{line.prompt}</p></div>
            <div><strong>你</strong><p>{line.answer}</p></div>
          </div>)}
          {!waiting && <div className={styles.dialogue}>
            <div><strong>AI 面试官 · {current.followUp ? '追问' : '主问题'}</strong><p>{current.prompt}</p></div>
            {voiceMode && (answer || voice.interim) && <div>
              <strong>{voice.interim ? '你 · 正在转写' : '你 · 待提交'}</strong>
              <p>{[answer, voice.interim].filter(Boolean).join(' ')}</p>
            </div>}
          </div>}
        </div>
        <footer><CheckCircleOutlined /> 已提交的回答随面试保存</footer>
      </aside>}
    </div>
  )
}

function Elapsed({ seconds, active }: { seconds: number; active: boolean }) {
  const [value, setValue] = useState(seconds)
  useEffect(() => {
    setValue(seconds)
    if (!active) return
    const started = Date.now()
    const timer = window.setInterval(() => setValue(seconds + Math.floor((Date.now() - started) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [seconds, active])
  return <span className={styles.elapsed}><ClockCircleOutlined /> {interviewTime(value)}</span>
}

export default function InterviewRoom({ session, update, error, reload }: {
  session: InterviewSession
  update: (session: InterviewSession) => void
  error?: string
  reload: () => void
}) {
  const action = useCareerAction()
  const { modal } = App.useApp()
  const { summary, current, pending, revision } = session
  const { id } = summary
  const active = summary.status === 'ACTIVE'
  const camera = useInterviewCamera()
  const { enable, disable } = camera
  useEffect(() => {
    if (summary.mode === 'VIDEO' && active) void enable()
    else disable()
  }, [active, disable, enable, summary.mode])

  function setStatus(status: InterviewStatus) {
    return action.run(async () => update(await interviewsApi.status(id, revision, status)))
  }

  function finish() {
    modal.confirm({
      title: '结束这场面试？',
      content: '已提交的回答会进入复盘，尚未提交的回答将被舍弃。',
      okText: '结束并查看复盘',
      cancelText: '继续面试',
      onOk: () => setStatus('FINISHED'),
    })
  }

  if (!current) return null
  return <>
    <header className={styles.heading}>
      <div><h1>{modeLabels[summary.mode]}</h1><p>{summary.job}</p></div>
      <Space wrap>
        <Elapsed seconds={summary.elapsedSeconds} active={active} />
        <Tag color="purple">主问题 {current.number} / {summary.count}</Tag>
        {active && <Button icon={<PauseCircleOutlined />} disabled={action.saving} onClick={() => void setStatus('PAUSED')}>暂停面试</Button>}
        {!active && <Link to={interviewPath()}>返回模拟面试</Link>}
      </Space>
    </header>
    {error && <Alert type="warning" showIcon message={error} action={<Button size="small" icon={<ReloadOutlined />} onClick={reload}>重载进度</Button>} />}
    {pending?.status === 'FAILED' ? <Alert type="warning" showIcon
      message="本轮回答已保存，评分暂未完成"
      description={pending.error}
      action={active && <Space wrap>
        <Button size="small" loading={action.saving} onClick={() =>
          void action.run(async () => update(await interviewsApi.retry(id, pending.id)))}>重新分析</Button>
        <Button size="small" disabled={action.saving} onClick={() =>
          void action.run(async () => update(await interviewsApi.advance(id, pending.id, true)))}>继续面试</Button>
      </Space>}
    /> : pending && <Alert type="info" showIcon message="回答已保存，面试官正在准备下一步…" />}
    <AnswerTurn key={`${current.number}-${current.followUp}`} session={session} camera={camera} saving={action.saving}
      onResume={() => void setStatus('ACTIVE')} onFinish={finish}
      onAnswer={(answer) => void action.run(async () => {
        const result = await action.submit(`mock-interview-answer-${id}`, { revision, answer }, (input) => interviewsApi.answer(id, input))
        update(result)
      })} />
    <ol className={styles.phaseProgress} aria-label="面试环节进度">
      {session.phases.map(({ phase, total, completed }) =>
        <li key={phase} data-current={phase === current.phase}>
          {phase === current.phase ? <AimOutlined /> : completed === total ? <CheckCircleOutlined /> : <ClockCircleOutlined />}
          <strong>{phaseLabels[phase]}</strong><small>{completed} / {total}</small>
        </li>)}
    </ol>
  </>
}

