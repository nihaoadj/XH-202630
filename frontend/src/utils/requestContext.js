/**
 * Capture an async request's context and make stale completions easy to reject.
 * Context values should be stable primitives; nested values are not deep-copied.
 *
 * @template {Record<string, unknown>} TContext
 * @param {() => TContext} contextGetter
 * @returns {{ capture: () => { isCurrent: () => boolean }, invalidate: () => void, dispose: () => void }}
 */
export function createRequestGuard(contextGetter) {
  let version = 0
  let disposed = false

  function capture() {
    const context = { ...contextGetter() }
    const requestVersion = ++version
    return {
      isCurrent() {
        if (disposed || requestVersion !== version) return false
        const currentContext = contextGetter()
        const keys = Object.keys(context)
        const currentKeys = Object.keys(currentContext)
        return keys.length === currentKeys.length
          && keys.every((key) => Object.prototype.hasOwnProperty.call(currentContext, key)
            && Object.is(context[key], currentContext[key]))
      },
    }
  }

  return {
    capture,
    invalidate() { version += 1 },
    dispose() {
      disposed = true
      version += 1
    },
  }
}
