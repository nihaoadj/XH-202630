import { api } from '../../api/client.js'
import { requireRoundCreation } from '../generation/roundApi.js'

/** @param {string} value */
const segment = value => encodeURIComponent(value)
/** @param {string} roundId */
const base = roundId => `/feedback/rounds/${segment(roundId)}`
/** @param {string} roundId @param {string} stageId */
const stage = (roundId, stageId) => `${base(roundId)}/stages/${segment(stageId)}`

export const roundFeedbackApi = {
  /** @param {string} learnerId @param {number} [offset] @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').LearningRoundListV1>>} */
  list: (learnerId, offset = 0) => api.get('/feedback/rounds', { params: { learner_id: learnerId, offset, limit: 20 } }),
  /** @param {string} roundId @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').LearningRoundDetailV1>>} */
  detail: roundId => api.get(base(roundId)),
  /** @param {string} roundId @param {string} [sourceAttemptId] @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RoundCandidatesV1>>} */
  candidates: (roundId, sourceAttemptId) => api.get(`${base(roundId)}/candidates`, { params: { source_attempt_id: sourceAttemptId } }),
  /** @param {string} learnerId @param {string} sourceAttemptId @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RoundCandidatesV1>>} */
  nextCandidates: (learnerId, sourceAttemptId) => api.get('/feedback/rounds/next/candidates', {
    params: { learner_id: learnerId, source_attempt_id: sourceAttemptId },
  }),
  /** @param {string} roundId @param {string} stageId @param {string} learnerId @param {string} [retakeFromSessionId] @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RoundEvaluationSessionV1>>} */
  session: (roundId, stageId, learnerId, retakeFromSessionId) => api.post(`${stage(roundId, stageId)}/evaluation-session`, {
    learner_id: learnerId, retake_from_session_id: retakeFromSessionId,
  }),
  /** @param {string} roundId @param {string} stageId @param {import('../../contracts/generated/contracts').RoundAttemptSubmitV1} data @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RoundFeedbackResultV1 | import('../../contracts/generated/contracts').RoundAttemptProcessingV1>>} */
  submit: (roundId, stageId, data) => api.post(`${stage(roundId, stageId)}/attempts`, data),
  /** @param {string} roundId @param {string} stageId @param {string} [sessionId] @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RoundFeedbackResultV1 | import('../../contracts/generated/contracts').RoundAttemptProcessingV1 | import('../../contracts/generated/contracts').RoundResultNotSubmittedV1>>} */
  result: (roundId, stageId, sessionId) => api.get(`${stage(roundId, stageId)}/result`, { params: { session_id: sessionId } }),
  /** @param {import('../../contracts/generated/contracts').RoundNextSelectionV1} data */
  next: data => api.post('/feedback/rounds/next/select', data).then(requireRoundCreation),
  /** @param {string} roundId @param {import('../../contracts/generated/contracts').RoundCorrectionSelectionV1} data */
  correct: (roundId, data) => api.post(`${base(roundId)}/corrections`, data).then(requireRoundCreation),
}
