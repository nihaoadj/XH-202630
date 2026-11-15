<template>
        <div class="question-list">
          <article v-for="(question, index) in questions" :key="question.question_id" class="question-card">
            <div class="question-topline">
              <span class="question-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <div class="question-tools">
                <el-tag class="question-type-tag" size="small" effect="plain">{{ questionTypeLabel(question.question_type) }}</el-tag>
                <el-tag class="question-knowledge-tag" size="small" effect="plain">{{ question.knowledge_point || '综合能力' }}</el-tag>
              </div>
            </div>
            <strong>{{ question.question }}</strong>

            <el-radio-group v-if="question.question_type === 'single_choice' && question.options?.length" :model-value="answers[question.question_id]" :disabled="locked" @update:model-value="answer(question.question_id, $event)" class="answer-options">
              <el-radio v-for="option in question.options" :key="option" :label="option" :value="option">{{ option }}</el-radio>
            </el-radio-group>
            <el-checkbox-group v-else-if="question.question_type === 'multiple_choice' && question.options?.length" :model-value="answers[question.question_id]" :disabled="locked" @update:model-value="answer(question.question_id, $event)" class="answer-options">
              <el-checkbox v-for="option in question.options" :key="option" :label="option">{{ option }}</el-checkbox>
            </el-checkbox-group>
            <el-input v-else :model-value="answers[question.question_id]" :disabled="locked" @update:model-value="answer(question.question_id, $event)" type="textarea" :rows="3" resize="none" :aria-label="`${ariaPrefix} 第 ${index + 1} 题答案`" placeholder="写下你的答案或思路" />
          </article>
        </div>
</template>
<script setup>
defineProps({ questions: { type: Array, required: true }, answers: { type: Object, required: true }, locked: Boolean, ariaPrefix: { type: String, default: '测评' }, questionTypeLabel: { type: Function, default: type => ({ single_choice: '单选题', multiple_choice: '多选题', short_answer: '问答题' })[type] || '问答题' } })
const emit = defineEmits(['answer'])
function answer(id, value) { emit('answer', { id, value }) }
</script>
