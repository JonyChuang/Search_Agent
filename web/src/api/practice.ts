import client from './client'

type Response<T> = { code: number; message: string; data: T }

interface Source {
  sourceName: string
  sourceUrl: string
  sourcedOn: string
}

export interface InterviewNote extends Source {
  id: string
  role: string
  company: string
  title: string
  summary: string
  publishedOn: string
}

export interface Question extends Source {
  id: string
  version: number
  role: string
  topic: string
  prompt: string
  options: string[]
}

export interface Submission {
  requestId: string
  questionId: string
  questionVersion: number
  answer: string
}

export interface Attempt extends Submission {
  gradingVersion: number
  prompt: string
  correct: boolean
  correctAnswer: string
  answerText: string
  correctAnswerText: string
  explanation: string
  submittedAt: string
}

interface AttemptPage {
  items: Attempt[]
  hasMore: boolean
}

interface WrongQuestion {
  questionId: string
  prompt: string
  topic: string
  wrongCount: number
  reviewed: boolean
}

export const practiceApi = {
  notes: async (signal: AbortSignal) => {
    const { data } = await client.get<unknown, Response<InterviewNote[]>>('/career/interview-notes', { signal })
    return data
  },
  questions: async (role: string | undefined, signal: AbortSignal) => {
    const { data } = await client.get<unknown, Response<Question[]>>('/career/questions', { params: { role }, signal })
    return data
  },
  question: async (id: string, signal: AbortSignal, version?: string) => {
    const { data } = await client.get<unknown, Response<Question>>(`/career/questions/${encodeURIComponent(id)}`, { signal, params: { version } })
    return data
  },
  submit: async (submission: Submission) => {
    const { data } = await client.post<unknown, Response<Attempt>>('/career/practice/attempts', submission)
    return data
  },
  attempts: async (page: number, signal: AbortSignal) => {
    const { data } = await client.get<unknown, Response<AttemptPage>>('/career/practice/attempts', { params: { page }, signal })
    return data
  },
  wrongQuestions: async (signal: AbortSignal) => {
    const { data } = await client.get<unknown, Response<WrongQuestion[]>>('/career/practice/wrong-questions', { signal })
    return data
  },
}
