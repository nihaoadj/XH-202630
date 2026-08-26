<template>
  <ul class="source-ref-list" :class="{ compact }">
    <li v-for="ref in refs" :key="referenceKey(ref)">
      <div>
        <strong>{{ ref.title || '知识库资料' }}</strong>
        <small>{{ referenceLocation(ref) }}</small>
      </div>
      <span v-if="referenceScore(ref) !== null">相关度 {{ referenceScore(ref).toFixed(2) }}</span>
    </li>
  </ul>
</template>

<script setup>
defineProps({
  refs: { type: Array, default: () => [] },
  compact: { type: Boolean, default: false },
})

function referenceKey(ref) {
  return ref.evidence_id || `${ref.doc_id || ref.document_id || 'source'}-${ref.chunk_id || ''}-${ref.section || ''}`
}

function referenceLocation(ref) {
  return [ref.section, ref.chunk_id ? `Chunk ${ref.chunk_id}` : '', ref.page ? `第 ${ref.page} 页` : ''].filter(Boolean).join(' · ') || '可信知识来源'
}

function referenceScore(ref) {
  const value = ref.score ?? ref.normalized_score
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}
</script>

<style scoped>
.source-ref-list { display:grid; min-width:0; max-width:100%; gap:7px; margin:0; padding:0; list-style:none; }
.source-ref-list li { display:flex; min-width:0; max-width:100%; align-items:center; justify-content:space-between; gap:14px; padding:9px 11px; border:1px solid #e2e9f1; border-radius:8px; background:#f5f8fb; color:#53677e; font-size:12px; }
.source-ref-list li > div { min-width:0; }
.source-ref-list strong,.source-ref-list small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.source-ref-list strong { font-weight:650; }.source-ref-list small { margin-top:3px; color:#8796a8; font-size:10px; }
.source-ref-list li > span { flex:0 0 auto; color:#74869b; font-size:11px; }
.source-ref-list.compact li { padding:7px 9px; background:#f7fafc; }
@media (max-width:560px) { .source-ref-list li { align-items:flex-start; flex-direction:column; gap:5px; } }
</style>
