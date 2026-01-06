import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { ApiError, fetchJson } from './api/client'
import type {
  ChatHistoryResponse,
  ChatMessage,
  ChatSendResponse,
  HealthResponse,
  PromptsResponse,
  RunCreateResponse,
  RunStatusResponse,
} from './api/types'
import TextAreaField from './components/TextAreaField'
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
type OutputKind = 'part1' | 'part2' | 'final'

const OUTPUT_META: Record<OutputKind, { label: string; desc: string }> = {
  part1: { label: 'Part 1：定位', desc: 'Market Positioning & Audience Analysis' },
  part2: { label: 'Part 2：策略', desc: 'Community Strategy（Top 5 社区）' },
  final: { label: 'Final：内容方案', desc: 'KPI + 内容草稿 + 种子评论' },
}

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
  if (phase === 'workflow1.py') return '阶段 1（产品理解）'
  if (phase === 'workflow2.py') return '阶段 2（定位与候选）'
  if (phase === 'workflow3.py') return '阶段 3（审计与筛选）'
  if (phase === 'workflow4.py') return '阶段 4（KPI 与草稿）'
  return phase
}

export default function App() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('unknown')
  const [loadingPrompts, setLoadingPrompts] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [defaultPrompts, setDefaultPrompts] = useState<Record<string, string> | null>(
    null,
  )
  const [draftPromptOverrides, setDraftPromptOverrides] = useLocalStorageState<
    Record<string, string>
  >('draftPromptOverrides', {})
  const [draftPrompts, setDraftPrompts] = useState<Record<string, string>>({})

  const [productContext, setProductContext] = useLocalStorageState(
    'draftProductContext',
    '',
  )

  const [runId, setRunId] = useLocalStorageState<string | null>('currentRunId', null)
  const [run, setRun] = useState<RunStatusResponse | null>(null)
  const [isStarting, setIsStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [isStopping, setIsStopping] = useState(false)
  const [stopError, setStopError] = useState<string | null>(null)

  const [selectedOutput, setSelectedOutput] = useState<OutputKind>('final')
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
      run?.status !== 'cancelled')

  const chatEnabled = !!runId && !!run && run.status !== 'pending' && run.status !== 'running'

  const promptErrors = useMemo(() => validatePrompts(draftPrompts), [draftPrompts])
  const productError = productContext.trim() ? null : '不能为空'

  const canRun = useMemo(() => {
    if (isLocked) return false
    if (!defaultPrompts) return false
    if (productError) return false
    for (const k of PROMPT_KEYS) {
      if (promptErrors[k]) return false
    }
    return true
  }, [defaultPrompts, isLocked, productError, promptErrors])

  const promptOverrides = useMemo(() => {
    if (!defaultPrompts) return {}
    return diffPrompts(defaultPrompts, draftPrompts)
  }, [defaultPrompts, draftPrompts])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoadingPrompts(true)
      setLoadError(null)

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
    setSelectedOutput('final')
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
    return keys.filter((k) => k === 'part1' || k === 'part2' || k === 'final')
  }, [run])

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

    let cancelled = false

    async function loadMarkdown(kind: OutputKind) {
      setOutputError(null)
      setOutputLoading(kind)
      try {
        const res = await fetch(`/api/runs/${runId}/download/${kind}`)
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        const text = await res.text()
        if (cancelled) return
        setOutputMarkdown((prev) => ({ ...prev, [kind]: text }))
      } catch {
        if (!cancelled) setOutputError('加载预览失败（可尝试直接下载）')
      } finally {
        if (!cancelled) setOutputLoading(null)
      }
    }

    void loadMarkdown(selectedOutput)
    return () => {
      cancelled = true
    }
  }, [availableOutputs, outputLoading, outputMarkdown, run?.status, runId, selectedOutput])

  async function startRun() {
    if (!defaultPrompts) return
    setStartError(null)
    setStopError(null)
    setRun(null)
    setIsStarting(true)

    try {
      const payload = {
        product_context_md: productContext,
        prompt_overrides: promptOverrides,
        wait: false,
      }
      const res = await fetchJson<RunCreateResponse>('/api/runs', {
        method: 'POST',
        body: JSON.stringify(payload),
        timeoutMs: 30000,
      })
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
            <div className="brand__title">Reddit 内容方案工作流</div>
            <div className="brand__subtitle">前端工作台（中文界面）</div>
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
                <div className="card__desc">粘贴英文 Markdown（每次运行可不同）。</div>
              </div>
              <div className="card__headerActions">
                <button
                  className="btn btn--ghost"
                  type="button"
                  disabled={isLocked}
                  onClick={() => setProductContext('')}
                >
                  清空
                </button>
              </div>
            </div>

            <TextAreaField
              label="Product Context（英文 Markdown）"
              value={productContext}
              onChange={setProductContext}
              placeholder={'[Client Product Data]\nProduct Name: ...\n...'}
              error={productError}
              disabled={isLocked}
              rows={12}
              monospace
            />
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
                const error = promptErrors[meta.key]
                const required = meta.requiredPlaceholders

                return (
                  <details className="accordion__item" key={meta.key} open={meta.key === 'phase1_prompt'}>
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

                      <TextAreaField
                        label={meta.key}
                        value={draftPrompts[meta.key] ?? ''}
                        onChange={(v) => setDraftPrompts((prev) => ({ ...prev, [meta.key]: v }))}
                        error={error}
                        disabled={isLocked}
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
                  {(['part1', 'part2', 'final'] as OutputKind[]).map((k) => {
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
                  <a
                    className="btn btn--primary"
                    href={`/api/runs/${runId}/download/${selectedOutput}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    下载当前
                  </a>
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

                {outputLoading === selectedOutput ? (
                  <div className="empty">正在加载预览…</div>
                ) : outputMarkdown[selectedOutput] ? (
                  <MarkdownPreview markdown={outputMarkdown[selectedOutput] ?? ''} />
                ) : (
                  <div className="empty">未加载预览（可点击上方 Tab 触发加载）。</div>
                )}
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
