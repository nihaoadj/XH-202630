import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const currentLearnerId = ref('stu_001')

  function setLearnerId(id) {
    currentLearnerId.value = id
  }

  return { currentLearnerId, setLearnerId }
})
