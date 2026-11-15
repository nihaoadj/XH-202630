import { ref, watch } from 'vue'
import { createRequestGuard } from '../../utils/requestContext.js'

/** @typedef {'retry' | 'append' | 'resource'} CommandChannel */
/** @typedef {{ learnerId: string, runId: string }} CommandContext */
/** @typedef {{ ticket: { isCurrent: () => boolean }, busyValue: string }} CommandOwner */
/**
 * @typedef {object} Command
 * @property {CommandChannel} channel
 * @property {string} [busyValue]
 * @property {() => Promise<Array<{ data: { run_id: string } }>>} execute
 * @property {() => void} [beforeSubmit]
 * @property {(runId: string) => void} [accepted]
 * @property {() => void} succeeded
 * @property {(error: unknown) => void} failed
 */

/**
 * Own only continuation commands and their UI completion, never server tasks.
 * @param {object} options
 * @param {() => CommandContext} options.getContext
 * @param {(runId: string) => void} options.selectRun
 * @param {(isCurrent: () => boolean) => Promise<boolean>} options.refreshJobs
 * @param {(runId: string) => Promise<void>} options.startRealtime
 */
export function useGenerationCommands({ getContext, selectRun, refreshJobs, startRealtime }) {
  const retrying = ref(false)
  const appendingResources = ref(false)
  const retryingResourceKey = ref('')
  /** @type {CommandChannel[]} */
  const names = ['retry', 'append', 'resource']
  /** @type {Record<CommandChannel, { guard: ReturnType<typeof createRequestGuard>, owner: CommandOwner | null }>} */
  const channels = {
    retry: { guard: createRequestGuard(getContext), owner: null },
    append: { guard: createRequestGuard(getContext), owner: null },
    resource: { guard: createRequestGuard(getContext), owner: null },
  }
  let disposed = false
  /** @type {CommandOwner | null} */
  let adoptingOwner = null

  /** @param {CommandChannel} name @param {boolean} busy @param {string} [value] */
  function setBusy(name, busy, value = '') {
    if (name === 'retry') retrying.value = busy
    else if (name === 'append') appendingResources.value = busy
    else retryingResourceKey.value = busy ? value : ''
  }

  // Synchronous invalidation also rejects A -> B -> A within one render tick.
  const stopWatching = watch(getContext, () => {
    for (const name of names) {
      const state = channels[name]
      if (adoptingOwner && state.owner === adoptingOwner) continue
      state.guard.invalidate()
      state.owner = null
      setBusy(name, false)
    }
  }, { flush: 'sync' })

  /** @param {Command} command @returns {Promise<boolean>} */
  async function run(command) {
    if (disposed) return false
    const { channel, busyValue = '' } = command
    const state = channels[channel]
    if (state.owner?.busyValue === busyValue) return false
    const owner = { ticket: state.guard.capture(), busyValue }
    state.owner = owner
    const isCurrent = () => !disposed && state.owner === owner && owner.ticket.isCurrent()
    setBusy(channel, true, busyValue)
    try {
      command.beforeSubmit?.()
      if (!isCurrent()) return false
      const responses = await command.execute()
      if (!isCurrent()) return false
      const runId = responses[0].data.run_id
      // Selecting our accepted child invalidates other commands, but this one
      // must explicitly adopt that context before crossing another await.
      adoptingOwner = owner
      try { selectRun(runId) } finally { adoptingOwner = null }
      owner.ticket = state.guard.capture()
      if (!isCurrent()) return false
      command.accepted?.(runId)
      if (!isCurrent()) return false
      if (!await refreshJobs(isCurrent) || !isCurrent()) return false
      await startRealtime(runId)
      if (!isCurrent()) return false
      command.succeeded()
      return true
    } catch (error) {
      if (isCurrent()) command.failed(error)
      return false
    } finally {
      if (state.owner === owner) {
        state.owner = null
        setBusy(channel, false)
      }
    }
  }

  function dispose() {
    disposed = true
    stopWatching()
    for (const name of names) {
      channels[name].guard.dispose()
      channels[name].owner = null
      setBusy(name, false)
    }
  }

  return { retrying, appendingResources, retryingResourceKey, run, dispose }
}
