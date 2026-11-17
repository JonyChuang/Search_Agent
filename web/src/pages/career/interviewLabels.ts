export const modeLabels = { VIDEO: '视频面试', VOICE: '语音面试', TEXT: '文字面试' }
export const phaseLabels = { WARMUP: '开场热身', CORE: '岗位深挖', SCENARIO: '综合情境' }

export function interviewTime(seconds: number) {
  const minutes = Math.floor(seconds / 60)
  return [minutes, seconds % 60].map((unit) => String(unit).padStart(2, '0')).join(':')
}