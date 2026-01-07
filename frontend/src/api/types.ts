export type HealthResponse = {
  status: string
}

export type PromptsResponse = {
  prompts: Record<string, string>
}

export type RunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown'

export type TopTimeFilter = 'day' | 'week' | 'month' | 'year' | 'all'

export type RunOptions = {
  top_time_filter?: TopTimeFilter
  top_posts_limit?: number
  hot_posts_limit?: number
  comments_per_post?: number
  replies_per_comment?: number
  comment_reply_depth?: 1 | 2
}

export type RunCreateRequest = {
  target_subreddit: string
  pre_materials: string
  options?: RunOptions
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
