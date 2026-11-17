import client from './client'
import type { CareerTask, TaskReference } from './careerWorkflow'

type Response<T> = { code: number; message: string; data: T }

export interface LearningQuestion {
  id: string
  version: number
  topic: string
  prompt: string
  references?: TaskReference[] | null
}

export interface LearningNote {
  sourceKey: string
  title: string
  summary: string
  sourceUrl?: string
  documentId?: string
  documentTitle?: string
  documentRevision?: string
  collectedAt: string
}

const path = (job: string) => '/career/learning/jobs/' + encodeURIComponent(job)
export const learningApi = {
  questions: async (job: string, signal: AbortSignal) =>
    (await client.get<unknown, Response<LearningQuestion[]>>(path(job) + '/questions', { signal })).data,
  question: async (job: string, id: string, signal: AbortSignal) =>
    (await client.get<unknown, Response<LearningQuestion>>(path(job) + '/questions/' + encodeURIComponent(id), { signal })).data,
  notes: async (job: string, signal: AbortSignal) =>
    (await client.get<unknown, Response<LearningNote[]>>(path(job) + '/notes', { signal })).data,
  saveNote: async (job: string, task: CareerTask, index: number) =>
    (await client.post<unknown, Response<string>>(path(job) + '/notes', { taskId: task.id, index })).data,
}

