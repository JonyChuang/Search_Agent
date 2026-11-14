export function preparationPath(tab = 'plan', values?: Record<string, string>) {
  return `/career/preparation?${new URLSearchParams({ ...values, tab })}`
}

export function jobPath(jobId: string, tab = 'research', values?: Record<string, string>) {
  return `/career/jobs/${encodeURIComponent(jobId)}?${new URLSearchParams({ ...values, tab })}`
}
