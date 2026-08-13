<template>
  <el-card>
    <template #header>
      <div class="timeline-header">
        <span>Agent 实时协同轨迹</span>
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
    <el-empty v-if="!trace.length && !markers.length" description="等待持久化工作流事件" />
    <el-timeline>
      <el-timeline-item
        v-for="(item, index) in trace"
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
        v-for="marker in markers"
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
import { computed } from 'vue'

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
})

defineEmits(['open-child-run'])

const connectionLabel = computed(() => ({
  connecting: '正在连接',
  live: '实时',
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
  color: #667085;
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
</style>
