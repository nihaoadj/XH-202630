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
  const currentLearnerId = ref(localStorage.getItem('last_learner_id') || 'stu_001')
  const currentLearningDirectionId = ref(localStorage.getItem('learning_direction_id') || '')
  const currentLearningDirectionName = ref(localStorage.getItem('learning_direction_name') || '')
  const currentProfile = ref(readJson('current_profile', null))
  const pendingDiagnosticQuestions = ref(readJson('pending_diagnostic_questions', []))
  const diagnosisResult = ref(readJson('diagnosis_result', null))

  function setLearnerId(id) {
    currentLearnerId.value = id
    localStorage.setItem('last_learner_id', id)
  }

  function setLearningDirectionId(id) {
    currentLearningDirectionId.value = id
    localStorage.setItem('learning_direction_id', id)
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
    currentLearnerId,
    currentLearningDirectionId,
    currentLearningDirectionName,
    currentProfile,
    pendingDiagnosticQuestions,
    diagnosisResult,
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
