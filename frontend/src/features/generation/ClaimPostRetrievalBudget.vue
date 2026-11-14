<template>
  <div class="claim-post-budget" role="group" aria-label="补检后修订设置">
    <label :for="`${uid}-budget`">补检后修订次数</label>
    <el-input-number
      :id="`${uid}-budget`"
      :model-value="modelValue" :min="0" :max="3" :step="1" :precision="0"
      :disabled="disabled" controls-position="right"
      aria-label="补检后修订次数" :aria-describedby="`${uid}-hint`"
      @update:model-value="$emit('update:modelValue', $event ?? 0)"
    />
    <small :id="`${uid}-hint`">0 次：补检后结束并查看报告；修订后会重新审核。</small>
  </div>
</template>

<script setup>
import { useId } from 'vue'
defineProps({ modelValue: { type: Number, default: 0 }, disabled: Boolean })
defineEmits(['update:modelValue'])
const uid = useId()
</script>

<style scoped>
.claim-post-budget { display: flex; align-items: center; flex-wrap: wrap; gap: 10px 14px; padding: 10px 0; }
.claim-post-budget label { color: var(--el-text-color-primary); font-size: 14px; }
.claim-post-budget :deep(.el-input-number) { width: 108px; }
.claim-post-budget small { flex-basis: 100%; color: var(--el-text-color-secondary); line-height: 1.5; }
</style>
