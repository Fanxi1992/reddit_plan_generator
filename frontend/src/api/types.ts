export type HealthResponse = {
  status: string
}

export type PromptsResponse = {
  prompts: Record<string, string>
}

export type RunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown'

export type RunCreateRequest = {
  product_context_md: string
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
