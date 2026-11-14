import { useCallback } from 'react'
import { Button, Card, Spin, Tag } from 'antd'
import { ArrowRightOutlined, FileSearchOutlined, ReadOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { careerWorkflow } from '@/api/careerWorkflow'
import { researchApi } from '@/api/research'
import { JobPreference } from './PreparationSidebar'
import { jobPath, preparationPath } from './paths'
import { useCareerQuery } from './useCareerQuery'
import { trainingQuestionPath } from './TrainingPlanCard'
import styles from './workspace.module.css'

const labels = { SUCCEEDED: '已生成', FAILED: '失败', QUEUED: '待执行', RUNNING: '运行中' }

export default function JobResearchSidebar({ jobId }: { jobId: string }) {
  const load = useCallback(async (signal: AbortSignal) => {
    const [reports, plans] = await Promise.all([
      researchApi.list(1, 1, jobId, signal),
      careerWorkflow.tasks('TRAINING', 1, signal, jobId),
    ])
    const plan = plans.items[0]
    const active = plans.items.find((item) => item.status === 'SUCCEEDED' && item.result?.questions?.length)
    const progress = active ? await careerWorkflow.trainingProgress(active.id, signal).catch(() => undefined) : undefined
    const next = progress && active?.result?.questions?.find(
      (question) => !progress.some(({ id, version }) => question.id === id && question.version === version),
    )
    return { report: reports.data.items[0], plan, next }
  }, [jobId])
  const { data, error, retry } = useCareerQuery(load)

  return (
    <aside className={styles.stack} aria-label="岗位备考与任务">
      <Card className={styles.panel}>
        <div className={styles.stack}>
          <div className={styles.row}>
            <h2 className={styles.sectionTitle}>求职记忆</h2>
            <Link to={jobPath(jobId, 'memory')}>查看岗位记忆 <ArrowRightOutlined /></Link>
          </div>
          <JobPreference jobId={jobId} />
        </div>
      </Card>
      <Card className={styles.panel}>
        <div className={styles.row}>
          <h2 className={styles.sectionTitle}>最近任务</h2>
          <Link to={jobPath(jobId, 'tasks')}>查看全部 <ArrowRightOutlined /></Link>
        </div>
        {error ? <p className={styles.muted}>任务暂时无法读取 <Button size="small" type="link" onClick={retry}>重试</Button></p>
          : !data ? <Spin size="small" />
          : !data.report && !data.plan ? <p className={styles.muted}>该岗位暂无调研或训练任务。</p>
          : <ul className={styles.items}>
            {data.report && <li>
              <span className={styles.itemIcon}><FileSearchOutlined /></span>
              <div className={styles.itemBody}>
                <Link className={styles.excerpt} to={jobPath(jobId, 'research', { report: data.report.id })}>{data.report.title || data.report.topic}</Link>
                <p className={styles.muted}>公司调研</p>
              </div>
              <Tag>{data.report.status === 'done' ? '已完成' : data.report.status === 'failed' ? '失败' : '进行中'}</Tag>
            </li>}
            {data.plan && <li>
              <span className={styles.itemIcon}><ReadOutlined /></span>
              <div className={styles.itemBody}><Link to={preparationPath('plan', { job: jobId })}>岗位训练计划</Link>
                <p className={styles.muted}>{new Date(data.plan.createdAt).toLocaleDateString('zh-CN')}</p></div>
              <Tag>{labels[data.plan.status]}</Tag>
            </li>}
          </ul>}
      </Card>
      <Card className={styles.panel}>
        <div className={styles.row}>
          <div>
            <h2 className={styles.sectionTitle}>下一步</h2>
            {data?.next && <p className={`${styles.muted} ${styles.excerpt}`}>{data.next.prompt}</p>}
          </div>
          <Link className={styles.primaryLink} to={data?.next ? trainingQuestionPath(data.next, jobId)
            : preparationPath('plan', { job: jobId })}>{data?.next ? '继续练习' : '打开备考计划'} <ArrowRightOutlined /></Link>
        </div>
      </Card>
    </aside>
  )
}
