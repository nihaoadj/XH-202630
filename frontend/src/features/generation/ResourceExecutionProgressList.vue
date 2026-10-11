<template>
  <div class="resource-execution-list">
    <el-empty v-if="!displayExecutions.length" :image-size="44" description="等待资源任务拆解" />
    <div v-else class="execution-grid">
      <article v-for="item in displayExecutions" :key="item.key" class="execution-card" :class="`is-${phaseMeta(item).type}`">
        <div class="execution-card-head">
          <div class="execution-title">
            <strong>{{ item.resource_type || '学习资源' }}</strong>
            <span>{{ representationLabel(item.representation) }}</span>
          </div>
          <el-tag :type="phaseMeta(item).type" size="small" effect="plain">
            {{ phaseMeta(item).label }}
          </el-tag>
        </div>

        <p v-if="item.learning_objective" class="execution-objective">{{ item.learning_objective }}</p>
        <div class="execution-meta">
          <span v-if="item.attempt">第 {{ item.attempt }} 次尝试</span>
          <span v-if="item.agent_name">{{ item.agent_name }}</span>
          <span v-if="item.validation_status">校验 {{ item.validation_status }}</span>
          <span v-if="item.claim_metric_status">Claim {{ claimStatusLabel(item.claim_metric_status) }}</span>
          <span v-if="item.claim_factual_pass_rate != null">事实通过 {{ percent(item.claim_factual_pass_rate) }}</span>
          <span v-if="item.claim_publish_decision_pending" class="claim-pending">待用户决定发布</span>
        </div>
        <el-alert
          v-if="item.claim_warning_publish"
          title="已带 Claim 警告发布"
          type="warning"
          :closable="false"
          show-icon
          class="claim-warning"
        />
        <p v-if="item.error_message || item.error_code" class="execution-error">
          {{ item.error_message || `处理失败（${item.error_code}）` }}
        </p>

        <div v-if="canOpen(item) || canRetry(item) || canShowClaimReport(item)" class="execution-actions">
          <el-button v-if="canOpen(item)" text type="primary" @click="$emit('open-resource', item)">
            查看已发布资源
          </el-button>
          <el-button v-if="canShowClaimReport(item)" text type="primary" @click="$emit('open-claim-report', item.resource_id)">
            查看审核报告
          </el-button>
          <el-button
            v-if="canRetry(item)"
            text
            type="warning"
            :loading="retryingKey === item.key"
            @click="$emit('retry-resource', item)"
          >
            重新生成此资源
          </el-button>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  resourceExecutionStateMeta,
  resourceRepresentationLabel,
} from '../../utils/generationDisplay'

const props = defineProps({
  executions: { type: Array, default: () => [] },
  phase: { type: String, default: 'all' },
  retryingKey: { type: String, default: '' },
  retryEnabled: { type: Boolean, default: true },
  claimReports: { type: Object, default: () => ({}) },
})

defineEmits(['open-resource', 'retry-resource', 'open-claim-report'])

function logicalState(items) {
  const states = items.map((item) => item.resource_execution_state)
  if (states.includes('failed')) return 'failed'
  if (states.includes('human_review')) return 'human_review'
  if (states.includes('revision_requested')) return 'revision_requested'
  if (states.includes('claim_checking')) return 'claim_checking'
  if (states.includes('reviewing')) return 'reviewing'
  if (states.includes('generating')) return 'generating'
  if (states.includes('queued') && states.some((state) => state !== 'queued')) return 'generating'
  if (states.includes('queued')) return 'queued'
  if (states.every((state) => state === 'approved')) return 'approved'
  return 'generated'
}

const displayExecutions = computed(() => {
  const groups = new Map()
  for (const item of props.executions) {
    const key = item.resource_spec_id || `${item.resource_type}:${item.representation || 'text'}`
    const items = groups.get(key) || []
    items.push(item)
    groups.set(key, items)
  }
  return [...groups.values()].map((items) => {
    const text = items.find((item) => item.representation === 'text') || items[0]
    return {
      ...text,
      key: text.resource_spec_id || text.key,
      representation: text.representation,
      resource_execution_state: logicalState(items),
      agent_name: text.agent_name,
      validation_status: items.map((item) => item.validation_status).filter(Boolean).join(' / '),
      error_code: items.find((item) => item.error_code)?.error_code || text.error_code,
    }
  }).sort((left, right) => (
  Number(left.display_order || 0) - Number(right.display_order || 0)
    || String(left.resource_type || '').localeCompare(String(right.resource_type || ''), 'zh-CN')
    || (left.representation === 'text' ? -1 : 1)
  ))
})

function representationLabel(representation) {
  return resourceRepresentationLabel(representation)
}

function phaseMeta(item) {
  const state = item.resource_execution_state
  if (props.phase === 'generation') {
    if (['generated', 'reviewing', 'claim_checking', 'approved'].includes(state)) {
      return { label: '生成完成', type: 'success' }
    }
    if (state === 'human_review') {
      if (item.claim_publish_decision_pending) return { label: 'Claim 审核报告待你决定', type: 'warning' }
      return { label: '已生成，待人工复核', type: 'warning' }
    }
    if (state === 'revision_requested') return { label: props.retryEnabled ? '等待重新生成' : '重新生成中', type: 'warning' }
  }
  if (props.phase === 'review') {
    if (['queued', 'generating'].includes(state)) return { label: '等待生成', type: 'info' }
    if (state === 'generated') return { label: '等待审核', type: 'info' }
    if (state === 'approved' && item.publication_status !== 'published') {
      return { label: '审核通过，等待发布', type: 'warning' }
    }
  }
  return resourceExecutionStateMeta(state)
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

function percent(value) {
  return `${(Number(value) * 100).toFixed(1)}%`
}

function claimStatusLabel(status) {
  return ({ complete: '已完成', incomplete: '未完成', not_applicable: '不适用' }[status] || status)
}
</script>

<style scoped>
.resource-execution-list { display: grid; gap: 10px; }
.execution-grid { display: grid; gap: 10px; }
.execution-card { min-width:0; padding:12px; border:1px solid #dce4eb; border-left:2px solid #9eb2c0; border-radius:4px; background:linear-gradient(180deg,#fff,#f9fbfc); }
.execution-card.is-success { border-left-color:#52978c; }
.execution-card.is-warning { border-left-color:#b68a52; }
.execution-card.is-danger { border-left-color:#b45c52; }
.execution-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 9px; }
.execution-title { display: flex; min-width: 0; flex: 1 1 auto; flex-wrap: wrap; align-items: baseline; gap: 4px 7px; }
.execution-card-head strong { min-width: 0; color: #172c45; font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; white-space: normal; }
.execution-title > span { flex: 0 0 auto; color: #59697b; font-size: 10px; }
.execution-card-head :deep(.el-tag) { flex: 0 1 auto; max-width: 55%; margin-top: 1px; white-space: normal; height: auto; line-height: 1.5; }
.execution-objective { margin: 9px 0 0; color: #59697b; font-size: 12px; line-height: 1.8; overflow-wrap: anywhere; }
.execution-meta { display:flex; flex-wrap:wrap; gap:4px 10px; margin-top:8px; padding-top:8px; border-top:1px solid #e6edf2; color:#59697b; font-size:11px; line-height:1.6; }
.execution-meta > span { min-width:0; max-width:100%; overflow-wrap:anywhere; }
.execution-error { margin: 10px 0 0; padding: 9px 10px; border-radius: 3px; background: #fff3f0; color: #a1322c; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.execution-actions { display:flex; flex-wrap:wrap; gap:4px 12px; margin-top:4px; }
.execution-actions :deep(.el-button) { min-height:44px; height:auto; max-width:100%; margin:0; padding:8px 0; border:0; border-radius:2px; background:transparent; color:#176b70; font-size:11px; font-weight:600; }
.execution-actions :deep(.el-button > span) { white-space:normal; overflow-wrap:anywhere; }
.execution-actions :deep(.el-button--warning) { color:#935719; }
.execution-actions :deep(.el-button:hover) { background:transparent; color:#125c60; text-decoration:underline; text-underline-offset:4px; }
.execution-actions :deep(.el-button--warning:hover) { background:transparent; color:#774312; }
.execution-actions :deep(.el-button:focus-visible) { outline: 2px solid #176b70; outline-offset: 2px; }
</style>
