<template>
  <section ref="workspaceElement" class="round-feedback-workspace" :class="{ 'has-feedback-result': Boolean(result) }" aria-label="本轮联合测评与反馈">
    <div v-if="detailError || error || pending" class="round-status" aria-live="polite">
      <p v-if="detailError" role="alert">{{ detailError }}<el-button @click="loadDetail">重新读取轮次</el-button></p>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="pending" role="status">{{ session ? '正在提交或等待评分，请稍候。' : '正在恢复本轮测评状态。' }}</p>
    </div>
    <section v-if="!result" class="feedback-workspace">
      <article class="evaluation-panel">
        <header class="section-heading">
          <div><span class="page-kicker">01 / PRACTICE CHECK</span><h2>完成知识测评</h2><p>题目会优先覆盖本轮资源涉及的知识点。</p></div>
          <span class="progress-pill assessment-progress" :class="{ ready: canSubmit }"><span class="progress-count"><strong>{{ answeredCount }}</strong><span class="progress-total">/ {{ totalQuestions }}</span></span><span class="progress-caption">已作答</span></span>
        </header>
        <label v-if="(detail?.stages.length || 0) > 1" class="round-stage-switch">学习阶段
          <el-select :model-value="stageId" :disabled="pending || Boolean(draft)" aria-label="选择本轮测评阶段" @update:model-value="changeStage">
            <el-option v-for="stage in detail?.stages || []" :key="stage.stage_id" :value="stage.stage_id" :label="stage.kind === 'initial' ? '本轮学习测评' : `本轮纠错 ${stage.ordinal} 复测`" />
          </el-select>
        </label>
        <RoundEvaluationGroups v-if="session" :session="session" :answers="answers" :members="detail?.members" :locked="pending || Boolean(draft)" @answer="updateAnswer" />
        <div v-else class="round-empty"><p>测评题目尚未准备就绪。</p><el-button v-if="!pending" @click="load">加载本次测评</el-button></div>
      </article>
      <FeedbackReflection :model-value="reflectionForm" :active="Boolean(session)" :locked="pending || Boolean(draft)" @update:model-value="reflectionForm = $event">
        <div v-if="session" class="submit-box">
          <div class="submit-summary"><strong>{{ canSubmit ? '可以提交本轮反馈' : '请先完成全部测评题' }}</strong></div>
          <el-button class="submit-feedback-button" type="primary" :loading="pending" :disabled="!canSubmit || versionConflict" @click="submit(reflectionForm)">统一提交本次测评</el-button>
          <el-button v-if="versionConflict" @click="refreshProfile">刷新画像后重新准备提交</el-button>
        </div>
      </FeedbackReflection>
    </section>
    <section v-else class="result-panel round-feedback-result" aria-label="各节点独立测评结果">
      <div v-if="result.nodes.length > 1" class="round-member-switch" role="group" aria-label="查看节点反馈">
        <button v-for="node in result.nodes" :key="node.member_id" type="button" :aria-pressed="selectedMember === node.member_id" @click="selectedMember = node.member_id">
          <span>{{ roundRoleLabel(node.role) }} · {{ nodeName(node.node_id) }}</span><strong>{{ Math.round(node.score * 100) }} 分</strong>
        </button>
      </div>
      <FeedbackReviewPanels :result="selectedFeedback || {}" :feedback-report="displayReport" :summary-state="summaryState" :summary-reason="selectedNode?.reason" :whole-round="Boolean(selectedFeedback?.attempt?.metadata?.round_context && result.nodes.length > 1)" />
      <section class="next-step-panel has-route-picker">
        <header class="next-step-copy">
          <div class="next-step-heading">
            <el-icon class="review-section-symbol" aria-hidden="true"><Compass /></el-icon>
            <h2>下一步方案</h2>
          </div>
          <div class="next-step-verdict">
            <span class="verdict-recommendation">系统推荐</span>
            <span class="result-action-label" :class="{ 'is-danger': ['补救学习', '降阶补基础'].includes(recommendationLabel), 'is-warning': recommendationLabel === '强化巩固' }">{{ recommendationLabel }}</span>
            <p v-if="recommendationReason" class="round-recommendation-reason">{{ recommendationReason }}</p>
          </div>
          <p v-if="confirmedChoice" class="confirmed-route-note" role="status">
            <span>已选择：</span>
            <span class="result-action-label" :class="{ 'is-warning': ['强化巩固', '巩固前置'].includes(confirmedChoiceLabel), 'is-danger': ['补救学习', '降阶补基础'].includes(confirmedChoiceLabel) }">{{ confirmedChoiceLabel }}</span>
          </p>
          <button v-else-if="correctionTargets.length" type="button" class="round-route-switch" role="switch"
            aria-label="纠错巩固" :aria-checked="selectedRoute === 'correction'"
            :disabled="Boolean(actionBusy) || nextRoundBusy || candidatesLoading"
            @click="selectedRoute = selectedRoute === 'learning' ? 'correction' : 'learning'">
            <span><el-icon aria-hidden="true"><ArrowRight /></el-icon>下一轮学习</span>
            <span><el-icon aria-hidden="true"><RefreshRight /></el-icon>纠错巩固</span>
          </button>
        </header>
        <fieldset class="round-route-content route-lock-fieldset" :disabled="Boolean(confirmedChoice) || candidatesLoading" :inert="Boolean(confirmedChoice) || candidatesLoading">
          <section v-if="correctionTargets.length" class="round-choice round-route-pane round-correction-pane" :class="{ 'is-route-hidden': selectedRoute !== 'correction' }" :aria-hidden="selectedRoute !== 'correction'" :inert="selectedRoute !== 'correction'" aria-label="本轮纠错选择">
            <header class="round-correction-heading">
              <div class="round-correction-heading-copy">
                <div class="round-correction-title-row">
                  <h3><el-icon aria-hidden="true"><RefreshRight /></el-icon>本轮纠错与新测评</h3>
                  <span class="round-correction-sequence-tag"><i aria-hidden="true"></i> CORRECTION LOOP</span>
                </div>
                <p>围绕本次薄弱点，生成纠错包并通过新测评验证掌握情况。</p>
              </div>
            </header>
            <div class="round-correction-selection">
              <span class="round-correction-selection-label"><strong>纠错目标</strong><small>{{ selectedCorrectionNodes.length }} / {{ correctionTargets.length }} 已选</small></span>
              <el-checkbox-group v-model="selectedCorrectionNodes" class="round-correction-targets" aria-label="选择纠错节点" :disabled="Boolean(actionBusy) || nextRoundBusy"><el-checkbox v-for="target in correctionTargets" :key="target.node_id" :label="target.node_id">{{ nodeName(target.node_id) }}</el-checkbox></el-checkbox-group>
            </div>
            <div class="round-correction-flow" role="list" aria-label="纠错学习闭环">
              <div class="round-correction-step" role="listitem"><span class="round-correction-step-index">01</span><span class="round-correction-step-copy"><strong>锁定薄弱点</strong><small>对照本轮测评结果</small></span></div>
              <el-icon class="round-correction-step-arrow" aria-hidden="true"><ArrowRight /></el-icon>
              <div class="round-correction-step" role="listitem"><span class="round-correction-step-index">02</span><span class="round-correction-step-copy"><strong>生成定向纠错</strong><small>围绕已选节点强化</small></span></div>
              <el-icon class="round-correction-step-arrow" aria-hidden="true"><ArrowRight /></el-icon>
              <div class="round-correction-step" role="listitem"><span class="round-correction-step-index">03</span><span class="round-correction-step-copy"><strong>新测评回验</strong><small>确认掌握后再推进</small></span></div>
            </div>
            <div class="round-correction-actions">
              <RoundClaimSwitches v-model:check="includeClaimCheck" v-model:retrieval="includeClaimEvidenceRetrieval" :disabled="Boolean(actionBusy) || nextRoundBusy" />
              <el-button class="round-correction-submit" type="primary" :loading="actionBusy === 'correction'" :disabled="!selectedCorrectionNodes.length || Boolean(actionBusy) || nextRoundBusy" @click="correct">
                <el-icon v-if="actionBusy !== 'correction'" class="round-correction-submit-leading" aria-hidden="true"><RefreshRight /></el-icon>
                <span>生成选中节点的纠错包与新测试题</span>
                <el-icon v-if="actionBusy !== 'correction'" class="round-correction-submit-trailing" aria-hidden="true"><ArrowRight /></el-icon>
              </el-button>
            </div>
          </section>
          <section v-if="candidates" class="round-choice round-route-pane" :class="{ 'is-route-hidden': selectedRoute !== 'learning' }" :aria-hidden="selectedRoute !== 'learning'" :inert="selectedRoute !== 'learning'" aria-label="选择下一轮学习目标">
            <NextRoundChoice :key="`${learnerId}:${result.attempt_id}:${confirmedChoice?.stageId || ''}`" compact :learner-id="learnerId" :source-attempt-id="result.attempt_id" :round-id="roundId" :candidates="candidates" :assessment-action="result.primary_path_action" :blocked="Boolean(actionBusy) || Boolean(confirmedChoice)" :confirmed-selection="confirmedChoice" :claim-options="claimOptions" @busy="nextRoundBusy = $event" @confirmed="confirmChoice">
              <template #actions-left>
                <RoundClaimSwitches v-model:check="includeClaimCheck" v-model:retrieval="includeClaimEvidenceRetrieval" :disabled="Boolean(actionBusy) || nextRoundBusy" />
              </template>
            </NextRoundChoice>
          </section>
          <p v-if="!candidates" class="round-route-loading">正在读取后续学习方案。</p>
        </fieldset>
      </section>
      <p v-if="actionError" role="alert" class="round-error">{{ actionError }}</p>
    </section>
  </section>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowRight, Compass, RefreshRight } from '@element-plus/icons-vue'
import FeedbackReflection from './FeedbackReflection.vue'
import FeedbackReviewPanels from './FeedbackReviewPanels.vue'
import RoundClaimSwitches from './RoundClaimSwitches.vue'
import { feedbackApi } from './api.js'
import { useRouter } from 'vue-router'
import { useAppStore } from '../../stores/app'
import { profileApi } from '../learners/api.js'
import NextRoundChoice from './NextRoundChoice.vue'
import { roundFeedbackApi } from './roundApi.js'
import { roundRoleLabel } from '../generation/roundWorkspace.js'
import { useRoundEvaluation } from './useRoundEvaluation.js'
import RoundEvaluationGroups from './RoundEvaluationGroups.vue'
import { chosenRouteLabel, confirmedRouteKey, readConfirmedRoute, saveConfirmedRoute, restoreServerChoice } from './confirmedRoute.js'

const props = defineProps({ roundId: { type: String, required: true }, learnerId: { type: String, required: true }, initialStageId: { type: String, default: '' }, reflection: { type: Object, default: () => ({}) } })
async function startEvaluation() {
  if (!session.value && !result.value && !pending.value) await load()
  await nextTick()
  workspaceElement.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}
const emit = defineEmits(['result-state'])
const defaultReflection = { completed: true, time_spent_seconds: 1800, self_rating: 4, difficulty_feeling: '', confusing_part: '', comment: '' }
const reflectionForm = ref({ ...defaultReflection, ...props.reflection })
const workspaceElement = ref(null)
const selectedMember = ref('')
const selectedRoute = ref('learning')
const confirmedChoice = ref(null)
function confirmChoice(value) {
  confirmedChoice.value = value
  if (value.candidates) candidates.value = value.candidates
  selectedRoute.value = value.route
  const payload = value.payload
  includeClaimCheck.value = Boolean(payload.include_claim_check)
  includeClaimEvidenceRetrieval.value = Boolean(payload.include_claim_evidence_retrieval)
  if (value.route === 'correction') selectedCorrectionNodes.value = payload.targets.map(target => target.node_id)
}
const nodeResults = ref([])
const summaryState = ref('')
const router = useRouter()
const store = useAppStore()
const detail = ref(null)
const candidates = ref(null)
const candidatesLoading = ref(true)
const stageId = ref('')
const detailError = ref('')
const nextRoundBusy = ref(false)
const actionBusy = ref('')
const actionError = ref('')
const selectedCorrectionNodes = ref([])
const includeClaimCheck = ref(false)
const includeClaimEvidenceRetrieval = ref(false)
const claimPostRetrievalMaxIterations = ref(0)
let version = 0
let disposed = false
const actionKeys = new Map()
const { session, result, answers, pending, error, draft, versionConflict, answeredCount, canSubmit, load, retake, submit, reset, clearRejectedDraft } = useRoundEvaluation({
  context: () => ({ learnerId: props.learnerId, roundId: props.roundId, stageId: stageId.value }),
  profileVersion: () => store.currentProfile?.profile_version || 1,
  accountId: () => store.currentUserId || '',
  onResult: value => {
    if (store.currentProfile?.learner_id === props.learnerId && value.profile_version >= store.currentProfile.profile_version) {
      store.setCurrentProfile({ ...store.currentProfile, profile_version: value.profile_version })
    }
    loadCandidates()
    loadNodeResults()
  },
})
const canRetake = computed(() => {
  const stages = detail.value?.stages || []
  const latest = stages.reduce((current, stage) => !current || stage.ordinal > current.ordinal ? stage : current, null)
  return Boolean(result.value && latest?.stage_id === stageId.value
    && !(detail.value.protocol_version === 'legacy-correction/v1' && latest.kind === 'initial'))
})
const roundBusy = computed(() => pending.value || Boolean(actionBusy.value) || nextRoundBusy.value)
async function startRetake() {
  if (!canRetake.value || roundBusy.value) return
  if (await retake()) {
    reflectionForm.value = { ...defaultReflection }
    await startEvaluation()
  }
}
defineExpose({ startEvaluation, startRetake, canRetake, roundBusy })
const totalQuestions = computed(() => session.value?.groups.reduce((sum, group) => sum + group.questions.length, 0) || 0)
const selectedNode = computed(() => result.value?.nodes.find(node => node.member_id === selectedMember.value) || result.value?.nodes[0])
const selectedFeedback = computed(() => nodeResults.value.find(item => item.attempt?.attempt_id === selectedNode.value?.source_attempt_id))
const repairRecommendation = computed(() => candidates.value?.remediation_recommendation)
const recommendationLabel = computed(() => ({
  prerequisite: '补救学习',
  downgrade: '降阶补基础',
  practice_prerequisite: '巩固前置',
  return_to_original: '返回原节点',
})[repairRecommendation.value?.kind] || actionLabel(result.value?.primary_path_action))
const confirmedChoiceLabel = computed(() => {
  const choice = confirmedChoice.value
  if (!choice) return ''
  const followsRepair = choice.route === 'learning' && repairRecommendation.value?.node?.skill_node_id
    && choice.payload?.primary_node_id === repairRecommendation.value.node.skill_node_id
  return choice.label === '下一轮学习' || followsRepair ? recommendationLabel.value : choice.label
})
const recommendationReason = computed(() => {
  if (!result.value) return ''
  const repair = repairRecommendation.value
  if (repair) {
    const { kind, node, original_node_name: original } = repair
    if (kind === 'return_to_original') return `前置测评已通过，可以返回「${original}」重新学习并测评。`
    if (kind === 'practice_prerequisite') return `「${node.name}」尚未达到 80%，建议继续巩固，通过后再返回「${original}」。`
    return `建议先补学「${node.name}」。通过所需前置测评后，再返回「${original}」。`
  }
  const decision = nodeResults.value.find(item => item.attempt?.attempt_id === result.value.attempt_id)?.decision
  if (decision?.action === result.value.primary_path_action && decision.decision_reason) return decision.decision_reason
  const primary = result.value.nodes.find(node => node.role === 'primary')
  return primary?.action === result.value.primary_path_action ? primary.reason : ''
})
const displayReport = computed(() => {
  const report = selectedFeedback.value?.feedback_report || {}
  const questions = report.question_results || []
  return { ...report, total_score: Math.round((selectedNode.value?.score || 0) * 100), max_score: 100,
    question_results: result.value?.nodes.length === 1 ? questions : questions.filter(item => item.skill_node_id === selectedNode.value?.node_id) }
})
watch(result, value => {
  emit('result-state', value)
  if (value) {
    selectedMember.value = value.nodes.find(node => node.role === 'primary')?.member_id || value.nodes[0]?.member_id
    selectedRoute.value = 'learning'
    confirmedChoice.value = null
    const saved = readConfirmedRoute(localStorage, confirmedRouteKey(store.currentUserId, props.learnerId, value.attempt_id))
    if (saved) confirmChoice(saved)
  }
}, { immediate: true })
async function loadNodeResults() {
  const captured = version
  const attempt = result.value?.attempt_id
  const isCurrent = () => !disposed && captured === version && result.value?.attempt_id === attempt
  summaryState.value = 'loading'
  try {
    const response = await feedbackApi.listResults(props.learnerId, { limit: 100 })
    if (isCurrent()) {
      nodeResults.value = response.data || []
      summaryState.value = 'loaded'
    }
  } catch {
    if (isCurrent()) summaryState.value = 'error'
  }
}
const nodeName = id => confirmedChoice.value?.nodes?.find(node => node.skill_node_id === id)?.name || detail.value?.members.find(member => member.node_id === id)?.node_name || id
const actionLabel = value => ({ hold: '保持主路径', advance: '下一节点', practice: '强化巩固', remediate: '补救学习' })[value] || '结果已记录'
const claimOptions = computed(() => ({
  include_claim_check: includeClaimCheck.value,
  include_claim_evidence_retrieval: includeClaimCheck.value && includeClaimEvidenceRetrieval.value,
  claim_post_retrieval_max_iterations: includeClaimCheck.value && includeClaimEvidenceRetrieval.value ? claimPostRetrievalMaxIterations.value : 0,
}))
const correctionTargets = computed(() => candidates.value?.correction_targets || [])
async function loadCandidates() {
  const captured = version
  const attemptId = result.value?.attempt_id
  candidatesLoading.value = true
  try {
    const response = await roundFeedbackApi.candidates(props.roundId, attemptId)
    if (disposed || captured !== version || result.value?.attempt_id !== attemptId) return
    const restored = restoreServerChoice(response.data.confirmed_selection, response.data, confirmedChoice.value)
    if (restored) confirmChoice(restored)
    candidates.value = confirmedChoice.value?.candidates || response.data
    if (!confirmedChoice.value) selectedCorrectionNodes.value = (response.data.correction_targets || []).map(target => target.node_id)
    if (!confirmedChoice.value && !response.data.remediation_recommendation && selectedCorrectionNodes.value.length
        && ['remediate', 'practice'].includes(result.value?.primary_path_action)) {
      selectedRoute.value = 'correction'
    }
  } catch (caught) { if (!disposed && captured === version) actionError.value = caught?.response?.data?.message || '后续方案暂不可用，请稍后重新读取轮次。' }
  finally { if (!disposed && captured === version && result.value?.attempt_id === attemptId) candidatesLoading.value = false }
}
async function loadDetail() {
  const captured = ++version
  reset(); nodeResults.value = []; emit('result-state', null); detailError.value = ''; actionError.value = ''
  try {
    const response = await roundFeedbackApi.detail(props.roundId)
    if (disposed || captured !== version) return
    if (response.data.learner_id !== props.learnerId) throw new Error('学习轮次不属于当前画像')
    detail.value = response.data
    stageId.value = response.data.stages.some(stage => stage.stage_id === props.initialStageId) ? props.initialStageId : [...response.data.stages].sort((a, b) => b.ordinal - a.ordinal)[0]?.stage_id || ''
    await load()
  } catch (caught) { if (captured === version && !disposed) detailError.value = caught?.response?.data?.message || caught.message || '轮次读取失败' }
}
function updateAnswer({ id, value }) { if (!pending.value && !draft.value) answers[id] = value }
async function changeStage(value) {
  ++version
  candidates.value = null
  nodeResults.value = []
  stageId.value = value
  actionError.value = ''
  await load()
}
function actionKey(kind, payload) {
  const identity = `round-action:${store.currentUserId || ''}:${props.learnerId}:${props.roundId}:${kind}:${JSON.stringify(payload)}`
  if (!actionKeys.has(identity)) {
    let stored = ''
    try { stored = sessionStorage.getItem(identity) || '' } catch { /* Memory fallback. */ }
    const key = stored || `round-${kind}-${crypto.randomUUID()}`
    actionKeys.set(identity, key)
    try { sessionStorage.setItem(identity, key) } catch { /* Memory fallback. */ }
  }
  return actionKeys.get(identity)
}
async function perform(kind, build, invoke) {
  if (actionBusy.value || nextRoundBusy.value || confirmedChoice.value || !result.value) return
  const captured = version
  actionBusy.value = kind; actionError.value = ''
  try {
    const data = build()
    const response = await invoke({ ...data, selection_key: actionKey(kind, data) })
    if (disposed || captured !== version) return
    const value = response.data
    const member = value.members.find(node => node.role === 'primary') || value.members[0]
    const runId = value.primary_default_run_id || member.job_ids[0]
    const choice = { confirmed: true, route: 'correction', label: chosenRouteLabel('correction'), payload: data,
      candidates: JSON.parse(JSON.stringify(candidates.value)),
      roundId: value.round_id, stageId: value.stage_id, runId }
    confirmChoice(choice)
    saveConfirmedRoute(localStorage, confirmedRouteKey(store.currentUserId, props.learnerId, result.value.attempt_id), choice)
    await router.push({ path: '/generate', query: { learnerId: props.learnerId, roundId: value.round_id, stageId: value.stage_id, memberId: member.member_id, runId } })
  } catch (caught) { if (!disposed && captured === version) actionError.value = caught?.response?.data?.message || caught?.response?.data?.detail || caught.message || '资源方案确认失败；重试会复用原选择。' }
  finally { if (!disposed && captured === version) actionBusy.value = '' }
}
function correct() {
  return perform('correction', () => ({ learner_id: props.learnerId, include_claim_check: includeClaimCheck.value,
    claim_post_retrieval_max_iterations: includeClaimCheck.value && includeClaimEvidenceRetrieval.value ? claimPostRetrievalMaxIterations.value : 0,
    include_claim_evidence_retrieval: Boolean(includeClaimCheck.value && includeClaimEvidenceRetrieval.value),
    targets: correctionTargets.value.filter(target => selectedCorrectionNodes.value.includes(target.node_id)) }), data => roundFeedbackApi.correct(props.roundId, data))
}
async function refreshProfile() {
  const captured = version
  try {
    const response = await profileApi.get(props.learnerId)
    if (!disposed && captured === version) { store.setCurrentProfile(response.data); clearRejectedDraft() }
  } catch (caught) { if (!disposed && captured === version) actionError.value = caught?.response?.data?.message || '画像刷新失败，请重试。' }
}
watch(() => [props.roundId, props.learnerId], () => { actionBusy.value = ''; candidates.value = null; actionKeys.clear(); loadDetail() }, { immediate: true })
onBeforeUnmount(() => { disposed = true; ++version })
</script>
<style scoped>
.route-lock-fieldset { margin:0; padding:0; border:0; min-width:0; }
.confirmed-route-note { display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin:12px 0 0; color:#315b84; font-size:13px; font-weight:600; }
.round-feedback-workspace { min-width:0; min-height:0; flex:1; display:flex; flex-direction:column; padding-top:0; scroll-margin-block-start:16px; }
.round-status { color:var(--feedback-muted); font-size:13px; }
.feedback-workspace { margin-top:0; }
.round-empty { padding:24px; color:var(--feedback-muted); }
.round-stage-switch { display:flex; align-items:center; gap:12px; padding:12px 24px; font-size:13px; }
.round-stage-switch .el-select { max-width:240px; }
.round-member-switch { display:flex; flex-wrap:wrap; gap:10px; }
.round-member-switch button { display:flex; align-items:center; gap:16px; min-height:44px; padding:10px 16px; color:var(--feedback-ink); border:1px solid #bed0e6; border-radius:10px; background:#fff; cursor:pointer; }
.round-member-switch button[aria-pressed=true] { background:#edf4ff; border-color:#7299ca; }
.round-member-switch button:focus-visible { outline:2px solid #3b70af; outline-offset:2px; }
.round-route-content { display:grid; min-width:0; align-content:start; grid-template-rows:auto; gap:10px; }
/* Both routes share one grid row so switching never changes the panel height.
   The row keeps the footprint the page had before the three-row plan layout, so the
   review cards above stay at the height they were tuned to. */
.round-choice.round-route-pane { display:flex; min-width:0; flex-direction:column; justify-content:center; grid-area:1 / 1; }
.round-feedback-result .round-choice.round-route-pane { min-block-size:281px; }
@media (min-width:1101px) and (min-height:800px) { .round-feedback-result .round-choice.round-route-pane { min-block-size:225px; } }
.round-route-loading { grid-area:1 / 1; margin:0; }
.round-choice.round-route-pane.is-route-hidden { visibility:hidden; pointer-events:none; }
.round-choice h3 { margin:0 0 8px; font-size:17px; }
.round-choice p { margin:0 0 12px; color:var(--feedback-muted); font-size:13px; }
.round-choice .el-checkbox-group { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:12px; }
.round-correction-actions { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px 16px; }
.round-correction-actions .el-button { min-height:44px; height:auto; max-width:100%; white-space:normal; }
.round-choice.round-route-pane.round-correction-pane {
  position:relative;
  display:grid;
  grid-template-rows:auto auto minmax(48px,1fr) auto;
  align-content:stretch;
  justify-content:stretch;
  gap:8px;
  isolation:isolate;
  overflow:visible;
  padding:6px 10px 0;
  border-radius:0;
  background:#fff;
}
.round-correction-heading { display:flex; min-width:0; align-items:center; justify-content:space-between; gap:12px; }
.round-correction-heading-copy { min-width:0; }
.round-correction-title-row { display:flex; min-width:0; flex-wrap:wrap; align-items:center; gap:8px 12px; }
.round-correction-title-row h3 { display:flex; align-items:center; gap:8px; margin:0; color:#173d60; font-size:17px; line-height:1.35; }
.round-correction-title-row h3 :deep(.el-icon) { display:grid; width:24px; height:24px; place-items:center; border:1px solid #b8d0ec; border-radius:8px; background:linear-gradient(145deg,#fff,#e6f0ff); color:#376ea9; box-shadow:0 2px 5px rgb(41 82 132 / 12%); }
.round-correction-heading p { margin:3px 0 0; color:var(--feedback-muted); font-size:12px; line-height:1.45; }
.round-correction-sequence-tag { display:inline-flex; align-items:center; gap:6px; padding:4px 8px; border:1px solid #d0e0f2; border-radius:999px; background:rgb(255 255 255 / 70%); color:#557698; font-size:9px; font-weight:700; letter-spacing:.12em; white-space:nowrap; }
.round-correction-sequence-tag i { width:6px; height:6px; border-radius:50%; background:#4c91c2; box-shadow:0 0 0 3px rgb(76 145 194 / 12%), 0 0 8px rgb(76 145 194 / 48%); }
.round-correction-selection { display:flex; min-width:0; align-items:center; gap:12px; padding:5px 9px; border:1px solid #dce8f5; border-radius:11px; background:linear-gradient(120deg,rgb(255 255 255 / 90%),rgb(240 247 255 / 82%)); box-shadow:inset 0 1px 0 #fff,0 3px 8px rgb(46 84 127 / 6%); }
.round-correction-selection-label { display:grid; flex:none; gap:2px; min-width:84px; }
.round-correction-selection-label strong { color:#315b84; font-size:11px; line-height:1.2; }
.round-correction-selection-label small { color:#7990a8; font-size:10px; line-height:1.2; }
.round-correction-targets { min-width:0; align-items:center; gap:7px !important; margin:0 !important; }
.round-correction-targets :deep(.el-checkbox) { min-height:30px; height:auto; margin:0; padding:4px 10px; border:1px solid #cbdced; border-radius:8px; background:linear-gradient(145deg,#fff,#f4f8ff); box-shadow:inset 0 1px 0 #fff,0 2px 5px rgb(43 80 125 / 8%); transition:border-color .16s ease,background .16s ease,box-shadow .16s ease; }
.round-correction-targets :deep(.el-checkbox.is-checked) { border-color:#8fb2d9; background:linear-gradient(145deg,#f2f7ff,#e1edff); box-shadow:inset 0 1px 0 #fff,0 3px 8px rgb(47 91 145 / 13%); }
.round-correction-targets :deep(.el-checkbox__label) { padding-left:7px; color:#345c83; font-size:12px; line-height:1.2; }
.round-correction-targets :deep(.el-checkbox__inner) { width:20px; height:20px; border-radius:50%; border-color:#b8cce4; background:linear-gradient(145deg,#fff,#f4f8ff); box-shadow:inset 0 1px 2px rgb(30 63 104 / 8%); }
.round-correction-targets :deep(.is-checked .el-checkbox__inner) { border-color:#477cb9; background:linear-gradient(145deg,#6199da,#3267a6); box-shadow:inset 0 1px 0 rgb(255 255 255 / 45%),0 2px 4px rgb(42 88 148 / 25%); }
.round-correction-targets :deep(.el-checkbox__inner::after) { inset:0; width:14px; height:14px; margin:auto; border:0; background:center / contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M3.5 8 6.5 11 12.5 5' fill='none' stroke='white' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"); opacity:0; transform:none; transition:opacity .15s ease; }
.round-correction-targets :deep(.el-checkbox__input.is-checked .el-checkbox__inner::after) { opacity:1; transform:none; }
.round-correction-targets :deep(.is-disabled .el-checkbox__inner) { opacity:.5; }
.round-correction-flow { position:relative; display:grid; min-width:0; grid-template-columns:minmax(0,1fr) 24px minmax(0,1fr) 24px minmax(0,1fr); align-items:center; gap:6px; min-height:48px; margin:0; padding:6px 10px; overflow:hidden; border:1px solid #d5e4f4; border-radius:12px; background:radial-gradient(circle at 90% 15%,rgb(107 167 218 / 16%),transparent 22%),repeating-linear-gradient(90deg,transparent 0 27px,rgb(107 153 201 / 5%) 27px 28px),linear-gradient(105deg,#f6faff,#fff 56%,#f1f7ff); box-shadow:inset 0 1px 0 #fff,0 4px 12px rgb(36 75 121 / 7%); }
.round-correction-step { display:flex; min-width:0; align-items:center; gap:8px; }
.round-correction-step-index { display:grid; flex:none; width:27px; height:27px; place-items:center; border:1px solid #a8c6e6; border-radius:8px; background:linear-gradient(145deg,#fff,#dfedff); color:#35699f; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:10px; font-weight:700; box-shadow:inset 0 1px 0 #fff,0 2px 5px rgb(38 77 124 / 12%); }
.round-correction-step-copy { display:grid; min-width:0; gap:2px; }
.round-correction-step-copy strong { color:#284e73; font-size:12px; font-weight:700; line-height:1.25; white-space:nowrap; }
.round-correction-step-copy small { color:#7189a2; font-size:11px; line-height:1.25; white-space:nowrap; }
.round-correction-step-arrow { justify-self:center; color:#76a0ca; font-size:14px; filter:drop-shadow(0 1px 1px rgb(48 89 136 / 12%)); }
.round-correction-actions { align-self:end; min-width:0; }
.round-correction-actions :deep(.round-claim-switches) { flex:0 1 auto; gap:8px; }
.round-correction-actions :deep(.round-claim-switch) { padding:4px 12px 4px 8px; }
.round-feedback-result .round-correction-actions :deep(button.el-button.round-correction-submit) { display:inline-flex; min-width:284px; min-height:44px; align-items:center; justify-content:center; gap:9px; padding-inline:16px; border:1px solid #315f96; border-radius:12px; background:radial-gradient(circle at 12% 0%,rgb(255 255 255 / 17%),transparent 38%),linear-gradient(135deg,#477fb9,#24558d); box-shadow:inset 0 1px 0 rgb(255 255 255 / 30%),0 4px 8px rgb(40 83 133 / 20%),0 12px 20px -13px rgb(28 65 108 / 68%); font-size:13px; font-weight:700; letter-spacing:.01em; transition:transform .16s ease,box-shadow .16s ease,background .16s ease; }
.round-feedback-result .round-correction-actions :deep(button.el-button.round-correction-submit .el-icon) { flex:none; font-size:16px; }
.round-feedback-result .round-correction-actions :deep(button.el-button.round-correction-submit:hover:not(:disabled)) { transform:translateY(-1px); border-color:#2b588e; background:radial-gradient(circle at 12% 0%,rgb(255 255 255 / 20%),transparent 38%),linear-gradient(135deg,#528ac6,#2e639e); box-shadow:inset 0 1px 0 rgb(255 255 255 / 34%),0 7px 13px rgb(40 83 133 / 25%),0 16px 24px -13px rgb(28 65 108 / 70%); }
.round-error { color:#a13030; }
@media (max-width:1100px) {
  .round-choice.round-route-pane.round-correction-pane { grid-template-rows:auto auto auto auto; gap:12px; }
  .round-correction-selection { align-items:flex-start; flex-direction:column; gap:7px; }
  .round-correction-selection-label { display:flex; align-items:center; gap:8px; min-width:0; }
  .round-correction-flow { grid-template-columns:minmax(0,1fr) 20px minmax(0,1fr) 20px minmax(0,1fr); padding-inline:8px; }
  .round-correction-actions { align-items:flex-start; }
}
@media (max-width:600px) {
  .round-correction-title-row { align-items:flex-start; flex-direction:column; gap:6px; }
  .round-correction-flow { grid-template-columns:minmax(0,1fr); gap:7px; padding:9px 10px; }
  .round-correction-step-arrow { transform:rotate(90deg); }
  .round-correction-actions { align-items:stretch; flex-direction:column; }
  .round-feedback-result .round-correction-actions :deep(button.el-button.round-correction-submit) { width:100%; min-width:0; }
}
@media (max-width:960px) { .reflection-panel { position:static; } }
</style>
