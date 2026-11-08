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
  /** @param {string} roundId @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RoundCandidatesV1>>} */
  candidates: roundId => api.get(`${base(roundId)}/candidates`),
  /** @param {string} roundId @param {string} stageId @param {string} learnerId @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RoundEvaluationSessionV1>>} */
  session: (roundId, stageId, learnerId) => api.post(`${stage(roundId, stageId)}/evaluation-session`, { learner_id: learnerId }),
  /** @param {string} roundId @param {string} stageId @param {import('../../contracts/generated/contracts').RoundAttemptSubmitV1} data @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RoundFeedbackResultV1 | import('../../contracts/generated/contracts').RoundAttemptProcessingV1>>} */
  submit: (roundId, stageId, data) => api.post(`${stage(roundId, stageId)}/attempts`, data),
  /** @param {string} roundId @param {string} stageId @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RoundFeedbackResultV1 | import('../../contracts/generated/contracts').RoundAttemptProcessingV1 | import('../../contracts/generated/contracts').RoundResultNotSubmittedV1>>} */
  result: (roundId, stageId) => api.get(`${stage(roundId, stageId)}/result`),
  /** @param {import('../../contracts/generated/contracts').RoundNextSelectionV1} data */
  next: data => api.post('/feedback/rounds/next/select', data).then(requireRoundCreation),
  /** @param {string} roundId @param {import('../../contracts/generated/contracts').RoundCorrectionSelectionV1} data */
  correct: (roundId, data) => api.post(`${base(roundId)}/corrections`, data).then(requireRoundCreation),
}
