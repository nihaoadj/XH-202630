/**
 * Courseware sources are frozen from one feedback batch only.  Keeping this
 * policy in a small pure function lets the UI and its browser-free tests use
 * the same boundary without relying on Vue internals.
 */
export function sameFeedbackBatchSources(resources, batchId) {
  const expectedBatchId = String(batchId || '').trim()
  if (!expectedBatchId) return []
  return (resources || []).filter((resource) => (
    resource?.resource_kind !== 'interactive_courseware'
    && String(resource?.batch_id || '').trim() === expectedBatchId
  ))
}
