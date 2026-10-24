<template>
  <section class="detail-module" aria-label="本次引用的冻结依据">
    <div class="detail-section-heading"><span class="section-number">SOURCE / SNAPSHOT</span><h3>检索到的证据</h3></div>
    <p class="audit-helper">仅展示本次节点明确引用的冻结依据。</p>
    <p v-if="!records.length" class="empty-note">本次执行未记录冻结来源引用。</p>
    <article v-for="(source, index) in records" :key="source.evidence_id || index" class="node-evidence-card">
      <header class="source-heading"><span class="source-number">{{ String(index + 1).padStart(2, '0') }}</span><h4>{{ source.missing ? '冻结依据缺失' : source.locator?.title || '冻结来源' }}</h4></header>
      <p v-if="source.missing" class="empty-note">冻结证据缺失，未使用其他来源替代。</p>
      <template v-else>
        <p class="source-locator">
          文档版本 {{ documentVersion(source) }}
          <span v-if="hasValue(source.locator?.section)"> · {{ source.locator.section }}</span>
          <span v-if="hasValue(source.locator?.page)"> · 第 {{ source.locator.page }} 页</span>
          <span v-if="hasValue(source.locator?.line_start)"> · 行 {{ source.locator.line_start }}<template v-if="hasValue(source.locator?.line_end)">–{{ source.locator.line_end }}</template></span>
          <span v-else-if="hasValue(source.locator?.line_end)"> · 截止行 {{ source.locator.line_end }}</span>
        </p>
        <blockquote v-if="hasValue(source.excerpt)" class="source-excerpt">{{ source.excerpt }}</blockquote>
        <p v-else class="empty-note">冻结证据未记录原文摘录。</p>
      </template>
      <details class="source-identity audit-identifiers">
        <summary>来源标识与冻结元数据</summary>
        <dl class="source-technical-fields"><div v-for="field in technicalFields(source)" :key="field.label"><dt>{{ field.label }}</dt><dd>{{ formatValue(field.value) }}</dd></div></dl>
      </details>
    </article>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ sources: { type: Array, default: () => [] } })
// Each row already corresponds to one explicitly referenced frozen Evidence ID.
// All display values and technical fields come from that row alone.
const records = computed(() => props.sources.filter(item => item && typeof item === 'object'))
function hasValue(value) { return value != null && value !== '' }
function recordedValue(value) { return hasValue(value) ? value : '未记录' }
function documentVersion(source) { return hasValue(source.document_version) ? source.document_version : recordedValue(source.locator?.document_version) }
function formatValue(value) { return typeof value === 'string' ? value : JSON.stringify(value) ?? '未记录' }
function technicalFields(source) {
  const locator = source.locator || {}
  return [
    ['Evidence ID', source.evidence_id], ['Run ID', source.run_id],
    ['知识库 ID', source.knowledge_base_id ?? locator.knowledge_base_id],
    ['文档 ID', source.document_id ?? locator.document_id],
    ['Chunk ID', source.chunk_id ?? locator.chunk_id],
    ['检索 Step ID', source.retrieval_step_id],
    ['来源类型', locator.source_type], ['来源路径', locator.source_path],
    ['定位器文档版本', locator.document_version],
    ['查询位次', source.query_rank], ['检索位次', source.rank],
    ['原始分数', source.raw_score], ['分数类型', source.score_kind],
    ['归一化分数', source.normalized_score], ['检索时间', source.retrieved_at],
    ['Excerpt Hash', source.excerpt_hash], ['Snapshot Hash', source.snapshot_hash],
    ['Config Hash', source.config_hash], ['Query Hash', source.query_hash],
  ].filter(([, value]) => hasValue(value)).map(([label, value]) => ({ label, value }))
}
</script>
