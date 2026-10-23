<template>
  <div class="resource-execution-list">
    <p v-if="!displayExecutions.length" class="execution-empty">暂无资源执行记录</p>
    <div v-else class="execution-grid">
      <article v-for="item in displayExecutions" :key="item.key" class="execution-card" :class="`is-${phaseMeta(item).type}`">
        <div class="execution-card-head">
          <svg class="execution-document" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Zm0 0v6h6M8 13h8M8 17h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
          <div class="execution-title">
            <strong>{{ item.resource_type || '学习资源' }}</strong>
            <span>{{ representationLabel(item.representation) }}</span>
          </div>
          <span class="execution-phase">
            <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path v-if="phaseMeta(item).type === 'success'" d="m3.5 8 3 3 6-6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
              <path v-else-if="phaseMeta(item).type === 'danger'" d="m5 5 6 6M11 5l-6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              <template v-else><circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.3" /><path d="M8 4.8v3.5l2 1.2" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" /></template>
            </svg>
            {{ phaseMeta(item).label }}
          </span>
        </div>

        <p v-if="item.learning_objective" class="execution-objective">{{ item.learning_objective }}</p>
        <div class="execution-status-line" role="status" aria-live="polite" aria-atomic="true">
          <span class="execution-status-context">{{ item.resource_type }}：{{ phaseMeta(item).label }}。</span>
          <span v-if="item.validation_status" class="execution-status-field"><small>校验</small><strong>{{ validationStatusLabel(item.validation_status) }}</strong></span>
          <span v-if="item.review_status" class="execution-status-field"><small>审核</small><strong>{{ reviewStatusLabel(item.review_status) }}</strong></span>
          <span class="execution-status-field"><small>发布状态</small><strong :class="{ 'is-published': item.publication_status === 'published' }">{{ publicationLabel(item) }}</strong></span>
          <span v-if="item.claim_metric_status" class="execution-status-field"><small>事实核验</small><strong>{{ claimStatusLabel(item.claim_metric_status) }}</strong></span>
        </div>
        <p v-if="isPublicationPending(item)" class="execution-notice claim-pending">
          <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m10 3 8 14H2L10 3Zm0 5v4m0 2v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg>
          待你决定发布
        </p>
        <p v-if="item.claim_warning_publish" class="execution-notice claim-warning">
          <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m10 3 8 14H2L10 3Zm0 5v4m0 2v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg>
          已带 Claim 警告发布
        </p>
        <p v-if="['failed', 'human_review', 'revision_requested'].includes(item.resource_execution_state) && (item.error_message || item.error_code)" class="execution-error">
          {{ item.error_message || `处理失败（${item.error_code}）` }}
        </p>

        <div v-if="item.attempt || item.agent_name || item.claim_factual_pass_rate != null" class="execution-meta">
          <span v-if="item.attempt">第 {{ item.attempt }} 次生成</span>
          <span v-if="item.agent_name">{{ resourceAgentLabel(item.agent_name) }}</span>
          <span v-if="item.claim_factual_pass_rate != null">已审事实通过 {{ percent(item.claim_factual_pass_rate) }}</span>
        </div>
        <div v-if="!item.request_placeholder" class="execution-actions">
          <el-button v-if="canOpen(item)" class="execution-primary" type="primary" aria-label="查看已发布资源" @click="$emit('open-resource', item)">
            查看资源<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h10m-4-4 4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg>
          </el-button>
          <el-button v-if="canShowClaimReport(item) && isPublicationPending(item)" class="execution-primary" type="primary" aria-label="查看审核报告" @click="$emit('open-claim-report', item.resource_id)">
            审核报告<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h10m-4-4 4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg>
          </el-button>
          <el-button
            v-if="canRetry(item)" class="execution-retry" type="warning"
            :class="canShowClaimReport(item) && isPublicationPending(item) ? 'execution-secondary' : 'execution-primary'"
            :loading="retryingKey === item.key" aria-label="重新生成此资源" @click="$emit('retry-resource', item)"
          >
            重新生成
          </el-button>
          <el-button v-if="canShowClaimReport(item) && !isPublicationPending(item)" class="execution-secondary" text type="primary" aria-label="查看审核报告" @click="$emit('open-claim-report', item.resource_id)">
            审核报告
          </el-button>
          <el-button class="execution-secondary" text type="primary" aria-label="查看过程详情" @click="$emit('inspect-resource', item)">过程详情</el-button>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { resourceRepresentationLabel } from '../../utils/generationDisplay'
import { resourceAgentLabel, resourceStatusMeta, validationStatusLabel } from './resourceStatusPresentation.js'

const props = defineProps({
  executions: { type: Array, default: () => [] },
  reviewEnabled: { type: Boolean, default: true },
  retryingKey: { type: String, default: '' },
  retryEnabled: { type: Boolean, default: true },
  claimReports: { type: Object, default: () => ({}) },
})

defineEmits(['open-resource', 'retry-resource', 'open-claim-report', 'inspect-resource'])

const displayExecutions = computed(() => props.executions.map(item => ({
  ...item,
  statusMeta: resourceStatusMeta({ ...item, claim_publish_decision_pending: isPublicationPending(item) }, {
    retryEnabled: props.retryEnabled, reviewEnabled: props.reviewEnabled,
  }),
})))

function representationLabel(representation) {
  return resourceRepresentationLabel(representation)
}

function phaseMeta(item) {
  return item.statusMeta
}

function publicationLabel(item) {
  if (item.publication_status !== 'published') return '尚未发布'
  return item.resource_execution_state === 'approved' ? '已发布' : '已有版本已发布'
}

function canOpen(item) {
  return item.resource_execution_state === 'approved'
    && item.publication_status === 'published'
    && Boolean(item.resource_id)
}

function canRetry(item) {
  return props.retryEnabled
    && Boolean(item.resource_spec_id)
    && ['failed', 'human_review', 'revision_requested'].includes(item.resource_execution_state)
}

function canShowClaimReport(item) {
  return Boolean(item.resource_id && props.claimReports[item.resource_id])
}

function isPublicationPending(item) {
  return Boolean(item.claim_publish_decision_pending ?? props.claimReports[item.resource_id]?.claim_publish_decision_pending)
}

function percent(value) {
  return `${(Number(value) * 100).toFixed(1)}%`
}

function claimStatusLabel(status) {
  return ({ complete: '已完成', incomplete: '未完成', not_applicable: '不适用' }[status] || status)
}

function reviewStatusLabel(status) {
  return ({ approved: '已通过', revision_requested: '需修订', rejected: '未通过', human_review: '待复核',
    skipped: '未启用', pending: '待审核' })[status] || status
}
</script>

<style scoped>
.resource-execution-list { --resource-ink:#172c45; --resource-muted:#59697b; --resource-accent:#176b70; --resource-line:#e1eaee; min-width:0; background:#f3f7fa; }
.execution-empty { margin:0; padding:12px 0; color:var(--resource-muted); font-size:12px; line-height:1.7; }
.execution-grid { display:grid; gap:10px; }
.execution-card { --execution-tone:var(--resource-muted); min-width:0; padding:10px; border:1px solid #d6e2e9; border-radius:8px; background:#fff; }
.execution-card.is-success,.execution-card.is-primary { --execution-tone:var(--resource-accent); }
.execution-card.is-warning { --execution-tone:#935719; }
.execution-card.is-danger { --execution-tone:#a1322c; }
.execution-card-head { display:grid; grid-template-columns:18px minmax(0,1fr) auto; align-items:start; gap:6px; }
.execution-document { width:18px; height:18px; margin-top:2px; color:var(--resource-accent); }
.execution-title { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 8px; min-width:0; }
.execution-title strong { color:var(--resource-ink); font-size:14px; font-weight:600; line-height:1.5; overflow-wrap:anywhere; }
.execution-title > span { color:var(--resource-muted); font-size:12px; line-height:1.7; }
.execution-phase { display:flex; align-items:center; gap:4px; max-width:120px; min-width:0; padding-top:1px; color:var(--execution-tone); font-size:12px; font-weight:500; line-height:1.6; overflow-wrap:anywhere; }
.execution-phase svg { width:16px; height:16px; flex:none; }
.execution-objective { margin:8px 0 0; color:var(--resource-muted); font-size:13px; line-height:1.8; overflow-wrap:anywhere; }
.execution-status-line { position:relative; display:flex; flex-wrap:wrap; gap:4px 12px; margin:8px 0 0; }
.execution-status-context { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; }
.execution-status-field { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 6px; min-width:0; max-width:100%; line-height:1.6; }
.execution-status-field small { color:var(--resource-muted); font-size:12px; }
.execution-status-field strong { color:var(--resource-ink); font-size:12px; font-weight:500; overflow-wrap:anywhere; }
.execution-status-field .is-published { color:var(--resource-accent); }
.execution-notice { display:flex; align-items:flex-start; gap:6px; margin:6px 0 0; color:#935719; font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
.execution-notice svg { width:18px; height:18px; margin-top:2px; flex:none; }
.execution-error { margin:6px 0 0; padding:6px 8px; border-radius:5px; background:#fff3f0; color:#a1322c; font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
.execution-actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin:8px 0 0; padding-top:8px; border-top:1px solid var(--resource-line); }
.resource-execution-list .execution-actions :deep(.el-button) { flex:0 1 auto; min-width:32px; min-height:34px; height:auto; max-width:100%; margin:0; padding:6px 8px; border-radius:5px; font-size:12px; font-weight:500; line-height:1.5; }
.resource-execution-list .execution-actions :deep(.el-button > span) { display:flex; justify-content:center; gap:6px; min-width:0; white-space:normal; overflow-wrap:anywhere; }
.execution-actions :deep(.execution-primary) { border:1px solid #bfdad6; background:#edf6f4; color:var(--resource-accent); }
.execution-actions :deep(.execution-primary:hover) { border-color:#8db9b0; background:#dfeeea; }
.execution-actions :deep(.execution-retry) { background:#fff3e3; color:#935719; }
.execution-actions :deep(.execution-retry:hover) { background:#ffeace; color:#774312; }
.execution-actions :deep(.execution-secondary) { border:1px solid transparent; background:transparent; color:var(--resource-accent); }
.execution-actions :deep(.execution-secondary.execution-retry) { background:#fff9f0; color:#935719; }
.execution-actions :deep(.execution-secondary:hover) { background:#eef5f6; }
.execution-actions :deep(.execution-secondary.execution-retry:hover) { background:#fff0da; color:#774312; }
.execution-actions svg { width:14px; height:14px; flex:none; align-self:center; }
.execution-actions :deep(.el-button:focus-visible) { outline:2px solid var(--resource-accent); outline-offset:2px; }
.execution-meta { display:flex; flex-wrap:wrap; gap:3px 12px; margin-top:4px; color:var(--resource-muted); font-size:12px; line-height:1.7; }
.execution-meta > span { min-width:0; max-width:100%; overflow-wrap:anywhere; }
.execution-meta .claim-pending { color:#935719; }
@media (pointer:coarse), (max-width:720px) { .resource-execution-list .execution-actions :deep(.el-button) { min-width:44px; min-height:44px; } }
@media (max-width:360px) { .execution-card-head { grid-template-columns:18px minmax(0,1fr); }.execution-phase { grid-column:2; max-width:none; } }
</style>
