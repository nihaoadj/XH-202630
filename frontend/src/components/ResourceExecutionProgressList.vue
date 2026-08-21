<template>
  <div class="resource-execution-list">
    <el-empty v-if="!displayExecutions.length" :image-size="44" description="等待资源任务拆解" />
    <div v-else class="execution-grid">
      <article v-for="item in displayExecutions" :key="item.key" class="execution-card">
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
        </div>
        <p v-if="item.error_message || item.error_code" class="execution-error">
          {{ item.error_message || `处理失败（${item.error_code}）` }}
        </p>

        <div v-if="canOpen(item) || canRetry(item)" class="execution-actions">
          <el-button v-if="canOpen(item)" text type="primary" @click="$emit('open-resource', item)">
            查看已发布资源
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
} from '../utils/generationDisplay'

const props = defineProps({
  executions: { type: Array, default: () => [] },
  phase: { type: String, default: 'all' },
  retryingKey: { type: String, default: '' },
  retryEnabled: { type: Boolean, default: true },
})

defineEmits(['open-resource', 'retry-resource'])

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
    const html = items.find((item) => item.representation === 'html')
    return {
      ...text,
      key: text.resource_spec_id || text.key,
      representation: html ? 'text_html' : text.representation,
      resource_execution_state: logicalState(items),
      agent_name: html ? `${text.agent_name || ''} · HTML` : text.agent_name,
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
    if (state === 'human_review') return { label: '已生成，待人工复核', type: 'warning' }
    if (state === 'revision_requested') return { label: props.retryEnabled ? '等待重新生成' : '重新生成中', type: 'warning' }
  }
  if (props.phase === 'review') {
    if (['queued', 'generating'].includes(state)) return { label: '等待生成', type: 'info' }
    if (state === 'generated') return { label: '等待审核', type: 'info' }
  }
  return resourceExecutionStateMeta(state)
}

function canOpen(item) {
  return item.resource_execution_state === 'approved' && Boolean(item.resource_id)
}

function canRetry(item) {
  return props.retryEnabled
    && Boolean(item.resource_spec_id)
    && ['failed', 'human_review', 'revision_requested'].includes(item.resource_execution_state)
}
</script>

<style scoped>
.resource-execution-list { display: grid; gap: 10px; }
.execution-grid { display: grid; gap: 9px; }
.execution-card { padding: 11px 12px; border: 1px solid #dce6ef; border-radius: 9px; background: linear-gradient(180deg, #fff, #f8fbfd); }
.execution-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 9px; }
.execution-title { display: flex; min-width: 0; flex: 1 1 auto; flex-wrap: wrap; align-items: baseline; gap: 4px 7px; }
.execution-card-head strong { min-width: 0; color: #203853; font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; white-space: normal; }
.execution-card-head span { flex: 0 0 auto; color: #75869a; font-size: 11px; }
.execution-card-head :deep(.el-tag) { flex: 0 0 auto; margin-top: 1px; }
.execution-objective { display: -webkit-box; margin: 8px 0 0; overflow: hidden; color: #63758b; font-size: 12px; line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.execution-meta { display: flex; flex-wrap: wrap; gap: 5px 10px; margin-top: 8px; color: #8290a2; font-size: 10px; }
.execution-error { margin: 8px 0 0; padding: 7px 8px; border-radius: 6px; background: #fff1ef; color: #a34b43; font-size: 11px; line-height: 1.45; }
.execution-actions { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 7px; }
.execution-actions :deep(.el-button) { height: 29px; margin: 0; padding: 0 8px; border: 1px solid #e5bc7b; border-radius: 7px; background: #fffaf1; color: #9a5a14; font-size: 11px; font-weight: 650; }
.execution-actions :deep(.el-button:hover) { border-color: #d99542; background: #fff0d5; color: #7c4307; }
</style>
