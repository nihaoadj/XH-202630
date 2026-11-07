<template>
  <section class="round-feedback-workspace" aria-label="本轮联合测评与反馈">
    <header class="round-feedback-header"><div><small>LEARNING ROUND</small><h2>本轮学习与纠错</h2><p>同页完成本次全部节点题目，一次提交，分别记录结果。</p></div>
      <label>学习阶段<select :value="stageId" :disabled="pending" aria-label="选择本轮测评阶段" @change="changeStage($event.target.value)">
        <option v-for="stage in detail?.stages || []" :key="stage.stage_id" :value="stage.stage_id">{{ stage.kind === 'initial' ? '本轮学习测评' : `本轮纠错 ${stage.ordinal} 复测` }}</option>
      </select></label>
    </header>
    <p v-if="detailError" role="alert">{{ detailError }}<el-button @click="loadDetail">重新读取轮次</el-button></p>
    <p v-if="error" class="round-error" role="alert">{{ error }}</p>
    <p v-if="pending" role="status">{{ session ? '正在提交或等待评分，请稍候。' : '正在恢复本轮测评状态。' }}</p>
    <template v-if="!result">
      <RoundEvaluationGroups v-if="session" :session="session" :answers="answers" :members="detail?.members" :locked="pending || Boolean(draft)" @answer="updateAnswer" @hint="$emit('hint', $event)" />
      <div class="round-submit-actions">
        <el-button v-if="!session && !pending" @click="load">加载本次测评</el-button>
        <el-button v-if="session" type="primary" :loading="pending" :disabled="!canSubmit || versionConflict" @click="submit(reflection)">统一提交本次测评</el-button>
        <span v-if="session">{{ answeredCount }} / {{ session.groups.reduce((count, group) => count + group.questions.length, 0) }} 已作答</span>
        <el-button v-if="versionConflict" @click="refreshProfile">刷新画像后重新准备提交</el-button>
      </div>
    </template>
    <section v-else class="round-feedback-result" aria-label="各节点独立测评结果">
      <h3>本次测评结果</h3><p>主路径建议：{{ actionLabel(result.primary_path_action) }}</p>
      <div class="round-result-nodes">
        <article v-for="node in result.nodes" :key="node.member_id"><small>{{ roundRoleLabel(node.role) }}</small><h4>{{ nodeName(node.node_id) }}</h4><strong>{{ Math.round(node.score * 100) }} 分</strong><p>{{ node.reason }}</p><p>{{ node.remediation_status === 'remediate' ? '待补救，后续优先推荐' : node.remediation_status === 'practice' ? '待巩固' : '本次结果已记录' }}</p></article>
      </div>
      <section v-if="correctionTargets.length" class="round-choice" aria-label="本轮纠错选择">
        <h3>本轮纠错与新测评</h3><p>每个选中节点分别生成纠错包和新测试题；两节点可同时纠错，仍属于本轮。</p>
        <el-checkbox-group v-model="selectedCorrectionNodes" :disabled="Boolean(actionBusy)">
          <el-checkbox v-for="target in correctionTargets" :key="target.node_id" :label="target.node_id">{{ nodeName(target.node_id) }}</el-checkbox>
        </el-checkbox-group>
        <el-button type="primary" :loading="actionBusy === 'correction'" :disabled="!selectedCorrectionNodes.length || Boolean(actionBusy)" @click="correct">生成选中节点的纠错包与新测试题</el-button>
      </section>
      <section v-if="creationEnabled && candidates" class="round-choice" aria-label="选择下一轮学习目标">
        <h3>下一轮学习</h3><p>只选择一个主节点，可附带一个已学节点；未解决的薄弱项继续保留。</p>
        <label>学习方式<select v-model="intent" :disabled="Boolean(actionBusy)"><option value="learn_new_knowledge">学习新节点</option><option value="reinforce_weakness">复习旧节点</option><option v-if="candidates.generation_options?.learning_candidates?.length" value="downgrade_learning">补齐前置知识</option></select></label>
        <el-radio-group v-model="primaryNodeId" class="round-targets" :disabled="Boolean(actionBusy)">
          <el-radio v-for="node in primaryCandidates" :key="node.skill_node_id" :label="node.skill_node_id" :disabled="Boolean(node.blocked_by_node_ids?.length)">{{ node.name }} · 第 {{ node.tier }} 阶<span v-if="node.blocked_by_node_ids?.length">（先修待补齐）</span></el-radio>
        </el-radio-group>
        <p v-if="!primaryCandidates.length">当前方式暂无可选主节点。</p>
        <label>主节点资源</label><el-checkbox-group v-model="primaryResourceTypes" :disabled="Boolean(actionBusy)"><el-checkbox v-for="type in resourceTypes" :key="type" :label="type">{{ type }}</el-checkbox></el-checkbox-group>
        <el-checkbox v-model="includeReview" :disabled="Boolean(actionBusy) || !reviewCandidates.length">附带复习一个已学节点</el-checkbox>
        <div v-if="includeReview"><p>固定生成复习清单、分阶测试题。</p><el-radio-group v-model="reviewNodeId" class="round-targets" :disabled="Boolean(actionBusy)"><el-radio v-for="node in reviewCandidates" :key="node.skill_node_id" :label="node.skill_node_id">{{ node.name }} · 第 {{ node.tier }} 阶</el-radio></el-radio-group></div>
        <el-button type="primary" :loading="actionBusy === 'next'" :disabled="!primaryNodeId || !primaryResourceTypes.length || (includeReview && !reviewNodeId) || Boolean(actionBusy)" @click="nextRound">生成下一轮已选资源</el-button>
      </section>
    </section>
    <el-checkbox v-model="includeClaimCheck" :disabled="Boolean(actionBusy)">启用 Claim 审核</el-checkbox>
    <p v-if="actionError" role="alert" class="round-error">{{ actionError }}</p>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../../stores/app'
import { profileApi } from '../learners/api.js'
import { roundGenerationApi } from '../generation/roundApi.js'
import { roundFeedbackApi } from './roundApi.js'
import { roundRoleLabel } from '../generation/roundWorkspace.js'
import { useRoundEvaluation } from './useRoundEvaluation.js'
import RoundEvaluationGroups from './RoundEvaluationGroups.vue'

const props = defineProps({ roundId: { type: String, required: true }, learnerId: { type: String, required: true }, initialStageId: { type: String, default: '' }, reflection: { type: Object, default: () => ({}) } })
defineEmits(['hint'])
const router = useRouter()
const store = useAppStore()
const detail = ref(null)
const candidates = ref(null)
const stageId = ref('')
const detailError = ref('')
const creationEnabled = ref(false)
const actionBusy = ref('')
const actionError = ref('')
const selectedCorrectionNodes = ref([])
const intent = ref('learn_new_knowledge')
const primaryNodeId = ref('')
const includeReview = ref(false)
const reviewNodeId = ref('')
const includeClaimCheck = ref(false)
const resourceTypes = ['讲义', '实操指南', '分阶测试题', '复习清单', '案例分析']
const primaryResourceTypes = ref(['讲义', '实操指南', '分阶测试题'])
let version = 0
let disposed = false
const actionKeys = new Map()
const { session, result, answers, pending, error, draft, versionConflict, answeredCount, canSubmit, load, submit, reset, clearRejectedDraft } = useRoundEvaluation({
  context: () => ({ learnerId: props.learnerId, roundId: props.roundId, stageId: stageId.value }),
  profileVersion: () => store.currentProfile?.profile_version || 1,
  accountId: () => store.currentUserId || '',
  onResult: value => {
    if (store.currentProfile?.learner_id === props.learnerId) store.setCurrentProfile({ ...store.currentProfile, profile_version: value.profile_version })
    loadCandidates()
  },
})
const nodeName = id => detail.value?.members.find(member => member.node_id === id)?.node_name || id
const actionLabel = value => ({ hold: '保持主路径', advance: '继续学习', practice: '强化巩固', remediate: '补救学习' })[value] || '结果已记录'
const primaryCandidates = computed(() => {
  const options = candidates.value?.generation_options
  return intent.value === 'downgrade_learning' ? options?.learning_candidates || [] : options?.[intent.value] || []
})
const reviewCandidates = computed(() => (candidates.value?.eligible_review_nodes || []).filter(node => node.skill_node_id !== primaryNodeId.value))
const correctionTargets = computed(() => candidates.value?.correction_targets || [])
watch(primaryCandidates, value => { if (!value.some(node => node.skill_node_id === primaryNodeId.value && !node.blocked_by_node_ids?.length)) primaryNodeId.value = value.find(node => !node.blocked_by_node_ids?.length)?.skill_node_id || '' })
watch(reviewCandidates, value => { if (!value.some(node => node.skill_node_id === reviewNodeId.value)) reviewNodeId.value = value[0]?.skill_node_id || '' })
async function loadCandidates() {
  const captured = version
  try {
    const response = await roundFeedbackApi.candidates(props.roundId)
    if (disposed || captured !== version) return
    candidates.value = response.data
    selectedCorrectionNodes.value = (response.data.correction_targets || []).map(target => target.node_id)
  } catch (caught) { if (!disposed && captured === version) actionError.value = caught?.response?.data?.message || '后续方案暂不可用，请稍后重新读取轮次。' }
}
async function loadDetail() {
  const captured = ++version
  reset(); detailError.value = ''; actionError.value = ''
  try {
    const response = await roundFeedbackApi.detail(props.roundId)
    if (disposed || captured !== version) return
    if (response.data.learner_id !== props.learnerId) throw new Error('学习轮次不属于当前画像')
    detail.value = response.data
    stageId.value = response.data.stages.some(stage => stage.stage_id === props.initialStageId) ? props.initialStageId : [...response.data.stages].sort((a, b) => b.ordinal - a.ordinal)[0]?.stage_id || ''
    await load()
    if (captured !== version || disposed) return
    const capability = await roundGenerationApi.capabilities()
    if (captured === version && !disposed) creationEnabled.value = capability.data.round_creation_enabled
  } catch (caught) { if (captured === version && !disposed) detailError.value = caught?.response?.data?.message || caught.message || '轮次读取失败' }
}
function updateAnswer({ id, value }) { if (!pending.value && !draft.value) answers[id] = value }
async function changeStage(value) { ++version; stageId.value = value; actionError.value = ''; await load() }
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
  if (actionBusy.value || !result.value) return
  const captured = version
  actionBusy.value = kind; actionError.value = ''
  try {
    const data = build()
    const response = await invoke({ ...data, selection_key: actionKey(kind, data) })
    if (disposed || captured !== version) return
    const value = response.data
    const member = value.members.find(node => node.role === 'primary') || value.members[0]
    const runId = value.primary_default_run_id || member.job_ids[0]
    await router.push({ path: '/generate', query: { learnerId: props.learnerId, roundId: value.round_id, stageId: value.stage_id, memberId: member.member_id, runId } })
  } catch (caught) { if (!disposed && captured === version) actionError.value = caught?.response?.data?.message || caught?.response?.data?.detail || caught.message || '资源方案确认失败；重试会复用原选择。' }
  finally { if (!disposed && captured === version) actionBusy.value = '' }
}
function correct() {
  return perform('correction', () => ({ learner_id: props.learnerId, include_claim_check: includeClaimCheck.value,
    targets: correctionTargets.value.filter(target => selectedCorrectionNodes.value.includes(target.node_id)) }), data => roundFeedbackApi.correct(props.roundId, data))
}
function nextRound() {
  return perform('next', () => ({ learner_id: props.learnerId, source_attempt_id: result.value.attempt_id,
    primary_node_id: primaryNodeId.value, primary_learning_intent: intent.value, primary_resource_types: primaryResourceTypes.value,
    review_node_id: includeReview.value ? reviewNodeId.value : null, include_claim_check: includeClaimCheck.value }), roundFeedbackApi.next)
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
.round-feedback-workspace { padding:20px; margin-top:18px; border:1px solid #d9e4eb; border-radius:12px; background:#f5f8fa; color:#173349; }.round-feedback-header { display:flex; flex-wrap:wrap; gap:20px; justify-content:space-between; align-items:center; }.round-feedback-header h2 { margin:6px 0; }.round-feedback-header p,.round-choice p { line-height:1.7; }.round-feedback-header small { color:#086575; letter-spacing:.12em; }
label { display:block; margin:12px 0; line-height:1.6; }select { min-height:44px; padding:8px; margin-left:10px; border:1px solid #b9ced5; border-radius:5px; color:inherit; background:white; max-width:100%; }.round-submit-actions { display:flex; flex-wrap:wrap; gap:12px; align-items:center; padding:16px 0; }
.round-result-nodes { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; }.round-result-nodes article { border:1px solid #d9e4eb; border-radius:8px; background:white; padding:18px; }.round-result-nodes strong { font-size:26px; }.round-result-nodes h4 { margin:8px 0; }.round-result-nodes p { font-size:14px; line-height:1.7; }.round-choice { margin:20px 0; padding:18px; background:white; border:1px solid #d9e4eb; border-radius:8px; }.round-choice :deep(.el-checkbox-group),.round-targets { display:flex; flex-wrap:wrap; gap:8px 18px; margin:14px 0; }.round-targets :deep(.el-radio),.round-choice :deep(.el-checkbox) { min-height:44px; height:auto; white-space:normal; }.round-error { color:#a13030; line-height:1.7; }select:focus-visible { outline:2px solid #086575; outline-offset:3px; }
</style>
