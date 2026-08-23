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

export function buildCoursewareRequest({ learnerId, sourceIds, preferences = {} }) {
  return {
    learner_id: learnerId,
    source_resource_ids: [...sourceIds],
    publish_mode: 'automatic',
    learning_goal: preferences.learning_goal || null,
    expected_duration_minutes: preferences.expected_duration_minutes ?? null,
    interaction_intensity: preferences.interaction_intensity || 'medium',
    visual_style_id: preferences.visual_style_id || null,
  }
}
