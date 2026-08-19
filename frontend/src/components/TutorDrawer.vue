<template>
  <el-drawer
    :model-value="modelValue"
    size="min(520px, 94vw)"
    class="tutor-drawer"
    :destroy-on-close="false"
    @update:model-value="emit('update:modelValue', $event)"
    @open="ensureSession"
  >
    <template #header>
      <div class="tutor-heading">
        <span>TUTOR · SOCRATIC GUIDE</span>
        <strong>{{ title || (contextType === 'question_help' ? '题目提示' : '学习导引') }}</strong>
        <small>提示等级由服务端控制，专业解释只使用当前可信证据。</small>
      </div>
    </template>

    <div class="tutor-body">
      <el-alert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false" />
      <div v-if="initializing" class="tutor-loading"><el-icon class="is-loading"><Loading /></el-icon><span>正在恢复 Tutor 会话…</span></div>
      <el-empty v-else-if="!turns.length" :image-size="68" description="描述你卡住的地方，Tutor 会先给方向性提示。" />

      <div v-else class="turn-list">
        <article v-for="turn in turns" :key="turn.turn_id" class="turn-card">
          <div class="user-bubble"><span>你</span><p>{{ turn.user_message || userMessageByTurn[turn.turn_id] || '本轮求助' }}</p></div>
          <div class="assistant-bubble">
            <div class="assistant-meta">
              <span>{{ actionLabel(turn.pedagogy_action) }}</span>
              <b>提示 {{ turn.hint_level }} / 3</b>
            </div>
            <p>{{ turn.message }}</p>
            <blockquote v-if="turn.follow_up_question">{{ turn.follow_up_question }}</blockquote>
            <div v-if="turn.source_refs?.length" class="turn-evidence">
              <strong>依据</strong>
              <SourceRefList :refs="turn.source_refs" compact />
            </div>
            <el-alert v-if="turn.grounding_status === 'evidence_insufficient'" type="warning" title="本轮未调用自由知识回答" :closable="false" show-icon />
          </div>
        </article>
      </div>
    </div>

    <template #footer>
      <div class="tutor-composer">
        <el-input
          v-model="message"
          type="textarea"
          :rows="3"
          maxlength="4000"
          show-word-limit
          :disabled="sending || initializing || !sessionId"
          :placeholder="contextType === 'question_help' ? '例如：我理解召回，但不懂为什么还要 rerank' : '告诉 Tutor 你具体卡在哪里'"
          @keydown.ctrl.enter.prevent="sendTurn"
        />
        <div class="composer-actions">
          <small>Ctrl + Enter 发送 · 不会直接修改画像或学习路径</small>
          <el-button type="primary" :loading="sending" :disabled="!canSend" @click="sendTurn">发送</el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'

import { tutorApi } from '../api/tutor'
import { buildTutorStorageKey, mergeTutorTurn } from '../utils/tutorState'
import SourceRefList from './SourceRefList.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  learnerId: { type: String, default: '' },
  resource: { type: Object, default: null },
  runId: { type: String, default: '' },
  contextType: { type: String, default: 'resource_help' },
  questionId: { type: String, default: '' },
  title: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'turn-saved', 'session-loaded'])

const sessionId = ref('')
const turns = ref([])
const message = ref('')
const initializing = ref(false)
const sending = ref(false)
const errorMessage = ref('')
const userMessageByTurn = reactive({})

const resourceId = computed(() => props.resource?.resource_id || '')
const effectiveRunId = computed(() => (
  props.contextType === 'question_help'
    ? (props.runId || props.resource?.run_id || '')
    : (props.resource?.run_id || '')
))
const storageKey = computed(() => buildTutorStorageKey({
  learnerId: props.learnerId,
  contextType: props.contextType,
  resourceId: props.contextType === 'resource_help' ? resourceId.value : '',
  runId: effectiveRunId.value,
  questionId: props.questionId,
}))
const canSend = computed(() => Boolean(sessionId.value && message.value.trim() && !sending.value && !initializing.value))

function actionLabel(action) {
  return { hint: '方向提示', guided_question: '引导提问', scaffold: '结构化拆解', explanation: '证据解释', check_understanding: '理解检查', evidence_insufficient: '证据不足' }[action] || action
}

function resetLocalState() {
  sessionId.value = ''
  turns.value = []
  message.value = ''
  errorMessage.value = ''
  Object.keys(userMessageByTurn).forEach((key) => delete userMessageByTurn[key])
}

async function restore(session) {
  sessionId.value = session.session_id
  const response = await tutorApi.getSession(session.session_id)
  turns.value = response.data.turns || []
  emit('session-loaded', { session: response.data.session, turns: turns.value })
  return response.data.session
}

async function ensureSession() {
  if (!props.modelValue || !props.learnerId || (!resourceId.value && !effectiveRunId.value)) return
  if (props.contextType === 'question_help' && !props.questionId) {
    errorMessage.value = '当前题目缺少可恢复的 Tutor 上下文'
    return
  }
  initializing.value = true
  errorMessage.value = ''
  try {
    const storedId = localStorage.getItem(storageKey.value)
    if (storedId) {
      try {
        const restored = await restore({ session_id: storedId })
        if (restored.status === 'active') return
        localStorage.removeItem(storageKey.value)
        resetLocalState()
      } catch (error) {
        if (error?.response?.status !== 404) throw error
        localStorage.removeItem(storageKey.value)
      }
    }
    const payload = {
      learner_id: props.learnerId,
      source_type: props.contextType === 'question_help' ? 'run' : 'resource',
      resource_id: props.contextType === 'resource_help' ? resourceId.value : null,
      run_id: props.contextType === 'question_help' ? (effectiveRunId.value || null) : null,
      context_type: props.contextType,
      question_id: props.contextType === 'question_help' ? props.questionId : null,
    }
    const created = await tutorApi.createSession(payload)
    sessionId.value = created.data.session_id
    turns.value = []
    localStorage.setItem(storageKey.value, sessionId.value)
    emit('session-loaded', { session: created.data, turns: [] })
  } catch (error) {
    console.error(error)
    errorMessage.value = error?.response?.data?.message || 'Tutor 会话加载失败'
  } finally {
    initializing.value = false
  }
}

function clientMessageId() {
  return globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function sendTurn() {
  if (!canSend.value) return
  sending.value = true
  errorMessage.value = ''
  const userMessage = message.value.trim()
  const clientId = clientMessageId()
  try {
    const response = await tutorApi.submitTurn(sessionId.value, { client_message_id: clientId, message: userMessage })
    const turn = { ...response.data, user_message: userMessage }
    userMessageByTurn[turn.turn_id] = userMessage
    turns.value = mergeTutorTurn(turns.value, turn)
    message.value = ''
    emit('turn-saved', turn)
  } catch (error) {
    console.error(error)
    errorMessage.value = error?.response?.data?.message || 'Tutor 暂时无法回答，请稍后重试'
  } finally {
    sending.value = false
  }
}

watch(
  () => [props.learnerId, resourceId.value, effectiveRunId.value, props.contextType, props.questionId],
  () => {
    resetLocalState()
    if (props.modelValue) ensureSession()
  },
)
</script>

<style scoped>
.tutor-heading span,.tutor-heading strong,.tutor-heading small { display:block; }.tutor-heading span { color:#23766d; font-size:10px; font-weight:800; letter-spacing:.11em; }.tutor-heading strong { margin-top:6px; color:#17304d; font-size:20px; }.tutor-heading small { margin-top:5px; color:#71839a; font-size:11px; font-weight:500; }
.tutor-body { min-height:360px; }.tutor-loading { display:flex; align-items:center; justify-content:center; gap:9px; min-height:260px; color:#71849b; font-size:13px; }.turn-list { display:grid; gap:16px; }.turn-card { display:grid; gap:9px; }.user-bubble { display:grid; grid-template-columns:26px minmax(0,1fr); gap:8px; align-items:start; }.user-bubble span { display:grid; width:25px; height:25px; place-items:center; border-radius:8px; background:#e9f0f8; color:#506b89; font-size:10px; font-weight:800; }.user-bubble p { margin:0; padding:10px 12px; border-radius:4px 12px 12px 12px; background:#f3f6fa; color:#3c5068; font-size:13px; line-height:1.65; }
.assistant-bubble { margin-left:34px; padding:14px; border:1px solid #d7e8e3; border-radius:12px; background:linear-gradient(140deg,#f6fcfa,#f7faff); }.assistant-meta { display:flex; align-items:center; justify-content:space-between; gap:10px; }.assistant-meta span { color:#197365; font-size:11px; font-weight:800; }.assistant-meta b { padding:4px 7px; border-radius:999px; background:#e8f6f2; color:#25766a; font-size:10px; }.assistant-bubble > p { margin:11px 0 0; color:#263f5a; font-size:14px; line-height:1.75; white-space:pre-wrap; }.assistant-bubble blockquote { margin:12px 0 0; padding:9px 11px; border-left:3px solid #43a898; background:#fff; color:#49647d; font-size:12px; line-height:1.6; }.turn-evidence { margin-top:12px; padding-top:11px; border-top:1px solid #dce9e6; }.turn-evidence > strong { display:block; margin-bottom:7px; color:#63798f; font-size:11px; }
.tutor-composer { display:grid; gap:9px; width:100%; }.composer-actions { display:flex; align-items:center; justify-content:space-between; gap:12px; }.composer-actions small { color:#8593a5; font-size:10px; }.composer-actions :deep(.el-button) { min-width:86px; font-weight:700; }
</style>
