import client from './client'

type Response<T> = { code: number; message: string; data: T }
export type ReminderType = 'REVIEW' | 'INTERVIEW' | 'APPLICATION'
export interface ReminderInput { jobId?: string | null; type: ReminderType; title: string; dueAt: string; externalDelivery?: boolean }
export interface CareerReminder extends ReminderInput {
  id: string; status: 'PENDING' | 'DONE' | 'CANCELLED'; revision: number; due: boolean; deliveryState: string
}

const path = '/career/reminders'
export const remindersApi = {
  list: async (signal: AbortSignal) =>
    (await client.get<unknown, Response<CareerReminder[]>>(path, { signal })).data,
  count: async (signal: AbortSignal) =>
    (await client.get<unknown, Response<number>>(path + '/due-count', { signal })).data,
  create: async (input: { requestId: string; reminder: ReminderInput }) =>
    (await client.post<unknown, Response<CareerReminder>>(path, input)).data,
  edit: async (item: CareerReminder, reminder: ReminderInput) =>
    (await client.put<unknown, Response<CareerReminder>>(path + '/' + item.id, { revision: item.revision, reminder })).data,
  change: async (item: CareerReminder, status: 'DONE' | 'CANCELLED') =>
    (await client.post<unknown, Response<CareerReminder>>(path + '/' + item.id + '/state', { revision: item.revision, status })).data,
}

