import { useCallback } from 'react'
import { Button, Card, Spin, Tag } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { careerWorkflow, type CareerTask } from '@/api/careerWorkflow'
import { jobPath, preparationPath } from './paths'
import TaskDetails from './TaskDetails'
import { useCareerQuery } from './useCareerQuery'
import styles from './workspace.module.css'

export function JobPreference({ jobId }: { jobId: string }) {
  const load = useCallback((signal: AbortSignal) => careerWorkflow.memory(jobId, signal), [jobId])
  const { data, error, retry } = useCareerQuery(load)
  return <>
    {error ? <p className={styles.muted}>偏好暂时无法读取 <Button size="small" type="link" onClick={retry}>重试</Button></p>
      : data ? <p className={styles.longText}>{data.notes || '尚未设置此岗位的备考偏好。'}</p> : <Spin size="small" />}
  </>
}

export function LatestReview({ jobId }: { jobId?: string }) {
  const load = useCallback(async (signal: AbortSignal) => {
    const results = await Promise.all([
      careerWorkflow.tasks('REVIEW', 1, signal, jobId),
      careerWorkflow.tasks('INTERVIEW', 1, signal, jobId),
    ])
    return results.flatMap(({ items }) => items.filter((task) => task.status === 'SUCCEEDED' && task.result?.feedback))
      .sort((first, second) => Date.parse(second.createdAt) - Date.parse(first.createdAt))[0] ?? null
  }, [jobId])
  const { data, error, retry } = useCareerQuery(load)
  return (
    <Card className={styles.panel}>
      <div className={styles.row}>
        <h2 className={styles.sectionTitle}>最近复盘</h2>
        <Link to={preparationPath('review', jobId ? { job: jobId } : undefined)}>查看错题与反馈 <ArrowRightOutlined /></Link>
      </div>
      {error ? <p className={styles.muted}>暂时无法读取复盘 <Button size="small" type="link" onClick={retry}>重试</Button></p>
        : data === undefined ? <Spin size="small" />
        : <p className={`${styles.muted} ${styles.excerpt}`}>{data?.result?.feedback || '完成练习后可在这里回看复盘建议。'}</p>}
    </Card>
  )
}

export default function PreparationSidebar({ jobId, plan }: { jobId?: string; plan?: CareerTask }) {
  const referenceCount = plan?.references?.length ?? 0
  return (
    <aside className={styles.stack} aria-label="备考资料与岗位">
      <Card className={styles.panel}>
        <div className={styles.stack}>
          <div className={styles.row}>
            <h2 className={styles.sectionTitle}>本次参考资料</h2>
            {plan && <Tag>{referenceCount} 份</Tag>}
          </div>
          {plan && referenceCount > 0 ? <TaskDetails task={plan} referenceList />
            : <p className={styles.muted}>{plan ? '这份计划没有引用个人资料。' : '创建计划后可在这里查看已引用的资料。'}</p>}
          <Link to="/knowledge">打开我的资料 <ArrowRightOutlined /></Link>
        </div>
      </Card>
      {jobId && <>
        <Card className={styles.panel}>
          <div className={styles.stack}>
            <h2 className={styles.sectionTitle}>备考偏好</h2>
            <JobPreference jobId={jobId} />
            <Link to={jobPath(jobId, 'memory')}>查看岗位记忆 <ArrowRightOutlined /></Link>
          </div>
        </Card>
        <Card className={styles.panel}>
          <div className={styles.stack}>
            <h2 className={styles.sectionTitle}>公司调研</h2>
            <p className={styles.muted}>围绕当前 JD 提出问题，查找公开来源。</p>
            <Link to={jobPath(jobId)}>打开公司调研 <ArrowRightOutlined /></Link>
          </div>
        </Card>
      </>}
    </aside>
  )
}
