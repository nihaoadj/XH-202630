<template>
  <section class="detail-module" aria-label="修订版本对照">
    <div class="detail-section-heading"><span class="section-number">01 / REVISIONS</span><h3>修订前后对照</h3></div>
    <p class="audit-helper revision-flow">发现问题 <span aria-hidden="true">→</span> 定向修订 <span aria-hidden="true">→</span> 再次审核</p>
    <label v-if="versions.length" class="resource-picker">查看修订版本
      <select v-model="compareId" aria-label="对比版本"><option v-for="item in versions" :key="item.resource_id" :value="item.resource_id">v{{ item.version || '?' }} · {{ reviewStatusLabel(item.review_status) }}</option></select>
    </label>
    <p v-if="!versions.length" class="empty-note">没有当前资源执行链的版本记录。</p>
    <template v-else-if="compareVersion">
      <p v-if="!parent" class="empty-note">无可对比前版：没有同一执行链中明确的父版本。</p>
      <template v-else>
        <p class="audit-helper">变化范围包含共同前后文之间的全部行。</p>
        <p v-if="contentMissing" class="empty-note">版本正文缺失，无法计算差异。</p>
        <template v-else>
          <p v-if="!diff.changed" class="audit-helper">两个版本正文相同。</p>
          <p v-if="diff.truncated" class="empty-note">变化内容较长，每侧截取前 12000 字符；完整正文可在下方展开。</p>
        </template>
        <div class="version-comparison">
          <article v-for="column in comparisonColumns" :key="column.key" class="version-column">
            <span class="version-kicker">{{ column.label }}</span>
            <h4>{{ column.title }} v{{ column.item.version }} · {{ reviewStatusLabel(column.item.review_status) }}</h4>
            <template v-if="!contentMissing"><p class="audit-helper">变化行 {{ column.range }}</p><pre :class="`version-${column.key}`">{{ column.text || '（无变化内容）' }}</pre></template>
            <ReviewNotes :review="reviewFor(column.item)" />
          </article>
        </div>
      </template>
      <ReviewNotes v-if="!parent" :review="reviewFor(compareVersion)" />
      <details v-if="parent" class="audit-full-content"><summary>完整前版正文</summary><pre>{{ parent.content_text ?? '正文未记录' }}</pre></details>
      <details class="audit-full-content"><summary>完整本版正文</summary><pre>{{ compareVersion.content_text ?? '正文未记录' }}</pre></details>
    </template>
  </section>
</template>

<script setup>
import { computed, defineComponent, h, ref, watch } from 'vue'
import { resourceVersionChain, reviewStatusLabel, textChangeRange } from '../generationAudit.js'

const props = defineProps({
  chain: { type: Array, default: () => [] }, resourceId: { type: String, default: '' },
  allReviews: { type: Array, default: () => [] }, runId: { type: String, default: '' },
})
const compareId = ref('')
const runVersions = computed(() => props.runId ? props.chain.filter(item => item && item.run_id === props.runId && item.resource_id) : [])
const anchor = computed(() => runVersions.value.find(item => item.resource_id === props.resourceId))
const versions = computed(() => resourceVersionChain(runVersions.value, anchor.value, props.runId))
watch([() => props.runId, () => props.resourceId], () => { compareId.value = anchor.value?.resource_id || '' }, { immediate: true })
watch(versions, items => {
  if (!items.some(item => item.resource_id === compareId.value)) compareId.value = anchor.value?.resource_id || ''
}, { immediate: true })
const compareVersion = computed(() => versions.value.find(item => item.resource_id === compareId.value))
const parent = computed(() => {
  const child = compareVersion.value
  if (!child?.parent_resource_id || child.parent_resource_id === child.resource_id) return null
  return versions.value.find(item => item.resource_id === child.parent_resource_id && item.run_id === child.run_id) || null
})
const contentMissing = computed(() => parent.value?.content_text == null || compareVersion.value?.content_text == null)
const diff = computed(() => textChangeRange(parent.value?.content_text, compareVersion.value?.content_text, 12000))
const comparisonColumns = computed(() => parent.value && compareVersion.value ? [
  { key: 'before', label: 'BEFORE', title: '前版', item: parent.value, range: diff.value.beforeRange, text: diff.value.before },
  { key: 'after', label: 'AFTER', title: '本版', item: compareVersion.value, range: diff.value.afterRange, text: diff.value.after },
] : [])
function reviewFor(item) {
  if (!item?.review_id || item.run_id !== props.runId) return null
  return props.allReviews.find(review => review && review.review_id === item.review_id
    && review.run_id === props.runId && review.resource_id === item.resource_id) || null
}
function formatValue(value) { return typeof value === 'string' ? value : JSON.stringify(value) ?? '未记录' }
function issueText(issue) { return typeof issue === 'string' ? issue : formatValue(issue?.description || issue?.message || issue?.code || issue) }
const ReviewNotes = defineComponent({
  props: { review: { type: Object, default: null } },
  setup(componentProps) {
    return () => {
      const review = componentProps.review
      if (!review) return h('div', { class: 'version-review-notes' }, [h('p', '未记录审核详情')])
      const issues = Array.isArray(review.issues) ? review.issues : []
      const instructions = Array.isArray(review.revision_instructions) ? review.revision_instructions : []
      return h('div', { class: 'version-review-notes' }, [
        h('h4', '审核与修改要求'), h('p', { class: 'version-review-status' }, `审核结果：${reviewStatusLabel(review.status)}`),
        issues.length ? h('ul', { class: 'version-review-issues' }, issues.map(issue => h('li', [
          h('p', issueText(issue)),
          ...(issue?.location || issue?.knowledge_point ? [h('small', `位置：${formatValue(issue.location || issue.knowledge_point)}`)] : []),
        ]))) : h('p', '本次普通审核未记录问题。'),
        ...(instructions.length ? [h('h5', '定向修订指令'), h('ol', instructions.map(item => h('li', formatValue(item?.action || item))))] : []),
      ])
    }
  },
})
</script>
