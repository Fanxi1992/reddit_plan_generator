export type ApiErrorPayload = {
  detail?: unknown
}

export class ApiError extends Error {
  status: number
  detail?: unknown

  constructor(message: string, status: number, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function withBase(path: string): string {
  if (!API_BASE) return path
  return `${API_BASE}${path}`
}

export async function fetchJson<T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  const { timeoutMs, ...requestInit } = init ?? {}
  const controller = new AbortController()
  const timeout = timeoutMs
    ? window.setTimeout(() => controller.abort(), timeoutMs)
    : null

  try {
    const res = await fetch(withBase(path), {
      ...requestInit,
      headers: {
        Accept: 'application/json',
        ...(requestInit?.body ? { 'Content-Type': 'application/json' } : {}),
        ...(requestInit?.headers ?? {}),
      },
      signal: controller.signal,
    })

    const contentType = res.headers.get('content-type') ?? ''
    const isJson = contentType.includes('application/json')

    if (!res.ok) {
      let payload: ApiErrorPayload | undefined
      if (isJson) {
        try {
          payload = (await res.json()) as ApiErrorPayload
        } catch {
          payload = undefined
        }
      }
      const msg =
        typeof payload?.detail === 'string'
          ? payload.detail
          : `请求失败 (HTTP ${res.status})`
      throw new ApiError(msg, res.status, payload?.detail)
    }

    if (!isJson) {
      throw new ApiError('后端返回了非 JSON 响应', res.status)
    }

    return (await res.json()) as T
  } finally {
    if (timeout) window.clearTimeout(timeout)
  }
}

