import client from './client'
import type { Application } from './careerWorkflow'

type Response<T> = { code: number; message: string; data: T }

export interface MaterialItem {
  id: string
  kind: 'FILE' | 'LINK'
  label: string
  required: boolean
  fileId?: string | null
  url?: string | null
}

export interface ApplicationQuestion {
  id: string
  label: string
  required: boolean
  answer?: string | null
}

export interface ApplicationAnswers {
  name?: string | null
  phone?: string | null
  email?: string | null
  education?: string | null
  startDate?: string | null
  weeklyDays?: number | null
  duration?: string | null
  motivation?: string | null
  questions: ApplicationQuestion[]
}

export interface MaterialFile {
  id: string
  name: string
  size: number
}

interface MaterialDraft {
  form: ApplicationAnswers
  attachments: MaterialItem[]
}

export interface MaterialsView {
  content: MaterialDraft
  files: MaterialFile[]
}

export interface ApplicationReceipt {
  submittedAt: string
  applicationNumber?: string | null
}

export interface ApplicationWorkspaceState {
  application: Application | null
  workspace: MaterialsView
  receipt: ApplicationReceipt | null
}

interface WorkspaceInput {
  requestId: string
  revision: number
  resumeId: string | null
  answers: string
  content: MaterialDraft
}

function workspacePath(jobId: string) {
  return `/career/jobs/${encodeURIComponent(jobId)}/application-workspace`
}

export const applicationWorkspace = {
  get: async (jobId: string, signal?: AbortSignal) =>
    (await client.get<unknown, Response<ApplicationWorkspaceState>>(workspacePath(jobId), { signal })).data,
  save: async (jobId: string, input: WorkspaceInput, pending: Record<string, File>) => {
    const body = new FormData()
    body.append('draft', new Blob([JSON.stringify(input)], { type: 'application/json' }))
    for (const item of input.content.attachments) {
      if (item.fileId && pending[item.fileId]) body.append(item.fileId, pending[item.fileId])
    }
    return (await client.put<unknown, Response<ApplicationWorkspaceState>>(workspacePath(jobId), body, { timeout: 120000 })).data
  },
  download: async (applicationId: string, file: MaterialFile) => {
    const blob = await client.get<unknown, Blob>(
      `/career/applications/${encodeURIComponent(applicationId)}/files/${encodeURIComponent(file.id)}`, {
        responseType: 'blob', timeout: 120000,
      },
    )
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.name
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  },
}
