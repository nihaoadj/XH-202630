<template>
  <section class="workflow-timeline" aria-label="工作流进度">
    <el-alert v-if="legacyPartial" title="该历史 Run 的事件记录不完整，仅展示真实存在的事件。" type="warning" :closable="false" show-icon class="timeline-alert" />
    <section class="resource-progress-tree" aria-label="资源状态">
      <div class="delivery-heading">
        <svg class="delivery-symbol" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5v-9Zm0 0 8 4.5 8-4.5M12 12v9M8 5.25l8 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
        <h4 class="phase-name">资源状态</h4>
        <span class="delivery-count"><span>已发布</span><strong>{{ progressSummary.published }}<small> / {{ progressSummary.total }}</small></strong></span>
      </div>
      <ResourceExecutionProgressList
        :executions="statusItems" :review-enabled="reviewEnabled"
        :retrying-key="retryingResourceKey" :retry-enabled="retryEnabled" :claim-reports="claimReports"
        @open-resource="$emit('open-resource', $event)" @retry-resource="$emit('retry-resource', $event)"
        @open-claim-report="$emit('open-claim-report', $event)" @inspect-resource="$emit('inspect-resource', $event)"
      />
    </section>
    <WorkflowExecutionGraph :trace="trace" @inspect-step="$emit('inspect-step', $event)" />
    <nav v-if="childRuns.length" class="workflow-followups" aria-label="后续生成任务">
      <button v-for="child in childRuns" :key="child.run_id" type="button" @click="$emit('open-child-run', child.run_id)">
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M4 4v6a3 3 0 0 0 3 3h9m-4-4 4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
        <span>查看后续生成</span><small>{{ child.run_id.slice(0, 8).toUpperCase() }}</small>
      </button>
    </nav>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import ResourceExecutionProgressList from './ResourceExecutionProgressList.vue'
import WorkflowExecutionGraph from './WorkflowExecutionGraph.vue'
import { normalizeResourceProgressSummary } from '../../utils/generationDisplay'
import { buildResourceStatusItems } from './resourceStatusPresentation.js'
const props = defineProps({
  trace: { type: Array, default: () => [] }, childRuns: { type: Array, default: () => [] },
  legacyPartial: Boolean,
  resourceExecutions: { type: Array, default: () => [] }, resourceProgressSummary: { type: Object, default: null },
  retryingResourceKey: { type: String, default: '' }, retryEnabled: Boolean,
  claimReports: { type: Object, default: () => ({}) },
  requestedResourceTypes: { type: Array, default: () => [] }, jobStatus: { type: String, default: '' },
  publishedResources: { type: Array, default: () => [] }, runId: { type: String, default: '' },
  reviewEnabled: { type: Boolean, default: true },
})
defineEmits(['open-child-run', 'open-resource', 'retry-resource', 'open-claim-report', 'inspect-resource', 'inspect-step'])
const statusItems = computed(() => buildResourceStatusItems(props.resourceExecutions, {
  requestedTypes: props.requestedResourceTypes, jobStatus: props.jobStatus,
  resources: props.publishedResources, runId: props.runId,
  claimReports: props.claimReports,
}))
const progressSummary = computed(() => normalizeResourceProgressSummary(props.resourceProgressSummary, statusItems.value))
</script>

<style scoped>
.workflow-timeline { display:grid; gap:14px; min-width:0; color:#172c45; }
.timeline-alert { margin-bottom:0; }
.resource-progress-tree { --delivery-ink:#172c45; --delivery-muted:#59697b; --delivery-accent:#176b70; min-width:0; padding:0 10px 10px; border:1px solid #dce7eb; border-radius:10px; background:#f3f7fa; }
.delivery-heading { display:flex; align-items:center; gap:8px; min-height:44px; }
.delivery-symbol { width:18px; height:18px; flex:none; color:var(--delivery-accent); }
.phase-name { margin:0; color:var(--delivery-ink); font-size:13px; font-weight:600; line-height:1.5; }
.delivery-count { display:flex; align-items:center; gap:8px; margin-left:auto; color:var(--delivery-muted); font-size:12px; white-space:nowrap; }
.delivery-count strong { color:var(--delivery-accent); font:600 16px/1.2 Consolas,monospace; }
.delivery-count small { color:var(--delivery-muted); font:400 12px/1.2 Consolas,monospace; }
.workflow-followups { display:flex; flex-wrap:wrap; gap:8px; }
.workflow-followups button { display:flex; align-items:center; gap:8px; min-height:44px; max-width:100%; padding:8px 4px; border:0; background:transparent; color:#176b70; text-align:left; font-family:inherit; font-size:13px; font-weight:500; line-height:1.5; cursor:pointer; }
.workflow-followups button svg { width:20px; height:20px; flex:none; }
.workflow-followups button small { color:#59697b; font:12px/1.5 Consolas,monospace; overflow-wrap:anywhere; }
.workflow-followups button:hover span { text-decoration:underline; text-underline-offset:4px; }
.workflow-followups button:focus-visible { outline:2px solid #176b70; outline-offset:2px; }
@media (max-width:420px) { .delivery-count { gap:6px; } }
</style>
