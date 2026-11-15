<template>
  <section class="history-resources" aria-label="本阶段资源详情" :aria-busy="loading">
    <p v-if="loading" role="status">正在读取资源与质量记录…</p>
    <p v-else-if="!ids.length">本阶段尚无关联资源</p>
    <el-button v-if="failed && !loading" text @click="retry++">部分记录读取失败，点击重试</el-button>
    <div v-if="!loading" class="history-resource-grid">
      <article v-for="id in ids" :key="id" class="history-resource-card">
        <template v-if="resources[id]">
          <div class="resource-identity" :title="resources[id].topic"><span class="resource-kind">{{ resources[id].resource_type }}</span><small>v{{ resources[id].version }}<span v-if="resources[id].publication_status !== 'published'"> · 未发布</span></small></div>
          <div class="resource-metric" :title="hallucinationMetricText(qualityFor(id)?.hallucination)"><span>幻觉率</span><strong :class="`tone-${qualityTone(qualityFor(id)?.hallucination)}`">{{ qualityValueText(qualityFor(id)?.hallucination) }}</strong><small>{{ metricNote(qualityFor(id)?.hallucination) }}</small></div>
          <div class="resource-metric" :title="qualityMetricText(qualityFor(id)?.coverage)"><span>知识覆盖</span><strong>{{ qualityValueText(qualityFor(id)?.coverage) }}</strong><small>{{ metricNote(qualityFor(id)?.coverage) }}</small></div>
          <el-button v-if="resources[id].publication_status === 'published'" class="resource-open" text @click="openResource(id)">查看资源 <span aria-hidden="true">↗</span></el-button>
          <span v-else class="resource-unavailable">尚未发布</span>
        </template>
        <span v-else class="resource-error">资源详情暂不可用，请重试。</span>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { resourceApi } from '../learning-documents/api.js'
import { runApi } from '../runs/queryApi.js'
import { hallucinationMetricText, qualityMetricText, qualityTone, qualityValueText, statusLabel, sourceLabel } from '../../utils/qualityMetricsPresentation.js'
const props = defineProps({ member: { type: Object, required: true }, learnerId: { type: String, required: true }, active: Boolean })
const router = useRouter()
const ids = computed(() => [...new Set(props.member.resource_ids || [])])
const resources = ref({}), qualities = ref([]), loading = ref(false), failed = ref(false), retry = ref(0)
let loadedKey = ''
async function batches(values, task) {
  const results = []
  for (let index = 0; index < values.length; index += 4) results.push(...await Promise.allSettled(values.slice(index, index + 4).map(task)))
  return results
}
watch(() => [props.active, props.learnerId, ids.value.join(','), (props.member.job_ids || []).join(','), retry.value], async (_, __, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  const key = JSON.stringify([props.learnerId, ids.value, props.member.job_ids, retry.value])
  if (!props.active || loadedKey === key) return
  loading.value = true
  failed.value = false
  resources.value = {}; qualities.value = []
  const learnerId = props.learnerId
  const resourceResults = await batches(ids.value, async id => {
    const { data } = await resourceApi.get(id)
    const item = data?.resource || data?.item || data
    if (item?.resource_id !== id || item.learner_id !== learnerId) throw new Error('Resource ownership mismatch')
    return item
  })
  if (!current) return
  const runIds = [...new Set([...(props.member.job_ids || []), ...resourceResults.filter(item => item.status === 'fulfilled').map(item => item.value.run_id)].filter(Boolean))]
  const qualityResults = await batches(runIds, async runId => {
    const { data } = await runApi.resourceQuality(runId)
    if (data.run_id !== runId) throw new Error('Quality run mismatch')
    return data.items.filter(item => item.run_id === runId)
  })
  if (!current) return
  resources.value = Object.fromEntries(resourceResults.filter(item => item.status === 'fulfilled').map(item => [item.value.resource_id, item.value]))
  qualities.value = qualityResults.filter(item => item.status === 'fulfilled').flatMap(item => item.value)
  failed.value = [...resourceResults, ...qualityResults].some(item => item.status === 'rejected')
  loading.value = false
  loadedKey = key
}, { immediate: true })
function qualityFor(id) {
  const resource = resources.value[id]
  return qualities.value.find(item => item.resource_id === id && item.resource_version === resource?.version && item.run_id === resource?.run_id)
}
function metricNote(metric) {
  if (!metric) return '未记录'
  if (metric.status === 'reference') return '参考 · 未校准'
  return metric.status === 'complete' ? sourceLabel(metric) : statusLabel(metric)
}
function openResource(id) {
  router.push({ path: '/resources', query: { learnerId: props.learnerId, runId: resources.value[id].batch_id || resources.value[id].run_id, resourceId: id } })
}
</script>

<style scoped>
.history-resources { width:100%; min-width:0; color:#536b7d; font-size:12px; }
.history-resource-grid { display:grid; gap:7px; }
.history-resource-card { display:grid; grid-template-columns:minmax(110px,.8fr) minmax(0,1.2fr) minmax(0,1.2fr) auto; align-items:center; gap:12px; min-width:0; padding:11px 14px; border:1px solid rgba(137,180,196,.3); border-radius:11px; background:linear-gradient(115deg,rgba(255,255,255,.87),rgba(235,246,249,.64)); box-shadow:0 3px 10px -8px rgba(24,68,88,.32),inset 0 1px rgba(255,255,255,.95); overflow-wrap:anywhere; }
.resource-identity { display:flex; align-items:center; flex-wrap:wrap; gap:7px; min-width:0; }
.resource-kind { color:#23566a; font-size:12px; font-weight:600; }
.resource-identity small { color:#728895; font-size:10px; }
.resource-metric { display:flex; align-items:baseline; flex-wrap:wrap; gap:5px 7px; min-width:0; padding-left:12px; border-left:1px solid rgba(154,187,201,.26); font-size:11px; line-height:1.7; }
.resource-metric strong { color:#254e65; font-size:13px; font-weight:600; font-variant-numeric:tabular-nums; }
.resource-metric small { color:#6b8390; font-size:10px; }
.resource-metric strong.tone-success { color:#17675c; } .resource-metric strong.tone-attention { color:#86602d; }
.history-resources .resource-open { min-height:30px; height:30px; padding:5px 7px; border-radius:7px; color:#21677e; font-size:11px; }
.resource-open span { margin-left:5px; }
.resource-error { grid-column:1 / -1; }
.resource-unavailable { font-size:11px; }
@media(max-width:760px) { .history-resource-card { grid-template-columns:minmax(0,1fr) auto; gap:8px; padding:11px; } .resource-identity { grid-column:1; grid-row:1; } .resource-open,.resource-unavailable { grid-column:2; grid-row:1; } .resource-metric { grid-column:1 / -1; border-left:0; padding-left:0; } }
</style>
