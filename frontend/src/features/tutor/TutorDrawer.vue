<template>
  <transition name="tutor-panel-slide">
    <aside v-show="modelValue" class="tutor-panel" :class="{ 'is-embedded': embedded, 'is-viewport-height': fullHeight }" aria-label="Tutor 辅导面板">
      <header class="tutor-panel-header">
        <span class="tutor-header-icon" aria-hidden="true">
          <TutorMark class="tutor-symbol" />
        </span>
        <div class="tutor-heading">
          <strong>{{ title || (contextType === 'question_help' ? '题目提示' : '学习导引') }}</strong>
          <small>围绕当前材料，一步步找到思路。</small>
        </div>
        <el-button class="tutor-close" text circle aria-label="关闭 Tutor" @click="emit('update:modelValue', false)">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>
        </el-button>
      </header>

    <main ref="tutorBodyRef" class="tutor-body">
      <el-alert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false" />
      <div v-if="initializing" class="tutor-loading"><el-icon class="is-loading"><Loading /></el-icon><span>正在恢复 Tutor 会话…</span></div>
      <section v-else-if="!turns.length && !pendingUserMessage" class="tutor-welcome">
        <div class="welcome-intro">
          <strong>哪里卡住了？</strong>
          <p>可以直接提问，也可以从一个提示开始。</p>
        </div>
        <div class="starter-prompts">
          <button v-for="prompt in starterPrompts" :key="prompt.label" type="button" @click="message = prompt.message">
            <component :is="prompt.icon" class="starter-icon tutor-symbol" aria-hidden="true" />
            <b>{{ prompt.label }}</b>
            <ArrowRight class="starter-arrow tutor-symbol" aria-hidden="true" />
          </button>
        </div>
      </section>

      <div v-else class="turn-list">
        <article v-for="turn in turns" :key="turn.turn_id" class="turn-card">
          <TutorUserMessage :text="turn.user_message || userMessageByTurn[turn.turn_id] || '本轮求助'" />
          <div class="assistant-bubble">
            <div class="assistant-meta">
              <span class="assistant-identity"><span class="assistant-avatar" aria-hidden="true"><TutorMark class="tutor-symbol" /></span><strong>Tutor</strong></span>
              <span v-if="actionLabel(turn.pedagogy_action) !== hintLevelLabel(turn.hint_level)" class="assistant-action">{{ actionLabel(turn.pedagogy_action) }}</span>
              <b title="Tutor 会根据你的追问逐步加深提示">{{ hintLevelLabel(turn.hint_level) }}</b>
            </div>
            <p>{{ turn.message }}</p>
            <blockquote v-if="turn.follow_up_question"><span>下一步想一想</span><p>{{ turn.follow_up_question }}</p></blockquote>
            <details v-if="turn.source_refs?.length" class="turn-evidence">
              <summary>查看参考来源</summary>
              <SourceRefList :refs="turn.source_refs" compact />
            </details>
            <el-alert v-if="turn.grounding_status === 'evidence_insufficient'" type="warning" title="本轮未调用自由知识回答" :closable="false" show-icon />
          </div>
        </article>
        <article v-if="pendingUserMessage" class="turn-card pending-turn">
          <TutorUserMessage :text="pendingUserMessage" />
          <div class="assistant-bubble thinking-bubble" role="status"><span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span><span>Tutor 正在思考…</span></div>
        </article>
      </div>
    </main>

      <footer class="tutor-composer">
        <div class="composer-editor" :class="{ 'is-disabled': sending || initializing || !sessionId, 'has-overflow': composerOverflow }">
          <div v-if="quotedText" class="quoted-context">
            <Link class="quote-icon tutor-symbol" aria-hidden="true" />
            <div><span>已引用材料</span><p>{{ quotedText }}</p></div>
            <button type="button" aria-label="移除引用内容" @click="emit('clear-quoted-text')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg></button>
          </div>
          <el-input
            ref="composerInput"
            v-model="message"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 4 }"
            maxlength="4000"
            aria-label="描述你的困难"
            :disabled="sending || initializing || !sessionId"
            :placeholder="contextType === 'question_help' ? '描述这道题让你困惑的地方…' : '说说你卡住的地方…'"
            @keydown.enter.exact.prevent="sendTurn"
          />
          <div class="composer-actions">
            <el-button class="composer-send" aria-label="发送" title="发送" :loading="sending" :disabled="!canSend" @click="sendTurn"><svg v-if="!sending" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6" /></svg></el-button>
          </div>
        </div>
        <small class="composer-label composer-shortcuts"><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd> + <kbd>Enter</kbd> 换行</small>
      </footer>
    </aside>
  </transition>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ArrowRight, Compass, Connection, Link, Loading, Reading } from '@element-plus/icons-vue'

import { tutorApi } from './api'
import { buildTutorStorageKey, mergeTutorTurn } from '../../utils/tutorState'
import SourceRefList from '../learning-documents/SourceRefList.vue'
import TutorUserMessage from './TutorUserMessage.vue'
import TutorMark from './TutorMark.vue'

const starterPrompts = [
  { label: '梳理关键概念', icon: Reading, message: '请帮我梳理这部分的关键概念' },
  { label: '解释关键步骤', icon: Connection, message: '请解释这一步为什么这样做' },
  { label: '给我一个提示', icon: Compass, message: '请先给我一个方向性提示' },
]

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
  quotedText: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'turn-saved', 'session-loaded', 'clear-quoted-text'])

const sessionId = ref('')
const turns = ref([])
const message = ref('')
const composerInput = ref(null)
const composerOverflow = ref(false)
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

watch(() => composerInput.value?.textarea, (textarea, _, onCleanup) => {
  if (!textarea) return
  const observer = new ResizeObserver(() => {
    composerOverflow.value = textarea.clientHeight > 0 && textarea.scrollHeight > textarea.clientHeight + 1
  })
  observer.observe(textarea)
  onCleanup(() => observer.disconnect())
}, { flush: 'post' })

watch(message, async () => {
  await nextTick()
  const textarea = composerInput.value?.textarea
  composerOverflow.value = Boolean(textarea?.clientHeight && textarea.scrollHeight > textarea.clientHeight + 1)
}, { flush: 'post' })

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
  const question = message.value.trim()
  const userMessage = props.quotedText
    ? `引用材料：\n“${props.quotedText}”\n\n我的问题：\n${question}`
    : question
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
    if (props.quotedText) emit('clear-quoted-text')
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
}, { immediate: true })
</script>

<style scoped>
.tutor-panel {
  --tutor-ink: #203549;
  --tutor-navy: #172c45;
  --tutor-muted: #596b7d;
  --tutor-line: #dce4eb;
  --tutor-soft: #f2f7fa;
  --tutor-accent: #126978;
  --tutor-focus: #16758a;
  --tutor-paper: #fff;
  --tutor-detail-ink: #35649a;
  --tutor-detail-soft: #edf5ff;
  --tutor-glass-edge: linear-gradient(145deg, #e4effb, #adc5df 48%, #8ba9cb);
  --tutor-glass-shadow: inset 0 2px 1px rgb(255 255 255 / 95%), inset 1px 0 0 rgb(255 255 255 / 80%), inset 0 -1px 1px rgb(112 152 199 / 22%), 0 2px 4px rgb(40 80 128 / 14%), 0 8px 16px -5px rgb(40 80 128 / 22%), 0 16px 28px -12px rgb(40 80 128 / 20%);
  position: fixed;
  z-index: 40;
  inset: 0 0 0 auto;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: min(460px, 94vw);
  overflow: hidden;
  border-left: 1px solid var(--tutor-line);
  background: var(--tutor-paper);
  color: var(--tutor-ink);
  box-shadow: -12px 0 36px rgb(23 44 69 / 10%);
}
.tutor-panel.is-embedded { position: sticky; top: 0; flex: 0 0 460px; width: 460px; height: calc(100dvh - 66px); box-shadow: none; }
.tutor-panel.is-embedded.is-viewport-height { height: 100dvh; }
.tutor-panel-header { display: flex; flex-shrink: 0; align-items: center; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--tutor-line); background: #fafcfd; }
.tutor-header-icon {
  display: grid;
  flex: 0 0 40px;
  height: 40px;
  place-items: center;
  border: 1px solid #b4cdeb;
  border-radius: 12px;
  background: linear-gradient(145deg, #fff, #e2edfc);
  color: #18586c;
  box-shadow: inset 0 1px 0 #fff, 0 2px 5px rgb(23 44 69 / 9%);
}
.tutor-heading { flex: 1; min-width: 0; }
.tutor-heading > strong, .tutor-heading > small { display: block; overflow-wrap: anywhere; }
.tutor-heading > strong { color: var(--tutor-navy); font-size: 16px; font-weight: 650; line-height: 1.45; }
.tutor-heading > small { margin-top: 4px; color: var(--tutor-muted); font-size: 12px; line-height: 1.65; }
.tutor-close { flex: 0 0 auto; width: 36px; height: 36px; margin: 0; padding: 8px; border: 1px solid transparent; border-radius: 10px; color: var(--tutor-muted); }
.tutor-close:hover { border-color: var(--tutor-line); background: var(--tutor-soft); color: var(--tutor-ink); }
.tutor-panel svg { flex-shrink: 0; width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.tutor-panel .tutor-symbol { fill: currentColor; stroke: none; }
.tutor-header-icon .tutor-symbol { width: 23px; height: 23px; }
.tutor-panel :is(button, textarea):focus-visible { outline: 3px solid var(--tutor-focus); outline-offset: 3px; }
.tutor-panel-slide-enter-active, .tutor-panel-slide-leave-active { transition: transform .22s ease, opacity .22s ease; }
.tutor-panel-slide-enter-from, .tutor-panel-slide-leave-to { opacity: 0; transform: translateX(100%); }
.tutor-body { flex: 1; min-width: 0; min-height: 0; padding: 24px; overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; background: #fafbfc; }
.tutor-loading { display: flex; align-items: center; justify-content: center; gap: 10px; min-height: 160px; color: var(--tutor-muted); font-size: 13px; }
.tutor-welcome { display: grid; gap: 20px; width: min(100%, 352px); margin: clamp(16px, 7vh, 62px) auto 24px; }
.tutor-welcome strong { color: var(--tutor-navy); font-size: 21px; font-weight: 650; line-height: 1.5; }
.tutor-welcome p { margin: 8px 0 0; color: var(--tutor-muted); font-size: 13px; line-height: 1.75; }
.starter-prompts { display: grid; gap: 8px; }
.starter-prompts button { display: flex; min-width: 0; min-height: 46px; align-items: center; gap: 10px; width: 100%; padding: 8px 12px; border: 1px solid var(--tutor-line); border-radius: 10px; background: var(--tutor-paper); color: var(--tutor-ink); text-align: left; cursor: pointer; transition: border-color .16s ease, background .16s ease; }
.starter-prompts button b { font-size: 13px; font-weight: 600; line-height: 1.5; }
.starter-icon { color: var(--tutor-accent); }
.starter-arrow { margin-inline-start: auto; color: var(--tutor-muted); }
.starter-prompts button:hover { border-color: #8bb8b8; background: #f6faf9; }
.turn-list { display: grid; gap: 30px; min-width: 0; width: 100%; }
.turn-card { display: grid; min-width: 0; gap: 18px; }
.assistant-bubble {
  min-width: 0;
  padding: 14px;
  border: 0;
  background: transparent;
  overflow-wrap: anywhere;
}
.assistant-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; color: var(--tutor-muted); font-size: 12px; line-height: 1.5; }
.assistant-identity { display: inline-flex; align-items: center; gap: 8px; margin-right: 2px; }
.assistant-avatar { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 10px; background: linear-gradient(145deg, #f7faff, #dce9fb); color: var(--tutor-accent); box-shadow: inset 0 1px 0 #fff, inset 0 0 0 1px rgb(153 184 224 / 28%); }
.assistant-identity strong { color: var(--tutor-navy); font-size: 13px; font-weight: 650; }
.assistant-meta b { margin-left: auto; padding: 3px 8px; border-radius: 99px; background: var(--tutor-detail-soft); color: var(--tutor-detail-ink); font-size: 11px; font-weight: 600; }
.assistant-bubble > p { margin: 12px 0 0; color: var(--tutor-ink); font-size: 14px; line-height: 1.8; overflow-wrap: anywhere; white-space: pre-wrap; }
.assistant-bubble blockquote {
  margin: 14px 0 0;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  background:
    linear-gradient(145deg, #fff 0%, #f5faff 38%, #e4effd 100%) padding-box,
    linear-gradient(145deg, #e7f2ff, #b5ceeb 52%, #8eafd5) border-box;
  box-shadow:
    inset 0 2px 1px rgb(255 255 255 / 95%),
    inset 1px 0 0 rgb(255 255 255 / 80%),
    inset 0 -1px 1px rgb(112 152 199 / 22%),
    0 2px 4px rgb(40 80 128 / 14%),
    0 8px 16px -5px rgb(40 80 128 / 22%),
    0 16px 28px -12px rgb(40 80 128 / 20%);
  color: var(--tutor-ink);
  font-size: 13px;
  line-height: 1.65;
}
.assistant-bubble blockquote span { color: var(--tutor-detail-ink); font-size: 12px; font-weight: 650; }
.assistant-bubble blockquote p { margin: 4px 0 0; white-space: pre-wrap; }
.turn-evidence { min-width: 0; margin-top: 18px; padding-top: 13px; border-top: 1px solid var(--tutor-line); }
.turn-evidence > summary { cursor: pointer; color: var(--tutor-muted); font-size: 12px; font-weight: 600; }
.turn-evidence[open] > summary { margin-bottom: 8px; }
.turn-evidence > summary:focus-visible { outline: 2px solid var(--tutor-ink); outline-offset: 4px; }
.turn-evidence :deep(.source-ref-list li) { gap: 8px; padding: 9px 11px; border-color: var(--tutor-line); border-radius: 8px; background: var(--tutor-soft); color: var(--tutor-ink); }
.turn-evidence :deep(.source-ref-list strong), .turn-evidence :deep(.source-ref-list small) { white-space: normal; overflow-wrap: anywhere; }
.turn-evidence :deep(.source-ref-list small), .turn-evidence :deep(.source-ref-list li > span) { color: var(--tutor-muted); font-size: 12px; line-height: 1.6; }
.assistant-bubble > :deep(.el-alert) { margin-top: 14px; }
.thinking-bubble { display: flex; align-items: center; gap: 10px; min-height: 32px; color: var(--tutor-muted); font-size: 13px; }
.thinking-dots { display: flex; gap: 4px; }
.thinking-dots i { width: 5px; height: 5px; border-radius: 50%; background: var(--tutor-accent); animation: tutor-thinking 1.1s infinite ease-in-out; }
.thinking-dots i:nth-child(2) { animation-delay: .14s; }
.thinking-dots i:nth-child(3) { animation-delay: .28s; }
@keyframes tutor-thinking { 0%, 80%, 100% { opacity: .35; } 40% { opacity: 1; } }
.tutor-composer { display: grid; flex-shrink: 0; box-sizing: border-box; gap: 6px; width: 100%; padding: 12px 18px 14px; background: var(--tutor-paper); }
.composer-editor {
  display: flex;
  min-width: 0;
  flex-direction: column;
  border: 1px solid transparent;
  border-radius: 24px;
  background:
    linear-gradient(180deg, #fff, #fcfdfe) padding-box,
    linear-gradient(155deg, #b8c6d2, #d8e1e8 46%, #aebfcd) border-box;
  box-shadow: inset 0 1px 0 #fff, 0 2px 5px rgb(23 44 69 / 12%), 0 8px 20px -9px rgb(23 44 69 / 28%);
  transition: border-color .16s ease, box-shadow .16s ease;
}
.composer-editor:not(.is-disabled):hover { border-color: #a8bac9; }
.composer-editor:not(.is-disabled):focus-within { border-color: #8198ad; box-shadow: inset 0 1px 0 #fff, 0 2px 6px rgb(23 44 69 / 14%), 0 8px 20px -9px rgb(23 44 69 / 32%); }
.composer-editor.is-disabled { box-shadow: inset 0 1px 0 #fff, 0 2px 5px rgb(23 44 69 / 8%); }
.composer-editor :deep(.el-textarea) { box-sizing: border-box; min-width: 0; padding: 6px 7px 0; }
.composer-editor :deep(.el-textarea__inner) {
  padding: 8px 9px 6px;
  border: 0;
  border-radius: 14px;
  background: transparent;
  color: var(--tutor-ink);
  caret-color: var(--tutor-ink);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
  box-shadow: none !important;
  resize: none;
  overflow-y: hidden;
  scrollbar-color: auto;
}
.composer-editor.has-overflow :deep(.el-textarea__inner) { overflow-y: auto; }
.composer-editor :deep(.el-textarea__inner::-webkit-scrollbar) { width: 6px; }
.composer-editor :deep(.el-textarea__inner::-webkit-scrollbar-track) { margin-block: 6px; background: transparent; }
.composer-editor :deep(.el-textarea__inner::-webkit-scrollbar-thumb) { border-radius: 99px; background: #d9dfe4; }
.composer-editor :deep(.el-textarea__inner::-webkit-scrollbar-thumb:hover) { background: #bec8d1; }
.composer-editor :deep(.el-textarea__inner::-webkit-scrollbar-button) { display: none; }
@supports (-moz-appearance: none) {
  .composer-editor :deep(.el-textarea__inner) { scrollbar-width: thin; scrollbar-color: #d9dfe4 transparent; }
}
.composer-editor :deep(.el-textarea__inner::placeholder) { color: var(--tutor-muted); }
.composer-editor :deep(.el-textarea__inner:focus-visible) { outline: none; }
.composer-actions { display: flex; justify-content: flex-end; padding: 0 10px 10px; }
.composer-shortcuts { min-width: 0; color: var(--tutor-muted); font-size: 11px; font-weight: 400; line-height: 1.6; text-align: center; }
.composer-shortcuts kbd { font: inherit; }
.composer-send { flex: 0 0 auto; width: 36px; height: 36px; margin: 0; padding: 8px; border: 1px solid transparent; border-radius: 50%; background: #2c65bb; color: #fff; transition: background-color .16s ease; }
.composer-send:hover, .composer-send:focus-visible { border-color: transparent; background: #2456a4; color: #fff; }
.composer-send:not(.is-disabled):active { background: #1e4788; }
.composer-send.is-disabled, .composer-send.is-disabled:hover { border-color: transparent; background: #eef1f4; color: #637284; }
.composer-send svg { stroke-width: 2; }
.composer-send :deep(.el-icon.is-loading) { margin: 0; }
.quoted-context { display: flex; min-width: 0; align-items: flex-start; gap: 8px; margin: 8px 8px 0; padding: 8px 10px; border-radius: 16px; background: #f5f7f9; }
.quoted-context > div { flex: 1; min-width: 0; }
.quote-icon { margin-top: 2px; color: var(--tutor-accent); }
.quoted-context span { color: var(--tutor-detail-ink); font-size: 12px; font-weight: 600; line-height: 1.5; }
.quoted-context p { display: -webkit-box; margin: 4px 0 0; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; color: var(--tutor-muted); font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
.quoted-context button { display: grid; flex: 0 0 auto; width: 28px; height: 28px; margin-top: -3px; place-items: center; padding: 4px; border: 0; border-radius: 7px; background: transparent; color: var(--tutor-muted); cursor: pointer; }
.quoted-context button:hover { background: #e2eeeb; color: var(--tutor-accent); }
@media (max-width: 1100px) {
  .tutor-panel.is-embedded { position: fixed; inset: 0 0 0 auto; flex: initial; width: min(460px, 94vw); height: auto; box-shadow: -12px 0 36px rgb(23 44 69 / 10%); }
}
@media (max-width: 560px) {
  .tutor-panel-header { gap: 10px; padding: 16px; }
  .tutor-body { padding: 20px 16px; }
  .tutor-welcome { margin-top: 20px; }
  .tutor-heading > strong { font-size: 17px; }
  .tutor-composer { padding: 12px 12px max(14px, env(safe-area-inset-bottom)); }
  .composer-shortcuts { display: none; }
  .composer-editor :deep(.el-textarea__inner) { font-size: 16px; }
  .assistant-bubble > p { font-size: 15px; }
  .assistant-meta { gap: 6px; }
}
@media (max-width: 720px), (pointer: coarse) {
  .tutor-close, .composer-send, .quoted-context button { width: 44px; height: 44px; }
  .quoted-context button { margin: -3px -4px -3px 0; }
}
@media (max-height: 600px) {
  .tutor-panel-header { padding-block: 12px; }
  .tutor-body { padding-block: 16px; }
  .tutor-welcome { margin-top: 0; gap: 18px; }
  .tutor-composer { padding-block: 10px; }
}
@media (prefers-reduced-motion: reduce) {
  .tutor-panel-slide-enter-active, .tutor-panel-slide-leave-active, .tutor-panel *, .tutor-panel :deep(.el-icon.is-loading) { animation: none !important; transition: none !important; scroll-behavior: auto !important; }
}
</style>
