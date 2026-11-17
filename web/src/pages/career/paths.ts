export const newJobPath = '/career/jobs?add=1'
export const resumeStudioPath = '/career/apply'

export function applicationPath(jobId?: string) {
  return '/career/apply?' + new URLSearchParams({ ...(jobId ? { job: jobId } : {}), tab: 'materials' })
}

export function resumeDesignPath(id: string, jobId: string | null) {
  return '/career/apply?' + new URLSearchParams({ version: id, job: jobId ?? 'general' })
}

export function preparationPath(tab = 'plan', values?: Record<string, string>) {
  return `/career/preparation?${new URLSearchParams({ ...values, tab })}`
}

export function interviewPath(values?: Record<string, string>) {
  return values ? `/career/interviews?${new URLSearchParams(values)}` : '/career/interviews'
}

export function jobPath(jobId: string, tab = 'research', values?: Record<string, string>) {
  return `/career/jobs/${encodeURIComponent(jobId)}?${new URLSearchParams({ ...values, tab })}`
}
