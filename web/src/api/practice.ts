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
  jobId?: string
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

export interface SessionQuestion {
  id: string
  version: number
  type: 'SINGLE' | 'OPEN'
  topic: string
  prompt: string
}

interface SessionSummary { id: string; position: number; total: number; prompt: string }
export interface PracticeSession extends Omit<SessionSummary, 'prompt'> {
  jobId: string | null
  current: SessionQuestion | null
  answerRequestId: string | null
  attempt: Attempt | null
  taskId: string | null
}

const sessionPath = '/career/practice/sessions'

export const practiceApi = {
  sessions: async (signal: AbortSignal, jobId?: string) =>
    (await client.get<unknown, Response<SessionSummary[]>>(sessionPath, { params: { jobId }, signal })).data,
  session: async (id: string, signal: AbortSignal) =>
    (await client.get<unknown, Response<PracticeSession>>(sessionPath + '/' + encodeURIComponent(id), { signal })).data,
  createSession: async (input: { requestId: string; jobId?: string; questions: Omit<SessionQuestion, 'prompt' | 'topic'>[] }) =>
    (await client.post<unknown, Response<PracticeSession>>(sessionPath, input)).data,
  advance: async (session: PracticeSession) =>
    (await client.post<unknown, Response<PracticeSession>>(sessionPath + '/' + session.id + '/advance', { position: session.position })).data,
  recommendations: async (jobId: string, signal: AbortSignal) => {
    const { data } = await client.get<unknown, Response<{ notes: InterviewNote[]; questions: Question[] }>>(
      '/career/recommendations', { params: { jobId }, signal },
    )
    return data
  },
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
  attempts: async (page: number, signal: AbortSignal, jobId?: string) => {
    const { data } = await client.get<unknown, Response<AttemptPage>>('/career/practice/attempts', { params: { page, jobId }, signal })
    return data
  },
  wrongQuestions: async (signal: AbortSignal, jobId?: string) => {
    const { data } = await client.get<unknown, Response<WrongQuestion[]>>('/career/practice/wrong-questions', { params: { jobId }, signal })
    return data
  },
}
