<template>
  <div class="round-question-groups">
    <section v-for="group in session.groups" :key="group.member_id" class="round-question-group" :aria-label="`${roundRoleLabel(group.role)}测评`">
      <header v-if="session.groups.length > 1" class="round-group-heading"><h3>{{ roundRoleLabel(group.role) }}测评 · {{ nodeName(group.node_id) }}</h3><span>{{ answered(group) }} / {{ group.questions.length }} 已作答</span></header>
      <FeedbackQuestions :questions="group.questions.map(question => ({ ...question, knowledge_point: question.knowledge_point || nodeName(group.node_id) }))" :answers="answers" :locked="locked" :aria-prefix="nodeName(group.node_id)" @answer="$emit('answer', $event)" />
    </section>
  </div>
</template>
<script setup>
import FeedbackQuestions from './FeedbackQuestions.vue'
import { hasRoundAnswer } from './roundEvaluationState.js'
import { roundRoleLabel } from '../generation/roundWorkspace.js'
const props = defineProps({ session: { type: Object, required: true }, answers: { type: Object, required: true }, members: { type: Array, default: () => [] }, locked: Boolean })
defineEmits(['answer'])
const nodeName = id => props.members.find(member => member.node_id === id)?.node_name || id
const answered = group => group.questions.filter(question => hasRoundAnswer(props.answers[question.question_id])).length
</script>
<style scoped>
.round-question-group { min-width:0; margin:0; border:0; border-radius:0; box-shadow:none; background:transparent; }
.round-group-heading { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:10px; padding:0 0 14px; border-bottom:1px solid var(--feedback-line); color:var(--feedback-muted); }
.round-group-heading h3 { margin:0; font-size:15px; color:var(--feedback-ink); }
.round-group-heading span { font-size:12px; }
.round-question { margin:0; }
.round-options { width:100%; }
:deep(.el-textarea__inner) { resize:none; border-radius:10px; background:linear-gradient(145deg,#fff,#f7faff); box-shadow:inset 0 0 0 1px #bed0e6,var(--feedback-control-shadow); }
</style>
