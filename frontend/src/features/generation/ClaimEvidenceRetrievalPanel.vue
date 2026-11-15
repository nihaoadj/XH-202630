<template>
  <section v-if="visible" class="claim-supplement" data-testid="claim-evidence-retrieval" aria-label="证据补检状态">
    <div class="claim-supplement-heading">
      <span class="section-number">SUPPLEMENT</span>
      <strong>{{ headline }}</strong>
    </div>
    <p class="claim-supplement-summary">{{ summaryText }}</p>
    <p v-if="globalHardBlock" class="claim-supplement-block">
      该资源版本因新增反证或来源冲突不得发布，需要修订后重新审核。
    </p>
    <ul v-if="rows.length" class="claim-supplement-sessions">
      <li v-for="row in rows" :key="row.key" :class="{ 'is-blocked': row.hardBlock }">
        <span class="claim-supplement-round">{{ row.roundLabel }}</span>
        <span class="claim-supplement-status">{{ row.statusLabel }}</span>
        <span class="claim-supplement-counts">
          目标 {{ row.targetTotal }} 条 · 已重判 {{ row.attemptedTotal }} 条 · 未执行 {{ row.remainingTotal }} 条
        </span>
        <span v-if="row.reason" class="claim-supplement-reason">{{ row.reason }}</span>
      </li>
    </ul>
    <p v-if="!rows.length" class="empty-note">本次没有产生补检会话，展示首次判定。</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import {
  shouldShowSupplement,
  supplementSessionRows,
  supplementStatusLabel,
  supplementSummaryText,
} from './claimEvidenceRetrievalPresentation.js'

const props = defineProps({
  summary: { type: Object, default: null },
})

const visible = computed(() => shouldShowSupplement(props.summary))
const rows = computed(() => supplementSessionRows(props.summary))
const summaryText = computed(() => supplementSummaryText(props.summary))
const headline = computed(() => supplementStatusLabel(props.summary?.status))
const globalHardBlock = computed(() => rows.value.some(row => row.hardBlock))
</script>

<style scoped>
.claim-supplement { margin: 10px 0 4px; padding: 12px; border: 1px solid #d7e2ee; border-radius: 12px; background: #f7fafd; color: #172c45; }
.claim-supplement-heading { display: flex; gap: 8px; align-items: baseline; }
.claim-supplement-heading strong { font-size: 14px; }
.claim-supplement-summary { margin: 6px 0; color: #44586d; font-size: 12px; }
.claim-supplement-block { margin: 6px 0; color: #98351f; font-size: 12px; font-weight: 600; }
.claim-supplement-sessions { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.claim-supplement-sessions li { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: baseline; padding: 6px 8px; border-radius: 8px; background: #fff; font-size: 12px; }
.claim-supplement-sessions li.is-blocked { background: #fff4f1; }
.claim-supplement-round { font-weight: 600; }
.claim-supplement-status { color: #2c5f8a; }
.claim-supplement-counts { color: #536577; }
.claim-supplement-reason { color: #7a5a24; }
@media (max-width: 640px) { .claim-supplement-sessions li { flex-direction: column; align-items: flex-start; } }
</style>
