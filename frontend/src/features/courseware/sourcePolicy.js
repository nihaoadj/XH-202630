/**
 * A selected resource creates its own interactive representation.  Keeping
 * this policy pure lets the UI and browser-free tests share the same rule.
 */
export const COURSEWARE_SOURCE_TYPES = Object.freeze(['实操指南', '复习清单'])

export function coursewareEligibleSources(resources) {
  return (resources || [])
    .filter((resource) => resource?.resource_kind !== 'interactive_courseware'
      && COURSEWARE_SOURCE_TYPES.includes(resource?.resource_type)
      && resource?.resource_id)
}

export function buildCoursewareBatchRequest({ learnerId, resourceIds, preferences = {} }) {
  return {
    learner_id: learnerId,
    resource_ids: [...resourceIds],
    learning_goal: preferences.learning_goal || null,
    expected_duration_minutes: preferences.expected_duration_minutes ?? null,
    interaction_intensity: preferences.interaction_intensity || 'medium',
  }
}
