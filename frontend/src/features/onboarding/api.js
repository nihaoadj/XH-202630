import { api } from '../../api/client.js'

export const onboardingApi = {
  getQuestions: (learningDirectionId) => api.get('/onboarding/questions', { params: { learning_direction_id: learningDirectionId } }),
  createInitialProfile: (data) => api.post('/onboarding/initial-profile', data),
}
