<template>
  <div class="next-round-choice" :class="{ 'is-compact': compact }">
    <div class="next-round-layout" :class="{ 'with-map': hasSelection, 'is-preview': !creationEnabled }">
      <div v-if="$slots.heading" class="next-round-heading"><slot name="heading" /></div>
      <div v-if="hasSelection" class="next-round-maps">
        <div class="next-round-field">
          <span>主节点（选 1 个）</span>
          <el-select v-if="compact" v-model="primaryNodeId" class="feedback-route-select" aria-label="主节点" placeholder="选择主节点" :disabled="unavailable" fit-input-width popper-class="refined-select-dropdown feedback-node-dropdown">
            <el-option
              v-for="node in primaryCandidates"
              :key="node.skill_node_id"
              :value="node.skill_node_id"
              :label="`${node.name} · 第 ${node.tier} 阶${intent === 'downgrade_learning' ? '（当前节点前置）' : ''}`"
            />
          </el-select>
          <SelectableNodeMap v-else v-model="primaryNodeId" :nodes="primaryCandidates" label="主节点" :disabled="unavailable" />
          <p v-if="compact && primaryNode && intent === 'downgrade_learning' && activeTier && primaryNode.tier < activeTier">
            确认后切换到第 {{ primaryNode.tier }} 阶。
          </p>
        </div>
        <div v-if="creationEnabled" class="next-round-review">
          <span class="next-round-review-label">副节点（可选）</span>
          <el-select
            v-model="reviewNodeId"
            class="feedback-route-select"
            aria-label="副节点"
            placeholder="不附带复习（可选）"
            clearable
            :disabled="unavailable || !reviewCandidates.length"
            fit-input-width
            popper-class="refined-select-dropdown feedback-node-dropdown"
          >
            <el-option label="不附带复习（可选）" value="" />
            <el-option v-for="node in reviewCandidates" :key="node.skill_node_id" :value="node.skill_node_id" :label="`${node.name} · 第 ${node.tier} 阶（复习清单+分阶测试）`" />
          </el-select>
          <p v-if="!reviewCandidates.length" class="next-round-review-hint">当前没有符合复习资格的其他节点。</p>
        </div>
      </div>
      <div class="next-round-settings">
        <p v-if="loadState === 'loading'" role="status">正在读取下一轮候选节点…</p>
        <div v-else-if="loadState === 'failed'">
          <p role="alert">下一轮候选暂时无法读取。</p>
          <el-button @click="load">重新读取</el-button>
        </div>
        <div v-else-if="!creationEnabled && hasSelection" class="next-round-preview">
          <template v-if="compact && primaryNode">
            <span>节点预览</span>
            <strong>{{ primaryNode.name }}</strong>
            <p>第 {{ primaryNode.tier }} 阶<span v-if="primaryNode.mastery_score != null"> · 掌握度 {{ Math.round(primaryNode.mastery_score * 100) }}%</span></p>
          </template>
          <p role="status">候选节点可预览。当前环境未启用下一轮学习创建。</p>
        </div>
        <div v-else-if="hasSelection" class="next-round-field">
          <span>主节点资源</span>
          <el-checkbox-group v-model="resourceTypes" class="next-round-resources" aria-label="主节点资源" :disabled="unavailable">
            <el-checkbox v-for="type in resourceOptions" :key="type" :label="type" :aria-label="type">
              <span v-if="compact" class="resource-option">
                <el-icon aria-hidden="true"><component :is="resourceTypeVisuals[type].icon" /></el-icon>
                <strong>{{ type }}</strong>
                <span>{{ resourceTypeVisuals[type].description }}</span>
              </span>
              <template v-else>{{ type }}</template>
            </el-checkbox>
          </el-checkbox-group>
        </div>
        <p v-else role="status">当前没有符合学习条件的主节点。测评结论和节点资格分别计算。</p>
        <slot v-if="creationEnabled && hasSelection" />
        <p v-if="error" class="next-round-error" role="alert">{{ error }}</p>
        <div v-if="creationEnabled && hasSelection" class="next-round-actions">
          <slot name="actions-left" />
          <el-button class="next-round-generate" type="primary" :loading="busy" :disabled="unavailable || !primaryNodeId || !resourceTypes.length" @click="submit">
            生成下一轮已选资源
            <el-icon v-if="!busy" class="el-icon--right" aria-hidden="true"><ArrowRight /></el-icon>
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../../stores/app'
import { resourceTypeVisuals } from '../../components/resourceTypeVisuals.js'
import { roundGenerationApi } from '../generation/roundApi.js'
import { roundFeedbackApi } from './roundApi.js'
import SelectableNodeMap from './SelectableNodeMap.vue'
import { nextRoundLearning, isSelectable } from './nextRoundLearning.js'
import { chosenRouteLabel, confirmedRouteKey, readConfirmedRoute, saveConfirmedRoute } from './confirmedRoute.js'

const props = defineProps({
  learnerId: { type: String, required: true },
  sourceAttemptId: { type: String, required: true },
  roundId: { type: String, default: '' },
  candidates: { type: Object, default: null },
  recommendedIntent: { type: String, default: '' },
  assessmentAction: { type: String, default: '' },
  blocked: Boolean,
  compact: Boolean,
  claimOptions: { type: Object, default: () => ({}) },
  confirmedSelection: { type: Object, default: null },
})
const emit = defineEmits(['busy', 'confirmed'])
const router = useRouter()
const store = useAppStore()
const loadedCandidates = ref(null)
const loadState = ref('loading')
const creationEnabled = ref(false)
const busy = ref(false)
const error = ref('')
const primaryNodeId = ref('')
const reviewNodeId = ref('')
const resourceOptions = ['讲义', '实操指南', '分阶测试题', '复习清单', '案例分析']
const resourceTypes = ref(['讲义', '实操指南', '分阶测试题'])
const confirmationKey = confirmedRouteKey(store.currentUserId, props.learnerId, props.sourceAttemptId)
const confirmed = ref(props.confirmedSelection || readConfirmedRoute(localStorage, confirmationKey))
if (confirmed.value?.route === 'learning') {
  primaryNodeId.value = confirmed.value.payload.primary_node_id
  reviewNodeId.value = confirmed.value.payload.review_node_id || ''
  resourceTypes.value = [...confirmed.value.payload.primary_resource_types]
}
const actionKeys = new Map()
let disposed = false

const unavailable = computed(() => !creationEnabled.value || busy.value || props.blocked || Boolean(confirmed.value))
const candidates = computed(() => confirmed.value?.candidates || props.candidates || loadedCandidates.value)
const activeTier = computed(() => candidates.value?.generation_options?.tier_progress?.active_tier)
const learning = computed(() => nextRoundLearning(candidates.value, props.assessmentAction, props.recommendedIntent))
const intent = computed(() => learning.value.intent)
const primaryCandidates = computed(() => learning.value.nodes)
const primaryNode = computed(() => primaryCandidates.value.find(node => node.skill_node_id === primaryNodeId.value))
const hasSelection = computed(() => loadState.value === 'ready' && primaryCandidates.value.length > 0)
const reviewCandidates = computed(() => (candidates.value?.eligible_review_nodes || [])
  .filter(node => node.skill_node_id !== primaryNodeId.value && isSelectable(node)))

watch(primaryCandidates, (value) => {
  if (confirmed.value) return
  if (value.some(node => node.skill_node_id === primaryNodeId.value)) return
  const preferred = candidates.value?.generation_options?.recommended_node_ids || []
  const repairId = learning.value.repairNodeId
  primaryNodeId.value = (value.find(node => node.skill_node_id === repairId)
    || value.find(node => preferred.includes(node.skill_node_id)) || value[0])?.skill_node_id || ''
}, { immediate: true })
watch(reviewCandidates, (value) => {
  if (confirmed.value) return
  if (reviewNodeId.value && !value.some(node => node.skill_node_id === reviewNodeId.value)) reviewNodeId.value = ''
})

async function load() {
  loadState.value = 'loading'
  try {
    const capability = await roundGenerationApi.capabilities()
    if (disposed) return
    creationEnabled.value = capability.data.round_creation_enabled
    if (!props.candidates) {
      const response = await roundFeedbackApi.nextCandidates(props.learnerId, props.sourceAttemptId)
      if (disposed) return
      loadedCandidates.value = response.data
    }
    loadState.value = 'ready'
  } catch {
    if (!disposed) loadState.value = 'failed'
  }
}

function selectionKey(payload) {
  const identity = `round-action:${store.currentUserId || ''}:${props.learnerId}:${props.roundId || props.sourceAttemptId}:next:${JSON.stringify(payload)}`
  if (!actionKeys.has(identity)) {
    let stored = ''
    try { stored = sessionStorage.getItem(identity) || '' } catch { /* Memory fallback. */ }
    const key = stored || `round-next-${crypto.randomUUID()}`
    actionKeys.set(identity, key)
    try { sessionStorage.setItem(identity, key) } catch { /* Memory fallback. */ }
  }
  return actionKeys.get(identity)
}

async function submit() {
  if (unavailable.value || !primaryNode.value || !resourceTypes.value.length) return
  busy.value = true
  emit('busy', true)
  error.value = ''
  const payload = {
    learner_id: props.learnerId,
    source_attempt_id: props.sourceAttemptId,
    primary_node_id: primaryNodeId.value,
    primary_learning_intent: intent.value,
    ...(learning.value.repairNodeId === primaryNodeId.value ? { follow_remediation: true } : {}),
    primary_resource_types: [...resourceTypes.value],
    review_node_id: reviewNodeId.value || null,
    ...props.claimOptions,
  }
  try {
    const { data } = await roundFeedbackApi.next({ ...payload, selection_key: selectionKey(payload) })
    if (disposed) return
    const primary = data.members.find(member => member.role === 'primary')
    const runId = data.primary_default_run_id || primary?.job_ids[0]
    if (!primary || !runId) throw new Error('下一轮响应缺少主学习任务。')
    confirmed.value = { confirmed: true, route: 'learning', label: chosenRouteLabel(payload.primary_learning_intent), payload,
      candidates: JSON.parse(JSON.stringify(candidates.value)),
      roundId: data.round_id, stageId: data.stage_id, runId }
    saveConfirmedRoute(localStorage, confirmationKey, confirmed.value)
    emit('confirmed', confirmed.value)
    await router.push({ path: '/generate', query: {
      learnerId: props.learnerId, roundId: data.round_id, stageId: data.stage_id, memberId: primary.member_id, runId,
    } })
  } catch (caught) {
    if (!disposed) error.value = caught?.response?.data?.message || caught?.response?.data?.detail || caught.message || '下一轮确认失败。'
  } finally {
    if (!disposed) {
      busy.value = false
      emit('busy', false)
    }
  }
}

load()
onBeforeUnmount(() => {
  disposed = true
  if (busy.value) emit('busy', false)
})
</script>

<style scoped>
.next-round-choice { min-width: 0; container: next-round / inline-size; }
.next-round-layout, .next-round-maps, .next-round-settings, .next-round-field {
  display: grid;
  min-width: 0;
  align-content: start;
  gap: 12px;
}
.next-round-heading { min-width: 0; }
.next-round-field { gap: 7px; }
.next-round-field > span { font-size: 13px; font-weight: 650; }
.next-round-choice p { margin: 0; font-size: 13px; line-height: 1.6; }
.next-round-resources { display: flex; flex-wrap: wrap; min-width: 0; gap: 8px; }
.next-round-choice :deep(:is(.el-radio, .el-checkbox)) { min-height: 44px; height: auto; min-width: 0; max-width: 100%; margin: 0; }
.next-round-resources :deep(.el-checkbox) { padding: 8px 12px; border: 1px solid #d0dfe6; border-radius: 6px; background: #f9fbfc; }
.next-round-choice :deep(:is(.el-radio__label, .el-checkbox__label)) { min-width: 0; white-space: normal; overflow-wrap: anywhere; }
.next-round-choice :deep(.el-button) { min-height: 44px; max-width: 100%; white-space: normal; }
.next-round-review { display: grid; gap: 4px; padding: 8px 12px 12px; border: 1px solid #d0dfe6; border-radius: 8px; }
.next-round-actions { padding-top: 10px; border-top: 1px solid #d0dfe6; }
.next-round-error { color: #a13030; overflow-wrap: anywhere; }
.next-round-preview { display: grid; align-content: center; min-width: 0; gap: 5px; overflow-wrap: anywhere; }
.is-compact .next-round-preview { padding: 12px 14px; border: 1px solid #d5e3f4; border-radius: 9px; background: #f5f9ff; }
.next-round-preview > span { color: #456688; font-size: 12px; font-weight: 650; }
.next-round-preview [role="status"] { color: #506982; }
.is-compact :is(.next-round-field, .next-round-review) :deep(.el-select) { width: 100%; }
.is-compact :is(.next-round-field, .next-round-review) :deep(.el-select__wrapper) {
  min-height: 44px;
  border-radius: 10px;
  background: linear-gradient(155deg, #fff, #f7fbff 62%, #eef6ff);
  box-shadow:
    0 0 0 1px #8fb3da inset,
    inset 0 1px 0 #fff,
    inset 0 -1px 0 rgb(104 145 191 / 22%),
    0 2px 4px rgb(30 63 104 / 14%),
    0 8px 16px -8px rgb(59 112 175 / 32%),
    0 18px 30px -22px rgb(30 63 104 / 55%);
}
.is-compact :is(.next-round-field, .next-round-review) :deep(.el-select__wrapper:hover) { box-shadow: 0 0 0 1px #8fb3da inset, inset 0 1px 0 #fff, 0 2px 6px rgb(30 63 104 / 12%), 0 12px 20px -14px rgb(30 63 104 / 42%); }
.is-compact :is(.next-round-field, .next-round-review) :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px #3b70af inset, inset 0 1px 0 #fff, 0 2px 8px rgb(59 112 175 / 24%), 0 12px 22px -14px rgb(59 112 175 / 38%);
}
.next-round-review-label { font-size: 13px; font-weight: 650; }
.next-round-review-hint { color: var(--feedback-muted); }
@container next-round (min-width: 720px) {
  .next-round-layout.with-map {
    grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr);
    grid-template-areas: "heading maps" "settings maps";
    grid-template-rows: auto 1fr;
    column-gap: clamp(16px, 2.2cqw, 28px);
  }
  .next-round-heading { grid-area: heading; }
  .next-round-maps { grid-area: maps; padding-inline-start: clamp(16px, 2.2cqw, 28px); border-inline-start: 1px solid #d6e3ea; }
  .with-map .next-round-settings { grid-area: settings; }
  .with-map:not(:has(.next-round-heading)) .next-round-settings { grid-row: 1 / -1; }
}
@media (max-width: 760px) { .next-round-actions :deep(.el-button) { width: 100%; } }
.is-compact .next-round-layout,
.is-compact .next-round-maps,
.is-compact .next-round-settings { gap: 6px; }
.is-compact .next-round-resources {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 155px), 1fr));
  gap: 6px;
}
.is-compact .next-round-resources :deep(.el-checkbox) {
  position: relative;
  min-height: 60px;
  padding: 8px 11px;
  align-items: flex-start;
  border: 1px solid transparent;
  border-radius: 12px;
  background:
    linear-gradient(158deg, #fdfeff, #f3f9ff 60%, #e9f3ff) padding-box,
    linear-gradient(145deg, #fff, #b7d1ea 48%, #7ea4d0) border-box;
  box-shadow:
    inset 0 1px 0 #fff,
    inset 0 -1px 0 rgb(104 145 191 / 16%),
    0 2px 5px rgb(30 63 104 / 12%),
    0 6px 14px -9px rgb(59 112 175 / 26%),
    0 14px 24px -18px rgb(30 63 104 / 48%);
}
.is-compact .next-round-resources :deep(.el-checkbox__input) { position: absolute; inset: 9px 9px auto auto; }
.is-compact .next-round-resources :deep(.el-checkbox__label) { width: 100%; padding: 0; color: var(--feedback-ink); }
.is-compact .next-round-resources :deep(.el-checkbox.is-checked) {
  background:
    linear-gradient(155deg, #fcfdff, #e8f2ff 62%, #daebff) padding-box,
    linear-gradient(145deg, #eaf5ff, #8db0d8 42%, #5c88bd) border-box;
  box-shadow:
    inset 0 1px 0 #fff,
    inset 0 0 0 1px rgb(255 255 255 / 46%),
    inset 0 -1px 0 rgb(84 128 178 / 18%),
    0 3px 7px rgb(30 63 104 / 16%),
    0 8px 16px -10px rgb(59 112 175 / 30%),
    0 16px 26px -16px rgb(30 63 104 / 54%);
}
.is-compact .next-round-resources :deep(.el-checkbox:not(.is-disabled):hover) { border-color: #7299ca; }
.is-compact .next-round-resources :deep(.el-checkbox:has(input:focus-visible)) {
  outline: 2px solid var(--feedback-navy);
  outline-offset: 2px;
}
.resource-option { display: grid; grid-template-columns: 20px minmax(0, 1fr); align-items: center; gap: 4px 6px; }
.resource-option > .el-icon { font-size: 18px; color: var(--feedback-navy); }
.resource-option > strong { padding-inline-end: 15px; font-size: 13px; font-weight: 650; }
.resource-option > span { grid-column: 1 / -1; color: var(--feedback-muted); font-size: 12px; line-height: 1.35; }
.is-compact .next-round-review { padding: 2px 10px; background: #f8fafc; }
.is-compact .next-round-actions { display: flex; justify-content: flex-end; padding-top: 6px; }
@container next-round (min-width: 760px) {
  .is-compact .next-round-layout {
    grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
    grid-template-areas: "heading heading" "maps settings";
    grid-template-rows: auto auto;
    gap: 8px 16px;
  }
  .is-compact .next-round-layout.with-map:not(:has(.next-round-heading)) {
    grid-template-areas: "maps settings";
    grid-template-rows: auto;
  }
  .is-compact .next-round-layout:not(.with-map) {
    grid-template-areas: "heading settings";
  }
  .is-compact .next-round-settings { grid-area: settings; }
  .is-compact .next-round-maps { padding-inline-start: 0; border-inline-start: 0; }
  .is-compact .is-preview .next-round-settings { align-content: stretch; }
  .is-compact .next-round-review { padding: 0 8px 4px; }
}
/* Round feedback result: 主节点 / 副节点 side by side, five resources on the next row,
   optional claim switches and the route action on the last row. */
.round-feedback-result .is-compact .next-round-layout.with-map,
.round-feedback-result .is-compact .next-round-layout.with-map:not(:has(.next-round-heading)) {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  grid-template-areas:
    "primary review"
    "resources resources"
    "actions actions";
  grid-template-rows: auto;
  gap: 10px 16px;
}
.round-feedback-result .is-compact .next-round-layout.with-map > .next-round-maps,
.round-feedback-result .is-compact .next-round-layout.with-map > .next-round-settings { display: contents; }
.round-feedback-result .is-compact .next-round-layout.with-map .next-round-maps > .next-round-field { grid-area: primary; }
.round-feedback-result .is-compact .next-round-layout.with-map .next-round-maps > .next-round-review {
  display: grid;
  align-content: start;
  grid-area: review;
  gap: 7px;
  padding: 0;
  border: 0;
  background: transparent;
}
.round-feedback-result .is-compact .next-round-layout.with-map .next-round-review :deep(.el-checkbox) { min-height: 22px; height: auto; }
.round-feedback-result .is-compact .next-round-layout.with-map .next-round-review .next-round-review-hint { font-size: 12px; line-height: 1.4; }
.round-feedback-result .is-compact .next-round-layout.with-map .next-round-settings > .next-round-field { grid-area: resources; }
.round-feedback-result .is-compact .next-round-layout.with-map .next-round-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  grid-area: actions;
  gap: 10px 16px;
  padding-top: 8px;
}
@container next-round (min-width: 720px) {
  .round-feedback-result .is-compact .next-round-layout.with-map .next-round-settings > .next-round-field .next-round-resources { grid-template-columns: repeat(5, minmax(0, 1fr)); }
}
.round-feedback-result .is-compact .next-round-layout.with-map { align-content: space-between; min-height: 242px; }
@media (min-width: 1101px) and (min-height: 800px) {
  .round-feedback-result .is-compact .next-round-layout.with-map { min-height: 225px; row-gap: 6px; }
  .round-feedback-result .is-compact .next-round-field { gap: 5px; }
  .round-feedback-result .is-compact :is(.next-round-field, .next-round-review) :deep(.el-select__wrapper) { min-height: 40px; }
  .round-feedback-result .is-compact .next-round-layout.with-map .next-round-actions { padding-top: 6px; }
  .round-feedback-result .next-round-actions :deep(.next-round-generate) { min-height: 44px; padding-block: 10px; }
  .round-feedback-result .is-compact .next-round-resources :deep(.el-checkbox) {
    min-height: 64px;
    padding: 10px 14px;
    box-shadow: inset 0 1px 0 #fff, 0 3px 6px rgb(30 63 104 / 13%), 0 12px 20px -12px rgb(30 63 104 / 38%);
  }
  .round-feedback-result .is-compact .next-round-resources :deep(.el-checkbox.is-checked) {
    border-color: #7fa5d5;
    background: linear-gradient(145deg, #f7faff, #e5f0ff) padding-box, linear-gradient(145deg, #d5e7fb, #83a8d5) border-box;
    box-shadow: inset 0 1px 0 #fff, inset 0 0 0 1px rgb(255 255 255 / 58%), 0 3px 6px rgb(30 63 104 / 13%), 0 12px 20px -12px rgb(30 63 104 / 38%);
  }
  .round-feedback-result .is-compact .next-round-resources :deep(.el-checkbox__input) { inset: 9px 10px auto auto; }
  .round-feedback-result .is-compact .next-round-resources :deep(.el-checkbox__inner) { width: 20px; height: 20px; border-radius: 50%; }
  .round-feedback-result .is-compact .next-round-resources :deep(.el-checkbox__inner::after) {
    left: 50%;
    top: 50%;
    width: 9px;
    height: 9px;
    border: 0;
    border-radius: 0;
    background: #fff;
    clip-path: polygon(100% 11%, 44% 89%, 35% 95%, 0 57%, 16% 40%, 39% 62%, 84% 0);
    transform: translate(-50%, -50%) scale(0);
  }
  .round-feedback-result .is-compact .next-round-resources :deep(.el-checkbox__input.is-checked .el-checkbox__inner::after) {
    transform: translate(-50%, -50%) scale(1);
  }
  .round-feedback-result .is-compact .next-round-resources :deep(.is-checked .el-checkbox__inner) {
    border-color: #356ba8;
    background: linear-gradient(145deg, #6093cc, #3265a3);
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 42%), 0 2px 4px rgb(42 88 148 / 22%);
  }
  .round-feedback-result .is-compact .resource-option > strong { padding-right: 24px; }
}
.is-compact .next-round-resources :deep(.el-checkbox) {
  min-height: 76px;
  padding: 12px 14px;
  box-shadow: inset 0 1px 0 #fff, 0 3px 6px rgb(30 63 104 / 13%), 0 12px 20px -12px rgb(30 63 104 / 38%);
}
.is-compact .next-round-resources :deep(.el-checkbox.is-checked) {
  border-color: #6d99ce;
  background: linear-gradient(145deg, #f3f8ff, #d9e9ff);
  box-shadow: inset 0 1px 0 #fff, inset 0 -3px 0 #7fa5d5, 0 4px 8px rgb(30 63 104 / 18%), 0 15px 24px -14px rgb(42 88 148 / 46%);
}
.is-compact .next-round-resources :deep(.el-checkbox__inner) {
  width: 19px;
  height: 19px;
  border-radius: 6px;
  border-color: #b8cce4;
  background: #fff;
  box-shadow: inset 0 1px 2px rgb(30 63 104 / 8%);
}
.is-compact .next-round-resources :deep(.is-checked .el-checkbox__inner) {
  border-color: #477cb9;
  background: linear-gradient(145deg, #6199da, #3267a6);
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 40%), 0 2px 4px rgb(42 88 148 / 22%);
}
.is-compact .next-round-resources :deep(.el-checkbox__inner::after) { left: 6px; top: 3px; }
.is-compact .resource-option { padding-right: 9px; }
.is-compact .resource-option > strong { font-size: 14px; padding-right: 17px; }
.round-feedback-result .next-round-actions :deep(.next-round-generate) {
  min-height: 46px;
  padding: 12px 20px;
  border-radius: 12px;
  font-weight: 650;
  letter-spacing: .02em;
}
.round-feedback-result .next-round-actions :deep(.next-round-generate:not(.is-disabled)) {
  border-color: #35649e;
  background: linear-gradient(135deg, #5688c8, #315f98 65%, #244d80);
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 40%), 0 4px 8px rgb(42 88 148 / 20%), 0 12px 20px -12px rgb(30 63 104 / 45%);
}
.round-feedback-result .next-round-actions :deep(.next-round-generate:not(.is-disabled):hover) {
  background: linear-gradient(135deg, #689ada, #3b6da9 65%, #2a568a);
}
@media (max-width: 760px) {
  .round-feedback-result .is-compact .next-round-layout.with-map { min-height: 0; gap: 12px; }
}
</style>
