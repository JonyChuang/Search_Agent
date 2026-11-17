import client from './client'

export type InterviewMode = 'VIDEO' | 'VOICE' | 'TEXT'
export type InterviewPhase = 'WARMUP' | 'CORE' | 'SCENARIO'
export type InterviewStatus = 'ACTIVE' | 'PAUSED' | 'FINISHED'

export interface InterviewSummary {
  id: string
  jobId: string
  job: string
  mode: InterviewMode
  status: InterviewStatus
  count: number
  answered: number
  followUps: number
  elapsedSeconds: number
  createdAt: string
}

export interface InterviewScore {
  accuracy: number
  evidence: number
  structure: number
  feedback: string
}

export interface InterviewAnswer {
  answer: string
  evaluation: InterviewScore | null
  evaluationUnavailable: boolean
}

export interface InterviewRound {
  question: {
    id: string
    version: number
    gradingVersion: number
    phase: InterviewPhase
    topic: string
    prompt: string
    rubric: string[]
    sourceName: string
    sourceUrl: string | null
  }
  main: InterviewAnswer
  followUp: string | null
  extra: InterviewAnswer | null
}

export interface InterviewSession {
  summary: InterviewSummary
  revision: number
  current: { number: number; phase: InterviewPhase; prompt: string; followUp: boolean } | null
  phases: { phase: InterviewPhase; total: number; completed: number }[]
  transcript: { prompt: string; answer: string; followUp: boolean }[]
  pending: { id: string; status: 'QUEUED' | 'RUNNING' | 'FAILED' | 'SUCCEEDED'; error: string | null; generation: number } | null
  review: InterviewRound[]
}

type Response<T> = { code: number; message: string; data: T }
const base = '/career/interviews'

async function send(path: string, input: object, signal?: AbortSignal) {
  return (await client.post<unknown, Response<InterviewSession>>(`${base}${path}`, input, { signal })).data
}

export const interviewsApi = {
  list: async (page: number, signal: AbortSignal) => (await client.get<unknown,
    Response<{ items: InterviewSummary[]; hasMore: boolean }>>(base, { signal, params: { page } })).data,
  get: async (id: string, signal: AbortSignal) => (await client.get<unknown, Response<InterviewSession>>(
    `${base}/${encodeURIComponent(id)}`, { signal },
  )).data,
  start: (input: { jobId: string; mode: InterviewMode; count: number; requestId: string }) => send('', input),
  answer: (id: string, input: { requestId: string; revision: number; answer: string }) => send(`/${id}/answer`, input),
  status: (id: string, revision: number, status: InterviewStatus) => send(`/${id}/status`, { revision, status }),
  advance: (id: string, taskId: string, skipFailed: boolean, signal?: AbortSignal) =>
    send(`/${id}/advance`, { taskId, skipFailed }, signal),
  retry: (id: string, taskId: string) => send(`/${id}/retry`, { taskId }),
}
