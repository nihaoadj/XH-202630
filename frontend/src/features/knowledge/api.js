import { api } from '../../api/client'

export const knowledgeApi = {
  listDomains: () => api.get('/knowledge/domains'),
  listDirections: () => api.get('/knowledge/directions'),
  getInfo: (learningDirectionId) => api.get('/knowledge/info', {
    params: { knowledge_base_id: learningDirectionId },
  }),
  listNodes: (learningDirectionId) => api.get('/skills/nodes', {
    params: { knowledge_base_id: learningDirectionId },
  }),
}
