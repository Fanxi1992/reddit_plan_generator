import { useEffect, useState } from 'react'

type StorageStateOptions = {
  readOnInit?: boolean
}

export function useLocalStorageState<T>(
  key: string,
  initialValue: T,
  options?: StorageStateOptions,
) {
  const readOnInit = options?.readOnInit ?? true
  const [state, setState] = useState<T>(() => {
    if (!readOnInit) return initialValue
    try {
      const raw = window.localStorage.getItem(key)
      if (!raw) return initialValue
      return JSON.parse(raw) as T
    } catch {
      return initialValue
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(state))
    } catch {
      // ignore quota/serialization errors
    }
  }, [key, state])

  return [state, setState] as const
}

