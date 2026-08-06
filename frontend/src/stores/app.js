import { defineStore } from 'pinia'
import { ref } from 'vue'

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch {
    return fallback
  }
}

export const useAppStore = defineStore('app', () => {
  const currentUserId = ref(localStorage.getItem('current_user_id') || '')
  const currentUserProfile = ref(readJson('current_user_profile', null))
  const currentLearnerId = ref(localStorage.getItem('last_learner_id') || '')
  const currentLearningDirectionId = ref(localStorage.getItem('learning_direction_id') || '')
  const currentLearningDirectionName = ref(localStorage.getItem('learning_direction_name') || '')
  const currentProfile = ref(readJson('current_profile', null))
  const pendingDiagnosticQuestions = ref(readJson('pending_diagnostic_questions', []))
  const diagnosisResult = ref(readJson('diagnosis_result', null))

  function setUserId(id) {
    currentUserId.value = id || ''
    localStorage.setItem('current_user_id', currentUserId.value)
  }

  function setCurrentUserProfile(profile) {
    currentUserProfile.value = profile || null
    if (profile?.user_id) {
      setUserId(profile.user_id)
    }
    localStorage.setItem('current_user_profile', JSON.stringify(currentUserProfile.value))
  }

  function setLearnerId(id) {
    currentLearnerId.value = id || ''
    localStorage.setItem('last_learner_id', currentLearnerId.value)
  }

  function setLearningDirectionId(id) {
    currentLearningDirectionId.value = id || ''
    localStorage.setItem('learning_direction_id', currentLearningDirectionId.value)
  }

  function setLearningDirectionName(name) {
    currentLearningDirectionName.value = name || ''
    localStorage.setItem('learning_direction_name', currentLearningDirectionName.value)
  }

  function setCurrentProfile(profile) {
    currentProfile.value = profile || null
    localStorage.setItem('current_profile', JSON.stringify(currentProfile.value))
  }

  function setPendingDiagnosis(questions) {
    pendingDiagnosticQuestions.value = questions || []
    localStorage.setItem('pending_diagnostic_questions', JSON.stringify(pendingDiagnosticQuestions.value))
  }

  function clearPendingDiagnosis() {
    pendingDiagnosticQuestions.value = []
    localStorage.removeItem('pending_diagnostic_questions')
  }

  function setDiagnosisResult(result) {
    diagnosisResult.value = result || null
    localStorage.setItem('diagnosis_result', JSON.stringify(diagnosisResult.value))
  }

  function resumeProfile(profile, directionId = '', directionName = '') {
    setLearnerId(profile?.learner_id || currentLearnerId.value)
    setLearningDirectionId(directionId || profile?.knowledge_base_id || '')
    setLearningDirectionName(directionName)
    setCurrentProfile(profile)
  }

  return {
    currentUserId,
    currentUserProfile,
    currentLearnerId,
    currentLearningDirectionId,
    currentLearningDirectionName,
    currentProfile,
    pendingDiagnosticQuestions,
    diagnosisResult,
    setUserId,
    setCurrentUserProfile,
    setLearnerId,
    setLearningDirectionId,
    setLearningDirectionName,
    setCurrentProfile,
    setPendingDiagnosis,
    clearPendingDiagnosis,
    setDiagnosisResult,
    resumeProfile,
  }
})
