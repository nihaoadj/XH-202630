import { api } from '../../api/client.js'

/** @param {import('axios').AxiosResponse<import('../../contracts/generated/contracts').RoundCreationResponseV1>} response */
export function requireRoundCreation(response) {
  const value = response?.data
  if (!value || typeof value.round_id !== 'string' || typeof value.stage_id !== 'string'
    || !Array.isArray(value.members) || !value.members.length
    || value.members.some(member => typeof member.member_id !== 'string' || !Array.isArray(member.job_ids))) {
    throw Object.assign(new Error('轮次响应格式无效'), { code: 'INVALID_API_RESPONSE' })
  }
  return response
}

export const roundGenerationApi = {
  capabilities: () => api.get('/generate/capabilities').then(response => {
    if (typeof response.data?.round_creation_enabled !== 'boolean') {
      throw Object.assign(new Error('轮次能力响应格式无效'), { code: 'INVALID_API_RESPONSE' })
    }
    return response
  }),
  /** @param {import('../../contracts/generated/contracts').GenerateRoundCreateRequestV1} data */
  create: data => api.post('/generate/rounds', data).then(requireRoundCreation),
}
