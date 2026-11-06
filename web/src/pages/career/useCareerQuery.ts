import { useCallback, useEffect, useState } from 'react'

export function useCareerQuery<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<string>()
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const request = new AbortController()
    load(request.signal).then(
      (result) => {
        if (!request.signal.aborted) setData(result)
      },
      (failure: Error) => {
        if (!request.signal.aborted) setError(failure.message)
      },
    )
    return () => request.abort()
  }, [attempt, load])

  const retry = useCallback(() => {
    setError(undefined)
    setAttempt((previous) => previous + 1)
  }, [])

  return { data, setData, error, retry }
}
