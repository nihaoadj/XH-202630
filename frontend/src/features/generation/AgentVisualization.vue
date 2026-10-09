<template>
  <el-card class="workflow-timeline">
    <template #header>
      <div class="timeline-header">
        <span>Agent 协同轨迹</span>
        <el-tag :type="connectionTagType" effect="plain">{{ connectionLabel }}</el-tag>
      </div>
    </template>
    <el-alert
      v-if="legacyPartial"
      title="该历史 Run 的事件记录不完整，仅展示真实存在的事件。"
      type="warning"
      :closable="false"
      show-icon
      class="timeline-alert"
    />
    <el-collapse v-if="resourceExecutions.length" v-model="expandedResourceSections" class="resource-progress-tree">
      <el-collapse-item name="generation" class="resource-phase">
        <template #title>
          <div class="resource-tree-title">
            <span class="phase-order" aria-hidden="true">01</span><span class="phase-name">资源生成</span>
            <el-tag size="small" effect="plain">{{ progressLabel }}</el-tag>
          </div>
        </template>
        <ResourceExecutionProgressList
          :executions="resourceExecutions"
          phase="generation"
          :retrying-key="retryingResourceKey"
          :retry-enabled="retryEnabled"
          :claim-reports="claimReports"
          @open-resource="$emit('open-resource', $event)"
          @retry-resource="$emit('retry-resource', $event)"
          @open-claim-report="$emit('open-claim-report', $event)"
        />
      </el-collapse-item>
      <el-collapse-item name="review" class="resource-phase">
        <template #title>
          <div class="resource-tree-title">
            <span class="phase-order" aria-hidden="true">02</span><span class="phase-name">审核与发布</span>
            <el-tag :type="progressSummary.failed ? 'warning' : 'success'" size="small" effect="plain">
              已发布 {{ progressSummary.published }}/{{ progressSummary.total }}
            </el-tag>
          </div>
        </template>
        <ResourceExecutionProgressList
          :executions="resourceExecutions"
          phase="review"
          :retrying-key="retryingResourceKey"
          :retry-enabled="retryEnabled"
          @open-resource="$emit('open-resource', $event)"
          @retry-resource="$emit('retry-resource', $event)"
        />
      </el-collapse-item>
    </el-collapse>
    <el-empty v-if="!trace.length && !markers.length && !resourceExecutions.length" description="等待持久化工作流事件" />
    <el-timeline>
      <el-timeline-item
        v-for="(item, index) in displayTrace"
        :key="item.key || item.step_id || index"
        :type="statusType(item.status)"
        :timestamp="`${item.action || ''} · ${statusLabel(item.status)}`"
      >
        <strong>{{ item.agent_name }}</strong>
        <p v-if="item.input_summary" class="muted">输入：{{ item.input_summary }}</p>
        <p>{{ item.output_summary }}</p>
        <p v-if="item.decision_reason" class="muted">理由：{{ item.decision_reason }}</p>
        <p v-if="item.evidence_refs && item.evidence_refs.length" class="muted">
          证据：{{ item.evidence_refs.slice(0, 3).join('；') }}
        </p>
        <div class="metrics">
          <el-tag v-if="item.duration_ms != null" size="small" effect="plain">{{ item.duration_ms }} ms</el-tag>
          <el-tag v-if="item.retry_count" size="small" effect="plain">重试 {{ item.retry_count }}</el-tag>
          <el-tag v-if="item.evidence_count != null" size="small" effect="plain">证据 {{ item.evidence_count }}</el-tag>
          <el-tag v-if="item.claim_count != null" size="small" effect="plain">Claim {{ item.claim_count }}</el-tag>
          <el-tag v-if="item.revision_count != null" size="small" effect="plain">返工轮次 {{ item.revision_count }}</el-tag>
        </div>
      </el-timeline-item>
      <el-timeline-item
        v-for="marker in displayMarkers"
        :key="marker.key"
        :type="statusType(marker.status)"
        :timestamp="marker.label"
      >
        <p>{{ marker.summary || marker.label }}</p>
        <el-button
          v-if="marker.event_type === 'followup_generation_created' && marker.payload?.child_run_id"
          text
          type="primary"
          @click="$emit('open-child-run', marker.payload.child_run_id)"
        >
          查看后续生成 {{ marker.payload.child_run_id.slice(0, 8).toUpperCase() }}
        </el-button>
      </el-timeline-item>
    </el-timeline>
  </el-card>
</template>

<script setup>
import { computed, ref } from 'vue'
import ResourceExecutionProgressList from './ResourceExecutionProgressList.vue'
import { normalizeResourceProgressSummary } from '../../utils/generationDisplay'

const props = defineProps({
  trace: {
    type: Array,
    default: () => [],
  },
  markers: {
    type: Array,
    default: () => [],
  },
  connectionStatus: {
    type: String,
    default: 'idle',
  },
  legacyPartial: Boolean,
  resourceExecutions: {
    type: Array,
    default: () => [],
  },
  resourceProgressSummary: {
    type: Object,
    default: null,
  },
  retryingResourceKey: {
    type: String,
    default: '',
  },
  retryEnabled: Boolean,
  claimReports: { type: Object, default: () => ({}) },
})

defineEmits(['open-child-run', 'open-resource', 'retry-resource', 'open-claim-report'])

const expandedResourceSections = ref(['generation', 'review'])
const progressSummary = computed(() => normalizeResourceProgressSummary(
  props.resourceProgressSummary,
  props.resourceExecutions,
))
const progressLabel = computed(() => `${progressSummary.value.completed}/${progressSummary.value.total} 项已终结`)

const connectionLabel = computed(() => ({
  connecting: '正在连接',
  live: '节点级同步',
  fallback: '轮询降级',
  terminal: '已结束',
  error: '连接异常',
}[props.connectionStatus] || '等待中'))

const connectionTagType = computed(() => ({
  live: 'success',
  connecting: 'warning',
  fallback: 'warning',
  terminal: 'info',
  error: 'danger',
}[props.connectionStatus] || 'info'))

const displayTrace = computed(() => [...props.trace]
  .sort((left, right) => Number(right.sequence || 0) - Number(left.sequence || 0)))

const displayMarkers = computed(() => [...props.markers]
  .sort((left, right) => Number(right.sequence || 0) - Number(left.sequence || 0)))

function statusLabel(status) {
  return ({
    running: '进行中', success: '完成', succeeded: '完成', completed: '完成',
    degraded: '降级', failed: '失败', human_review: '人工复核', skipped: '跳过',
  }[status] || status || '已记录')
}

function statusType(status) {
  return ({
    running: 'warning', success: 'success', succeeded: 'success', completed: 'success',
    degraded: 'warning', failed: 'danger', human_review: 'warning', skipped: 'info',
  }[status] || 'info')
}
</script>

<style scoped>
.muted {
  color: #59697b;
  font-size: 13px;
  margin: 4px 0;
}

.timeline-header,
.metrics {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.timeline-header {
  justify-content: space-between;
}

.timeline-alert {
  margin-bottom: 16px;
}

.resource-progress-tree {
  position: relative;
  margin-bottom: 20px;
  padding-left: 30px;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.resource-progress-tree::before {
  content: '';
  position: absolute;
  top: 25px;
  bottom: 18px;
  left: 11px;
  width: 1px;
  background: #c4d7de;
}

.resource-progress-tree :deep(.el-collapse-item__header) {
  min-height: 48px;
  height: auto;
  padding: 8px 0;
  border-bottom-color: transparent;
  background: transparent;
}

.resource-progress-tree :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
  background: transparent;
}

.resource-progress-tree :deep(.el-collapse-item__content) {
  padding: 4px 0 18px;
}

.resource-tree-title {
  position: relative;
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-right: 4px;
  color: #172c45;
  font-size: 13px;
  font-weight: 700;
}

.phase-order { position:absolute; left:-30px; top:50%; transform:translateY(-50%); display:grid; place-items:center; width:24px; height:24px; border:1px solid #91b7bd; border-radius:50%; background:#f1f7f8; color:#176b70; font:10px/1 Consolas,monospace; }
.phase-name { flex:1; min-width:0; line-height:1.5; }
.resource-tree-title :deep(.el-tag) { flex:0 1 auto; max-width:62%; font-size:10px; }

.workflow-timeline {
  height: auto;
  overflow: visible;
}

.workflow-timeline :deep(.el-card__body) {
  max-height: none;
  overflow: visible;
}
.workflow-timeline :deep(.el-timeline) { padding: 0 0 0 6px; }
.workflow-timeline :deep(.el-timeline-item__tail) { border-color: #d1dfe5; }
.workflow-timeline :deep(.el-timeline-item__node) { box-shadow:0 0 0 4px #f3f7fa; }
.workflow-timeline :deep(.el-timeline-item__wrapper) { padding-left:24px; }
.workflow-timeline :deep(.el-timeline-item) { padding-bottom:24px; }
.workflow-timeline :deep(.el-timeline-item__content) { color: #172c45; font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.workflow-timeline :deep(.el-timeline-item__timestamp) { color: #59697b; font-size: 11px; line-height: 1.5; }
.workflow-timeline :deep(.el-timeline-item__content > strong) { font-size: 14px; }
.workflow-timeline :deep(.el-timeline-item__content > p) { margin: 6px 0; }
.workflow-timeline :deep(.el-tag) { height: auto; min-height: 24px; padding: 3px 7px; border-radius: 3px; white-space: normal; line-height: 1.5; }
.workflow-timeline :deep(.el-tag--primary) { color: #176b70; border-color: #bbd9d2; background: #eef7f4; }
.workflow-timeline :deep(.el-tag--info) { color: #59697b; }
.workflow-timeline :deep(.el-tag--success) { color: #176b70; border-color: #bbd9d2; background: #eef7f4; }
.workflow-timeline :deep(.el-tag--warning) { color: #935719; border-color: #e4c59f; background: #fff7ed; }
.workflow-timeline :deep(.el-tag--danger) { color: #a1322c; border-color: #e8c5c0; background: #fff3f0; }
.workflow-timeline :deep(.el-button:focus-visible),.workflow-timeline :deep(.el-collapse-item__header:focus-visible) { outline: 2px solid #176b70; outline-offset: -2px; }
</style>
