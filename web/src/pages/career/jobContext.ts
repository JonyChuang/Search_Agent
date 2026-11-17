import type { JobInput } from '@/api/career'

export function withJobContext(job: JobInput, prompt: string) {
  const context = [`目标岗位：${job.company} · ${job.title}`, `岗位描述：${job.description}`]
  if (job.skills) context.push(`已确认技能：${job.skills}`)
  return [...context, prompt].join('\n')
}
