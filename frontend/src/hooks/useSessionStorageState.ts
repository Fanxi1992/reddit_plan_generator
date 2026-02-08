import { useEffect, useState } from 'react'

export function useSessionStorageState<T>(key: string, initialValue: T) {
  const [state, setState] = useState<T>(() => {
    try {
      const raw = window.sessionStorage.getItem(key)
      if (!raw) return initialValue
      return JSON.parse(raw) as T
    } catch {
      return initialValue
    }
  })

  useEffect(() => {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(state))
    } catch {
      // ignore quota/serialization errors
    }
  }, [key, state])

  return [state, setState] as const
}

