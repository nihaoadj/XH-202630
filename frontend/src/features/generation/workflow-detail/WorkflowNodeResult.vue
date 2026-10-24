<template>
  <section class="detail-module node-result" :data-role="role.key" :aria-label="role.result">
    <div class="detail-section-heading"><span class="section-number">{{ role.code }}</span><h3>{{ role.result }}</h3></div>
    <div class="result-primary" :class="`result-${role.contentKind}`">
      <template v-if="result.kind === 'path'">
        <p class="result-caption">执行摘要中的路径片段 · 非完整学习计划</p>
        <ol class="planning-path"><li v-for="(topic, index) in result.topics" :key="index"><span class="path-index" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span><div><span class="path-label">学习主题</span><p>{{ topic }}</p></div></li></ol>
      </template>
      <template v-else-if="result.kind === 'diagnosis'">
        <div class="diagnosis-result"><div class="diagnosis-level"><span class="result-caption">推荐起点</span><strong>{{ result.difficulty }}</strong></div><div class="diagnosis-blindspots"><span class="result-caption">待加强的知识点</span><p>{{ result.blindspots }}</p></div></div>
        <p class="result-caption">来自本次诊断摘要；接口未提供完整诊断报告。</p>
      </template>
      <template v-else-if="role.key === 'generate'">
        <template v-if="resource">
          <div class="generated-heading"><strong>{{ resource.resource_type || '学习资源' }} <span>v{{ resource.version || '?' }}</span></strong><span class="result-caption">只读执行产物</span></div>
          <p v-if="resource.content_text == null" class="empty-note">此版本正文未记录，无法展示生成内容。</p>
          <pre v-else class="generated-content">{{ resource.content_text }}</pre>
        </template>
        <p v-else class="empty-note">本节点未关联可读取的生成版本，未使用其他资源替代。</p>
      </template>
      <p v-else class="node-output">{{ result.raw || '未记录输出摘要。' }}</p>
    </div>
    <section v-if="role.reason" class="node-guidance result-context" :aria-label="role.reason"><span class="context-index">{{ role.key === 'diagnose' ? 'RECOMMENDATION' : 'RATIONALE' }}</span><h4>{{ role.reason }}</h4><p class="node-output">{{ step.decision_reason || '未记录决策理由。' }}</p></section>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { detailRole, projectNodeResult } from '../workflowDetailPresentation.js'
const props = defineProps({ step: { type: Object, required: true }, resource: { type: Object, default: null } })
const role = computed(() => detailRole(props.step))
const result = computed(() => projectNodeResult(props.step))
</script>
