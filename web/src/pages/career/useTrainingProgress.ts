import { useCallback } from 'react'
import { careerWorkflow, type CareerTask } from '@/api/careerWorkflow'
import { useCareerQuery } from './useCareerQuery'

export type PlanQuestion = NonNullable<NonNullable<CareerTask['result']>['questions']>[number]

export function useTrainingProgress(task?: CareerTask) {
  const taskId = task?.id
  const load = useCallback(async (signal: AbortSignal) => taskId
    ? { taskId, answers: await careerWorkflow.trainingProgress(taskId, signal) }
    : undefined, [taskId])
  const progress = useCareerQuery(load)
  const questions = task?.result?.questions ?? []
  const answers = progress.data?.taskId === taskId ? progress.data?.answers : undefined
  const hasProgress = !!answers && !progress.error
  const isComplete = (question: PlanQuestion) => hasProgress && answers.some(({ id, version }) =>
    id === question.id && version === question.version)

  return {
    questions, hasProgress, isComplete, error: progress.error, retry: progress.retry,
    completed: questions.filter(isComplete).length,
    next: hasProgress ? questions.find((question) => !isComplete(question)) : undefined,
  }
}
