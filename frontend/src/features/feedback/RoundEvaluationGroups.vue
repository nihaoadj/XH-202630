<template>
  <div class="round-question-groups">
    <section v-for="group in session.groups" :key="group.member_id" class="round-question-group" :aria-label="`${roundRoleLabel(group.role)}测评`">
      <header><h3>{{ roundRoleLabel(group.role) }}测评 · {{ nodeName(group.node_id) }}</h3><span>{{ answered(group) }} / {{ group.questions.length }} 已作答</span></header>
      <article v-for="(question, index) in group.questions" :key="question.question_id" class="round-question">
        <div class="question-heading"><strong>{{ index + 1 }}. {{ question.question }}</strong><el-button text type="primary" @click="$emit('hint', question)">需要提示</el-button></div>
        <el-radio-group v-if="question.question_type === 'single_choice' && question.options?.length" :model-value="answers[question.question_id]" :disabled="locked" class="round-options" @update:model-value="setAnswer(question.question_id, $event)">
          <el-radio v-for="option in question.options" :key="option" :label="option" :value="option">{{ option }}</el-radio>
        </el-radio-group>
        <el-checkbox-group v-else-if="question.question_type === 'multiple_choice' && question.options?.length" :model-value="answers[question.question_id]" :disabled="locked" class="round-options" @update:model-value="setAnswer(question.question_id, $event)">
          <el-checkbox v-for="option in question.options" :key="option" :label="option">{{ option }}</el-checkbox>
        </el-checkbox-group>
        <el-input v-else :model-value="answers[question.question_id]" :disabled="locked" type="textarea" :rows="3" :aria-label="`${nodeName(group.node_id)} 第 ${index + 1} 题答案`" @update:model-value="setAnswer(question.question_id, $event)" />
      </article>
    </section>
  </div>
</template>
<script setup>
import { hasRoundAnswer } from './roundEvaluationState.js'
import { roundRoleLabel } from '../generation/roundWorkspace.js'
const props = defineProps({ session: { type: Object, required: true }, answers: { type: Object, required: true }, members: { type: Array, default: () => [] }, locked: Boolean })
const emit = defineEmits(['answer', 'hint'])
const nodeName = id => props.members.find(member => member.node_id === id)?.node_name || id
const answered = group => group.questions.filter(question => hasRoundAnswer(props.answers[question.question_id])).length
function setAnswer(id, value) { emit('answer', { id, value }) }
</script>
<style scoped>
.round-question-group { border:1px solid #d9e4eb; border-radius:10px; padding:18px; margin-bottom:18px; background:#fff; color:#173349; }
header { display:flex; flex-wrap:wrap; align-items:center; gap:12px; justify-content:space-between; border-bottom:1px solid #d9e4eb; padding-bottom:12px; }h3 { margin:0; font-size:17px; }header span { font-size:13px; }
.round-question { padding:18px 0; border-bottom:1px solid #edf1f4; }.round-question:last-child { border:0; padding-bottom:0; }.question-heading { display:flex; gap:12px; justify-content:space-between; align-items:flex-start; line-height:1.7; }.question-heading strong { overflow-wrap:anywhere; }
.round-options { display:grid; gap:8px; margin-top:12px; }.round-options :deep(.el-radio),.round-options :deep(.el-checkbox) { min-height:44px; height:auto; margin:0; white-space:normal; }.round-options :deep(.el-radio__label),.round-options :deep(.el-checkbox__label) { white-space:normal; line-height:1.6; }
</style>
