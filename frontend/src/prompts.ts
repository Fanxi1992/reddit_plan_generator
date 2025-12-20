export type PromptKey = 'phase1_prompt' | 'phase2_prompt' | 'phase3_prompt' | 'phase4_prompt'

export const PROMPT_KEYS: PromptKey[] = [
  'phase1_prompt',
  'phase2_prompt',
  'phase3_prompt',
  'phase4_prompt',
]

export type PromptMeta = {
  key: PromptKey
  title: string
  description: string
  requiredPlaceholders: string[]
}

export const PROMPT_METAS: PromptMeta[] = [
  {
    key: 'phase1_prompt',
    title: '阶段 1：产品理解（建立会话）',
    description:
      '用于让模型理解产品背景并创建会话（interaction id）。必须包含产品占位符。',
    requiredPlaceholders: ['{{product_context}}'],
  },
  {
    key: 'phase2_prompt',
    title: '阶段 2：定位 + Subreddit 候选列表',
    description:
      '生成定位分析（Markdown）+ 30+ 候选 subreddit（JSON code block）。',
    requiredPlaceholders: [],
  },
  {
    key: 'phase3_prompt',
    title: '阶段 3：规则审计后筛选 + 社区策略',
    description:
      '根据 PRAW 抓取的真实规则/订阅数等数据，筛选 Top 5 并写策略。必须包含规则上下文占位符。',
    requiredPlaceholders: ['{{rules_context}}'],
  },
  {
    key: 'phase4_prompt',
    title: '阶段 4：KPI 分析 + 内容草稿',
    description:
      '根据 KPI 与本月热帖风格参考，生成最终内容方案与种子评论。必须包含挖掘上下文占位符。',
    requiredPlaceholders: ['{{mined_context}}'],
  },
]

export function diffPrompts(
  defaults: Record<string, string>,
  current: Record<string, string>,
): Record<string, string> {
  const overrides: Record<string, string> = {}
  for (const key of PROMPT_KEYS) {
    if ((current[key] ?? '').trim() !== (defaults[key] ?? '').trim()) {
      overrides[key] = current[key] ?? ''
    }
  }
  return overrides
}

export function validatePrompts(
  prompts: Record<string, string>,
): Record<PromptKey, string | null> {
  const errors = {} as Record<PromptKey, string | null>
  for (const meta of PROMPT_METAS) {
    const value = (prompts[meta.key] ?? '').trim()
    if (!value) {
      errors[meta.key] = '不能为空'
      continue
    }
    const missing = meta.requiredPlaceholders.filter((p) => !value.includes(p))
    if (missing.length > 0) {
      errors[meta.key] = `缺少占位符：${missing.join(', ')}`
      continue
    }
    errors[meta.key] = null
  }
  return errors
}

