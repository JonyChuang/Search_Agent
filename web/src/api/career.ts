import client from './client'

type Response<T> = { code: number; message: string; data: T }

export interface CareerProfile {
  targetRole?: string | null
  graduationMonth?: string | null
  preferences?: string | null
}

export type ExperienceType = 'education' | 'research' | 'project' | 'internship'

export interface ExperienceInput {
  type: ExperienceType
  title: string
  organization?: string | null
  startMonth?: string | null
  endMonth?: string | null
  description: string
  sourceNote?: string | null
  confirmed: boolean
}

export interface JobInput {
  company: string
  title: string
  location?: string | null
  description: string
  sourceName: string
  sourceUrl?: string | null
  sourcedOn: string
}

export interface CareerRecords<T> {
  list: (signal?: AbortSignal) => Promise<(T & { id: string })[]>
  save: (id: string | undefined, input: T) => Promise<T & { id: string }>
  remove: (id: string) => Promise<void>
}

function records<T>(path: string): CareerRecords<T> {
  return {
    list: async (signal) => {
      const { data } = await client.get<unknown, Response<(T & { id: string })[]>>(path, { signal })
      return data
    },
    save: async (id, input) => {
      const { data } = id
        ? await client.put<unknown, Response<T & { id: string }>>(`${path}/${id}`, input)
        : await client.post<unknown, Response<T & { id: string }>>(path, input)
      return data
    },
    remove: async (id) => {
      await client.delete(`${path}/${id}`)
    },
  }
}

export const careerApi = {
  profile: async (signal?: AbortSignal) => {
    const { data } = await client.get<unknown, Response<CareerProfile | null>>('/career/profile', { signal })
    return data
  },
  saveProfile: async (profile: CareerProfile) => {
    const { data } = await client.put<unknown, Response<CareerProfile>>('/career/profile', profile)
    return data
  },
  experiences: records<ExperienceInput>('/career/experiences'),
  jobs: records<JobInput>('/career/jobs'),
}
