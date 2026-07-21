import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

export const learnerApi = {
  createProfile: (data) => api.post('/learner/profile', data),
  getProfile: (id) => api.get(`/learner/profile/${id}`),
}

export const generateApi = {
  generate: (data) => api.post('/generate/', data),
}

export const feedbackApi = {
  submit: (data) => api.post('/feedback/', data),
}

export const reportApi = {
  get: (id) => api.get(`/report/${id}`),
}
