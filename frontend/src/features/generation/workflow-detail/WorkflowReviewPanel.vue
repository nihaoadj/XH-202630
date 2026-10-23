<template>
  <section class="detail-module" aria-label="资源审核结论">
    <div class="detail-section-heading"><span class="section-number">01 / REVIEW</span><h3>审核结论与修订要求</h3></div>
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
import { reviewStatusLabel } from '../generationAudit.js'

const props = defineProps({
  reviews: { type: Array, default: () => [] },
  step: { type: Object, default: null },
})
// The shell supplies only Reviews linked to the selected resource and Run.
// This panel does not search for replacements or promote execution success.
const records = computed(() => props.reviews.filter(item => item && typeof item === 'object'))
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
