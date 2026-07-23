<template>
  <el-card>
    <template #header>Agent 协同调度轨迹</template>
    <el-timeline>
      <el-timeline-item
        v-for="(item, index) in trace"
        :key="index"
        :type="item.agent_name === 'supervisor' ? 'primary' : 'info'"
        :timestamp="item.action"
      >
        <strong>{{ item.agent_name }}</strong>
        <p v-if="item.input_summary" class="muted">输入：{{ item.input_summary }}</p>
        <p>{{ item.output_summary }}</p>
        <p v-if="item.decision_reason" class="muted">理由：{{ item.decision_reason }}</p>
        <p v-if="item.evidence_refs && item.evidence_refs.length" class="muted">
          证据：{{ item.evidence_refs.slice(0, 3).join('；') }}
        </p>
      </el-timeline-item>
    </el-timeline>
  </el-card>
</template>

<script setup>
defineProps({
  trace: {
    type: Array,
    default: () => [],
  },
})
</script>

<style scoped>
.muted {
  color: #667085;
  font-size: 13px;
  margin: 4px 0;
}
</style>
