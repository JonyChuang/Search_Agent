import client from './client'
import type { ExperienceType } from './career'
import type { Resume } from './careerWorkflow'

type Response<T> = { code: number; message: string; data: T }

export type ResumeTemplate = 'classic' | 'tech' | 'campus' | 'modern' | 'academic' | 'mono'
export type ResumeEntryKind = ExperienceType | 'award'

export interface ResumeEntry {
  id: string
  kind: ResumeEntryKind
  title: string
  organization: string
  role: string
  startMonth: string
  endMonth: string
  description: string
  sourceNote?: string | null
}

export interface ResumeDesign {
  name: string
  phone: string
  email: string
  targetRole: string
  skills: string
  photo: string | null
  showPhoto: boolean
  template: ResumeTemplate
  entries: ResumeEntry[]
}

export interface ResumeProfile {
  revision: number
  content: ResumeDesign
}

export const resumeStudio = {
  profile: async (signal: AbortSignal) =>
    (await client.get<unknown, Response<ResumeProfile>>('/career/resume-profile', { signal })).data,
  save: async (input: ResumeProfile & { confirmExperienceId?: string }) =>
    (await client.put<unknown, Response<ResumeProfile>>('/career/resume-profile', input)).data,
  generate: async (input: { requestId: string; jobId: string | null; revision: number }) =>
    (await client.post<unknown, Response<Resume>>('/career/resumes/composed', input)).data,
  composition: async (id: string, signal: AbortSignal) =>
    (await client.get<unknown, Response<ResumeDesign>>('/career/resumes/' + encodeURIComponent(id) + '/composition', { signal })).data,
}

