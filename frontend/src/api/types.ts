export type HealthResponse = {
  status: string
}

export type PromptsResponse = {
  prompts: Record<string, string>
}

export type EffectivePromptsRequest = {
  prompt_overrides: Record<string, string>
  strategy_id: string
  strategy_notes: string | null
}

export type StrategyBrandRules = {
  min_mentions: number
  max_mentions: number
  allow_in_title: boolean
  notes?: string | null
}

export type StrategyDef = {
  id: string
  title: string
  description: string
  pov?: string | null
  brand: StrategyBrandRules
  title_templates: string[]
  beats: string[]
  draft_template_md: string
}

export type StrategiesResponse = {
  strategies: StrategyDef[]
}

export type RunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown'
export type PostV1Mode = 'generate' | 'client_draft'

export type RunCreateRequest = {
  target_subreddit: string
  pre_materials: string
  strategy_id?: string
  strategy_notes?: string | null
  post_v1_mode?: PostV1Mode
  post_v1_client_draft?: string | null
  stop_after_mod_review?: boolean
  prompt_overrides?: Record<string, string>
  run_id?: string | null
  wait?: boolean
}

export type RunCreateResponse = {
  run_id: string
  status: RunStatus
  downloads: Record<string, string>
  error?: string | null
}

export type RunStatusResponse = {
  run_id: string
  status: RunStatus
  current_phase?: string | null
  run_dir: string
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  error?: string | null
  outputs: Record<string, string>
  downloads: Record<string, string>
}

export type RunRestoreResponse = {
  run_id: string
  target_subreddit: string
  pre_materials: string
  prompts: Record<string, string>
  strategy_id: string
  strategy_notes: string | null
  post_v1_mode: PostV1Mode
  post_v1_client_draft: string | null
  stop_after_mod_review: boolean
}

export type ChatRole = 'user' | 'model'

export type ChatMessage = {
  role: ChatRole
  text: string
}

export type ChatHistoryResponse = {
  messages: ChatMessage[]
}

export type ChatSendRequest = {
  message: string
}

export type ChatSendResponse = {
  reply: string
}
