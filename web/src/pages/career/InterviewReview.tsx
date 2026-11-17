import { useState } from 'react'
import { Alert, Button, Card, Empty, Space, Tag } from 'antd'
import { ArrowLeftOutlined, FileTextOutlined, HistoryOutlined, ReloadOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import type { InterviewAnswer, InterviewRound, InterviewSession } from '@/api/interviews'
import { interviewTime, modeLabels, phaseLabels } from './interviewLabels'
import { interviewPath, preparationPath } from './paths'
import styles from './interview.module.css'

const dimensions = [
  { key: 'accuracy', label: '内容准确性' },
  { key: 'evidence', label: '论证与证据' },
  { key: 'structure', label: '表达结构' },
] as const

function lowestScore(round: InterviewRound) {
  const scores = [round.main.evaluation, round.extra?.evaluation].flatMap((evaluation) =>
    evaluation ? dimensions.map(({ key }) => evaluation[key]) : [])
  return scores.length ? Math.min(...scores) : 6
}

function AnswerReview({ title, turn }: { title: string; turn: InterviewAnswer }) {
  return <>
    <div className={styles.reviewAnswer}><strong>{title}</strong><p>{turn.answer}</p></div>
    {turn.evaluation ? <>
      <div className={styles.scoreGrid}>
        {dimensions.map(({ key, label }) =>
          <div key={key}><small>{label}</small><strong>{turn.evaluation![key]} / 5</strong></div>)}
      </div>
      <div className={styles.coaching}><strong>面试官点评</strong><p>{turn.evaluation.feedback}</p></div>
    </> : turn.evaluationUnavailable && <Alert type="warning" showIcon message="这条回答已保存，暂无评分。" />}
  </>
}

export default function InterviewReview({ session }: { session: InterviewSession }) {
  const { summary, review } = session
  const available = review.filter((round) => lowestScore(round) < 6)
  const focus = available.reduce<InterviewRound | undefined>((weakest, round) =>
    !weakest || lowestScore(round) < lowestScore(weakest) ? round : weakest, undefined)
  const [selection, setSelection] = useState(focus?.question.id ?? review[0]?.question.id)
  const navigate = useNavigate()
  const selected = review.find((round) => round.question.id === selection)
  const question = selected?.question

  return <>
    <header className={styles.heading}>
      <div><h1>面试复盘</h1><p>{summary.job} · {modeLabels[summary.mode]}</p></div>
      <Space wrap>
        <Link to={interviewPath({ tab: 'history' })}><ArrowLeftOutlined /> 返回面试记录</Link>
        {available.length > 0 && <Link to={preparationPath('plan', { job: summary.jobId, create: '1' })}>
          制定下一轮备考计划
        </Link>}
        <Button type="primary" icon={<ReloadOutlined />} onClick={() => navigate(interviewPath({ job: summary.jobId }))}>再练一场</Button>
      </Space>
    </header>
    <section className={styles.reviewSummary} aria-label="本场概况">
      <div className={styles.reviewFocus}>
        <h2>{focus ? `优先复习 · ${focus.question.topic}` : '本场面试已结束'}</h2>
        <p>{focus ? '从分数最低的回答开始，结合评分要点和点评回看。'
          : summary.answered ? '可以回看已提交的回答和题目评分要点。' : '本场没有提交回答。'}</p>
      </div>
      <div className={styles.summaryStats}>
        <div><strong>{summary.answered} / {summary.count}</strong><small>主问题已回答</small></div>
        <div><strong>{summary.followUps} 次</strong><small>追问已回答</small></div>
        <div><strong>{interviewTime(summary.elapsedSeconds)}</strong><small>面试用时</small></div>
      </div>
    </section>
    {selected && question ? <div className={styles.reviewGrid}>
      <Card className={styles.panel} title={<><UnorderedListOutlined /> 逐题复盘</>}>
        <ol className={styles.reviewList}>
          {review.map((round, index) => <li key={round.question.id}>
            <button type="button" aria-pressed={round.question.id === selection} onClick={() => setSelection(round.question.id)}>
              <span className={styles.questionNumber}>{index + 1}</span>
              <span><strong>{round.question.topic}</strong>
                <small>{phaseLabels[round.question.phase]}{round.followUp ? ' · 有追问' : ''}</small></span>
              {round === focus && lowestScore(round) < 4
                ? <Tag bordered={false} color="purple">优先复习</Tag> : null}
            </button>
          </li>)}
        </ol>
      </Card>
      <Card className={styles.panel} title={<><FileTextOutlined /> 第 {review.indexOf(selected) + 1} 题 · {phaseLabels[question.phase]}</>}>
        <div className={styles.reviewDetail}>
          <div><h2>{question.prompt}</h2>
            <p className={styles.questionMeta}>{question.sourceUrl
              ? <a href={question.sourceUrl} target="_blank" rel="noreferrer">{question.sourceName}</a> : question.sourceName}
              {' · '}题目 v{question.version} · 评分规则 v{question.gradingVersion}</p></div>
          <details className={styles.rubric}>
            <summary>查看本题评分要点</summary>
            <ul>{question.rubric.map((point, index) => <li key={index}>{point}</li>)}</ul>
          </details>
          <AnswerReview title="你的主问题回答" turn={selected.main} />
          {selected.followUp && <div className={styles.reviewFollowUp}><strong>AI 追问</strong><p>{selected.followUp}</p></div>}
          {selected.extra ? <AnswerReview title="你的追问回答" turn={selected.extra} />
            : selected.followUp && <p className={styles.questionMeta}>本次追问尚未作答。</p>}
        </div>
      </Card>
    </div> : <Card className={styles.panel}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可复盘的回答">
      <Link to={interviewPath({ tab: 'history' })}><HistoryOutlined /> 查看其他面试记录</Link>
    </Empty></Card>}
  </>
}
