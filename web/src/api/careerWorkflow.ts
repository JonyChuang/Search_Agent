import client from './client'
import type { ExperienceInput } from './career'
import type { Question } from './practice'

type Response<T> = { code: number; message: string; data: T }
type JobRequest = { jobId: string }
type PreparationInput = { documentIds?: string[]; skillId?: string }

export type TaskKind = 'TRAINING' | 'REVIEW' | 'INTERVIEW' | 'PREPARATION' | 'DISCOVERY'

export interface OpenQuestion {
  topic: string
  prompt: string
  rubric: string[]
}

export interface CareerTask {
  id: string
  kind: TaskKind
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  request: { jobId?: string; questionVersion?: number }
  job: string
  interview: { prompt: string; gradingVersion: number; sourceUrl: string; answer: string } | null
  result: {
    analysis?: string
    questions?: (Pick<Question, 'id' | 'version' | 'prompt'> & { kind?: 'OPEN' })[]
    openQuestions?: OpenQuestion[]
    skills?: string[]
    steps?: string[]
    feedback?: string
    sources?: { title: string; url: string; snippet: string }[]
    searchedAt?: string
  } | null
  error: string | null
  generation: number
  trainingStep?: 'FIND_QUESTIONS' | 'GENERATE_PLAN' | 'SAVE_PLAN' | 'COMPLETE' | null
  references?: { id: string; title: string; revision: string }[] | null
  createdAt: string
}

export interface TaskEvent {
  generation: number
  sequenceNo: number
  step: string
  outcome: 'succeeded' | 'failed'
  elapsedMs: number
  inputTokens: number | null
  outputTokens: number | null
}

export interface JobMemory {
  revision: number
  notes: string | null
}

export interface Resume {
  id: string
  jobId: string
  company: string
  jobTitle: string
  evidence: (ExperienceInput & { id: string })[]
  createdAt: string
}

export const applicationStages = {
  DRAFT: '草稿',
  SUBMITTED: '已投递',
  SCREENING: '筛选中',
  INTERVIEW: '面试中',
  OFFER: '已获录用',
  REJECTED: '未通过',
  WITHDRAWN: '已撤回',
}
export type Stage = keyof typeof applicationStages

interface Draft {
  resumeId?: string | null
  answers?: string
}

export interface Application extends Draft {
  id: string
  jobId: string
  company: string
  jobTitle: string
  sourceUrl: string | null
  stage: Stage
  revision: number
}

export interface ApplicationEvent {
  stage: Stage
  note: string | null
  createdAt: string
}

async function get<T>(path: string, signal?: AbortSignal, params?: Record<string, unknown>) {
  return (await client.get<unknown, Response<T>>(path, { signal, params })).data
}

async function post<T>(path: string, input?: object) {
  return (await client.post<unknown, Response<T>>(path, input)).data
}

export const careerWorkflow = {
  tasks: (kind: TaskKind, page: number, signal: AbortSignal, jobId?: string) =>
    get<{ items: CareerTask[]; hasMore: boolean }>('/career/tasks', signal, { kind, page, jobId }),
  task: (id: string, signal: AbortSignal) => get<CareerTask>(`/career/tasks/${encodeURIComponent(id)}`, signal),
  taskEvents: (id: string, signal: AbortSignal) => get<TaskEvent[]>(`/career/tasks/${id}/events`, signal),
  trainingProgress: (id: string, signal: AbortSignal) =>
    get<Pick<Question, 'id' | 'version'>[]>(`/career/tasks/${id}/training-progress`, signal),
  memory: (jobId: string, signal: AbortSignal) => get<JobMemory>(`/career/jobs/${jobId}/memory`, signal),
  saveMemory: async (jobId: string, input: JobMemory) =>
    (await client.put<unknown, Response<JobMemory>>(`/career/jobs/${jobId}/memory`, input)).data,
  prepare: (input: JobRequest & PreparationInput & { requestId: string }) => post<CareerTask>('/career/tasks/preparation', input),
  discover: (input: JobRequest & { requestId: string }) => post<CareerTask>('/career/tasks/discovery', input),
  training: (input: JobRequest & PreparationInput & { requestId: string; role?: string; preparationId?: string; preferredQuestion?: string }) =>
    post<CareerTask>('/career/tasks/training', input),
  review: (input: { requestId: string; planId: string }) => post<CareerTask>('/career/tasks/review', input),
  interview: (input: JobRequest & PreparationInput & { requestId: string; questionId: string; questionVersion: number; answer: string }) =>
    post<CareerTask>('/career/tasks/interview', input),
  retry: (id: string) => post<CareerTask>(`/career/tasks/${id}/retry`),
  resumes: (signal: AbortSignal) => get<Resume[]>('/career/resumes', signal),
  generate: (input: JobRequest & { requestId: string; experienceIds: string[] }) =>
    post<Resume>('/career/resumes', input),
  applications: (signal: AbortSignal) => get<Application[]>('/career/applications', signal),
  createApplication: (input: JobRequest & Draft) => post<Application>('/career/applications', input),
  updateApplication: async (id: string, input: Draft & { revision: number }) =>
    (await client.put<unknown, Response<Application>>(`/career/applications/${id}`, input)).data,
  updateStage: (id: string, input: { stage: Stage; revision: number; note?: string }) =>
    post<Application>(`/career/applications/${id}/stage`, input),
  events: (id: string, signal: AbortSignal) => get<ApplicationEvent[]>(`/career/applications/${id}/events`, signal),
}
