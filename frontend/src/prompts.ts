export type PromptKey =
  | 'brief_prompt'
  | 'dossier_prompt'
  | 'post_draft_prompt'
  | 'mod_review_prompt'
  | 'revise_prompt'
  | 'native_polish_prompt'
  | 'engagement_prompt'

export const PROMPT_KEYS: PromptKey[] = [
  'brief_prompt',
  'dossier_prompt',
  'post_draft_prompt',
  'mod_review_prompt',
  'revise_prompt',
  'native_polish_prompt',
  'engagement_prompt',
]

export type PromptMeta = {
  key: PromptKey
  title: string
  description: string
  requiredPlaceholders: string[]
}

export const PROMPT_METAS: PromptMeta[] = [
  {
    key: 'brief_prompt',
    title: '阶段 0：产品 Brief 抽取',
    description:
      '从前置资料中抽取“可执行的产品 brief”（不应引用原文）。必须包含占位符。',
    requiredPlaceholders: ['{{pre_materials}}'],
  },
  {
    key: 'dossier_prompt',
    title: '阶段 1：Subreddit Dossier（风格/规则/禁忌）',
    description:
      '基于抓取到的 meta + rules + 语料片段，生成该 sub 的写作/互动指南。',
    requiredPlaceholders: [
      '{{subreddit_name}}',
      '{{subreddit_meta}}',
      '{{subreddit_rules}}',
      '{{corpus_excerpt}}',
    ],
  },
  {
    key: 'post_draft_prompt',
    title: '阶段 2：Post 初稿（v1）',
    description: '基于产品 brief + dossier，生成单一最佳版本的 post 初稿。',
    requiredPlaceholders: [
      '{{subreddit_name}}',
      '{{product_brief}}',
      '{{subreddit_dossier}}',
    ],
  },
  {
    key: 'mod_review_prompt',
    title: '阶段 3：Mod 审核（Pass/Fail）',
    description: '站在版主视角逐条对照规则，给出是否会删帖与改进建议。',
    requiredPlaceholders: [
      '{{subreddit_name}}',
      '{{subreddit_rules}}',
      '{{subreddit_dossier}}',
      '{{post_draft}}',
    ],
  },
  {
    key: 'revise_prompt',
    title: '阶段 4：合规修订（v2）',
    description: '根据 mod 审核结果，输出更安全的 v2 版本。',
    requiredPlaceholders: ['{{subreddit_name}}', '{{mod_review}}', '{{post_draft}}'],
  },
  {
    key: 'native_polish_prompt',
    title: '阶段 5：Reddit-native 打磨（Final）',
    description: '去营销味、增强真实感与互动钩子（不刻意制造错字）。',
    requiredPlaceholders: [
      '{{subreddit_name}}',
      '{{subreddit_dossier}}',
      '{{post_revision}}',
    ],
  },
  {
    key: 'engagement_prompt',
    title: '阶段 6：互动文案包（OP-only）',
    description:
      '生成 OP 可用的首评/补充评论 + 回复模板（不伪装其他用户）。',
    requiredPlaceholders: [
      '{{subreddit_name}}',
      '{{subreddit_dossier}}',
      '{{post_final}}',
    ],
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

