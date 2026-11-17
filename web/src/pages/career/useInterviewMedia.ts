import { useCallback, useEffect, useRef, useState } from 'react'
import { chatApi } from '@/api/chat'

export async function openInterviewDevice(type: 'video' | 'audio') {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('请使用 HTTPS 或 localhost 打开页面后访问摄像头和麦克风。')
  }
  try {
    return await navigator.mediaDevices.getUserMedia({ [type]: true })
  } catch {
    throw new Error(type === 'video' ? '无法访问摄像头，请检查浏览器权限。' : '无法访问麦克风，请检查浏览器权限。')
  }
}

function release(stream?: MediaStream) {
  stream?.getTracks().forEach((track) => track.stop())
}

export function useInterviewCamera() {
  const streamRef = useRef<MediaStream>()
  const requestId = useRef(0)
  const [stream, setStream] = useState<MediaStream>()
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState('')

  const close = useCallback(() => {
    requestId.current++
    release(streamRef.current)
    streamRef.current = undefined
  }, [])

  const disable = useCallback(() => {
    close()
    setStream(undefined)
    setChecking(false)
    setError('')
  }, [close])

  useEffect(() => close, [close])

  const enable = useCallback(async () => {
    close()
    const request = requestId.current
    setChecking(true)
    setError('')
    try {
      const next = await openInterviewDevice('video')
      if (requestId.current !== request) {
        release(next)
        return
      }
      streamRef.current = next
      setStream(next)
      next.getVideoTracks()[0]?.addEventListener('ended', () => {
        if (streamRef.current !== next) return
        disable()
        setError('摄像头已断开，可以重新开启。')
      }, { once: true })
    } catch (failure) {
      if (requestId.current === request) setError((failure as Error).message)
    } finally {
      if (requestId.current === request) setChecking(false)
    }
  }, [close, disable])

  return { stream, checking, error, enable, disable }
}

type RecognitionResult = {
  resultIndex: number
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>
}
type Recognition = {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: RecognitionResult) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

function recognitionType() {
  const browser = window as unknown as {
    SpeechRecognition?: new () => Recognition
    webkitSpeechRecognition?: new () => Recognition
  }
  return browser.SpeechRecognition ?? browser.webkitSpeechRecognition
}

type VoiceState = 'idle' | 'starting' | 'listening' | 'processing'

export function useInterviewVoice(enabled: boolean, onText: (text: string) => void) {
  const Recognition = recognitionType()
  const [serverMode, setServerMode] = useState(!Recognition)
  const [status, setStatus] = useState<VoiceState>('idle')
  const [interim, setInterim] = useState('')
  const [error, setError] = useState('')
  const cancel = useRef<() => void>()
  const stop = useRef<() => void>()
  const request = useRef(0)

  const reset = useCallback(() => {
    request.current++
    cancel.current?.()
    cancel.current = undefined
    stop.current = undefined
  }, [])

  useEffect(() => {
    if (!enabled) {
      setStatus('idle')
      setInterim('')
    }
    return reset
  }, [enabled, reset])

  async function start() {
    reset()
    const id = request.current
    setError('')
    setInterim('')
    setStatus('starting')
    if (Recognition && !serverMode) {
      const recognition = new Recognition()
      recognition.lang = 'zh-CN'
      recognition.continuous = true
      recognition.interimResults = true
      recognition.onresult = ({ results, resultIndex }) => {
        if (request.current !== id) return
        const finalized: string[] = []
        const partial: string[] = []
        for (let index = resultIndex; index < results.length; index++) {
          const result = results[index]
          const destination = result.isFinal ? finalized : partial
          destination.push(result[0].transcript)
        }
        if (finalized.length) onText(finalized.join(' '))
        setInterim(partial.join(' '))
      }
      recognition.onerror = ({ error: reason }) => {
        if (request.current !== id) return
        setError(reason === 'not-allowed' ? '麦克风权限被拒绝。'
          : '浏览器未能转写，重试、使用服务转写或切换文字回答。')
      }
      recognition.onend = () => {
        if (request.current !== id) return
        setInterim('')
        setStatus('idle')
      }
      cancel.current = () => recognition.abort()
      stop.current = () => {
        setStatus('processing')
        recognition.stop()
      }
      try {
        recognition.start()
        setStatus('listening')
      } catch {
        setError('浏览器语音识别无法启动，可使用服务转写或文字回答。')
        setStatus('idle')
      }
      return
    }

    let stream: MediaStream | undefined
    try {
      if (typeof MediaRecorder === 'undefined') throw new Error('当前浏览器无法录音，请切换文字回答。')
      stream = await openInterviewDevice('audio')
      if (id !== request.current) {
        release(stream)
        return
      }
      const recorder = new MediaRecorder(stream)
      const chunks: Blob[] = []
      const upload = new AbortController()
      const timer = window.setTimeout(() => stop.current?.(), 60_000)
      cancel.current = () => {
        window.clearTimeout(timer)
        upload.abort()
        if (recorder.state === 'recording') recorder.stop()
        release(stream)
      }
      stop.current = () => {
        if (recorder.state === 'recording') recorder.stop()
      }
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
      recorder.onerror = () => {
        if (id !== request.current) return
        reset()
        setError('录音中断，请重试或切换文字回答。')
        setStatus('idle')
      }
      recorder.onstop = async () => {
        release(stream)
        window.clearTimeout(timer)
        if (id !== request.current) return
        setStatus('processing')
        try {
          const recording = new Blob(chunks, { type: recorder.mimeType })
          if (recording.size < 1000) throw new Error('录音太短，请重试。')
          const { data } = await chatApi.transcribe(recording, upload.signal)
          if (id !== request.current) return
          if (data.text?.trim()) onText(data.text)
          else setError('没有识别到语音，请重新录制。')
        } catch (failure) {
          if (id === request.current) setError((failure as Error).message || '语音转写失败。')
        } finally {
          if (id === request.current) setStatus('idle')
        }
      }
      recorder.start()
      setStatus('listening')
    } catch (failure) {
      release(stream)
      if (id === request.current) {
        reset()
        setError((failure as Error).message)
        setStatus('idle')
      }
    }
  }

  function toggle() {
    if (!enabled) return
    if (status === 'listening') stop.current?.()
    if (status === 'idle') void start()
  }

  return { status, interim, error, serverMode, browserAvailable: Boolean(Recognition), setServerMode, toggle }
}
