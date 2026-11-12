import { createContext, useContext, type ReactNode } from 'react'
import { Alert, Button, Select, Space } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { careerApi, type JobInput } from '@/api/career'
import { useCareerAction } from './useCareerAction'
import { useCareerQuery } from './useCareerQuery'

const JobContext = createContext<{
  job?: JobInput & { id: string }
  jobs?: (JobInput & { id: string })[]
  error?: string
  loading: boolean
  saving: boolean
  select: (id: string | null, onSaved?: () => void) => void
  reload: () => void
} | null>(null)

export function CurrentJobProvider({ children }: { children: ReactNode }) {
  const jobs = useCareerQuery(careerApi.jobs.list)
  const active = useCareerQuery(careerApi.activeJob)
  const action = useCareerAction()

  return (
    <JobContext.Provider value={{
      job: jobs.data?.find((item) => item.id === active.data?.jobId),
      jobs: jobs.data,
      error: jobs.error || active.error,
      loading: (!jobs.data || !active.data) && !jobs.error && !active.error,
      saving: action.saving,
      select: (id, onSaved) => void action.run(async () => {
        active.setData(await careerApi.selectJob(id))
        onSaved?.()
      }),
      reload: () => { jobs.retry(); active.retry() },
    }}>
      {children}
    </JobContext.Provider>
  )
}

export function useCurrentJob() {
  const context = useContext(JobContext)
  if (!context) throw new Error('CurrentJobProvider is missing')
  return context
}

export function CurrentJobSelect({ maxWidth }: { maxWidth?: number }) {
  const { job, jobs, error, loading, saving, select, reload } = useCurrentJob()
  const [params, setParams] = useSearchParams()

  function changeJob(value?: string) {
    select(value ?? null, () => {
      if (!params.has('job') && !params.has('question')) return
      const next = new URLSearchParams(params)
      next.delete('job')
      next.delete('question')
      next.delete('version')
      setParams(next, { replace: true })
    })
  }

  return (
    <Space wrap style={{ display: 'flex', marginBottom: 16, maxWidth, marginInline: 'auto' }}>
      <Select aria-label="当前目标岗位" placeholder="选择当前目标岗位" allowClear showSearch
        optionFilterProp="label" value={job?.id} loading={loading || saving} disabled={saving || loading || !!error}
        style={{ width: 250, maxWidth: '75vw' }}
        options={jobs?.map((item) => ({ value: item.id, label: `${item.company} · ${item.title}` }))}
        onChange={changeJob} />
      <Link to="/career/jobs">{jobs?.length ? '管理岗位' : '新增岗位'}</Link>
      {error && <Alert type="error" message={error} action={<Button size="small" onClick={reload}>重试</Button>} />}
    </Space>
  )
}
