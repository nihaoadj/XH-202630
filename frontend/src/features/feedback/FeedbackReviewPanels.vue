<template>
      <section class="result-details" aria-label="复盘详情">
          <article v-if="result.analysis || weakKnowledgePoints.length || summaryState" class="analysis-summary" aria-labelledby="feedback-analysis-heading">
            <header class="review-section-heading">
              <el-icon class="review-section-symbol" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6M8 8h2m-2 4h6m-6 4h8" />
                  <path d="m17 2 1.2 2.8L21 6l-2.8 1.2L17 10l-1.2-2.8L13 6l2.8-1.2Z" />
                </svg>
              </el-icon>
              <div>
                <h2 id="feedback-analysis-heading" class="analysis-heading"><strong>学习小结</strong><span v-if="result.analysis?.analysis_status === 'llm'">AI 分析</span></h2>
                <p>{{ wholeRound && result.analysis ? '总结本轮所有测评节点的表现。' : '理解本轮表现，找到学习重点。' }}</p>
              </div>
            </header>
            <div class="analysis-content" role="region" aria-label="学习小结正文" tabindex="0">
                <div v-if="weakKnowledgePoints.length" class="weak-points">
                  <span>优先巩固</span>
                  <b v-for="item in weakKnowledgePoints" :key="item.id">{{ item.label }}</b>
                </div>
              <template v-if="result.analysis">
            <p v-if="summaryState && result.analysis.analysis_status === 'fallback'">AI 小结未生成，以下是测评概况。</p>
            <p>{{ friendlyText(result.analysis.summary) }}</p>
            <p v-if="result.analysis.reflection_insight" class="reflection-insight">{{ friendlyText(result.analysis.reflection_insight) }}</p>
            <ul v-if="result.analysis.learner_suggestions?.length"><li v-for="item in result.analysis.learner_suggestions" :key="item">{{ friendlyText(item) }}</li></ul>
              </template>
              <template v-else-if="summaryState">
                <p v-if="summaryState === 'loading'" role="status">正在读取学习小结…</p>
                <p v-else>{{ summaryState === 'error' ? '暂时无法读取学习小结。' : '本次测评未保存 AI 学习小结。' }}</p>
                <p v-if="summaryReason">{{ summaryReason }}</p>
              </template>
            </div>
          </article>
          <article class="capability-result-panel" aria-labelledby="feedback-questions-heading">
            <header class="review-section-heading questions-section-heading">
              <div class="questions-heading-copy">
              <el-icon class="review-section-symbol" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M8 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-1" />
                  <rect x="8" y="3" width="8" height="4" rx="1.5" />
                  <path d="m8 12 1.2 1.2 2-2.4M14 12h2m-8 5h2m4 0h2" />
                </svg>
              </el-icon>
              <div>
                <h2 id="feedback-questions-heading" class="analysis-heading"><strong>逐题结果</strong><small v-if="feedbackReport.question_results?.length">{{ feedbackReport.question_results.length }} 道题</small></h2>
                <p>逐项核对知识点的掌握情况。</p>
              </div>
              </div>
              <div class="result-score" :class="{ 'is-danger': scoreRate != null && scoreRate < 0.6, 'is-warning': scoreRate >= 0.6 && scoreRate < 0.8 }">
                <span>测评得分</span>
                <div><strong>{{ Number(feedbackReport.total_score ?? 0) }}</strong><span> / {{ Number(feedbackReport.max_score ?? 100) }}</span></div>
                <meter v-if="feedbackReport.max_score > 0" min="0" :max="feedbackReport.max_score" :value="feedbackReport.total_score" aria-label="测评得分"></meter>
              </div>
            </header>
            <div v-if="feedbackReport.question_results?.length" class="question-results-content" role="region" aria-label="逐题结果明细" tabindex="0">
            <ul class="capability-result-list">
              <li v-for="(item, index) in feedbackReport.question_results" :key="item.question_id">
                <span class="result-question-index">{{ String(index + 1).padStart(2, '0') }}</span>
                <div class="result-question-label">
                  <strong>{{ item.knowledge_point || `第 ${index + 1} 题` }}</strong>
                  <span>{{ questionTypeLabel(item.question_type) }} · {{ item.correct ? '正确' : '待加强' }}</span>
                </div>
                <span class="result-question-score">{{ Number(item.score ?? 0) }} / {{ Number(item.max_score ?? 0) }}</span>
              </li>
            </ul>
            </div>
            <p v-else class="question-results-empty">本次反馈暂未提供逐题明细。</p>
          </article>
      </section>
</template>
<script setup>
import { computed } from 'vue'

const props = defineProps({
  result: { type: Object, required: true },
  feedbackReport: { type: Object, default: () => ({}) },
  weakKnowledgePoints: { type: Array, default: () => [] },
  summaryState: { type: String, default: '' },
  summaryReason: { type: String, default: '' },
  wholeRound: Boolean,
  friendlyText: { type: Function, default: value => String(value || '') },
  questionTypeLabel: { type: Function, default: type => ({ single_choice: '单选题', multiple_choice: '多选题', short_answer: '问答题' })[type] || '问答题' },
})
const scoreRate = computed(() => props.feedbackReport.total_score != null && props.feedbackReport.max_score > 0
  ? props.feedbackReport.total_score / props.feedbackReport.max_score : null)
</script>
