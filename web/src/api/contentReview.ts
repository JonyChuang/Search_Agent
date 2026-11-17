import client from './client'

type Response<T> = { code: number; message: string; data: T }
export type ReviewKind = 'QUESTION' | 'NOTE'
export type ReviewStatus = 'DRAFT' | 'PUBLISHED' | 'DISMISSED'
export interface ReviewContent {
  targetId?: string
  role: string
  topic?: string
  title: string
  explanation: string
  company?: string
  options?: string[]
  correctAnswer?: string
  sourceName: string
  sourceUrl: string
  publishedOn?: string
}
export interface ReviewDraft {
  id: string
  kind: ReviewKind
  status: ReviewStatus
  content: ReviewContent
  baseVersion?: number
  revision: number
}
const base = '/career/content-review'
export const contentReview = {
  access: async (signal: AbortSignal) =>
    (await client.get<unknown, Response<boolean>>(base + '/access', { signal })).data,
  feeds: async (signal: AbortSignal) =>
    (await client.get<unknown, Response<number>>(base + '/feeds', { signal })).data,
  list: async (status: ReviewStatus, page: number, signal: AbortSignal) =>
    (await client.get<unknown, Response<{ items: ReviewDraft[]; hasMore: boolean }>>(base, { signal, params: { status, page } })).data,
  save: async (kind: ReviewKind, content: ReviewContent, draft?: ReviewDraft) => draft
    ? (await client.put<unknown, Response<ReviewDraft>>(base + '/' + draft.id, { revision: draft.revision, content })).data
    : (await client.post<unknown, Response<ReviewDraft>>(base, { kind, content })).data,
  review: async (draft: ReviewDraft, decision: 'publish' | 'dismiss') =>
    (await client.post<unknown, Response<ReviewDraft>>(base + '/' + draft.id + '/' + decision, { revision: draft.revision })).data,
  refresh: async () =>
    (await client.post<unknown, Response<{ succeeded: number; failed: number; busy: boolean }>>(base + '/feeds/refresh', undefined, { timeout: 120000 })).data,
}

