import { Alert, Button, Card, Collapse, Progress, Tag } from 'antd'
import { ArrowRightOutlined, CheckOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import { careerWorkflow, type CareerTask } from '@/api/careerWorkflow'
import { preparationPath } from './paths'
import { practiceLink } from './QuestionCatalog'
import TaskDetails from './TaskDetails'
import { useCareerAction } from './useCareerAction'
import { useTrainingProgress, type PlanQuestion } from './useTrainingProgress'
import styles from './workspace.module.css'

export function trainingQuestionPath(question: PlanQuestion, jobId?: string) {
  return question.kind === 'OPEN'
    ? preparationPath('open', { question: question.id, ...(jobId ? { job: jobId } : {}) })
    : practiceLink(question.id, question.version, jobId)
}

export default function TrainingPlanCard({ task }: { task: CareerTask }) {
  const navigate = useNavigate()
  const review = useCareerAction()
  const progress = useTrainingProgress(task)
  const { questions, isComplete, completed, hasProgress, next } = progress
  const jobId = task.request.jobId
  const scope = jobId ? { job: jobId } : undefined

  return (
    <Card className={styles.panel}>
      <div className={styles.stack}>
        <div className={styles.row}>
          <div>
            <h2 className={styles.sectionTitle}>{task.job} · 面试训练计划</h2>
            <p className={styles.muted}>制定于 {new Date(task.createdAt).toLocaleDateString('zh-CN')}</p>
            {task.request.previousPlanId && <Link to={preparationPath('plan', { ...scope, plan: task.request.previousPlanId })}>查看上一版计划</Link>}
          </div>
          <Tag color={hasProgress && questions.length > 0 && !next ? 'success' : 'purple'}>
            {hasProgress && questions.length ? next ? '备考中' : '练习完成' : '计划已生成'}
          </Tag>
        </div>
        {progress.error ? <Alert type="warning" message="暂时无法读取练习进度"
          action={<Button size="small" onClick={progress.retry}>重试</Button>} />
          : questions.length > 0 && <div>
            <div className={styles.row}>
              <span className={styles.muted}>练习进度</span>
              <span>{hasProgress ? `已完成 ${completed} / ${questions.length}` : '读取中…'}</span>
            </div>
            {hasProgress && <Progress percent={Math.round(completed / questions.length * 100)}
              showInfo={false} strokeColor="#6050d8" aria-label={`已完成 ${completed} 道，共 ${questions.length} 道`} />}
          </div>}

        {next && <div className={styles.next}>
          <div><h3 className={styles.smallTitle}>下一项 · {next.prompt}</h3>
            <p className={styles.muted}>{next.kind === 'OPEN' ? '开放题' : '客观题'}</p></div>
          <Link to={trainingQuestionPath(next, jobId)} className={styles.primaryLink}>继续练习 <ArrowRightOutlined aria-hidden /></Link>
        </div>}

        {questions.length > 0 && <div>
          <h3 className={styles.smallTitle}>计划内练习</h3>
          <ul className={styles.items}>
            {questions.map((question) => {
              const done = hasProgress && isComplete(question)
              return <li key={`${question.id}:${question.version}`}>
                <span className={`${styles.itemIcon} ${done ? styles.done : ''}`} aria-hidden="true">
                  {done ? <CheckOutlined /> : next === question ? <ArrowRightOutlined /> : <ClockCircleOutlined />}
                </span>
                <div className={styles.itemBody}>
                  <strong>{question.prompt}</strong>
                  <p className={styles.muted}>{question.kind === 'OPEN' ? '开放题练习' : '客观题'}
                    {hasProgress && (done ? ' · 已完成' : next === question ? ' · 下一项' : ' · 待练习')}</p>
                </div>
                <Link className={styles.itemAction} to={done
                  ? preparationPath('review', { ...scope, ...(question.kind === 'OPEN' ? {} : { section: 'history' }) })
                  : trainingQuestionPath(question, jobId)}>{done ? '查看复盘' : '开始'}</Link>
              </li>
            })}
          </ul>
        </div>}

        <Collapse size="small" items={[{
          key: 'analysis', label: '岗位分析与训练步骤',
          children: <>
            {task.result?.analysis && <p className={styles.longText}>{task.result.analysis}</p>}
            {!!task.result?.steps?.length && <ol>{task.result.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>}
            <TaskDetails task={task} />
          </>,
        }]} />
        <div>
          <Button loading={review.saving} onClick={() => review.run(async () => {
            await review.submit('review', { planId: task.id }, careerWorkflow.review)
            navigate(preparationPath('review', scope))
          })}>根据练习与面试生成复习建议</Button>
        </div>
      </div>
    </Card>
  )
}
