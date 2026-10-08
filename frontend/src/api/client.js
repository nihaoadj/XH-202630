import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const isAuthPage = ['/login', '/register'].includes(window.location.pathname)
    const isAuthRequest = String(error?.config?.url || '').startsWith('/auth/')
    if (error?.response?.status === 401 && !isAuthPage && !isAuthRequest) {
      window.location.assign(`/login?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`)
    }
    return Promise.reject(error)
  },
)
