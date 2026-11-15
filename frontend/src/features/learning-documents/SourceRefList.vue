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
.source-ref-list {
  display: grid;
  min-width: 0;
  max-width: 100%;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.source-ref-list li {
  display: flex;
  min-width: 0;
  max-width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 9px 11px;
  border: 1px solid transparent;
  border-radius: 3px;
  background:
    linear-gradient(112deg, rgb(255 255 255 / 96%), rgb(247 250 252 / 96%) 64%, rgb(240 248 247 / 94%)) padding-box,
    linear-gradient(112deg, rgb(96 157 174 / 42%), rgb(193 213 222 / 72%) 52%, rgb(104 174 159 / 42%)) border-box;
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 94%),
    inset 0 -1px 1px rgb(111 142 167 / 10%),
    0 2px 4px -3px rgb(33 64 86 / 24%),
    0 8px 16px -10px rgb(33 64 86 / 28%);
  color: #53677e;
  font-size: 12px;
  transition: background 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}

.source-ref-list li:hover {
  background:
    linear-gradient(112deg, #fff, rgb(249 252 253 / 98%) 64%, rgb(241 249 248 / 98%)) padding-box,
    linear-gradient(112deg, rgb(69 143 163 / 56%), rgb(181 207 218 / 78%) 52%, rgb(78 161 146 / 54%)) border-box;
  box-shadow:
    inset 0 1px 0 #fff,
    inset 0 -1px 1px rgb(111 142 167 / 12%),
    0 4px 8px -5px rgb(33 64 86 / 26%),
    0 10px 17px -13px rgb(33 64 86 / 36%);
  transform: translateY(-1px);
}

.source-ref-list li > div { min-width:0; }
.source-ref-list strong,.source-ref-list small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.source-ref-list strong { color: #3f5a72; font-weight: 650; }
.source-ref-list small { margin-top:3px; color:#8796a8; font-size:10px; }
.source-ref-list li > span { flex:0 0 auto; color:#497e83; font-size:11px; }
.source-ref-list.compact li { padding:7px 9px; }
@media (max-width:560px) { .source-ref-list li { align-items:flex-start; flex-direction:column; gap:5px; } }
</style>
