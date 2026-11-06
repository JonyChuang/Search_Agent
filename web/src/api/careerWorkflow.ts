import client from './client'
import type { ExperienceInput } from './career'
import type { Question } from './practice'

type Response<T> = { code: number; message: string; data: T }
type JobRequest = { jobId: string }

export type TaskKind = 'TRAINING' | 'REVIEW' | 'INTERVIEW'

export interface CareerTask {
  id: string
  kind: TaskKind
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  request: { questionVersion?: number }
  job: string
  interview: { prompt: string; gradingVersion: number; sourceUrl: string; answer: string } | null
  result: { analysis?: string; questions?: Question[]; steps?: string[]; feedback?: string } | null
  error: string | null
  generation: number
  createdAt: string
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
  tasks: (kind: TaskKind, page: number, signal: AbortSignal) =>
    get<{ items: CareerTask[]; hasMore: boolean }>('/career/tasks', signal, { kind, page }),
  training: (input: JobRequest & { requestId: string; role: string }) =>
    post<CareerTask>('/career/tasks/training', input),
  review: (input: { requestId: string; planId: string }) => post<CareerTask>('/career/tasks/review', input),
  interview: (input: JobRequest & { requestId: string; questionId: string; questionVersion: number; answer: string }) =>
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
