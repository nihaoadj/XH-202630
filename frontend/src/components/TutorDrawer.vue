<template>
  <transition name="tutor-panel-slide">
    <aside v-show="modelValue" class="tutor-panel" :class="{ 'is-embedded': embedded, 'is-viewport-height': fullHeight }" aria-label="Tutor 辅导面板">
      <header class="tutor-panel-header">
        <div class="tutor-heading">
          <span>TUTOR · SOCRATIC GUIDE</span>
          <strong>{{ title || (contextType === 'question_help' ? '题目提示' : '学习导引') }}</strong>
          <small>提示等级由服务端控制，专业解释只使用当前可信证据。</small>
        </div>
        <el-button class="tutor-close" text circle aria-label="关闭 Tutor" @click="emit('update:modelValue', false)">×</el-button>
      </header>

    <main ref="tutorBodyRef" class="tutor-body">
      <el-alert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false" />
      <div v-if="initializing" class="tutor-loading"><el-icon class="is-loading"><Loading /></el-icon><span>正在恢复 Tutor 会话…</span></div>
      <section v-else-if="!turns.length && !pendingUserMessage" class="tutor-welcome">
        <div class="welcome-intro">
          <span class="welcome-mark">T</span>
          <div>
            <span class="welcome-eyebrow">循序提示</span>
            <strong>从卡住的地方开始</strong>
            <p>我会基于当前资源逐步提示，不直接替你完成答案。</p>
          </div>
        </div>
        <div class="starter-prompts">
          <button type="button" @click="message = '请帮我梳理这部分的关键概念'"><span><b>梳理关键概念</b><small>先建立知识框架</small></span><em>→</em></button>
          <button type="button" @click="message = '请解释这一步为什么这样做'"><span><b>解释关键步骤</b><small>理解当前步骤的原因</small></span><em>→</em></button>
          <button type="button" @click="message = '请先给我一个方向性提示'"><span><b>给我一个提示</b><small>只给下一步方向</small></span><em>→</em></button>
        </div>
      </section>

      <div v-else class="turn-list">
        <article v-for="turn in turns" :key="turn.turn_id" class="turn-card">
          <div class="user-bubble"><span>你</span><p>{{ turn.user_message || userMessageByTurn[turn.turn_id] || '本轮求助' }}</p></div>
          <div class="assistant-bubble">
            <div class="assistant-meta">
              <span>{{ actionLabel(turn.pedagogy_action) }}</span>
              <b title="Tutor 会根据你的追问逐步加深提示">当前：{{ hintLevelLabel(turn.hint_level) }}</b>
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
        <article v-if="pendingUserMessage" class="turn-card pending-turn">
          <div class="user-bubble"><span>你</span><p>{{ pendingUserMessage }}</p></div>
          <div class="assistant-bubble thinking-bubble"><span class="thinking-dots"><i></i><i></i><i></i></span><span>Tutor 正在思考…</span></div>
        </article>
      </div>
    </main>

      <footer class="tutor-composer">
        <div class="composer-label"><span>描述你的困难</span><small><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd><i>+</i><kbd>Enter</kbd> 换行</small></div>
        <div class="composer-editor" :class="{ 'is-disabled': sending || initializing || !sessionId }">
          <el-input
            v-model="message"
            type="textarea"
            :rows="2"
            maxlength="4000"
            show-word-limit
            :disabled="sending || initializing || !sessionId"
            :placeholder="contextType === 'question_help' ? '例如：我理解召回，但不懂为什么还要 rerank' : '告诉 Tutor 你具体卡在哪里'"
            @keydown.enter.exact.prevent="sendTurn"
          />
          <div class="composer-actions">
            <el-button class="composer-send" :loading="sending" :disabled="!canSend" @click="sendTurn"><el-icon><Promotion /></el-icon><span>发送</span></el-button>
          </div>
        </div>
      </footer>
    </aside>
  </transition>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { Loading, Promotion } from '@element-plus/icons-vue'

import { tutorApi } from '../api/tutor'
import { buildTutorStorageKey, mergeTutorTurn } from '../utils/tutorState'
import SourceRefList from './SourceRefList.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  learnerId: { type: String, default: '' },
  resource: { type: Object, default: null },
  batchId: { type: String, default: '' },
  runId: { type: String, default: '' },
  contextType: { type: String, default: 'resource_help' },
  questionId: { type: String, default: '' },
  title: { type: String, default: '' },
  embedded: { type: Boolean, default: false },
  fullHeight: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'turn-saved', 'session-loaded'])

const sessionId = ref('')
const turns = ref([])
const message = ref('')
const initializing = ref(false)
const sending = ref(false)
const errorMessage = ref('')
const pendingUserMessage = ref('')
const tutorBodyRef = ref(null)
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
  batchId: props.contextType === 'question_help' ? props.batchId : '',
  runId: effectiveRunId.value,
  questionId: props.questionId,
}))
const canSend = computed(() => Boolean(sessionId.value && message.value.trim() && !sending.value && !initializing.value))

function actionLabel(action) {
  return { hint: '方向提示', guided_question: '引导提问', scaffold: '结构化拆解', explanation: '证据解释', check_understanding: '理解检查', evidence_insufficient: '证据不足' }[action] || action
}

function hintLevelLabel(level) {
  return { 1: '方向提示', 2: '步骤拆解', 3: '深入解释' }[Number(level)] || '循序提示'
}

function resetLocalState() {
  sessionId.value = ''
  turns.value = []
  message.value = ''
  errorMessage.value = ''
  pendingUserMessage.value = ''
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
  if (!props.modelValue || !props.learnerId || (!resourceId.value && !props.batchId && !effectiveRunId.value)) return
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
      source_type: props.contextType === 'question_help' && props.batchId ? 'batch' : (props.contextType === 'question_help' ? 'run' : 'resource'),
      resource_id: props.contextType === 'resource_help' ? resourceId.value : null,
      run_id: props.contextType === 'question_help' && !props.batchId ? (effectiveRunId.value || null) : null,
      batch_id: props.contextType === 'question_help' && props.batchId ? props.batchId : null,
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

async function scrollToLatestTurn() {
  await nextTick()
  tutorBodyRef.value?.scrollTo({ top: tutorBodyRef.value.scrollHeight, behavior: 'smooth' })
}

async function sendTurn() {
  if (!canSend.value) return
  sending.value = true
  errorMessage.value = ''
  const userMessage = message.value.trim()
  const clientId = clientMessageId()
  pendingUserMessage.value = userMessage
  message.value = ''
  void scrollToLatestTurn()
  try {
    const response = await tutorApi.submitTurn(sessionId.value, { client_message_id: clientId, message: userMessage })
    const turn = { ...response.data, user_message: userMessage }
    userMessageByTurn[turn.turn_id] = userMessage
    turns.value = mergeTutorTurn(turns.value, turn)
    pendingUserMessage.value = ''
    void scrollToLatestTurn()
    emit('turn-saved', turn)
  } catch (error) {
    console.error(error)
    pendingUserMessage.value = ''
    message.value = userMessage
    errorMessage.value = error?.response?.data?.message || 'Tutor 暂时无法回答，请稍后重试'
  } finally {
    sending.value = false
  }
}

watch(
  () => [props.learnerId, resourceId.value, props.batchId, effectiveRunId.value, props.contextType, props.questionId],
  () => {
    resetLocalState()
    if (props.modelValue) ensureSession()
  },
)
watch(() => props.modelValue, (isOpen) => {
  if (isOpen) ensureSession()
})
</script>

<style scoped>
.tutor-panel { position: fixed; z-index: 40; top: 0; right: 0; bottom: 0; display: flex; flex-direction: column; box-sizing: border-box; width: min(460px, 94vw); overflow: hidden; border-left: 1px solid #cce2e1; background: #fbfdff; box-shadow: -14px 0 34px rgba(26, 70, 83, .14); }
.tutor-panel.is-embedded { position: sticky; top: 0; flex: 0 0 460px; width: 460px; height: calc(100dvh - 66px); box-shadow: none; }.tutor-panel.is-embedded.is-viewport-height { height: 100dvh; }
.tutor-panel-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 22px 20px 17px 24px; border-bottom: 1px solid #dbe9e8; background: linear-gradient(140deg, #f4fcfa, #f6f9ff); }.tutor-close { flex: 0 0 auto; width: 32px; height: 32px; margin: 0; border: 1px solid #d7e5e9; border-radius: 9px; color: #52718a; font-size: 23px; line-height: 1; }.tutor-close:hover { border-color: #9ccfc8; background: #e8f4f2; color: #19756a; }
.tutor-panel-slide-enter-active,.tutor-panel-slide-leave-active { transition: transform .24s ease, opacity .24s ease; }.tutor-panel-slide-enter-from,.tutor-panel-slide-leave-to { opacity: 0; transform: translateX(100%); }
.tutor-heading span,.tutor-heading strong,.tutor-heading small { display:block; }.tutor-heading span { color:#23766d; font-size:10px; font-weight:800; letter-spacing:.11em; }.tutor-heading strong { margin-top:6px; color:#17304d; font-size:20px; }.tutor-heading small { margin-top:5px; color:#71839a; font-size:11px; font-weight:500; }
.tutor-body { flex: 1; min-width: 0; min-height: 0; padding: 24px; overflow-x: hidden; overflow-y: auto; background: #fbfdff; }.tutor-loading { display:flex; align-items:center; justify-content:center; gap:9px; min-height:260px; color:#71849b; font-size:13px; }.tutor-welcome { display:grid; gap:20px; width:min(100%, 392px); margin:clamp(12px, 13vh, 100px) auto 0; padding:20px; border:1px solid #d4e7e5; border-radius:16px; background:linear-gradient(145deg,#f2fbf9,#f4f8ff); box-shadow:0 12px 26px rgba(30,96,103,.05); }.welcome-intro { display:grid; grid-template-columns:42px minmax(0,1fr); gap:12px; align-items:start; }.welcome-mark { display:grid; width:42px; height:42px; place-items:center; border-radius:13px; background:linear-gradient(135deg,#238f82,#4c9de0); box-shadow:0 7px 15px rgba(38,132,126,.18); color:#fff; font-size:17px; font-weight:850; }.welcome-eyebrow { display:block; margin-bottom:4px; color:#218174; font-size:10px; font-weight:800; letter-spacing:.08em; }.tutor-welcome strong { color:#1b3b57; font-size:16px; }.tutor-welcome p { margin:5px 0 0; color:#6a8199; font-size:12px; line-height:1.65; }.starter-prompts { display:grid; gap:8px; }.starter-prompts button { display:flex; align-items:center; justify-content:space-between; width:100%; padding:11px 12px; border:1px solid #cfe2e6; border-radius:10px; background:rgba(255,255,255,.86); color:#356078; text-align:left; cursor:pointer; transition:.18s ease; }.starter-prompts button span { display:grid; gap:3px; }.starter-prompts button b { font-size:12px; }.starter-prompts button small { color:#7b91a6; font-size:10px; font-weight:500; }.starter-prompts button em { color:#69a69d; font-size:16px; font-style:normal; transition:transform .18s ease; }.starter-prompts button:hover,.starter-prompts button:focus-visible { border-color:#53a99c; background:#fff; color:#18756e; box-shadow:0 4px 10px rgba(42,129,119,.1); }.starter-prompts button:hover em,.starter-prompts button:focus-visible em { transform:translateX(3px); }.turn-list { display:grid; gap:16px; min-width:0; width:100%; }.turn-card { display:grid; min-width:0; gap:9px; }.user-bubble { display:grid; grid-template-columns:26px minmax(0,1fr); min-width:0; gap:8px; align-items:start; }.user-bubble span { display:grid; width:25px; height:25px; place-items:center; border-radius:8px; background:#e9f0f8; color:#506b89; font-size:10px; font-weight:800; }.user-bubble p { min-width:0; margin:0; padding:10px 12px; overflow-wrap:anywhere; border-radius:4px 12px 12px 12px; background:#f3f6fa; color:#3c5068; font-size:13px; line-height:1.65; }
.assistant-bubble { min-width:0; margin-left:34px; padding:14px; overflow-wrap:anywhere; border:1px solid #d7e8e3; border-radius:12px; background:linear-gradient(140deg,#f6fcfa,#f7faff); }.assistant-meta { display:flex; align-items:center; justify-content:space-between; gap:10px; }.assistant-meta span { color:#197365; font-size:11px; font-weight:800; }.assistant-meta b { padding:4px 7px; border-radius:999px; background:#e8f6f2; color:#25766a; font-size:10px; }.assistant-bubble > p { margin:11px 0 0; color:#263f5a; font-size:14px; line-height:1.75; overflow-wrap:anywhere; white-space:pre-wrap; }.assistant-bubble blockquote { margin:12px 0 0; padding:9px 11px; overflow-wrap:anywhere; border-left:3px solid #43a898; background:#fff; color:#49647d; font-size:12px; line-height:1.6; }.turn-evidence { min-width:0; margin-top:12px; padding-top:11px; border-top:1px solid #dce9e6; }.turn-evidence > strong { display:block; margin-bottom:7px; color:#63798f; font-size:11px; }.thinking-bubble { display:flex; align-items:center; gap:9px; color:#5c7d8d; font-size:12px; font-weight:700; }.thinking-dots { display:flex; gap:4px; }.thinking-dots i { width:6px; height:6px; border-radius:50%; background:#42a99c; animation:tutor-thinking 1s infinite ease-in-out; }.thinking-dots i:nth-child(2) { animation-delay:.14s; }.thinking-dots i:nth-child(3) { animation-delay:.28s; }@keyframes tutor-thinking { 0%,80%,100% { transform:translateY(0); opacity:.35; } 40% { transform:translateY(-3px); opacity:1; } }
.tutor-composer { display:grid; gap:10px; width:100%; padding:15px 24px 18px; border-top:1px solid #dfe9ef; background:#fff; box-shadow:0 -8px 20px rgba(37,72,91,.025); }.composer-label { display:flex; align-items:baseline; justify-content:space-between; gap:12px; padding:0 2px; }.composer-label span { color:#31536d; font-size:12px; font-weight:800; }.composer-label small { display:flex; align-items:center; gap:3px; color:#7890a5; font-size:10px; }.composer-label kbd { padding:1px 4px; border:1px solid #d6e1e8; border-bottom-color:#bdccd6; border-radius:4px; background:#fff; color:#5d7389; font-family:inherit; font-size:9px; font-weight:700; }.composer-label i { color:#9aaabd; font-size:10px; font-style:normal; }.composer-editor { display:grid; grid-template-columns:minmax(0,1fr) 92px; overflow:hidden; border:1px solid #cfdfe9; border-radius:13px; background:linear-gradient(145deg,#fbfdff,#f5fafb); box-shadow:inset 0 1px 0 rgba(255,255,255,.8),0 4px 10px rgba(38,76,99,.035); transition:border-color .18s ease,box-shadow .18s ease,background .18s ease; }.composer-editor:focus-within { border-color:#5ba99d; background:#fff; box-shadow:0 0 0 3px rgba(63,159,147,.12),0 6px 14px rgba(38,102,101,.06); }.composer-editor.is-disabled { opacity:.72; }.composer-editor :deep(.el-textarea) { min-width:0; }.composer-editor :deep(.el-textarea__inner) { min-height:76px !important; padding:12px 13px 22px; border:0; border-radius:0; background:transparent; color:#28445f; line-height:1.55; box-shadow:none !important; resize:none; }.composer-editor :deep(.el-input__count) { right:12px; bottom:6px; padding:0; background:transparent; color:#94a1af; font-size:10px; }.composer-actions { display:flex; align-items:center; justify-content:center; padding:9px; border-left:1px solid #dce9e8; background:linear-gradient(160deg,#edf9f7,#eaf4ff); }.composer-send { width:100%; height:100% !important; min-height:58px; margin:0; border:0; border-radius:10px; background:linear-gradient(145deg,#197c71,#2a9b8d); box-shadow:0 7px 14px rgba(30,126,114,.2); color:#fff; font-weight:800; letter-spacing:.02em; transition:transform .18s ease,box-shadow .18s ease,background .18s ease; }.composer-send :deep(.el-icon) { margin-right:4px; font-size:15px; }.composer-send:hover,.composer-send:focus-visible { background:linear-gradient(145deg,#126b62,#238f82); box-shadow:0 9px 18px rgba(30,126,114,.28); color:#fff; transform:translateY(-1px); }.composer-send.is-disabled,.composer-send.is-disabled:hover { background:#a9cfc9; box-shadow:none; transform:none; }
@media (max-width: 1100px) { .tutor-panel.is-embedded { position: fixed; top: 0; right: 0; bottom: 0; flex: initial; width: min(460px, 94vw); height: auto; box-shadow: -14px 0 34px rgba(26, 70, 83, .14); } }
@media (max-width: 560px) { .tutor-panel-header { padding: 18px 16px 14px; }.tutor-body { padding: 14px 16px; }.tutor-welcome { margin-top:18px; padding:16px; }.tutor-composer { padding: 12px 16px 16px; }.composer-editor { grid-template-columns:minmax(0,1fr) 82px; }.composer-actions { padding:7px; }.composer-send { min-height:56px; font-size:12px; } }
</style>
