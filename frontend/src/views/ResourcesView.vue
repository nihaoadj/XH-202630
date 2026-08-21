<template>
  <div class="resources-page" :class="{ 'is-focus-mode': isFocusMode }">
    <header class="learning-toolbar">
      <div class="toolbar-title">
        <span class="eyebrow">Learning Resources</span>
        <h3>学习资源</h3>
      </div>
      <div class="toolbar-fields">
        <label class="field-label">
          <span>学习画像</span>
          <el-select v-model="selectedLearnerId" filterable placeholder="选择学习画像" popper-class="refined-select-dropdown" @change="handleProfileChange">
            <el-option v-for="item in profileOptions" :key="item.learner_id" :label="item.label" :value="item.learner_id" />
          </el-select>
        </label>
        <label class="field-label">
          <span>资源批次</span>
          <el-select v-model="selectedRunId" filterable :disabled="!taskGroups.length" placeholder="选择资源批次" popper-class="refined-select-dropdown" @change="handleRunChange">
            <el-option v-for="task in taskGroups" :key="task.runId" :label="task.label" :value="task.runId" />
          </el-select>
        </label>
      </div>
      <div class="toolbar-actions">
        <el-tooltip content="刷新资源" placement="bottom">
          <el-button class="refresh-button" :icon="Refresh" circle :loading="loading" aria-label="刷新资源" @click="loadResources" />
        </el-tooltip>
        <el-tooltip content="进入专注学习模式" placement="bottom">
          <el-button class="focus-button" :icon="FullScreen" circle aria-label="进入专注学习模式" @click="enterFocusMode" />
        </el-tooltip>
      </div>
    </header>

    <template v-if="activeTask">
      <section class="learning-workspace">
        <aside class="resource-shelf">
          <div class="shelf-heading">
            <div><span class="eyebrow">Current Materials</span><h3>本次资源</h3></div>
            <span class="shelf-count">{{ activeTask.resources.length }}</span>
          </div>
          <button v-for="(resource, index) in activeResources" :key="resource.resource_id" type="button" class="resource-item" :class="{ 'is-active': resource.resource_id === selectedResourceId }" @click="selectedResourceId = resource.resource_id">
            <span class="resource-order">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="resource-item-copy"><strong>{{ resource.resource_type || '学习资源' }}</strong><small>{{ resource.difficulty || '待分级' }} · {{ knowledgePointSummary(resource) }}</small></span>
            <span class="resource-arrow">→</span>
          </button>
          <div class="shelf-footnote"><span class="footnote-dot"></span>按顺序完成本批次学习</div>
        </aside>

        <main class="reading-stage">
          <ResourceViewer
            v-if="selectedResource"
            :resources="[selectedResource]"
            :progress-label="resourceProgress"
            :resource-choices="isFocusMode ? activeResources : []"
            :selected-resource-id="selectedResourceId"
            @select-resource="selectedResourceId = $event"
          />
        </main>
      </section>
    </template>

    <el-empty v-if="!activeTask && loaded && !loading" class="library-empty">
      <template #description><p>该学习画像下暂时没有可阅读的资源</p><span>完成学习方向中的资源生成后，材料会自动归档到这里。</span></template>
      <el-button type="primary" @click="$router.push('/learning/new')">新建学习方向</el-button>
    </el-empty>

    <el-tooltip v-if="isFocusMode" content="退出专注学习模式" placement="left">
      <el-button class="focus-exit" :icon="Close" circle aria-label="退出专注学习模式" @click="exitFocusMode" />
    </el-tooltip>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, FullScreen, Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { generateApi, knowledgeApi, profileApi, resourceApi } from '../api'
import { useAppStore } from '../stores/app'
import { formatDateTime } from '../utils/generationDisplay'
import ResourceViewer from '../components/ResourceViewer.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const selectedLearnerId = ref(route.query.learnerId || store.currentLearnerId || localStorage.getItem('last_learner_id') || '')
const selectedRunId = ref(route.query.runId || localStorage.getItem('current_generation_run_id') || '')
const selectedResourceId = ref('')
const resources = ref([])
const loaded = ref(false)
const loading = ref(false)
const profiles = ref([])
const tracks = ref([])
const generationJobs = ref([])
const resourceDetails = ref({})
let detailRequestGeneration = 0

const activeProfile = computed(() => profiles.value.find((item) => item.learner_id === selectedLearnerId.value) || null)
const isFocusMode = computed(() => route.query.focus === '1')
const activeDirectionName = computed(() => resolveTrackName(activeProfile.value?.knowledge_base_id))
const visibleResources = computed(() => {
  const supersededRunIds = new Set(
    generationJobs.value.filter((job) => job.superseded_by_run_id).map((job) => job.run_id),
  )
  const latestReplacementRunByType = new Map()
  for (const job of generationJobs.value) {
    if (job.superseded_by_run_id) continue
    const batchId = job.batch_id || job.run_id
    const types = job.request_payload?.constraints?.replacement_resource_types || []
    for (const type of types) {
      const key = `${batchId}:${type}`
      const current = latestReplacementRunByType.get(key)
      if (!current || String(current.created_at || '') < String(job.created_at || '')) {
        latestReplacementRunByType.set(key, job)
      }
    }
  }
  // A full-batch regeneration replaces the source run. Keep its workflow
  // history, but never mix its published artifacts into the current batch.
  return resources.value.filter((resource) => {
    if (supersededRunIds.has(resource.run_id)) return false
    const batchId = resource.batch_id || resource.run_id
    const replacement = latestReplacementRunByType.get(`${batchId}:${resource.resource_type}`)
    return !replacement || resource.run_id === replacement.run_id
  })
})
const profileOptions = computed(() => profiles.value.map((profile) => ({
  ...profile,
  label: `${resolveTrackName(profile.knowledge_base_id)} / ${profile.skill_level || '未分级'}`,
})))

function resolveTrackName(trackId) {
  return tracks.value.find((item) => item.track_id === trackId)?.name || trackId || '未命名方向'
}

const taskGroups = computed(() => {
  const groups = new Map()
  for (const resource of visibleResources.value) {
    const batchId = resource.batch_id || resource.run_id || `resource:${resource.resource_id}`
    if (!groups.has(batchId)) groups.set(batchId, { runId: batchId, batchId, shortRunId: batchId.startsWith('resource:') ? '独立资源' : batchId.slice(0, 8).toUpperCase(), resources: [] })
    groups.get(batchId).resources.push(resource)
  }
  const jobsByBatch = new Map()
  for (const job of generationJobs.value) {
    const batchId = job.batch_id || job.run_id
    if (!jobsByBatch.has(batchId)) jobsByBatch.set(batchId, [])
    jobsByBatch.get(batchId).push(job)
  }
  let initialIndex = 0
  let feedbackIndex = 0
  return Array.from(groups.values())
    .sort((left, right) => String(left.resources[0]?.created_at || '').localeCompare(String(right.resources[0]?.created_at || '')))
    .map((task) => {
    const timestamp = task.resources[0]?.created_at || task.resources[0]?.updated_at
    const isFeedbackBatch = (jobsByBatch.get(task.batchId) || []).some(
      (job) => Boolean(job.request_payload?.constraints?.feedback_attempt_id),
    )
    const batchLabel = isFeedbackBatch
      ? `反馈批次 ${String(++feedbackIndex).padStart(2, '0')}`
      : `初始资源批次 ${String(++initialIndex).padStart(2, '0')}`
    return { ...task, batchLabel, label: `${batchLabel} · ${task.resources.length} 份资源 · ${formatDateTime(timestamp)}` }
  })
})
const activeTask = computed(() => taskGroups.value.find((item) => item.runId === selectedRunId.value) || taskGroups.value[0] || null)
const activeResources = computed(() => activeTask.value?.resources || [])
const selectedResource = computed(() => {
  const resource = activeResources.value.find(
    (item) => item.resource_id === selectedResourceId.value,
  ) || activeResources.value[0] || null
  if (!resource?.resource_id) return resource
  return resourceDetails.value[resource.resource_id] || resource
})
const activeResourceIndex = computed(() => {
  const index = activeResources.value.findIndex((item) => item.resource_id === selectedResource.value?.resource_id)
  return index < 0 ? 0 : index + 1
})
const resourceProgress = computed(() => `第 ${String(activeResourceIndex.value).padStart(2, '0')} 份 / 共 ${String(activeResources.value.length).padStart(2, '0')} 份`)

function knowledgePointSummary(resource) {
  const points = resource.knowledge_points || []
  if (!points.length) return '核心知识学习'
  return points.length === 1 ? points[0] : `${points[0]} 等 ${points.length} 个知识点`
}

function syncSelectedRun() {
  if (!taskGroups.value.length) { selectedRunId.value = ''; return }
  if (selectedRunId.value && taskGroups.value.some((item) => item.runId === selectedRunId.value)) return
  const currentRunId = localStorage.getItem('current_generation_run_id') || ''
  const currentResource = visibleResources.value.find((item) => item.run_id === currentRunId)
  const currentBatchId = currentResource?.batch_id || currentResource?.run_id || currentRunId
  selectedRunId.value = taskGroups.value.some((item) => item.runId === currentBatchId)
    ? currentBatchId
    : taskGroups.value[0].runId
}

function syncSelectedResource() {
  if (!activeResources.value.some((item) => item.resource_id === selectedResourceId.value)) selectedResourceId.value = activeResources.value[0]?.resource_id || ''
}

async function loadSelectedResourceDetail() {
  const resourceId = selectedResourceId.value || activeResources.value[0]?.resource_id
  detailRequestGeneration += 1
  const generation = detailRequestGeneration
  if (!resourceId || resourceDetails.value[resourceId]) return
  try {
    const response = await resourceApi.get(resourceId)
    if (generation !== detailRequestGeneration) return
    const detail = response.data?.resource || response.data?.item || response.data
    if (detail?.resource_id === resourceId) {
      resourceDetails.value = { ...resourceDetails.value, [resourceId]: detail }
    }
  } catch (error) {
    if (generation !== detailRequestGeneration) return
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || error?.response?.data?.message || '资源正文加载失败')
  }
}

function handleRunChange(value) {
  if (value && !value.startsWith('resource:')) localStorage.setItem('current_generation_run_id', value)
  syncSelectedResource()
}

function enterFocusMode() {
  router.replace({ query: { ...route.query, focus: '1' } })
}

function exitFocusMode() {
  const query = { ...route.query }
  delete query.focus
  router.replace({ query })
}

function syncProfileContext() {
  const profile = activeProfile.value
  if (!profile) return
  store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id))
  localStorage.setItem('last_learner_id', profile.learner_id)
}

async function loadProfiles() {
  const [profileRes, domainRes] = await Promise.all([profileApi.list({ page: 1, page_size: 50 }), knowledgeApi.listDomains()])
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
  if (!profiles.value.length) { selectedLearnerId.value = ''; return }
  if (!profiles.value.some((item) => item.learner_id === selectedLearnerId.value)) selectedLearnerId.value = store.currentLearnerId || profiles.value[0].learner_id
  syncProfileContext()
}

async function loadResources() {
  if (!selectedLearnerId.value) {
    resources.value = []; loaded.value = true; selectedRunId.value = ''; selectedResourceId.value = ''
    return
  }
  loading.value = true
  try {
    const [res, jobsRes] = await Promise.all([
      resourceApi.listByLearner(selectedLearnerId.value, {
        page: 1,
        page_size: 100,
        summary_only: true,
      }),
      generateApi.listJobs(selectedLearnerId.value),
    ])
    detailRequestGeneration += 1
    resourceDetails.value = {}
    resources.value = res.data.resources || []
    generationJobs.value = jobsRes.data.items || []
    loaded.value = true
    syncSelectedRun()
    syncSelectedResource()
    await loadSelectedResourceDetail()
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '资源加载失败')
  } finally {
    loading.value = false
  }
}

async function handleProfileChange() {
  syncProfileContext()
  selectedRunId.value = ''
  selectedResourceId.value = ''
  await loadResources()
}

watch(activeTask, () => {
  syncSelectedResource()
  void loadSelectedResourceDetail()
})
watch(selectedResourceId, () => {
  viewMode.value = 'text'
  void loadSelectedResourceDetail()
})
onMounted(async () => { await loadProfiles(); await loadResources() })
</script>

<style scoped>
.resources-page { display: flex; flex-direction: column; gap: 20px; max-width: 1540px; margin: 0 auto; padding-bottom: 24px; }
.library-hero { position: relative; display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; min-height: 210px; padding: 36px 40px; overflow: hidden; border-radius: 24px; background: radial-gradient(circle at 84% 20%, rgba(45, 212, 191, .38), transparent 24%), radial-gradient(circle at 78% 120%, rgba(96, 165, 250, .35), transparent 42%), linear-gradient(120deg, #102d51 0%, #174b69 51%, #12646b 100%); box-shadow: 0 18px 38px rgba(20, 61, 91, .17); color: #fff; }
.hero-orbit { position: absolute; border: 1px solid rgba(255, 255, 255, .2); border-radius: 50%; pointer-events: none; }
.hero-orbit-one { right: 146px; top: -112px; width: 330px; height: 330px; }.hero-orbit-two { right: -38px; bottom: -164px; width: 330px; height: 330px; }
.hero-copy, .hero-actions { position: relative; z-index: 1; }.eyebrow { display: block; color: #2f6e5f; font-size: 12px; font-weight: 800; letter-spacing: 0; line-height: 1.2; text-transform: uppercase; }.library-hero .eyebrow { color: rgba(214, 249, 247, .75); }
.hero-copy h2 { margin: 10px 0 0; font-size: 32px; letter-spacing: -.03em; }.hero-copy p { max-width: 630px; margin: 10px 0 0; color: rgba(235, 249, 255, .82); font-size: 15px; line-height: 1.7; }.hero-actions { display: flex; flex: 0 0 auto; gap: 10px; }.hero-actions :deep(.el-button) { height: 40px; border-radius: 10px; font-weight: 650; }.hero-actions :deep(.el-button--primary) { border-color: #f7fffe; background: #f7fffe; color: #13545b; }.hero-refresh { border-color: rgba(255, 255, 255, .38) !important; background: rgba(255, 255, 255, .08) !important; color: #fff !important; }
.selection-card { display: grid; grid-template-columns: minmax(260px, .85fr) minmax(460px, 1.15fr); gap: 26px; align-items: center; padding: 22px 26px; border: 1px solid #dce6f2; border-radius: 18px; background: rgba(255,255,255,.92); box-shadow: 0 10px 30px rgba(38,69,105,.05); }.selection-title { display: flex; align-items: center; gap: 13px; }.step-badge { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 12px; background: #eaf2ff; color: #255db7; font-size: 13px; font-weight: 800; }.selection-title strong { color: #172a45; font-size: 16px; }.selection-title p { margin: 5px 0 0; color: #72819a; font-size: 13px; }.selection-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }.field-label { display: flex; flex-direction: column; gap: 7px; color: #65758e; font-size: 12px; font-weight: 650; }.field-label :deep(.el-select) { width: 100%; }.field-label :deep(.el-select__wrapper) { min-height: 40px; border-radius: 9px; box-shadow: 0 0 0 1px #d8e2ef inset; }
.path-overview { display: flex; align-items: stretch; justify-content: space-between; gap: 24px; padding: 25px 30px; border: 1px solid #dfe8f2; border-radius: 18px; background: linear-gradient(105deg, #f7fbff, #f3fbfa); }.path-heading h3, .shelf-heading h3 { margin: 7px 0 0; color: #162d49; font-size: 22px; letter-spacing: -.02em; }.path-heading p { margin: 9px 0 0; color: #61728b; font-size: 14px; }.path-stats { display: grid; grid-template-columns: repeat(3, minmax(106px, 1fr)); min-width: 380px; border-left: 1px solid #dbe7ed; }.stat-item { display: flex; flex-direction: column; justify-content: center; padding-left: 25px; }.stat-item + .stat-item { border-left: 1px solid #dbe7ed; }.stat-item span { color: #74859b; font-size: 12px; }.stat-item strong { margin-top: 7px; color: #173654; font-size: 24px; line-height: 1; }.stat-item small { color: #8091a8; font-size: 12px; font-weight: 500; }.task-stamp strong { color: #176b70; font-size: 15px; letter-spacing: .04em; }
.learning-workspace { display: grid; grid-template-columns: 290px minmax(0, 1fr); align-items: start; gap: 20px; }.resource-shelf { position: sticky; top: 0; padding: 23px 15px 15px; border: 1px solid #dce6ef; border-radius: 18px; background: #fff; box-shadow: 0 12px 30px rgba(35,62,94,.05); }.shelf-heading { display: flex; align-items: flex-start; justify-content: space-between; padding: 0 10px 18px; }.shelf-heading h3 { font-size: 18px; }.shelf-count { display: grid; min-width: 28px; height: 28px; place-items: center; border-radius: 9px; background: #e8f7f5; color: #17776f; font-size: 12px; font-weight: 800; }.resource-item { display: grid; grid-template-columns: 30px minmax(0, 1fr) 14px; width: 100%; gap: 10px; align-items: center; padding: 13px 10px; border: 1px solid transparent; border-radius: 12px; background: transparent; color: #344963; cursor: pointer; text-align: left; transition: .18s ease; }.resource-item:hover { background: #f4f8fd; }.resource-item.is-active { border-color: #b4d1ee; background: linear-gradient(100deg, #eaf4ff, #e8f9f5); box-shadow: 0 7px 15px rgba(53,110,157,.1); }.resource-order { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 8px; background: #eff4fa; color: #71839b; font-size: 10px; font-weight: 800; }.resource-item.is-active .resource-order { background: #1e6ed2; color: #fff; }.resource-item-copy { display: flex; min-width: 0; flex-direction: column; gap: 4px; }.resource-item-copy strong, .resource-item-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.resource-item-copy strong { color: #203853; font-size: 14px; }.resource-item-copy small { color: #77889d; font-size: 11px; }.resource-arrow { color: #91a1b6; font-size: 16px; transition: transform .18s ease; }.resource-item.is-active .resource-arrow { color: #18736d; transform: translateX(2px); }.shelf-footnote { display: flex; align-items: center; gap: 7px; margin: 15px 10px 2px; padding-top: 14px; border-top: 1px solid #e9eef5; color: #8594a8; font-size: 11px; }.footnote-dot { width: 6px; height: 6px; border-radius: 50%; background: #34b5a2; }.reading-stage { min-width: 0; }.reading-stage-topline { display: flex; justify-content: space-between; margin: 0 5px 9px; color: #718198; font-size: 12px; font-weight: 650; }.reading-stage-topline span:last-child { color: #38837e; }
.library-empty { padding: 58px 20px; border: 1px dashed #c9d7e6; border-radius: 18px; background: rgba(255,255,255,.72); }.library-empty :deep(.el-empty__description p) { margin: 0; color: #344a65; font-size: 16px; }.library-empty :deep(.el-empty__description span) { display: block; margin-top: 7px; color: #8592a4; font-size: 13px; }
@media (max-width: 1100px) { .selection-card, .learning-workspace { grid-template-columns: 1fr; }.resource-shelf { position: static; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; }.shelf-heading, .shelf-footnote { grid-column: 1 / -1; } }
@media (max-width: 760px) { .library-hero, .path-overview { flex-direction: column; align-items: flex-start; }.library-hero { min-height: auto; padding: 28px 24px; }.hero-copy h2 { font-size: 27px; }.selection-fields, .path-stats, .resource-shelf { grid-template-columns: 1fr; }.path-stats { width: 100%; min-width: 0; border-top: 1px solid #dbe7ed; border-left: 0; }.stat-item { padding: 16px 0 0; }.stat-item + .stat-item { margin-top: 12px; border-top: 1px solid #dbe7ed; border-left: 0; } }

/* The learning view keeps context compact so the reader remains the primary surface. */
.resources-page {
  min-height: calc(100dvh - 66px);
  gap: 12px;
  max-width: none;
  padding-bottom: 0;
}

.learning-toolbar {
  display: grid;
  grid-template-columns: minmax(150px, .55fr) minmax(540px, 1.45fr) 84px;
  gap: 18px;
  align-items: end;
  padding: 15px 18px;
  border: 1px solid #dbe6f2;
  border-radius: 10px;
  background: rgba(255, 255, 255, .94);
  box-shadow: 0 8px 22px rgba(35, 62, 94, .045);
}

.toolbar-title { display: flex; flex-direction: column; gap: 5px; padding-bottom: 1px; }
.toolbar-title .eyebrow { color: #2f6e5f; font-size: 12px; font-weight: 800; letter-spacing: 0; text-transform: uppercase; }
.toolbar-title h3 { margin: 0; color: #172033; font-size: 28px; line-height: 1.1; }
.toolbar-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.field-label { gap: 5px; font-size: 11px; }
.field-label :deep(.el-select__wrapper) { min-height: 36px; border-radius: 8px; }
.refresh-button { width: 36px; height: 36px; margin: 0; border-color: #cbd9e8; color: #276b67; }
.toolbar-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.focus-button { width: 36px; height: 36px; margin: 0; border-color: #b9d5cc; color: #1f776a; background: #f4fbf8; }
.focus-button:hover, .focus-button:focus-visible { border-color: #2f8b7b; color: #fff; background: #2f7768; }

.learning-context {
  display: flex;
  align-items: center;
  gap: 18px;
  min-height: 62px;
  padding: 10px 18px;
  border: 1px solid #dbe9ee;
  border-radius: 10px;
  background: linear-gradient(90deg, #f8fcff, #f2faf8);
}

.context-heading { display: flex; min-width: 220px; flex-direction: column; gap: 4px; }
.context-heading strong { color: #183653; font-size: 17px; }
.context-caption { color: #6e8199; font-size: 13px; }
.context-stats { display: flex; gap: 18px; margin-left: auto; color: #547087; font-size: 12px; white-space: nowrap; }
.context-stats span + span { padding-left: 18px; border-left: 1px solid #d7e6eb; }
.context-stats b { color: #1b6e6b; font-size: 17px; }

.learning-workspace {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  flex: 1;
}

.resource-shelf {
  position: static;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-height: none;
  padding: 10px 12px;
  border-radius: 10px;
  overflow-x: auto;
  overflow-y: hidden;
}

.shelf-heading { flex: 0 0 156px; align-items: center; padding: 0 6px; }
.shelf-count { align-self: center; }
.shelf-heading h3 { color: #172033; font-size: 17px; }
.resource-item { flex: 0 0 clamp(178px, 18vw, 238px); width: auto; padding: 11px 8px; border-color: #d9e1ec; border-radius: 9px; background: #fff; }
.shelf-footnote { display: none; }
.reading-stage { min-height: 0; }
.representation-switch { display: flex; justify-content: flex-end; margin-bottom: 10px; }
.representation-switch :deep(.el-button) { min-width: 96px; }
.reading-stage :deep(.reader-card) { min-height: calc(100dvh - 153px); }

.resources-page.is-focus-mode { min-height: 100dvh; height: 100dvh; gap: 0; padding: 12px; overflow-y: auto; background: #f3f7fb; }
.is-focus-mode .learning-toolbar, .is-focus-mode .resource-shelf { display: none; }
.is-focus-mode .learning-workspace, .is-focus-mode .reading-stage { flex: 1; min-height: calc(100dvh - 24px); }
.is-focus-mode .reading-stage :deep(.reader-card), .is-focus-mode .reading-stage :deep(.html-guide-card) { width: 100%; min-height: calc(100dvh - 24px); }
.focus-exit { position: fixed; right: 20px; bottom: 20px; z-index: 20; width: 42px; height: 42px; margin: 0; border-color: #8ab7ac; box-shadow: 0 8px 22px rgb(23 58 72 / 20%); color: #fff; background: #276f63; }
.focus-exit:hover, .focus-exit:focus-visible { border-color: #245e55; color: #fff; background: #1d584f; }

@media (max-width: 1100px) {
  .learning-toolbar { grid-template-columns: 1fr 84px; }
  .toolbar-title { display: none; }
  .learning-workspace { display: flex; flex-direction: column; }
}

@media (max-width: 760px) {
  .resources-page { min-height: auto; }
  .learning-toolbar { grid-template-columns: 1fr 84px; padding: 12px; }
  .toolbar-fields { grid-template-columns: 1fr; }
  .learning-workspace { display: flex; flex-direction: column; }
  .resource-shelf { align-items: stretch; }
  .shelf-heading { flex-basis: 132px; }
  .resource-item { flex-basis: 178px; }
  .reading-stage :deep(.reader-card) { min-height: auto; }
  .resources-page.is-focus-mode { padding: 8px; }
  .is-focus-mode .learning-workspace, .is-focus-mode .reading-stage, .is-focus-mode .reading-stage :deep(.reader-card), .is-focus-mode .reading-stage :deep(.html-guide-card) { min-height: calc(100dvh - 16px); }
  .focus-exit { right: 14px; bottom: 14px; }
}
</style>
