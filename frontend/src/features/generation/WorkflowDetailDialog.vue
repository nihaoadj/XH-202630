<template>
  <el-dialog :model-value="visible" :title="detailTitle" class="workflow-detail-dialog" width="min(1120px, calc(100vw - 24px))" top="4vh" @update:model-value="$emit('update:visible', $event)">
    <template #header="{ titleId }">
      <div class="audit-dialog-heading">
        <svg class="detail-node-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path v-for="(path, index) in iconPaths(step ? role.key : 'review')" :key="index" :d="path" /></svg>
        <div class="detail-heading-copy"><span class="audit-header-code">{{ step ? `STEP ${step.step_sequence ?? step.sequence ?? '—'} / ${role.code}` : 'RESOURCE / REVIEW' }}</span><h2 :id="titleId">{{ detailTitle }}</h2></div>
        <div v-if="step" class="detail-execution-status"><strong :class="executionTone(step.status)">{{ reviewStatusLabel(step.status) }}</strong><span>{{ formatDuration(step.duration_ms) }}</span></div>
        <el-button class="audit-refresh" :loading="loading" @click="$emit('refresh')">刷新数据</el-button>
      </div>
    </template>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <p v-if="loading" class="audit-loading" role="status">正在加载执行详情…</p>
    <div v-else class="audit-workspace">
      <main class="audit-main" aria-label="执行详情正文">
        <div class="detail-content" :data-content-kind="contentKind">
          <label v-if="isResourceContent && resources.length > 1" class="resource-picker primary-resource-picker">关联资源<select :value="resourceId" aria-label="审核资源" @change="$emit('update:resourceId', $event.target.value)"><option v-for="(item, index) in resources" :key="item.resource_id" :value="item.resource_id">{{ resourceOption(item, index) }}</option></select></label>
          <p v-else-if="isResourceContent && resource" class="detail-resource-caption">{{ resourceTitle }}<span>本次执行关联版本</span></p>
          <section v-if="contentKind === 'evidence'" class="retrieval-result" aria-label="检索证据">
            <dl v-if="retrievalStats.length" class="retrieval-stats"><div v-for="item in retrievalStats" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div></dl>
            <WorkflowEvidencePanel :sources="nodeEvidence" />
          </section>
          <template v-else-if="contentKind === 'review'">
            <WorkflowReviewPanel :reviews="reviews" :step="step" />
            <details v-if="hasRevisions" class="review-revisions detail-disclosure"><summary>修订前后对照 · {{ chain.length }} 个版本</summary><WorkflowVersionPanel :chain="chain" :resource-id="resourceId" :all-reviews="snapshot.reviews || []" :run-id="runId" /></details>
          </template>
          <section v-else-if="contentKind === 'claims'" class="claim-verification detail-module" aria-label="陈述事实核验">
            <el-alert v-if="claimsError && claimEnabled" :title="claimsError" type="warning" :closable="false" show-icon />
            <div class="claim-audit-heading detail-section-heading"><span class="section-number">CLAIM / EVIDENCE</span><h3>{{ claimAuditSummary(metric, claimEnabled) }}</h3></div>
            <ClaimEvidenceList v-if="claimEnabled && resource" :key="resourceId" :rows="rows" focus-first><template v-if="rows.length" #summary><div class="claim-verdict-counts"><span v-for="item in verdictCounts" :key="item.verdict" :class="`is-${item.verdict}`" :aria-label="`${item.label} ${item.count}`">{{ item.shortLabel }} <strong>{{ item.count }}</strong></span></div></template></ClaimEvidenceList>
            <p v-else-if="claimEnabled" class="empty-note">本节点未关联可核验的资源，无法展示 Claim 判定。</p>
            <p v-else class="result-caption">此节点没有启用事实核验，不能据此认为事实通过。</p>
          </section>
          <WorkflowNodeResult v-else-if="step" :step="step" :resource="resource || null" />
        </div>
      </main>
      <details class="audit-context detail-disclosure" aria-label="执行上下文">
        <summary class="audit-context-heading"><span>执行记录与技术信息</span><span class="context-heading-copy">{{ resource ? resourceTitle : role.title }}<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg></span></summary>
        <div class="audit-context-body">
          <dl v-if="step" class="context-fields"><div><dt>节点执行</dt><dd :class="executionTone(step.status)">{{ reviewStatusLabel(step.status) }}</dd></div><div><dt>耗时</dt><dd>{{ formatDuration(step.duration_ms) }}</dd></div><div><dt>技术重试</dt><dd>{{ step.retry_count || 0 }} 次</dd></div></dl>
          <label v-if="isResourceContent && resources.length === 1" class="resource-picker">关联资源<select :value="resourceId" aria-label="审核资源" @change="$emit('update:resourceId', $event.target.value)"><option v-for="(item, index) in resources" :key="item.resource_id" :value="item.resource_id">{{ resourceOption(item, index) }}</option></select></label>
          <details v-if="step" class="audit-execution-summary detail-disclosure"><summary>完整执行摘要</summary><dl class="execution-summary-fields"><div><dt>输入</dt><dd>{{ step.input_summary || '未记录' }}</dd></div><div><dt>输出</dt><dd>{{ step.output_summary || '未记录' }}</dd></div><div><dt>决策理由</dt><dd>{{ step.decision_reason || '未记录' }}</dd></div></dl></details>
          <details class="audit-identifiers detail-disclosure"><summary>技术信息与审计标识</summary><p>Run ID：{{ runId }}</p><template v-if="step"><p>节点：{{ step.node_name || '未记录' }} · 顺序 {{ step.step_sequence ?? step.sequence ?? '未记录' }}</p><p>Step ID：{{ step.step_id || '未记录' }}</p><p v-if="step.evidence_refs?.length">来源引用：{{ step.evidence_refs.join('；') }}</p><p v-if="step.retrieval_config_hash">检索配置 hash：{{ step.retrieval_config_hash }}</p><p v-if="step.retrieval_query_hashes?.length">查询 hash：{{ step.retrieval_query_hashes.join('；') }}</p><pre v-if="step.retrieval_profile && Object.keys(step.retrieval_profile).length">{{ JSON.stringify(step.retrieval_profile, null, 2) }}</pre></template><p v-if="resource">Resource ID：{{ resource.resource_id }}</p><p v-for="review in reviews" :key="review.review_id">Review ID：{{ review.review_id }}</p></details>
        </div>
      </details>
    </div>
  </el-dialog>
</template>
<script setup>
import { computed } from 'vue'
import ClaimEvidenceList from './ClaimEvidenceList.vue'
import WorkflowNodeResult from './workflow-detail/WorkflowNodeResult.vue'
import WorkflowReviewPanel from './workflow-detail/WorkflowReviewPanel.vue'
import WorkflowEvidencePanel from './workflow-detail/WorkflowEvidencePanel.vue'
import WorkflowVersionPanel from './workflow-detail/WorkflowVersionPanel.vue'
import { associatedStepResources, buildClaimRows, claimAuditSummary, resourceVersionChain, reviewStatusLabel, verdictLabels } from './generationAudit.js'
import { formatDuration } from './workflowPresentation.js'
import { iconPaths } from './workflowNodeIcons.js'
import { detailRole } from './workflowDetailPresentation.js'
import './workflow-detail/workflowDetail.css'
const props = defineProps({
  visible: Boolean, loading: Boolean, error: { type: String, default: '' }, claimsError: { type: String, default: '' },
  snapshot: { type: Object, default: () => ({}) }, claims: { type: Object, default: () => ({}) },
  step: { type: Object, default: null }, resourceId: { type: String, default: '' }, runId: { type: String, default: '' }, claimEnabled: { type: Boolean, default: true },
})
defineEmits(['update:visible', 'update:resourceId', 'refresh'])
const role = computed(() => detailRole(props.step))
const contentKind = computed(() => props.step ? role.value.contentKind : 'review')
const isResourceContent = computed(() => ['document', 'review', 'claims'].includes(contentKind.value))
const detailTitle = computed(() => props.step ? `${role.value.title} · 执行详情` : '资源审核详情')
const runResources = computed(() => (props.snapshot.resource_versions || []).filter(item => item.run_id === props.runId))
const resources = computed(() => props.step ? associatedStepResources(props.snapshot, props.step, props.runId) : runResources.value)
const resource = computed(() => resources.value.find(item => item.resource_id === props.resourceId))
const resourceTitle = computed(() => resource.value ? `${resource.value.resource_type || '学习资源'} · v${resource.value.version || '?'}` : '')
const reviews = computed(() => resource.value ? (props.snapshot.reviews || []).filter(item => item.resource_id === resource.value.resource_id && item.run_id === props.runId
  && (!props.step?.review_ids?.length || props.step.review_ids.includes(item.review_id)))
  .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))) : [])
const metric = computed(() => resource.value ? props.claims.resource_metrics?.[resource.value.resource_id] : null)
const rows = computed(() => props.claimEnabled && resource.value ? buildClaimRows(props.claims, props.resourceId, props.runId, props.snapshot.evidence, resource.value) : [])
const verdictCounts = computed(() => Object.entries(verdictLabels).map(([verdict, label]) => ({ verdict, label,
  shortLabel: ({ supported: '证据支持', contradicted: '证据矛盾', not_in_evidence: '未获支持', incomplete: '未完成', non_factual: '非事实' })[verdict], count: rows.value.filter(row => row.verdict === verdict).length })).filter(item => item.count))
const nodeEvidence = computed(() => [...new Set(props.step?.evidence_refs || [])].map(id => (props.snapshot.evidence || []).find(item => item.evidence_id === id && item.run_id === props.runId) || { evidence_id: id, missing: true }))
const retrievalStats = computed(() => [
  { label: '证据引用', value: nodeEvidence.value.length }, { label: '检索状态', value: props.step?.retrieval_status },
  { label: '查询数', value: props.step?.retrieval_query_count }, { label: '候选条目', value: props.step?.retrieval_candidate_count },
  { label: '剔除条目', value: props.step?.retrieval_dropped_candidate_count }, { label: '局部失败', value: props.step?.retrieval_partial_failure_count },
].filter(item => item.value != null && item.value !== ''))
const chain = computed(() => resourceVersionChain(runResources.value, resource.value, props.runId))
const hasRevisions = computed(() => chain.value.some(item => item.parent_resource_id && item.parent_resource_id !== item.resource_id && chain.value.some(parent => parent.resource_id === item.parent_resource_id)))
function executionTone(value) { return ({ success: 'is-approved', completed: 'is-approved', failed: 'is-rejected', error: 'is-rejected', degraded: 'is-revision' })[value] || 'is-pending' }
function resourceOption(item, index) {
  const label = `${item.resource_type || '学习资源'} · v${item.version || '?'}`
  return resources.value.filter(other => other.resource_type === item.resource_type && other.version === item.version).length > 1 ? `${label} · 资源 ${index + 1}` : label
}
</script>
