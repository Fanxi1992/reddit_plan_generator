import { useEffect, useMemo, useState } from 'react'
import './App.css'
import { ApiError, fetchJson } from './api/client'
import type {
  HealthResponse,
  PromptsResponse,
  RunCreateResponse,
  RunStatusResponse,
} from './api/types'
import TextAreaField from './components/TextAreaField'
import StatusPill from './components/StatusPill'
import MarkdownPreview from './components/MarkdownPreview'
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

  const [selectedOutput, setSelectedOutput] = useState<OutputKind>('final')
  const [outputMarkdown, setOutputMarkdown] = useState<Partial<Record<OutputKind, string>>>({})
  const [outputLoading, setOutputLoading] = useState<OutputKind | null>(null)
  const [outputError, setOutputError] = useState<string | null>(null)

  const isLocked =
    isStarting || (runId !== null && run?.status !== 'succeeded' && run?.status !== 'failed')

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

  const availableOutputs = useMemo(() => {
    const downloads = run?.downloads ?? {}
    const keys = Object.keys(downloads) as OutputKind[]
    return keys.filter((k) => k === 'part1' || k === 'part2' || k === 'final')
  }, [run])

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

  function resetAllPrompts() {
    if (!defaultPrompts) return
    setDraftPrompts({ ...defaultPrompts })
  }

  function resetOnePrompt(key: PromptKey) {
    if (!defaultPrompts) return
    setDraftPrompts((prev) => ({ ...prev, [key]: defaultPrompts[key] }))
  }

  function clearRun() {
    if (isLocked) return
    setRunId(null)
    setRun(null)
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
        </section>
      </main>
    </div>
  )
}
