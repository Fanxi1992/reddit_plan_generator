import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { ApiError, fetchJson } from './api/client'
import type {
  ChatHistoryResponse,
  ChatMessage,
  ChatSendResponse,
  HealthResponse,
  PromptsResponse,
  StrategiesResponse,
  StrategyDef,
  RunCreateResponse,
  RunRestoreResponse,
  RunStatusResponse,
} from './api/types'
import TextAreaField from './components/TextAreaField'
import InputField from './components/InputField'
import SelectField from './components/SelectField'
import StatusPill from './components/StatusPill'
import MarkdownPreview from './components/MarkdownPreview'
import MarkdownBlock from './components/MarkdownBlock'
import {
  diffPrompts,
  PROMPT_KEYS,
  PROMPT_METAS,
  type PromptKey,
  validatePrompts,
} from './prompts'
import { useLocalStorageState } from './hooks/useLocalStorageState'

type BackendStatus = 'online' | 'offline' | 'unknown'
type PostV1Mode = 'generate' | 'client_draft'
type OutputKind =
  | 'post_final'
  | 'engagement_kit'
  | 'subreddit_dossier'
  | 'mod_review'
  | 'product_brief'
  | 'post_v1'
  | 'post_v2'

const OUTPUT_META: Record<OutputKind, { label: string; desc: string }> = {
  post_final: { label: '最终 Post', desc: '可直接发帖的最终文案' },
  engagement_kit: { label: '互动文案包', desc: 'OP 首评/回复模板（OP-only）' },
  subreddit_dossier: { label: 'Sub Dossier', desc: '风格/禁忌/标题模板/评论氛围' },
  mod_review: { label: 'Mod 审核', desc: 'Pass/Fail + 修改建议' },
  product_brief: { label: '产品 Brief', desc: '从前置资料抽取的结构化摘要' },
  post_v1: { label: 'Post v1', desc: '初稿' },
  post_v2: { label: 'Post v2', desc: '合规修订稿' },
}

const OUTPUT_ORDER: OutputKind[] = [
  'post_final',
  'engagement_kit',
  'subreddit_dossier',
  'mod_review',
  'product_brief',
  'post_v1',
  'post_v2',
]

const RUN_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/

function toCnStatus(status: RunStatusResponse['status']) {
  switch (status) {
    case 'pending':
      return '排队中'
    case 'running':
      return '运行中'
    case 'succeeded':
      return '已完成'
    case 'failed':
      return '失败'
    case 'cancelled':
      return '已取消'
    default:
      return '未知'
  }
}

function humanPhase(phase: string | null | undefined) {
  if (!phase) return ''
  if (phase === 'stage0_brief') return '阶段 0（Brief 抽取）'
  if (phase === 'paid_workflow1_scrape.py') return '阶段 1（抓取语料）'
  if (phase === 'paid_workflow2_dossier.py') return '阶段 2（Dossier）'
  if (phase === 'paid_workflow3_post_v1.py') return '阶段 3（Post v1）'
  if (phase === 'paid_workflow4_mod_review.py') return '阶段 4（Mod 审核）'
  if (phase === 'paid_workflow5_post_v2.py') return '阶段 5（Post v2）'
  if (phase === 'paid_workflow6_post_final.py') return '阶段 6（最终 Post）'
  if (phase === 'paid_workflow7_engagement_kit.py') return '阶段 7（互动文案包）'
  return phase
}

export default function App() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('unknown')
  const [loadingPrompts, setLoadingPrompts] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadingStrategies, setLoadingStrategies] = useState(false)
  const [strategiesError, setStrategiesError] = useState<string | null>(null)
  const [strategyCatalog, setStrategyCatalog] = useState<StrategyDef[]>([])

  const [defaultPrompts, setDefaultPrompts] = useState<Record<string, string> | null>(
    null,
  )
  const [draftPromptOverrides, setDraftPromptOverrides] = useLocalStorageState<
    Record<string, string>
  >('draftPromptOverrides', {})
  const [draftPrompts, setDraftPrompts] = useState<Record<string, string>>({})

  const [targetSubreddit, setTargetSubreddit] = useLocalStorageState(
    'draftTargetSubreddit',
    '',
  )
  const [preMaterials, setPreMaterials] = useLocalStorageState('draftPreMaterials', '')
  const [strategyId, setStrategyId] = useLocalStorageState<string>('draftStrategyId', 'free')
  const [strategyNotes, setStrategyNotes] = useLocalStorageState('draftStrategyNotes', '')
  const [postV1Mode, setPostV1Mode] = useLocalStorageState<PostV1Mode>(
    'draftPostV1Mode',
    'generate',
  )
  const [clientPostV1Draft, setClientPostV1Draft] = useLocalStorageState(
    'draftClientPostV1Draft',
    '',
  )
  const [stopAfterModReview, setStopAfterModReview] = useLocalStorageState<boolean>(
    'draftStopAfterModReview',
    false,
  )

  const [runId, setRunId] = useLocalStorageState<string | null>('currentRunId', null)
  const [run, setRun] = useState<RunStatusResponse | null>(null)
  const [isStarting, setIsStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [isStopping, setIsStopping] = useState(false)
  const [stopError, setStopError] = useState<string | null>(null)

  const [recentRunIds, setRecentRunIds] = useLocalStorageState<string[]>(
    'recentRunIds',
    [],
  )
  const [resumeRunId, setResumeRunId] = useState('')
  const [resumeLoading, setResumeLoading] = useState(false)
  const [resumeError, setResumeError] = useState<string | null>(null)

  const [restoreLoading, setRestoreLoading] = useState(false)
  const [restoreError, setRestoreError] = useState<string | null>(null)

  const [selectedOutput, setSelectedOutput] = useState<OutputKind>('post_final')
  const [outputMarkdown, setOutputMarkdown] = useState<Partial<Record<OutputKind, string>>>({})
  const [outputLoading, setOutputLoading] = useState<OutputKind | null>(null)
  const [outputError, setOutputError] = useState<string | null>(null)

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatDraft, setChatDraft] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [chatSending, setChatSending] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)
  const chatEndRef = useRef<HTMLDivElement | null>(null)

  const isLocked =
    isStarting ||
    isStopping ||
    (runId !== null &&
      run?.status !== 'succeeded' &&
      run?.status !== 'failed' &&
      run?.status !== 'cancelled' &&
      run?.status !== 'unknown')

  const chatEnabled = !!runId && !!run && run.status !== 'pending' && run.status !== 'running'

  const clientPostV1DraftError =
    postV1Mode === 'client_draft' && !clientPostV1Draft.trim()
      ? '不能为空（客户初稿模式需要粘贴文案）'
      : null

  const promptErrors = useMemo(() => {
    const errors = validatePrompts(draftPrompts)
    if (postV1Mode === 'client_draft') {
      errors.post_draft_prompt = null
    }
    return errors
  }, [draftPrompts, postV1Mode])
  const subredditError = targetSubreddit.trim() ? null : '不能为空'
  const materialsError = preMaterials.trim() ? null : '不能为空'

  const canRun = useMemo(() => {
    if (isLocked) return false
    if (!defaultPrompts) return false
    if (subredditError) return false
    if (materialsError) return false
    if (clientPostV1DraftError) return false
    for (const k of PROMPT_KEYS) {
      if (promptErrors[k]) return false
    }
    return true
  }, [
    clientPostV1DraftError,
    defaultPrompts,
    isLocked,
    materialsError,
    promptErrors,
    subredditError,
  ])

  const promptOverrides = useMemo(() => {
    if (!defaultPrompts) return {}
    return diffPrompts(defaultPrompts, draftPrompts)
  }, [defaultPrompts, draftPrompts])

  const strategyOptions = useMemo(() => {
    if (strategyCatalog.length) {
      return strategyCatalog.map((st) => ({ value: st.id, label: st.title }))
    }
    const base = [{ value: 'free', label: 'Free 自由模式（不限定脚本）' }]
    if (strategyId && strategyId !== 'free') {
      return [
        { value: strategyId, label: `(未知策略: ${strategyId}，将按 free 处理)`, disabled: true },
        ...base,
      ]
    }
    return base
  }, [strategyCatalog, strategyId])

  const selectedStrategy = useMemo(() => {
    const found = strategyCatalog.find((st) => st.id === strategyId)
    if (found) return found
    return strategyCatalog.find((st) => st.id === 'free') ?? null
  }, [strategyCatalog, strategyId])

  const strategyPreviewMarkdown = useMemo(() => {
    if (!selectedStrategy) return ''
    const brand = selectedStrategy.brand
    const titlePatterns = (selectedStrategy.title_templates ?? []).map((t) => `- ${t}`).join('\n')
    const beats = (selectedStrategy.beats ?? []).map((b) => `- ${b}`).join('\n')
    const template = (selectedStrategy.draft_template_md ?? '').trim()
    let md = `# ${selectedStrategy.title}\n\n${selectedStrategy.description ?? ''}\n\n## Hard Rules\n`
    md += `- Brand mentions: ${brand?.min_mentions ?? 1}–${brand?.max_mentions ?? 1} times in **Body**\n`
    md += `- Brand in title: ${(brand?.allow_in_title ?? false) ? 'allowed' : 'not allowed'}\n`
    if (brand?.notes) md += `- Notes: ${brand.notes}\n`
    if (titlePatterns) md += `\n## Title Patterns (choose 1)\n${titlePatterns}\n`
    if (beats) md += `\n## Beat Sheet (follow this pacing)\n${beats}\n`
    if (template) md += `\n## Draft Template\n\n${template}\n`
    return md.trim()
  }, [selectedStrategy])

  useEffect(() => {
    if (!runId) return
    if (!RUN_ID_RE.test(runId)) return
    setRecentRunIds((prev) => {
      if (prev[0] === runId) return prev
      const next = [runId, ...prev.filter((id) => id !== runId)]
      return next.slice(0, 12)
    })
  }, [runId, setRecentRunIds])

  useEffect(() => {
    setRestoreError(null)
  }, [runId])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoadingPrompts(true)
      setLoadError(null)
      setLoadingStrategies(true)
      setStrategiesError(null)

      try {
        await fetchJson<HealthResponse>('/api/health', { timeoutMs: 4000 })
        if (!cancelled) setBackendStatus('online')
      } catch {
        if (!cancelled) setBackendStatus('offline')
      }

      try {
        const data = await fetchJson<PromptsResponse>('/api/prompts', { timeoutMs: 15000 })
        if (cancelled) return
        setDefaultPrompts(data.prompts)

        const merged: Record<string, string> = { ...data.prompts }
        for (const key of PROMPT_KEYS) {
          const override = draftPromptOverrides[key]
          if (typeof override === 'string') merged[key] = override
        }
        setDraftPrompts(merged)
      } catch (e) {
        if (cancelled) return
        const msg = e instanceof ApiError ? e.message : '无法加载默认提示词，请检查后端'
        setLoadError(msg)
      } finally {
        if (!cancelled) setLoadingPrompts(false)
      }

      try {
        const data = await fetchJson<StrategiesResponse>('/api/strategies', { timeoutMs: 15000 })
        if (cancelled) return
        setStrategyCatalog(data.strategies ?? [])
      } catch (e) {
        if (cancelled) return
        const msg = e instanceof ApiError ? e.message : '无法加载脚本策略，请检查后端'
        setStrategiesError(msg)
        setStrategyCatalog([])
      } finally {
        if (!cancelled) setLoadingStrategies(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!defaultPrompts) return
    setDraftPromptOverrides(promptOverrides)
  }, [defaultPrompts, promptOverrides, setDraftPromptOverrides])

  useEffect(() => {
    if (!strategyCatalog.length) return
    const ids = new Set(strategyCatalog.map((s) => s.id))
    if (!ids.has(strategyId)) setStrategyId('free')
  }, [strategyCatalog, strategyId, setStrategyId])

  useEffect(() => {
    if (!runId) return
    let cancelled = false
    let timer: number | null = null

    async function tick() {
      try {
        const data = await fetchJson<RunStatusResponse>(`/api/runs/${runId}`, {
          timeoutMs: 20000,
        })
        if (cancelled) return
        setRun(data)

        if (data.status === 'running' || data.status === 'pending') {
          timer = window.setTimeout(tick, 2000)
        }
      } catch {
        if (!cancelled) timer = window.setTimeout(tick, 4000)
      }
    }

    void tick()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [runId])

  useEffect(() => {
    setSelectedOutput('post_final')
    setOutputMarkdown({})
    setOutputLoading(null)
    setOutputError(null)
  }, [runId])

  useEffect(() => {
    setChatMessages([])
    setChatDraft('')
    setChatError(null)
    setChatLoading(false)
    setChatSending(false)
  }, [runId])

  const availableOutputs = useMemo(() => {
    const downloads = run?.downloads ?? {}
    const keys = Object.keys(downloads) as OutputKind[]
    return keys.filter(
      (k) =>
        k === 'post_final' ||
        k === 'engagement_kit' ||
        k === 'subreddit_dossier' ||
        k === 'mod_review' ||
        k === 'product_brief' ||
        k === 'post_v1' ||
        k === 'post_v2',
    )
  }, [run])

  useEffect(() => {
    if (run?.status !== 'succeeded') return
    if (!availableOutputs.length) return
    if (availableOutputs.includes(selectedOutput)) return

    const preferred: OutputKind[] = [
      'post_final',
      'engagement_kit',
      'post_v2',
      'mod_review',
      'post_v1',
      'subreddit_dossier',
      'product_brief',
    ]
    const next = preferred.find((k) => availableOutputs.includes(k)) ?? availableOutputs[0]
    setSelectedOutput(next)
  }, [availableOutputs, run?.status, selectedOutput])

  async function loadChatHistory() {
    if (!runId) return
    setChatError(null)
    setChatLoading(true)
    try {
      const data = await fetchJson<ChatHistoryResponse>(
        `/api/runs/${runId}/chat/history?limit=200`,
        { timeoutMs: 30000 },
      )
      setChatMessages(data.messages ?? [])
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : '无法加载聊天记录，请检查后端'
      setChatError(msg)
    } finally {
      setChatLoading(false)
    }
  }

  useEffect(() => {
    if (!chatEnabled) return
    void loadChatHistory()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatEnabled])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [chatMessages.length])

  useEffect(() => {
    if (!runId) return
    if (run?.status !== 'succeeded') return
    if (!availableOutputs.includes(selectedOutput)) return
    if (outputMarkdown[selectedOutput]) return
    if (outputLoading) return

    const kind = selectedOutput
    let cancelled = false
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 25000)

    async function loadMarkdown() {
      setOutputError(null)
      setOutputLoading(kind)
      try {
        const res = await fetch(`/api/runs/${runId}/download/${kind}`, {
          signal: controller.signal,
        })
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        const text = await res.text()
        if (cancelled) return
        setOutputMarkdown((prev) => ({ ...prev, [kind]: text }))
      } catch {
        if (cancelled) return
        if (controller.signal.aborted) {
          setOutputError('预览加载超时或已取消（可尝试直接下载）')
        } else {
          setOutputError('加载预览失败（可尝试直接下载）')
        }
      } finally {
        window.clearTimeout(timeout)
        if (!cancelled) setOutputLoading(null)
      }
    }

    void loadMarkdown()
    return () => {
      cancelled = true
      window.clearTimeout(timeout)
      controller.abort()
      // Avoid getting stuck in dev StrictMode where effects are mounted/unmounted twice.
      setOutputLoading((prev) => (prev === kind ? null : prev))
    }
  }, [availableOutputs, outputLoading, outputMarkdown, run?.status, runId, selectedOutput])

  function rememberRunId(id: string) {
    const normalized = id.trim()
    if (!normalized || !RUN_ID_RE.test(normalized)) return
    setRecentRunIds((prev) => {
      if (prev[0] === normalized) return prev
      const next = [normalized, ...prev.filter((x) => x !== normalized)]
      return next.slice(0, 12)
    })
  }

  async function openRunById(rawId: string) {
    if (isLocked) return

    const id = rawId.trim()
    if (!id) return

    if (!RUN_ID_RE.test(id)) {
      setResumeError(
        'run_id 格式不正确（仅允许字母/数字/下划线/短横线，最长 64 位）',
      )
      return
    }

    if (id === runId) {
      setResumeError(null)
      setResumeRunId('')
      return
    }

    setResumeError(null)
    setResumeLoading(true)
    try {
      const data = await fetchJson<RunStatusResponse>(`/api/runs/${id}`, {
        timeoutMs: 20000,
      })
      rememberRunId(id)
      setStartError(null)
      setStopError(null)
      setRunId(id)
      setRun(data)
      setResumeRunId('')
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '无法加载该 run_id，请检查后端/网络'
      setResumeError(msg)
    } finally {
      setResumeLoading(false)
    }
  }

  function applyRestoreSnapshot(data: RunRestoreResponse) {
    setTargetSubreddit(data.target_subreddit ?? '')
    setPreMaterials(data.pre_materials ?? '')
    setStrategyId(data.strategy_id ?? 'free')
    setStrategyNotes(data.strategy_notes ?? '')
    setStopAfterModReview(!!data.stop_after_mod_review)
    setPostV1Mode(data.post_v1_mode ?? 'generate')
    setClientPostV1Draft(
      data.post_v1_mode === 'client_draft' ? (data.post_v1_client_draft ?? '') : '',
    )

    setDraftPrompts(() => {
      const next: Record<string, string> = {}
      for (const key of PROMPT_KEYS) {
        next[key] = data.prompts?.[key] ?? defaultPrompts?.[key] ?? ''
      }
      return next
    })
  }

  async function restoreDraftFromCurrentRun() {
    if (!runId) return
    if (isLocked) return

    if (!defaultPrompts) {
      setRestoreError('默认提示词尚未加载，无法恢复。')
      return
    }

    const confirmed = window.confirm(
      `将用 run_id=${runId} 的历史输入/提示词覆盖左侧草稿？\n\n提示：这不会影响该 run 的聊天；重新运行会生成新的 run_id。`,
    )
    if (!confirmed) return

    setRestoreError(null)
    setRestoreLoading(true)
    try {
      const data = await fetchJson<RunRestoreResponse>(`/api/runs/${runId}/restore`, {
        timeoutMs: 30000,
      })
      applyRestoreSnapshot(data)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '恢复失败，请检查后端/网络'
      setRestoreError(msg)
    } finally {
      setRestoreLoading(false)
    }
  }

  async function startRun() {
    if (!defaultPrompts) return
    setStartError(null)
    setStopError(null)
    setRun(null)
    setIsStarting(true)

    try {
      const normalizedSub = targetSubreddit.trim().replace(/^r\//i, '')
      const payload = {
        target_subreddit: normalizedSub,
        pre_materials: preMaterials,
        strategy_id: strategyId,
        strategy_notes: strategyNotes.trim() ? strategyNotes : null,
        prompt_overrides: promptOverrides,
        post_v1_mode: postV1Mode,
        ...(postV1Mode === 'client_draft'
          ? { post_v1_client_draft: clientPostV1Draft }
          : {}),
        stop_after_mod_review: stopAfterModReview,
        wait: false,
      }
      const res = await fetchJson<RunCreateResponse>('/api/runs', {
        method: 'POST',
        body: JSON.stringify(payload),
        timeoutMs: 30000,
      })
      rememberRunId(res.run_id)
      setRunId(res.run_id)
    } catch (e) {
      if (e instanceof ApiError) {
        setStartError(e.message)
      } else {
        setStartError('启动失败，请检查后端/网络')
      }
    } finally {
      setIsStarting(false)
    }
  }

  async function forceStopRun() {
    if (!runId) return
    const confirmed = window.confirm(
      '确认强制停止当前任务并清除前端状态？\n\n提示：会尝试通知后端取消；若后端仍在运行，新任务可能会被拒绝。',
    )
    if (!confirmed) return

    setStopError(null)
    setIsStopping(true)

    try {
      await fetchJson<RunStatusResponse>(`/api/runs/${runId}/cancel`, {
        method: 'POST',
        timeoutMs: 20000,
      })
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : '强制停止请求失败（可能后端离线）'
      setStopError(`${msg}；已清除前端任务状态。`)
    } finally {
      setIsStopping(false)
      clearRunLocal()
    }
  }

  function isLongMessage(text: string) {
    if (text.length > 2000) return true
    const lines = text.split(/\r?\n/g)
    return lines.length > 60
  }

  async function sendChat() {
    if (!runId) return
    if (!chatEnabled) return
    if (chatSending) return

    const message = chatDraft.trim()
    if (!message) return

    setChatError(null)
    setChatSending(true)
    setChatMessages((prev) => [...prev, { role: 'user', text: message }])
    setChatDraft('')

    try {
      const res = await fetchJson<ChatSendResponse>(`/api/runs/${runId}/chat`, {
        method: 'POST',
        body: JSON.stringify({ message }),
        timeoutMs: 120000,
      })
      setChatMessages((prev) => [...prev, { role: 'model', text: res.reply ?? '' }])
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '追问失败，请检查后端/网络'
      setChatError(msg)
    } finally {
      setChatSending(false)
    }
  }

  function resetAllPrompts() {
    if (!defaultPrompts) return
    setDraftPrompts({ ...defaultPrompts })
  }

  function resetOnePrompt(key: PromptKey) {
    if (!defaultPrompts) return
    setDraftPrompts((prev) => ({ ...prev, [key]: defaultPrompts[key] }))
  }

  function clearRunLocal() {
    setRunId(null)
    setRun(null)
  }

  function clearRun() {
    if (isLocked) return
    clearRunLocal()
    setStartError(null)
    setStopError(null)
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__left">
          <div className="brand">
            <div className="brand__title">Reddit 单 Sub 深度写作工作流</div>
            <div className="brand__subtitle">付款后交付版 · 前端工作台</div>
          </div>
        </div>

        <div className="topbar__right">
          <div className="statusRow">
            <StatusPill
              status={backendStatus}
              text={
                backendStatus === 'online'
                  ? '后端在线'
                  : backendStatus === 'offline'
                    ? '后端离线'
                    : '后端未知'
              }
            />
            {runId ? (
              <div className="runId">
                <span className="runId__label">run_id</span>
                <span className="runId__value">{runId}</span>
                <button
                  className="btn btn--ghost"
                  onClick={() => navigator.clipboard.writeText(runId)}
                  type="button"
                >
                  复制
                </button>
                <a
                  className="btn btn--ghost"
                  href={`/api/runs/${runId}/download/history`}
                  target="_blank"
                  rel="noreferrer"
                >
                  下载历史
                </a>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <main className="layout">
        <section className="col col--left">
          <div className="card">
            <div className="card__header">
              <div>
                <div className="card__title">输入</div>
                <div className="card__desc">
                  锁定一个 subreddit + 输入前置资料（原文不落盘，只抽取 brief）。
                </div>
              </div>
              <div className="card__headerActions">
                <button
                  className="btn btn--ghost"
                  type="button"
                  disabled={isLocked}
                   onClick={() => {
                     setTargetSubreddit('')
                     setPreMaterials('')
                     setStrategyId('free')
                     setStrategyNotes('')
                   }}
                 >
                   清空
                 </button>
               </div>
            </div>

            <InputField
              label="Target Subreddit（不带 r/）"
              value={targetSubreddit}
              onChange={setTargetSubreddit}
              placeholder="CrewAI"
              error={subredditError}
              disabled={isLocked}
            />

            <TextAreaField
              label="前置资料（粘贴文本）"
              value={preMaterials}
              onChange={setPreMaterials}
              placeholder={
                '例如：初步方案、产品详细资料、素材链接、硬性约束（must include / must avoid）…'
              }
              helper="后端会将原始前置资料保存到 runs/<run_id>/pre_materials.md 以支持恢复；但对话/追问上下文仅使用抽取后的 product_brief.md。"
              error={materialsError}
              disabled={isLocked}
              rows={12}
              monospace
            />

            {loadingStrategies ? (
              <div className="empty">正在加载脚本策略…</div>
            ) : strategiesError ? (
              <div className="alert alert--bad">
                <div className="alert__title">脚本策略加载失败</div>
                <div className="alert__body">{strategiesError}</div>
              </div>
            ) : null}

            <SelectField
              label="脚本策略（Strategy Selector）"
              value={strategyId}
              onChange={setStrategyId}
              options={strategyOptions}
              helper="选择主贴写作脚本；后端会在 Post v1 / Mod 审核 / Post v2 / Post Final 阶段持续注入该策略，避免后续修改跑偏。"
              disabled={isLocked || loadingStrategies}
            />

            <TextAreaField
              label="策略备注（可选）"
              value={strategyNotes}
              onChange={setStrategyNotes}
              placeholder="例如：品牌名必须出现 2 次；不要提价格；强调隐私；更像真实用户而不是创始人…"
              helper="会作为 Custom Notes 注入到策略说明中（所有后续写作/审核/改写阶段可见）。"
              disabled={isLocked}
              rows={4}
            />

            {strategyPreviewMarkdown ? (
              <details className="details">
                <summary className="details__summary">
                  预览：脚本策略内容（标题模板/节拍/模板）
                </summary>
                <div className="details__body">
                  <MarkdownBlock markdown={strategyPreviewMarkdown} />
                </div>
              </details>
            ) : null}

            <div className="hint">
              采样策略：后端固定抓取 <code className="hint__code">Top Week</code> 下最多{' '}
              <code className="hint__code">20</code> 个帖子（不抓取评论正文）。
            </div>
          </div>

          <div className="card">
            <div className="card__header">
              <div>
                <div className="card__title">提示词（Prompts）</div>
                <div className="card__desc">
                  每个阶段一个大字符串；支持修改。运行中将锁定。
                </div>
              </div>
              <div className="card__headerActions">
                <button
                  className="btn btn--ghost"
                  type="button"
                  disabled={isLocked || !defaultPrompts}
                  onClick={resetAllPrompts}
                >
                  恢复全部默认
                </button>
              </div>
            </div>

            {loadingPrompts ? (
              <div className="empty">正在加载默认提示词…</div>
            ) : loadError ? (
              <div className="alert alert--bad">
                <div className="alert__title">加载失败</div>
                <div className="alert__body">{loadError}</div>
              </div>
            ) : null}

            <div className="accordion">
              {PROMPT_METAS.map((meta) => {
                const changed =
                  defaultPrompts &&
                  (draftPrompts[meta.key] ?? '').trim() !==
                    (defaultPrompts[meta.key] ?? '').trim()
                const isPostV1Prompt = meta.key === 'post_draft_prompt'
                const isClientDraftMode = isPostV1Prompt && postV1Mode === 'client_draft'
                const error = isClientDraftMode ? null : promptErrors[meta.key]
                const required = isClientDraftMode ? [] : meta.requiredPlaceholders

                return (
                  <details className="accordion__item" key={meta.key} open={meta.key === 'brief_prompt'}>
                    <summary className="accordion__summary">
                      <div className="accordion__summaryLeft">
                        <span className="accordion__title">{meta.title}</span>
                        {changed ? <span className="tag tag--warn">已修改</span> : null}
                        {error ? <span className="tag tag--bad">有问题</span> : null}
                      </div>
                      <span className="accordion__chev">▾</span>
                    </summary>

                    <div className="accordion__content">
                      <div className="muted">{meta.description}</div>
                      {isPostV1Prompt ? (
                        <div className="hint">
                          初稿模式：
                          <button
                            className={`btn btn--sm ${postV1Mode === 'generate' ? 'btn--primary' : 'btn--ghost'}`}
                            type="button"
                            disabled={isLocked}
                            onClick={() => setPostV1Mode('generate')}
                          >
                            通用模式（生成 v1）
                          </button>
                          <button
                            className={`btn btn--sm ${postV1Mode === 'client_draft' ? 'btn--primary' : 'btn--ghost'}`}
                            type="button"
                            disabled={isLocked}
                            onClick={() => setPostV1Mode('client_draft')}
                          >
                            客户初稿模式（原样直通）
                          </button>
                        </div>
                      ) : null}
                      {required.length ? (
                        <div className="hint">
                          必须保留占位符：
                          {required.map((p) => (
                            <code className="hint__code" key={p}>
                              {p}
                            </code>
                          ))}
                        </div>
                      ) : null}

                      {isClientDraftMode ? (
                        <TextAreaField
                          label="客户初稿（将原样作为 post_v1.md）"
                          value={clientPostV1Draft}
                          onChange={setClientPostV1Draft}
                          placeholder="粘贴客户提供的文案（可包含 Title/Body/Markdown）。内容将原样写入 post_v1.md。"
                          helper="此模式下不会调用大模型生成 v1；post_draft_prompt 将被忽略（可保留用于通用模式）。"
                          error={clientPostV1DraftError}
                          disabled={isLocked}
                          rows={12}
                          monospace
                          rightActions={
                            <>
                              <button
                                className="btn btn--ghost"
                                type="button"
                                disabled={isLocked}
                                onClick={() => setClientPostV1Draft('')}
                              >
                                清空
                              </button>
                              <button
                                className="btn btn--ghost"
                                type="button"
                                onClick={() => navigator.clipboard.writeText(clientPostV1Draft ?? '')}
                              >
                                复制
                              </button>
                            </>
                          }
                        />
                      ) : null}

                      <TextAreaField
                        label={meta.key}
                        value={draftPrompts[meta.key] ?? ''}
                        onChange={(v) => setDraftPrompts((prev) => ({ ...prev, [meta.key]: v }))}
                        helper={
                          isClientDraftMode ? '客户初稿模式下，该提示词不会被执行（仅通用模式使用）。' : undefined
                        }
                        error={error}
                        disabled={isLocked || isClientDraftMode}
                        rows={10}
                        monospace
                        rightActions={
                          <>
                            <button
                              className="btn btn--ghost"
                              type="button"
                              disabled={isLocked || !defaultPrompts}
                              onClick={() => resetOnePrompt(meta.key)}
                            >
                              恢复默认
                            </button>
                            <button
                              className="btn btn--ghost"
                              type="button"
                              onClick={() => navigator.clipboard.writeText(draftPrompts[meta.key] ?? '')}
                            >
                              复制
                            </button>
                          </>
                        }
                      />
                    </div>
                  </details>
                )
              })}
            </div>
          </div>
        </section>

        <section className="col col--right">
          <div className="card">
            <div className="card__header">
              <div>
                <div className="card__title">运行</div>
                <div className="card__desc">使用异步执行 + 轮询（避免超时）。</div>
              </div>
              <div className="card__headerActions">
                <button
                  className="btn btn--primary"
                  type="button"
                  disabled={!canRun}
                  onClick={startRun}
                >
                  一键运行
                </button>
                {runId ? (
                  <button
                    className="btn btn--danger"
                    type="button"
                    disabled={
                      isStarting ||
                      isStopping ||
                      run?.status === 'succeeded' ||
                      run?.status === 'failed' ||
                      run?.status === 'cancelled'
                    }
                    onClick={forceStopRun}
                  >
                    {isStopping ? '正在停止…' : '强制停止'}
                  </button>
                ) : null}
                <button
                  className="btn btn--ghost"
                  type="button"
                  disabled={isLocked || !runId}
                  onClick={clearRun}
                >
                  清除任务
                </button>
              </div>
            </div>

            <div className="hint">
              流程模式：
              <button
                className={`btn btn--sm ${stopAfterModReview ? 'btn--ghost' : 'btn--primary'}`}
                type="button"
                disabled={isLocked}
                onClick={() => setStopAfterModReview(false)}
              >
                完整流程（7 阶段）
              </button>
              <button
                className={`btn btn--sm ${stopAfterModReview ? 'btn--primary' : 'btn--ghost'}`}
                type="button"
                disabled={isLocked}
                onClick={() => setStopAfterModReview(true)}
              >
                仅到 Mod 审核（4 阶段）
              </button>
            </div>

            <InputField
              label="接续旧任务（run_id）"
              value={resumeRunId}
              onChange={(v) => {
                setResumeRunId(v)
                if (resumeError) setResumeError(null)
              }}
              placeholder="20260110_114637"
              helper="切换到该 run_id，并自动加载该任务的历史输出/聊天记录（不会覆盖左侧草稿）。"
              error={resumeError}
              disabled={isLocked || resumeLoading}
              rightActions={
                <button
                  className="btn btn--ghost"
                  type="button"
                  disabled={isLocked || resumeLoading || !resumeRunId.trim()}
                  onClick={() => openRunById(resumeRunId)}
                >
                  {resumeLoading ? '加载中…' : '接续'}
                </button>
              }
            />

            {recentRunIds.length ? (
              <div className="recentRuns">
                <div className="recentRuns__label">最近 run_id：</div>
                <div className="recentRuns__list">
                  {recentRunIds.slice(0, 8).map((id) => (
                    <button
                      key={id}
                      className="btn btn--ghost btn--sm recentRuns__btn"
                      type="button"
                      disabled={isLocked || resumeLoading || id === runId}
                      onClick={() => openRunById(id)}
                      title={id}
                    >
                      {id}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {runId ? (
              <div className="hint">
                恢复草稿：
                <button
                  className="btn btn--ghost btn--sm"
                  type="button"
                  disabled={isLocked || restoreLoading || loadingPrompts || !defaultPrompts}
                  onClick={restoreDraftFromCurrentRun}
                >
                  {restoreLoading ? '恢复中…' : '恢复到左侧'}
                </button>
                <span className="tag tag--warn">会覆盖左侧草稿</span>
              </div>
            ) : null}

            {restoreError ? (
              <div className="alert alert--bad">
                <div className="alert__title">恢复失败</div>
                <div className="alert__body">{restoreError}</div>
              </div>
            ) : null}

            {startError ? (
              <div className="alert alert--bad">
                <div className="alert__title">启动失败</div>
                <div className="alert__body">{startError}</div>
              </div>
            ) : null}

            {stopError ? (
              <div className="alert alert--bad">
                <div className="alert__title">强制停止提示</div>
                <div className="alert__body">{stopError}</div>
              </div>
            ) : null}

            {!runId ? (
              <div className="empty">
                还没有任务。填写左侧内容后，点击「一键运行」。
              </div>
            ) : (
              <div className="runBox">
                <div className="runBox__row">
                  <div className="runBox__label">状态</div>
                  <div className="runBox__value">
                    <StatusPill
                      status={run?.status ?? 'unknown'}
                      text={toCnStatus(run?.status ?? 'unknown')}
                    />
                  </div>
                </div>
                <div className="runBox__row">
                  <div className="runBox__label">当前阶段</div>
                  <div className="runBox__value">{humanPhase(run?.current_phase)}</div>
                </div>
                {run?.error ? (
                  <div className="alert alert--bad">
                    <div className="alert__title">错误</div>
                    <div className="alert__body">{run.error}</div>
                  </div>
                ) : null}
              </div>
            )}
          </div>

          <div className="card">
            <div className="card__header">
              <div>
                <div className="card__title">结果预览</div>
                <div className="card__desc">完成后可下载，也可直接在页面预览。</div>
              </div>
            </div>

            {!runId ? (
              <div className="empty">还没有任务，先运行一次。</div>
            ) : run?.status !== 'succeeded' ? (
              <div className="empty">
                {run?.status === 'failed'
                  ? '任务失败：请查看上方错误信息，调整后重试。'
                  : '任务未完成：完成后会自动显示预览与下载。'}
              </div>
            ) : availableOutputs.length === 0 ? (
              <div className="empty">已完成，但没有检测到可下载结果文件。</div>
            ) : (
                <div className="results">
                  <div className="tabs">
                  {OUTPUT_ORDER.map((k) => {
                    const enabled = availableOutputs.includes(k)
                    const active = selectedOutput === k
                    return (
                      <button
                        key={k}
                        className={`tab ${active ? 'tab--active' : ''}`}
                        type="button"
                        disabled={!enabled}
                        onClick={() => setSelectedOutput(k)}
                      >
                        <div className="tab__label">{OUTPUT_META[k].label}</div>
                        <div className="tab__desc">{OUTPUT_META[k].desc}</div>
                      </button>
                    )
                  })}
                </div>

                <div className="results__actions">
                  <button
                    className="btn btn--primary"
                    type="button"
                    disabled={!availableOutputs.includes(selectedOutput)}
                    onClick={() =>
                      window.open(
                        `/api/runs/${runId}/download/${selectedOutput}`,
                        '_blank',
                        'noopener,noreferrer',
                      )
                    }
                  >
                    下载当前
                  </button>
                  <button
                    className="btn btn--ghost"
                    type="button"
                    disabled={!outputMarkdown[selectedOutput]}
                    onClick={() =>
                      navigator.clipboard.writeText(outputMarkdown[selectedOutput] ?? '')
                    }
                  >
                    复制 Markdown
                  </button>
                </div>

                {outputError ? (
                  <div className="alert alert--bad">
                    <div className="alert__title">预览加载失败</div>
                    <div className="alert__body">{outputError}</div>
                  </div>
                ) : null}

                {outputMarkdown[selectedOutput] ? (
                  <MarkdownPreview markdown={outputMarkdown[selectedOutput] ?? ''} />
                ) : null}
              </div>
            )}
          </div>

          <div className="card">
            <div className="card__header">
              <div>
                <div className="card__title">追问</div>
                <div className="card__desc">
                  任务结束后，可继续在当前 run 下聊天（会追加保存到 chat_history.jsonl）。
                </div>
              </div>
              <div className="card__headerActions">
                <button
                  className="btn btn--ghost"
                  type="button"
                  disabled={!chatEnabled || chatLoading || chatSending}
                  onClick={loadChatHistory}
                >
                  {chatLoading ? '加载中…' : '刷新'}
                </button>
              </div>
            </div>

            {!runId ? (
              <div className="empty">还没有任务，先运行一次。</div>
            ) : !run ? (
              <div className="empty">正在加载任务状态…</div>
            ) : run.status === 'running' || run.status === 'pending' ? (
              <div className="empty">任务运行中：完成/失败/取消后可追问。</div>
            ) : (
              <div className="chat">
                <div className="chat__log">
                  {chatLoading ? (
                    <div className="empty">正在加载聊天记录…</div>
                  ) : chatMessages.length === 0 ? (
                    <div className="empty">暂无聊天记录（你可以从这里开始追问）。</div>
                  ) : (
                    <div className="chat__msgs">
                      {chatMessages.map((m, idx) => {
                        const long = isLongMessage(m.text)
                        const body =
                          m.role === 'model' ? (
                            <MarkdownBlock markdown={m.text} />
                          ) : (
                            <pre className="chatMsg__pre">{m.text}</pre>
                          )
                        return (
                          <div className={`chatMsg chatMsg--${m.role}`} key={idx}>
                            <div className="chatMsg__meta">{m.role === 'user' ? '你' : 'AI'}</div>
                            {long ? (
                              <details className="chatMsg__details">
                                <summary className="chatMsg__summary">内容较长，点击展开</summary>
                                <div className="chatMsg__body">{body}</div>
                              </details>
                            ) : (
                              <div className="chatMsg__body">{body}</div>
                            )}
                          </div>
                        )
                      })}
                      <div ref={chatEndRef} />
                    </div>
                  )}
                </div>

                {chatError ? (
                  <div className="alert alert--bad">
                    <div className="alert__title">追问失败</div>
                    <div className="alert__body">{chatError}</div>
                  </div>
                ) : null}

                <TextAreaField
                  label="追问"
                  value={chatDraft}
                  onChange={setChatDraft}
                  placeholder="例如：请解释 Final 里第 2 个 subreddit 的策略依据，并给出更不营销的标题备选。"
                  helper="会带上本 run 的完整 history（chat_history.jsonl）作为上下文。"
                  disabled={!chatEnabled || chatSending}
                  rows={4}
                  rightActions={
                    <>
                      <button
                        className="btn btn--ghost"
                        type="button"
                        disabled={!chatDraft.trim() || !chatEnabled || chatSending}
                        onClick={() => setChatDraft('')}
                      >
                        清空
                      </button>
                      <button
                        className="btn btn--primary"
                        type="button"
                        disabled={!chatDraft.trim() || !chatEnabled || chatSending}
                        onClick={sendChat}
                      >
                        {chatSending ? '发送中…' : '发送'}
                      </button>
                    </>
                  }
                />
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  )
}
