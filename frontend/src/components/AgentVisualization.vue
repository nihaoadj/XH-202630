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
        <p>{{ item.output_summary }}</p>
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
