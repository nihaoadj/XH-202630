<template>
  <section ref="pickerRoot" class="workflow-timeline" aria-label="工作流进度">
    <el-alert v-if="legacyPartial" title="该历史 Run 的事件记录不完整，仅展示真实存在的事件。" type="warning" :closable="false" show-icon class="timeline-alert" />
    <nav v-if="statusItems.length" class="resource-chain-picker workspace-glass-control" aria-label="选择资源执行链路">
      <button v-for="(item, index) in statusItems" :key="item.key" type="button"
        :class="`tone-${phaseMeta(item).type}`" :title="`${resourceName(item, index)} · ${phaseMeta(item).label}`"
        :aria-pressed="selectedResource?.key === item.key && !batchMode"
        :aria-label="`${resourceName(item, index)}，${phaseMeta(item).label}，查看执行链路`"
        @click="selectResource(item.key)">
        <strong>{{ resourceName(item, index) }}</strong>
      </button>
      <el-dropdown v-if="statusItems.length" trigger="click" class="resource-menu" @command="resourceCommand">
        <button type="button" class="resource-actions-trigger" aria-label="所选资源操作">···</button>
        <template #dropdown><el-dropdown-menu>
          <el-dropdown-item command="batch">{{ batchMode ? '返回资源链路' : '查看批次记录' }}</el-dropdown-item>
          <el-dropdown-item v-for="action in resourceActions" :key="action.key" :command="action.key">{{ action.label }}</el-dropdown-item>
        </el-dropdown-menu></template>
      </el-dropdown>
    </nav>
    <p v-if="!batchMode && resourceWorkflow.omitted" class="chain-record-note" role="status">部分步骤缺少明确关联，完整过程可查看批次记录。</p>
    <WorkflowExecutionGraph :key="`${runId}:${batchMode ? 'batch' : selectedResource?.key || 'empty'}`" :trace="visibleTrace" :resource-sequence="!batchMode && Boolean(selectedResource)"
      :empty-label="selectedResource ? '等待本资源的关联执行记录' : '等待执行记录'"
      @inspect-step="$emit('inspect-step', $event)" />
    <nav v-if="childRuns.length" class="workflow-followups" aria-label="后续生成任务">
      <button v-for="child in childRuns" :key="child.run_id" type="button" @click="$emit('open-child-run', child.run_id)">
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M4 4v6a3 3 0 0 0 3 3h9m-4-4 4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
        <span>查看后续生成</span><small>{{ child.run_id.slice(0, 8).toUpperCase() }}</small>
      </button>
    </nav>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import WorkflowExecutionGraph from './WorkflowExecutionGraph.vue'
import { buildResourceStatusItems, resourceStatusMeta } from './resourceStatusPresentation.js'
import { buildResourceWorkflow } from './resourceWorkflowPresentation.js'
const props = defineProps({
  trace: { type: Array, default: () => [] }, childRuns: { type: Array, default: () => [] },
  resourceEvents: { type: Array, default: () => [] }, resourceVersions: { type: Array, default: () => [] },
  resourceReviews: { type: Array, default: () => [] },
  legacyPartial: Boolean,
  resourceExecutions: { type: Array, default: () => [] },
  retryEnabled: Boolean,
  claimReports: { type: Object, default: () => ({}) },
  requestedResourceTypes: { type: Array, default: () => [] }, jobStatus: { type: String, default: '' },
  publishedResources: { type: Array, default: () => [] }, runId: { type: String, default: '' },
  reviewEnabled: { type: Boolean, default: true },
})
const emit = defineEmits(['open-child-run', 'open-resource', 'open-claim-report', 'inspect-resource', 'inspect-step', 'resource-change', 'select-resource'])
const selectedResourceKey = ref('')
const batchMode = ref(false)
const pickerRoot = ref(null)
const statusItems = computed(() => buildResourceStatusItems(props.resourceExecutions.filter(item => !item.run_id || item.run_id === props.runId), {
  requestedTypes: props.requestedResourceTypes, jobStatus: props.jobStatus,
  resources: props.publishedResources, runId: props.runId,
  claimReports: props.claimReports,
}))
const selectedResource = computed(() => statusItems.value.find(item => item.key === selectedResourceKey.value) || null)
watch(statusItems, (items, previous = []) => {
  if (items.some(item => item.key === selectedResourceKey.value)) return
  const old = previous.find(item => item.key === selectedResourceKey.value)
  const replacement = old?.request_placeholder && items.filter(item => item.resource_type === old.resource_type).length === 1
    ? items.find(item => item.resource_type === old.resource_type) : items[0]
  selectedResourceKey.value = replacement?.key || ''
  if (old && !old.request_placeholder) emit('resource-change')
}, { immediate: true })
watch(selectedResource, resource => emit('select-resource', { runId: props.runId, resource }), { immediate: true })
watch(() => props.runId, () => { batchMode.value = false; selectedResourceKey.value = ''; emit('resource-change') }, { flush: 'sync' })
const resourceActions = computed(() => {
  const item = selectedResource.value
  if (!item || item.request_placeholder) return []
  const actions = []
  if (item.readable_resource_id) actions.push({ key: 'open', label: '查看已发布资源' })
  if (item.resource_id && props.claimReports[item.resource_id]) actions.push({ key: 'report', label: '查看审核报告' })
  actions.push({ key: 'details', label: '查看过程详情' })
  return actions
})
const resourceWorkflow = computed(() => buildResourceWorkflow({
  trace: props.trace, events: props.resourceEvents, versions: props.resourceVersions,
  reviews: props.resourceReviews, resource: selectedResource.value, runId: props.runId,
}))
const visibleTrace = computed(() => batchMode.value || !selectedResource.value
  ? props.trace.filter(item => !item.run_id || item.run_id === props.runId) : resourceWorkflow.value.trace)
function phaseMeta(item) {
  return resourceStatusMeta(item, { retryEnabled: props.retryEnabled, reviewEnabled: props.reviewEnabled })
}
function resourceName(item, index) {
  return statusItems.value.filter(other => other.resource_type === item.resource_type).length > 1
    ? `${item.resource_type} · 资源 ${index + 1}` : item.resource_type
}
function selectResource(key) {
  if (key === selectedResourceKey.value && !batchMode.value) return
  emit('resource-change')
  batchMode.value = false
  selectedResourceKey.value = key
  // Keep the selection and its card visible; status-only updates never scroll.
  nextTick(() => { const scroller = pickerRoot.value?.closest('.process-scroll'); if (scroller) scroller.scrollTop = 0 })
}
function toggleBatch() {
  emit('resource-change')
  batchMode.value = !batchMode.value
}
function resourceCommand(command) {
  if (command === 'batch') { toggleBatch(); return }
  const item = selectedResource.value
  if (!item || !resourceActions.value.some(action => action.key === command)) return
  if (command === 'open') emit('open-resource', item)
  if (command === 'report') emit('open-claim-report', item.resource_id)
  if (command === 'details') emit('inspect-resource', item)
}
</script>

<style scoped>
.workflow-timeline { display:grid; gap:14px; min-width:0; color:#172c45; }
.resource-chain-picker { display:flex; flex-wrap:wrap; align-items:center; gap:4px; min-width:0; padding:4px; }
.resource-chain-picker button { --resource-tone:#7b8c9c; position:relative; display:flex; align-items:center; justify-content:center; gap:7px; min-height:36px; min-width:0; max-width:100%; padding:8px 12px; border:1px solid transparent; border-radius:6px; background:transparent; text-align:left; color:#59697b; font:inherit; font-size:12px; line-height:1.5; cursor:pointer; overflow-wrap:anywhere; }
.resource-chain-picker button strong { font-weight:500; }
.resource-chain-picker button.tone-success { --resource-tone:#176b70; }.resource-chain-picker button.tone-warning { --resource-tone:#ad752c; }.resource-chain-picker button.tone-danger { --resource-tone:#b34841; }
.resource-chain-picker > button::before { content:''; width:5px; height:5px; flex:none; border-radius:50%; background:#81909e; }
.resource-chain-picker button:hover { color:#172c45; background:#ffffff80; }
.resource-chain-picker > button[aria-pressed="true"] {
  color:#14515a;
  background:transparent;
}
.resource-chain-picker > button[aria-pressed="true"]::after {
  content:'';
  position:absolute;
  inset:auto 0 3px;
  width:20px;
  margin-inline:auto;
  height:2px;
  border-radius:2px;
  background:linear-gradient(90deg,#287e82,#72b5af);
  pointer-events:none;
}
.resource-chain-picker > button[aria-pressed="true"]::before {
  background:var(--resource-tone);
  transform:scale(1.15);
  box-shadow:0 0 0 2px color-mix(in srgb,var(--resource-tone) 20%,transparent);
}
.resource-chain-picker > button[aria-pressed="true"] strong { font-weight:650; }
.resource-chain-picker button:focus-visible { outline:2px solid #176b70; outline-offset:1px; }
.resource-menu { margin-left:auto; align-self:center; }
.resource-chain-picker .resource-actions-trigger { min-width:30px; padding:3px 6px; color:#59697b; font-size:18px; letter-spacing:1px; line-height:1; }
.chain-record-note { margin:0; color:#59697b; font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
.chain-record-note { margin:-6px 0 0; color:#59697b; font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
.chain-record-note { padding:8px 10px; border-left:2px solid #c7d9df; background:#f5f9fb; }
@media(pointer:coarse),(max-width:720px) { .resource-chain-picker button { min-height:44px; } }
.timeline-alert { margin-bottom:0; }
.workflow-followups { display:flex; flex-wrap:wrap; gap:8px; }
.workflow-followups button { display:flex; align-items:center; gap:8px; min-height:44px; max-width:100%; padding:8px 4px; border:0; background:transparent; color:#176b70; text-align:left; font-family:inherit; font-size:13px; font-weight:500; line-height:1.5; cursor:pointer; }
.workflow-followups button svg { width:20px; height:20px; flex:none; }
.workflow-followups button small { color:#59697b; font:12px/1.5 Consolas,monospace; overflow-wrap:anywhere; }
.workflow-followups button:hover span { text-decoration:underline; text-underline-offset:4px; }
.workflow-followups button:focus-visible { outline:2px solid #176b70; outline-offset:2px; }
</style>
