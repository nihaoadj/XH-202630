<template>
  <section class="detail-module" aria-label="资源审核结论">
    <div class="detail-section-heading"><span class="section-number">01 / REVIEW</span><h3>审核结论与修订要求</h3></div>
    <div v-if="quality" class="review-quality" aria-label="质量指标来源与测量状态">
      <div class="review-quality-row">
        <span class="review-quality-label">知识覆盖</span>
        <strong :class="`is-${qualityTone(quality.coverage)}`">{{ qualityValueText(quality.coverage) }}</strong>
        <small>{{ qualityMetricText(quality.coverage) }}</small>
      </div>
      <div class="review-quality-row">
        <span class="review-quality-label">幻觉率</span>
        <strong :class="`is-${qualityTone(quality.hallucination)}`">{{ hallucinationMetricText(quality.hallucination) }}</strong>
        <small v-if="isReferenceMetric(quality.hallucination)">未校准规则参考值，不作为达标结论。</small>
      </div>
      <p v-if="coverageRows.length" class="review-quality-targets">
        逐知识点结果：{{ coverageSummary }}
      </p>
      <ul v-if="coverageRows.length" class="review-quality-targets" aria-label="逐知识点定位">
        <li v-for="row in coverageRows" :key="row.target_id">{{ row.display_name }}（{{ row.target_id }}）：{{ row.covered ? '已覆盖' : '未覆盖' }}<span v-if="row.location"> · {{ row.location }}</span></li>
      </ul>
      <p class="review-quality-targets">事实与证据：{{ dimensionStatusLabel(quality.ordinary_review?.factual_evidence) }} · 难度：{{ dimensionStatusLabel(quality.ordinary_review?.difficulty) }} · 自包含性：{{ dimensionStatusLabel(quality.ordinary_review?.self_contained) }}</p>
      <div v-if="quality.issue_statistics" class="review-quality-targets" aria-label="完整问题账本统计">
        <p>问题账本：{{ ({ complete: '完整', partial: '部分记录', unavailable: '历史不可用' })[quality.issue_statistics.history_completeness] || '未知' }}；当前开放 {{ quality.issue_statistics.open_issue_total ?? '未知' }}，阻断 {{ quality.issue_statistics.blocked_by_issue_total ?? '未知' }}</p>
        <p>已修复 {{ quality.issue_statistics.fixed_issue_total ?? '未知' }} · 误报 {{ quality.issue_statistics.false_positive_issue_total ?? '未知' }} · 仍开放 {{ quality.issue_statistics.still_open_issue_total ?? '未知' }} · 无法核验 {{ quality.issue_statistics.unverifiable_issue_total ?? '未知' }} · 重新打开 {{ quality.issue_statistics.reopened_issue_total ?? '未知' }}</p>
        <p v-if="quality.issue_statistics.open_by_severity">开放严重程度：轻微 {{ quality.issue_statistics.open_by_severity.low }} · 一般 {{ quality.issue_statistics.open_by_severity.medium }} · 严重 {{ quality.issue_statistics.open_by_severity.high }} · 关键 {{ quality.issue_statistics.open_by_severity.critical }}</p>
        <p v-if="quality.issue_statistics.open_by_dimension">开放维度：事实与证据 {{ quality.issue_statistics.open_by_dimension.factual_evidence }} · 覆盖 {{ quality.issue_statistics.open_by_dimension.coverage }} · 难度 {{ quality.issue_statistics.open_by_dimension.difficulty }} · 自包含性 {{ quality.issue_statistics.open_by_dimension.self_contained }}</p>
      </div>
      <p class="review-quality-caption">以上数值来自后端版本化质量投影（{{ quality.metric_policy_version }}），前端不重算。</p>
    </div>
    <p v-if="!records.length" class="empty-note">当前资源没有可展示的普通审核记录；执行完成不能替代审核通过。</p>
    <article v-for="(review, reviewIndex) in records" :key="review.review_id || reviewIndex" class="review-card" :class="reviewTone(review.status)">
      <header class="review-card-heading">
        <h4>
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <circle cx="10" cy="10" r="8" />
            <path v-if="reviewTone(review.status) === 'is-approved'" d="m6 10 3 3 5-6" />
            <path v-else d="M10 5v6m0 2v2" />
          </svg>
          {{ reviewStatusLabel(review.status) }}
        </h4>
        <span>返工 {{ review.revision_count || 0 }} 轮</span>
      </header>
      <p v-if="!issuesFor(review).length" class="review-clear">本次普通审核未记录问题。</p>
      <div v-else class="review-issues">
        <article v-for="(issue, index) in issuesFor(review)" :key="index" class="review-issue">
          <span class="issue-number">{{ String(index + 1).padStart(2, '0') }}</span>
          <div class="review-issue-copy">
            <div class="issue-heading"><strong>问题 {{ index + 1 }}</strong><span class="issue-level">{{ severityLabel(issue?.severity) }}</span></div>
            <p>{{ issueText(issue) }}</p>
            <small v-if="issue?.location || issue?.knowledge_point">位置：{{ formatValue(issue.location || issue.knowledge_point) }}</small>
          </div>
        </article>
      </div>
      <div v-if="instructionsFor(review).length" class="revision-instructions">
        <h4>定向修订指令</h4>
        <ol><li v-for="(instruction, index) in instructionsFor(review)" :key="index">{{ formatValue(instruction?.action || instruction) }}</li></ol>
      </div>
    </article>
    <section v-if="props.step" class="review-agent-output">
      <header class="review-agent-output-heading">
        <span class="section-number">NODE OUTPUT</span>
        <h4>本次审核节点记录</h4>
      </header>
      <dl class="review-output-copy">
        <div>
          <dt>审核执行摘要</dt>
          <dd>{{ stepValue(props.step.output_summary) }}</dd>
        </div>
        <div>
          <dt>审核说明</dt>
          <dd>{{ stepValue(props.step.decision_reason) }}</dd>
        </div>
      </dl>
      <p class="review-agent-output-caption">接口未保存完整模型回复；这里展示已保存的审核节点摘要与说明，不代表事实正确率统计。</p>
    </section>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import {
  coverageTargetRows, dimensionStatusLabel, hallucinationMetricText, isReferenceMetric,
  qualityMetricText, qualityTone, qualityValueText,
} from '../../../utils/qualityMetricsPresentation.js'
import { reviewStatusLabel } from '../generationAudit.js'

const props = defineProps({
  reviews: { type: Array, default: () => [] },
  step: { type: Object, default: null },
  quality: { type: Object, default: null },
})
// The shell supplies only Reviews linked to the selected resource and Run.
// This panel does not search for replacements or promote execution success.
const records = computed(() => props.reviews.filter(item => item && typeof item === 'object'))
const coverageRows = computed(() => coverageTargetRows(props.quality))
const coverageSummary = computed(() => {
  const covered = coverageRows.value.filter(row => row.covered)
  const missing = coverageRows.value.filter(row => !row.covered).map(row => row.target_id)
  const coveredText = `已覆盖 ${covered.length}/${coverageRows.value.length}`
  return missing.length ? `${coveredText}；未覆盖：${missing.join('、')}` : coveredText
})
function issuesFor(review) { return Array.isArray(review.issues) ? review.issues : [] }
function instructionsFor(review) { return Array.isArray(review.revision_instructions) ? review.revision_instructions : [] }
function formatValue(value) { return typeof value === 'string' ? value : JSON.stringify(value) ?? '未记录' }
function stepValue(value) {
  if (typeof value === 'string') return value.trim() ? value : '未记录'
  return value == null ? '未记录' : formatValue(value)
}
function issueText(issue) { return typeof issue === 'string' ? issue : formatValue(issue?.description || issue?.message || issue?.code || issue) }
function severityLabel(value) { return ({ low: '轻微', medium: '一般', high: '严重', critical: '关键问题' })[value] || value || '未分级' }
function reviewTone(value) {
  return ({ approved: 'is-approved', pass: 'is-approved', rejected: 'is-rejected', reject: 'is-rejected', revision_requested: 'is-revision', revise: 'is-revision' })[value] || 'is-pending'
}
</script>

<style scoped>
.review-quality { display:grid; gap:6px; margin:0 0 12px; padding:10px; border:1px solid #d6e2e9; border-radius:6px; background:#f6f9fb; }
.review-quality-row { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 8px; }
.review-quality-label { min-width:64px; color:#59697b; font-size:12px; }
.review-quality-row strong { font-size:13px; font-weight:600; color:#172c45; }
.review-quality-row strong.is-success { color:#176b70; }
.review-quality-row strong.is-attention { color:#935719; }
.review-quality-row strong.is-muted { color:#59697b; }
.review-quality-row small { color:#59697b; font-size:12px; overflow-wrap:anywhere; }
.review-quality-targets { margin:0; color:#172c45; font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
.review-quality-caption { margin:0; color:#59697b; font-size:12px; }
</style>
