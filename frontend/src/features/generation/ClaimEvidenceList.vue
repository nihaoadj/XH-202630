<template>
  <section class="claim-evidence-list" data-testid="claim-evidence-list" aria-label="事实与冻结证据对照">
    <div class="claim-list-heading">
      <slot name="summary"><strong>陈述与证据 · {{ rows.length }} 条</strong></slot>
      <label>筛选 <select v-model="filter" aria-label="事实判定筛选">
        <option value="all">全部陈述</option>
        <option v-for="(label, verdict) in verdictLabels" :key="verdict" :value="verdict">{{ label }}</option>
      </select></label>
    </div>
    <p class="coverage-note">仅覆盖已抽取陈述；冻结摘录不代表全文正确率。</p>
    <p v-if="!filteredRows.length" class="empty-note">{{ rows.length ? '此分类没有陈述。' : '没有可展示的 Claim 记录，不能据此认为事实通过。' }}</p>
    <details v-for="(row, index) in filteredRows" :key="row.claim_id" class="claim-detail" :open="focusFirst && row.claim_id === focusClaimId">
      <summary>
        <span class="claim-number" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span>
        <span class="claim-copy"><span class="verdict" :class="`is-${row.verdict}`">{{ verdictLabels[row.verdict] || row.verdict }}</span><span class="claim-statement">{{ row.claim_text }}</span><span class="claim-summary-reason">{{ row.reason }}</span></span>
        <svg class="claim-expand" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
      </summary>
      <div class="claim-detail-body">
        <div class="claim-statement-panel"><span class="evidence-section-label"><span>CLAIM</span> 陈述与判定</span>
        <p><strong>判定理由：</strong>{{ row.reason }}</p>
        <p v-if="row.source_text"><strong>生成原句：</strong>{{ row.source_text }}</p>
        <p v-if="row.resource_version" class="claim-resource-version">资源版本 v{{ row.resource_version }}</p>
        <p v-if="row.provenanceUnavailable" class="empty-note">历史记录缺少版本或审核关联字段，无法完整追溯。</p>
        </div>
        <div class="claim-evidence-panel"><span class="evidence-section-label"><span>EVIDENCE</span> 冻结来源依据</span>
        <p v-if="!row.evidence.length" class="empty-note">未关联冻结证据。当前证据未支持，不等于现实中的陈述一定错误。</p>
        <article v-for="source in row.evidence" :key="source.evidence_id" class="evidence-card">
          <p v-if="source.missing" class="empty-note">冻结证据缺失：{{ source.evidence_id }}。未使用其他来源替代。</p>
          <template v-else>
            <strong>{{ source.locator?.title || source.document_id || '冻结来源' }}</strong>
            <p class="source-locator">
              文档版本 {{ source.document_version || source.locator?.document_version || '未记录' }}
              <span v-if="source.locator?.section"> · {{ source.locator.section }}</span>
              <span v-if="source.locator?.page != null"> · 第 {{ source.locator.page }} 页</span>
              <span v-if="source.locator?.line_start != null"> · 行 {{ source.locator.line_start }}–{{ source.locator.line_end ?? source.locator.line_start }}</span>
            </p>
            <blockquote class="evidence-excerpt">{{ source.excerpt }}</blockquote>
            <details class="source-identity"><summary>来源标识</summary><p>Evidence ID：{{ source.evidence_id }}</p><p>摘录 hash：{{ source.excerpt_hash || '未记录' }}</p></details>
          </template>
        </article>
        </div>
      </div>
    </details>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { verdictLabels } from './generationAudit.js'
const props = defineProps({ rows: { type: Array, default: () => [] }, focusFirst: { type: Boolean, default: false } })
const filter = ref('all')
const filteredRows = computed(() => props.rows.filter(row => filter.value === 'all' || row.verdict === filter.value))
const focusClaimId = computed(() => (filteredRows.value.find(row => ['contradicted', 'not_in_evidence', 'incomplete'].includes(row.verdict)) || filteredRows.value[0])?.claim_id)
</script>

<style scoped>
.claim-evidence-list { min-width:0; color:#172c45; }
.claim-list-heading { display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; align-items:center; padding:4px 0; }
.claim-list-heading strong { font-size:14px; font-weight:600; }.claim-list-heading label { color:#536577; font-size:12px; }
select { max-width:100%; margin-left:6px; }
.coverage-note,.source-locator { font-size:12px; color:#536577; line-height:1.7; overflow-wrap:anywhere; }
.coverage-note { margin:0 0 8px; }
.empty-note { padding:10px 12px; border-left:2px solid #a06c30; background:#fbf7ef; color:#785327; font-size:13px; line-height:1.7; overflow-wrap:anywhere; }
.claim-detail { margin:0; border-top:1px solid #dce4eb; background:#fff; }.claim-detail:last-child { border-bottom:1px solid #dce4eb; }
summary { display:flex; align-items:flex-start; gap:12px; cursor:pointer; min-height:48px; padding:12px 4px; line-height:1.7; overflow-wrap:anywhere; list-style:none; }
summary::-webkit-details-marker { display:none; }
.claim-number { width:24px; flex:none; padding-top:1px; color:#536577; font:11px/1.8 Consolas,monospace; font-variant-numeric:tabular-nums; }
.claim-copy { flex:1; min-width:0; }.claim-statement { display:block; margin-top:4px; color:#172c45; font-size:15px; font-weight:600; line-height:1.7; }
.claim-summary-reason { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; color:#536577; font-size:12px; margin-top:4px; }
.claim-expand { flex:none; width:16px; height:16px; color:#176b70; margin-top:5px; transition:transform .15s ease; }
.claim-detail[open] > summary .claim-expand { transform:rotate(180deg); }.claim-detail[open] > summary .claim-summary-reason { display:none; }
.claim-detail[open] > summary { padding-bottom:12px; }.claim-detail > summary:hover .claim-statement { color:#176b70; }
.verdict { display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:600; color:#785327; }
.verdict::before { content:''; width:5px; height:5px; border:1px solid currentColor; border-radius:50%; flex:none; }
.is-supported { color:#176556; }.is-contradicted { color:#a1322c; }.is-non_factual { color:#536577; }
.claim-detail-body { display:grid; grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr); gap:20px; margin:0 0 18px 40px; padding:16px 0; border-top:1px solid #edf1f5; font-size:14px; line-height:1.85; overflow-wrap:anywhere; }
.claim-statement-panel,.claim-evidence-panel { min-width:0; }.claim-statement-panel p { margin:12px 0; }.claim-statement-panel .claim-resource-version { color:#536577; font-size:12px; }
.evidence-section-label { display:flex; align-items:center; gap:8px; color:#536577; font-size:12px; margin-bottom:12px; }.evidence-section-label > span { font:10px/1.5 Consolas,monospace; letter-spacing:.06em; color:#176b70; }
.claim-evidence-panel { padding-left:20px; border-left:1px solid #dce4eb; }.evidence-card { margin:0 0 16px; }.evidence-card > strong { font-size:13px; }
.evidence-excerpt { margin:12px 0 4px; padding:10px 14px; border-left:2px solid #3d8a86; background:#f2f8f8; color:#24394e; white-space:pre-wrap; overflow-wrap:anywhere; }
.source-locator { margin:4px 0; }.source-identity { color:#536577; font-size:12px; }.source-identity p { margin:4px 0; font-family:Consolas,monospace; }
.source-identity summary { min-height:44px; padding:10px 0; font-size:12px; color:#536577; list-style:revert; display:list-item; }
summary:focus-visible { outline:2px solid #176b70; outline-offset:2px; }
@media (max-width:760px) { .claim-detail-body { grid-template-columns:1fr; gap:16px; margin-left:0; padding:14px 0; }.claim-evidence-panel { border-left:0; border-top:1px solid #dce4eb; padding:16px 0 0; }.claim-detail > summary { gap:8px; padding:12px 0; }.claim-number { width:20px; }.claim-statement { font-size:14px; } }
@media (prefers-reduced-motion:reduce) { .claim-expand { transition:none; } }
</style>
