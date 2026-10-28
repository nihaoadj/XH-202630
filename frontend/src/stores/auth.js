import { defineStore } from 'pinia'
import { ref } from 'vue'

import { authApi } from '../features/auth/api.js'
import { useAppStore } from './app'
import { clearAllDrafts } from '../features/onboarding/onboardingState.js'


export const useAuthStore = defineStore('auth', () => {
  const currentUser = ref(null)
  const initialized = ref(false)

  function syncUser(user) {
    const appStore = useAppStore()
    const previousId = currentUser.value?.user_id || appStore.currentUserId
    if (!user || (previousId && previousId !== user.user_id)) {
      clearAllDrafts()
      if (user) appStore.clearLearnerContext()
    }
    currentUser.value = user || null
    if (user) {
      appStore.setCurrentUserProfile(user)
    } else {
      appStore.clearUserContext()
    }
  }

  async function initialize() {
    if (initialized.value) return currentUser.value
    try {
      const response = await authApi.me()
      syncUser(response.data.user)
    } catch {
      syncUser(null)
    } finally {
      initialized.value = true
    }
    return currentUser.value
  }

  async function register(payload) {
    const response = await authApi.register(payload)
    syncUser(response.data.user)
    initialized.value = true
    return response.data.user
  }

  async function login(payload) {
    const response = await authApi.login(payload)
    syncUser(response.data.user)
    initialized.value = true
    return response.data.user
  }

  async function logout() {
    try {
      await authApi.logout()
    } finally {
      syncUser(null)
      initialized.value = true
    }
  }

  return {
    currentUser,
    initialized,
    initialize,
    setCurrentUser: syncUser,
    register,
    login,
    logout,
  }
})
