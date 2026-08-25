<template>
  <div class="courseware-generation-page">
    <section v-if="!embedded" class="workspace-header">
      <div>
        <span class="eyebrow">Interactive Courseware</span>
        <h3>互动课件生成</h3>
        <p>仅支持选择已发布的实操指南或复习清单；系统会为每一份资源独立生成互动 HTML 课件。</p>
      </div>
      <div class="workspace-header-actions">
        <el-button @click="$emit('open-text-workspace')">文本资源生成</el-button>
        <el-button @click="openLearningResources">返回学习资源</el-button>
      </div>
    </section>

    <section v-if="!embedded" class="workspace-controls">
      <label>
        <span>学习画像</span>
        <el-select v-model="selectedLearnerId" filterable placeholder="选择学习画像" @change="handleLearnerChange">
          <el-option v-for="profile in profiles" :key="profile.learner_id" :value="profile.learner_id" :label="profileLabel(profile)" />
        </el-select>
      </label>
      <label>
        <span>课件任务</span>
        <el-select v-model="selectedRunId" filterable :disabled="!jobs.length" placeholder="选择课件任务" @change="handleRunChange">
          <el-option v-for="job in jobs" :key="job.run_id" :value="job.run_id" :label="jobLabel(job)" />
        </el-select>
      </label>
      <el-button type="primary" :disabled="!canCreate" @click="sourceDialogVisible = true">生成新课件版本</el-button>
    </section>
    <section v-else-if="!hideControls" class="embedded-workspace-controls">
      <div><span class="eyebrow">Interactive Courseware</span><strong>互动课件生成过程</strong><small>课件将作为当前资源批次的追加资源创建。</small></div>
      <el-select v-model="selectedRunId" filterable :disabled="!jobs.length" placeholder="选择互动课件任务" @change="handleRunChange">
        <el-option v-for="job in jobs" :key="job.run_id" :value="job.run_id" :label="jobLabel(job)" />
      </el-select>
      <el-button type="primary" :disabled="!canCreate" @click="openCreateDialog">追加互动课件</el-button>
    </section>

    <section v-if="currentJob && !hideControls" class="courseware-job-summary">
      <div><span>任务状态</span><strong :class="`state-${currentJob.status}`">{{ stateLabel(currentJob.status) }}</strong></div>
      <div><span>课件任务</span><strong>{{ currentJob.title || shortRunId }}</strong></div>
      <div><span>来源批次</span><strong>{{ currentJob.source_batch_id || '冻结中' }}</strong></div>
      <div><span>创建时间</span><strong>{{ formatDateTime(currentJob.created_at) }}</strong></div>
      <div><span>当前连接</span><strong>{{ connectionLabel }}</strong></div>
      <div><span>发布资源</span><strong>{{ currentJob.resource_id ? '已就绪' : '尚未发布' }}</strong></div>
    </section>

    <section v-if="currentJob" class="generation-grid">
      <article class="process-panel">
        <div class="panel-title"><div><span class="eyebrow">Workflow Trace</span><h3>生成过程</h3></div><el-tag :type="connectionStatus === 'live' ? 'success' : 'info'" effect="plain">{{ connectionLabel }}</el-tag></div>
        <ol class="workflow-snake" aria-label="课件生成步骤">
          <li
            v-for="(stage, index) in stages"
            :key="stage.id"
            class="workflow-snake-step"
            :class="{ 'is-complete': index < activeStage - 1, 'is-active': index === activeStage - 1 }"
            :style="snakeStepPosition(index)"
          >
            <span class="workflow-snake-node">{{ index + 1 }}</span>
            <span class="workflow-snake-copy"><strong>{{ stage.label }}</strong><small>{{ stageDescription(stage) || (index < activeStage - 1 ? '已完成' : '等待中') }}</small></span>
          </li>
        </ol>
        <p v-if="currentJob.error_message" class="error-message">{{ currentJob.error_message }}</p>
        <div class="process-actions">
          <el-button @click="refreshCurrentJob">刷新状态</el-button>
          <el-button v-if="retryable" type="warning" :loading="busy" @click="retryJob">重试任务</el-button>
          <el-button v-if="published" type="primary" @click="openPublishedResource">进入学习</el-button>
        </div>
      </article>

      <article class="details-panel">
        <div class="panel-title"><div><span class="eyebrow">Courseware Details</span><h3>课件过程详情</h3></div></div>
        <div class="details-scroll">
          <section v-if="Object.keys(visibleRequestOptions).length" class="frozen-options"><strong>已冻结偏好</strong><el-tag v-for="(value, key) in visibleRequestOptions" :key="key" effect="plain">{{ optionLabel(key) }}：{{ value }}</el-tag></section>
          <section v-if="currentJob.quality_summary && Object.keys(currentJob.quality_summary).length" class="quality-summary"><strong>质量汇总</strong><span>发布：{{ currentJob.quality_summary.publication_success ? '成功' : '未发布' }}</span><span>来源覆盖：{{ qualityPercent(currentJob.quality_summary.adopted_source_coverage) }}</span><span>场景恢复：{{ qualityPercent(currentJob.quality_summary.required_scene_recovery_rate) }}</span><span>审核：{{ currentJob.quality_summary.rubric_passed ? '通过' : '进行中或未通过' }}</span></section>
          <section class="scene-list"><div class="section-heading"><strong>页面与场景</strong><span>{{ currentJob.scenes?.length || 0 }} 个</span></div><el-empty v-if="!currentJob.scenes?.length" description="课程蓝图完成后，这里将显示每页的生成状态。" :image-size="80" /><ol v-else><li v-for="scene in currentJob.scenes" :key="scene.scene_id"><div><strong>{{ scene.scene_order + 1 }}. {{ scene.title || scene.kind }}</strong><small>{{ scene.status }} · 第 {{ scene.attempt }} 次尝试</small></div><el-button v-if="retryableScene(scene)" link type="primary" :loading="busy" @click="retryScene(scene.scene_id)">重试此页</el-button></li></ol></section>
          <ul v-if="currentJob.warnings?.length" class="warnings"><li v-for="warning in currentJob.warnings" :key="`${warning.code}:${warning.message}`">{{ warning.message || warning.code }}</li></ul>
        </div>
      </article>
    </section>

    <section v-else-if="!hideControls" class="empty-workspace"><span class="eyebrow">Ready to create</span><h3>还没有可展示的互动课件任务</h3><p>选择已发布的实操指南或复习清单，分别生成互动版。</p></section>

    <el-dialog v-model="sourceDialogVisible" title="创建互动课件" width="min(680px, 92vw)" :close-on-click-modal="false">
      <p class="source-hint">每个选中的资源都会独立冻结、独立规划、独立生成。不会合并资源内容；实操指南生成固定阶段操作版，复习清单生成主动回忆版。</p>
      <div class="preference-grid"><label><span>学习目标</span><el-input v-model="preferences.learning_goal" maxlength="240" placeholder="例如：完成本资源的核心练习" /></label><label><span>预计时长（分钟）</span><el-input-number v-model="preferences.expected_duration_minutes" :min="5" :max="240" :step="5" /></label><label><span>互动强度</span><el-select v-model="preferences.interaction_intensity"><el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /></el-select></label></div>
      <el-checkbox-group v-model="selectedSourceIds" class="source-list"><el-checkbox v-for="resource in sourceCandidates" :key="resource.resource_id" :label="resource.resource_id" :disabled="selectedSourceIds.length >= 8 && !selectedSourceIds.includes(resource.resource_id)"><strong>{{ resource.resource_type }}</strong><span>{{ resource.topic || resource.title || resource.resource_id }}</span></el-checkbox></el-checkbox-group>
      <template #footer><el-button @click="sourceDialogVisible = false">取消</el-button><el-button type="primary" :disabled="!selectedSourceIds.length" :loading="busy" @click="createCourseware">为 {{ selectedSourceIds.length }} 份资源生成互动版</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { knowledgeApi, profileApi } from '../../api'
import { resourceLibraryApi } from '../resource-library/api'
import { buildCoursewareBatchRequest, coursewareEligibleSources } from './sourcePolicy'
import { coursewareApi } from './api'
import { formatDateTime } from '../../utils/generationDisplay'

const route = useRoute()
const router = useRouter()
const props = defineProps({
  embedded: { type: Boolean, default: false },
  hideControls: { type: Boolean, default: false },
  learnerId: { type: String, default: '' },
  activeRunId: { type: String, default: '' },
  sourceResources: { type: Array, default: () => [] },
})
const emit = defineEmits(['open-text-workspace', 'created', 'published'])
const terminalStates = new Set(['published', 'published_with_warnings', 'quarantined', 'failed', 'rejected_admission', 'release_blocked', 'cancelled', 'timed_out'])
const WORKSPACE_KIND_STORAGE_KEY = 'generation_workspace_kind'
const ACTIVE_RUN_STORAGE_KEY = 'courseware_active_run_id'
const stages = [
  { id: 'queued', label: '准备任务' }, { id: 'admitting', label: '校验来源' }, { id: 'snapshotting', label: '冻结来源' },
  { id: 'design_reviewing', label: '规划课程' }, { id: 'composing', label: '生成页面' }, { id: 'trace_reviewing', label: '审核来源' },
  { id: 'quality_reviewing', label: '质量审核' }, { id: 'auto_revising', label: '定向修订' }, { id: 'rendering', label: '渲染课件' },
  { id: 'validating', label: '发布校验' }, { id: 'publishing', label: '自动发布' }, { id: 'published', label: '课件已就绪' },
]
const profiles = ref([]); const tracks = ref([]); const sourceResources = ref([]); const jobs = ref([])
const selectedLearnerId = ref(props.learnerId || route.query.learnerId || localStorage.getItem('last_learner_id') || '')
const selectedRunId = ref(props.activeRunId || route.query.runId || '')
const currentJob = ref(null); const selectedSourceIds = ref([])
const sourceDialogVisible = ref(false); const busy = ref(false); const connectionStatus = ref('idle')
const preferences = ref({ learning_goal: '', expected_duration_minutes: 30, interaction_intensity: 'medium' })
let stream = null; let pollTimer = null
let publishedRunId = ''
const sourceCandidates = computed(() => coursewareEligibleSources(sourceResources.value))
const visibleRequestOptions = computed(() => Object.fromEntries(
  Object.entries(currentJob.value?.request_options || {}).filter(([key]) => key !== 'visual_style_id'),
))
const canCreate = computed(() => Boolean(selectedLearnerId.value) && sourceCandidates.value.length > 0)
const published = computed(() => ['published', 'published_with_warnings'].includes(currentJob.value?.status))
const retryable = computed(() => ['failed', 'rejected_admission', 'release_blocked', 'timed_out'].includes(currentJob.value?.status))
const shortRunId = computed(() => currentJob.value?.run_id?.slice(0, 8).toUpperCase() || '-')
const activeStage = computed(() => { if (published.value) return stages.length; const position = stages.findIndex((stage) => stage.id === currentJob.value?.status); return position < 0 ? 0 : position + 1 })
const connectionLabel = computed(() => ({ live: '实时同步', polling: '轮询恢复', terminal: '已完成', idle: '等待连接', error: '连接已断开' }[connectionStatus.value] || '任务记录'))

function profileLabel(profile) { return `${trackName(profile.knowledge_base_id)} / ${profile.skill_level || '未分级'}` }
function trackName(id) { return tracks.value.find((track) => track.track_id === id)?.name || id || '未命名方向' }
function jobLabel(job) { return `${stateLabel(job.status)} / ${String(job.run_id).slice(0, 8).toUpperCase()} / ${formatDateTime(job.updated_at || job.created_at)}` }
function stateLabel(status) { return ({ queued: '排队中', admitting: '校验来源', snapshotting: '冻结来源', design_reviewing: '课程设计', composing: '生成页面', trace_reviewing: '来源审核', quality_reviewing: '质量审核', auto_revising: '定向修订', rendering: '渲染课件', validating: '发布校验', publishing: '自动发布', approved_pending_publish: '等待发布', published: '已发布', published_with_warnings: '已发布（有警告）', failed: '失败', rejected_admission: '来源未通过', release_blocked: '发布受阻', quarantined: '已隔离', cancelled: '已取消', timed_out: '已超时' }[status] || status || '等待中') }
function optionLabel(key) { return ({ learning_goal: '学习目标', expected_duration_minutes: '预计时长', interaction_intensity: '互动强度' }[key] || key) }
function qualityPercent(value) { return typeof value === 'number' ? `${Math.round(value * 100)}%` : '未测量' }
function stageDescription(stage) { if (stage.id === currentJob.value?.status) return '正在执行'; if (published.value && stage.id !== 'published') return '已完成'; return '' }
function snakeStepPosition(index) {
  const columns = 3
  const row = Math.floor(index / columns)
  const positionInRow = index % columns
  return { gridRow: row + 1, gridColumn: row % 2 === 0 ? positionInRow + 1 : columns - positionInRow }
}
function retryableScene(scene) { return ['failed', 'retry_queued', 'revision_required'].includes(scene.status) }
function stopTracking() { stream?.close(); stream = null; if (pollTimer) { window.clearInterval(pollTimer); pollTimer = null } }
function activeRunStorageKey(learnerId = selectedLearnerId.value) {
  return learnerId ? `${ACTIVE_RUN_STORAGE_KEY}:${learnerId}` : ACTIVE_RUN_STORAGE_KEY
}
function rememberedRunId() {
  return route.query.runId || localStorage.getItem(activeRunStorageKey()) || localStorage.getItem(ACTIVE_RUN_STORAGE_KEY) || ''
}
function syncRoute(runId = selectedRunId.value) {
  if (runId) {
    localStorage.setItem(activeRunStorageKey(), runId)
    // Keep the legacy key while older open pages still write/read it.
    localStorage.setItem(ACTIVE_RUN_STORAGE_KEY, runId)
  }
  if (props.embedded) return
  localStorage.setItem(WORKSPACE_KIND_STORAGE_KEY, 'courseware')
  router.replace({ query: { ...route.query, kind: 'courseware', learnerId: selectedLearnerId.value || undefined, runId: runId || undefined } })
}
function selectDefaultSources() { selectedSourceIds.value = sourceCandidates.value.map((item) => item.resource_id).slice(0, 8) }
function openCreateDialog() { selectDefaultSources(); sourceDialogVisible.value = true }

async function loadProfiles() { if (props.embedded) return; const [profileRes, domainRes] = await Promise.all([profileApi.list({ page: 1, page_size: 50 }), knowledgeApi.listDomains()]); profiles.value = profileRes.data.items || profileRes.data.profiles || []; tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || []); if (!profiles.value.some((item) => item.learner_id === selectedLearnerId.value)) selectedLearnerId.value = profiles.value[0]?.learner_id || '' }
async function loadSourceResources() { if (props.embedded) { sourceResources.value = props.sourceResources.map((item) => ({ ...item, resource_id: item.resource_id || item.id })); selectDefaultSources(); return } if (!selectedLearnerId.value) { sourceResources.value = []; return } const response = await resourceLibraryApi.listByLearner(selectedLearnerId.value); sourceResources.value = (response.data || []).filter((item) => item.resource_kind !== 'interactive_courseware').map((item) => ({ ...item, resource_id: item.resource_id || item.id })); selectDefaultSources() }
async function loadJobs() {
  if (!selectedLearnerId.value) { jobs.value = []; currentJob.value = null; return }
  const restoredRunId = rememberedRunId()
  try {
    const response = await coursewareApi.listJobs(selectedLearnerId.value)
    jobs.value = response.data.items || []
  } catch (error) {
    // A rolling local deployment can temporarily run an API process from
    // before the list endpoint was added. The task itself still has a stable
    // detail endpoint, so never make an already-created task disappear.
    jobs.value = []
    if (!restoredRunId) {
      ElMessage.error(error?.response?.data?.detail || '课件任务列表加载失败')
      currentJob.value = null
      return
    }
    try {
      const response = await coursewareApi.getJobDetail(restoredRunId)
      jobs.value = [response.data]
    } catch (restoreError) {
      ElMessage.error(restoreError?.response?.data?.detail || '无法恢复已创建的课件任务')
      currentJob.value = null
      return
    }
  }
  if (!jobs.value.some((job) => job.run_id === selectedRunId.value)) {
    selectedRunId.value = jobs.value.some((job) => job.run_id === restoredRunId) ? restoredRunId : jobs.value[0]?.run_id || ''
  }
  await loadCurrentJob()
}
async function loadCurrentJob() { stopTracking(); if (!selectedRunId.value) { currentJob.value = null; connectionStatus.value = 'idle'; return } try { const response = await coursewareApi.getJobDetail(selectedRunId.value); currentJob.value = response.data; const position = jobs.value.findIndex((job) => job.run_id === selectedRunId.value); if (position >= 0) jobs.value.splice(position, 1, { ...jobs.value[position], ...response.data }); syncRoute(); if (terminalStates.has(currentJob.value.status)) { connectionStatus.value = 'terminal'; return } startTracking(selectedRunId.value) } catch (error) { connectionStatus.value = 'error'; ElMessage.error(error?.response?.data?.detail || '课件任务加载失败') } }
function startTracking(runId) { if (!runId || typeof EventSource === 'undefined') { startPolling(); return } connectionStatus.value = 'live'; stream = new EventSource(coursewareApi.eventsUrl(runId)); stream.addEventListener('courseware_progress', () => { void refreshCurrentJob() }); stream.onerror = () => { stream?.close(); stream = null; startPolling() } }
function startPolling() { if (pollTimer || terminalStates.has(currentJob.value?.status)) return; connectionStatus.value = 'polling'; pollTimer = window.setInterval(() => void refreshCurrentJob(), 2500) }
function notifyPublished() { if (!published.value || !currentJob.value?.resource_id || publishedRunId === currentJob.value.run_id) return; publishedRunId = currentJob.value.run_id; emit('published', currentJob.value) }
async function refreshCurrentJob() { if (!selectedRunId.value) return; try { const response = await coursewareApi.getJobDetail(selectedRunId.value); currentJob.value = response.data; const position = jobs.value.findIndex((job) => job.run_id === selectedRunId.value); if (position >= 0) jobs.value.splice(position, 1, { ...jobs.value[position], ...response.data }); if (terminalStates.has(currentJob.value.status)) { stopTracking(); connectionStatus.value = 'terminal'; notifyPublished() } } catch (_) { startPolling() } }
async function createCourseware() { if (!selectedSourceIds.value.length) return; busy.value = true; try { const response = await coursewareApi.createJobs(buildCoursewareBatchRequest({ learnerId: selectedLearnerId.value, resourceIds: selectedSourceIds.value, preferences: preferences.value })); const created = response.data.jobs || []; const job = created[0]; sourceDialogVisible.value = false; if (!job) throw new Error('未创建课件任务'); selectedRunId.value = job.run_id; jobs.value = [...created, ...jobs.value.filter((item) => !created.some((createdJob) => createdJob.run_id === item.run_id))]; localStorage.setItem('courseware_active_run_id', job.run_id); syncRoute(job.run_id); await loadCurrentJob(); emit('created', { jobs: created, activeJob: currentJob.value }); ElMessage.success(`已为 ${created.length} 份资源追加互动课件任务。`) } catch (error) { ElMessage.error(error?.response?.data?.detail || error?.response?.data?.message || '互动课件创建失败') } finally { busy.value = false } }
async function retryJob() { busy.value = true; try { await coursewareApi.retryJob(selectedRunId.value); await refreshCurrentJob(); ElMessage.success('已提交课件重试') } catch (error) { ElMessage.error(error?.response?.data?.detail || '课件重试失败') } finally { busy.value = false } }
async function retryScene(sceneId) { busy.value = true; try { await coursewareApi.retryScene(selectedRunId.value, sceneId); await refreshCurrentJob(); ElMessage.success('已提交页面级重试') } catch (error) { ElMessage.error(error?.response?.data?.detail || '页面重试失败') } finally { busy.value = false } }
function openPublishedResource() { if (!currentJob.value?.resource_id) return; if (props.embedded) { emit('published', currentJob.value); return } router.push({ path: '/resources', query: { learnerId: selectedLearnerId.value, runId: currentJob.value.source_batch_id || '', resourceId: currentJob.value.resource_id } }) }
function openLearningResources() { router.push({ path: '/resources', query: { learnerId: selectedLearnerId.value || undefined } }) }
async function handleLearnerChange() { localStorage.setItem('last_learner_id', selectedLearnerId.value); selectedRunId.value = ''; await Promise.all([loadSourceResources(), loadJobs()]) }
async function handleRunChange() { await loadCurrentJob() }
watch(() => props.learnerId, async (learnerId) => { if (!props.embedded || learnerId === selectedLearnerId.value) return; stopTracking(); selectedLearnerId.value = learnerId || ''; selectedRunId.value = ''; await Promise.all([loadSourceResources(), loadJobs()]) })
watch(() => props.activeRunId, async (runId) => { if (!props.embedded || !runId || runId === selectedRunId.value) return; stopTracking(); selectedRunId.value = runId; await loadCurrentJob() })
watch(() => props.sourceResources, () => { if (props.embedded) void loadSourceResources() }, { deep: true })
onMounted(async () => { await loadProfiles(); await Promise.all([loadSourceResources(), loadJobs()]) })
onBeforeUnmount(stopTracking)
defineExpose({ openCreateDialog, refreshCurrentJob })
</script>

<style scoped>
.courseware-generation-page{display:flex;flex-direction:column;gap:20px;color:#172033}.workspace-header,.workspace-controls,.courseware-job-summary,.process-panel,.details-panel,.empty-workspace{border:1px solid #d9e1ec;border-radius:12px;background:#fff;box-shadow:0 14px 32px rgba(35,62,94,.06)}.workspace-header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:24px}.workspace-header-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}.eyebrow{display:block;color:#2058a7;font-size:12px;font-weight:800;text-transform:uppercase}.workspace-header h3,.panel-title h3,.empty-workspace h3{margin:5px 0 0;font-size:22px}.workspace-header p,.empty-workspace p{margin:10px 0 0;color:#65758e;line-height:1.65}.workspace-controls{display:grid;grid-template-columns:minmax(260px,1fr) minmax(300px,1.2fr) auto;gap:14px;align-items:end;padding:16px 20px}.workspace-controls label,.preference-grid label{display:flex;min-width:0;flex-direction:column;gap:7px;color:#63728a;font-size:12px;font-weight:700}.workspace-controls :deep(.el-select){width:100%}.courseware-job-summary{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));overflow:hidden}.courseware-job-summary>div{min-height:62px;padding:11px 14px;border-right:1px solid #e4ebf3}.courseware-job-summary>div:last-child{border:0}.courseware-job-summary span{display:block;margin-bottom:5px;color:#71839a;font-size:12px}.courseware-job-summary strong{font-size:14px;overflow-wrap:anywhere}.state-published,.state-published_with_warnings{color:#198666}.state-failed,.state-rejected_admission,.state-release_blocked{color:#b5473f}.generation-grid{display:grid;grid-template-columns:minmax(340px,.8fr) minmax(460px,1.2fr);gap:20px;align-items:stretch;min-height:clamp(430px,calc(100vh - 260px),720px)}.process-panel,.details-panel{display:flex;min-width:0;min-height:0;flex-direction:column;padding:20px}.panel-title{display:flex;flex:none;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid #e4ebf3}.workflow-snake{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));grid-template-rows:repeat(3,minmax(58px,1fr));gap:12px 8px;margin:0;padding:0;list-style:none}.workflow-snake-step{position:relative;display:flex;min-width:0;align-items:center;gap:7px;padding:7px 5px;border:1px solid #e0e8f1;border-radius:10px;background:#fbfdff;color:#65758e}.workflow-snake-step:not(:nth-child(4n))::after{position:absolute;z-index:0;top:50%;width:9px;border-top:1px dashed #bed0e2;content:""}.workflow-snake-step:nth-child(-n+4)::after,.workflow-snake-step:nth-child(n+9)::after{left:100%}.workflow-snake-step:nth-child(n+5):nth-child(-n+8)::after{right:100%}.workflow-snake-node{position:relative;z-index:1;display:grid;width:23px;height:23px;flex:none;place-items:center;border:2px solid #aebdcb;border-radius:50%;background:#fff;color:#6a7b8f;font-size:11px;font-weight:800}.workflow-snake-copy{min-width:0}.workflow-snake-copy strong,.workflow-snake-copy small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.workflow-snake-copy strong{font-size:12px}.workflow-snake-copy small{margin-top:3px;font-size:11px}.workflow-snake-step.is-complete{border-color:#ccebc5;background:#f7fff5;color:#3d9e32}.workflow-snake-step.is-complete .workflow-snake-node{border-color:#63c953;color:#3d9e32}.workflow-snake-step.is-active{border-color:#84baf8;background:#f2f8ff;color:#1769c2;box-shadow:0 0 0 2px rgba(64,145,241,.12)}.workflow-snake-step.is-active .workflow-snake-node{border-color:#368be8;color:#1769c2}.process-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:auto;padding-top:18px}.details-scroll{min-height:0;flex:1;overflow-y:auto;padding-right:8px;scrollbar-gutter:stable}.details-scroll::-webkit-scrollbar{width:7px}.details-scroll::-webkit-scrollbar-thumb{border-radius:8px;background:#ccd8e5}.frozen-options,.quality-summary{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:16px;padding:13px;border:1px solid #dce7f3;border-radius:9px;background:#f8fbff;color:#52677f;font-size:13px}.frozen-options strong,.quality-summary strong{margin-right:4px;color:#203853}.scene-list{border-top:1px solid #e6edf4;padding-top:15px}.section-heading{display:flex;justify-content:space-between;color:#203853}.section-heading span{color:#71839a;font-size:12px}.scene-list ol{margin:12px 0 0;padding:0;list-style:none}.scene-list li{display:flex;justify-content:space-between;gap:15px;align-items:center;padding:12px 2px;border-bottom:1px solid #edf1f6}.scene-list strong,.scene-list small{display:block}.scene-list small{margin-top:4px;color:#71839a;font-size:12px}.warnings{margin:16px 0 0;padding:12px 14px 12px 30px;border:1px solid #f4d49b;border-radius:8px;background:#fff8ea;color:#9a6417}.error-message{margin:16px 0 0;padding:12px;border:1px solid #ffcec8;border-radius:8px;background:#fff3f1;color:#b5473f}.empty-workspace{padding:46px 30px;text-align:center}.source-hint{margin:0 0 16px;color:#65758e;line-height:1.65}.preference-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.preference-grid :deep(.el-select),.preference-grid :deep(.el-input-number){width:100%}.source-list{display:grid;gap:9px;margin-top:18px}.source-list :deep(.el-checkbox){height:auto;margin-right:0;padding:10px 12px;border:1px solid #dce6ef;border-radius:8px}.source-list :deep(.el-checkbox__label){display:grid;gap:4px;white-space:normal}.source-list span{color:#71839a;font-size:12px}@media(max-width:1000px){.generation-grid{grid-template-columns:1fr;min-height:0}.process-panel,.details-panel{min-height:0}.details-scroll{max-height:520px}.courseware-job-summary{grid-template-columns:repeat(3,1fr)}.courseware-job-summary>div:nth-child(3n){border-right:0}}@media(max-width:700px){.workspace-header,.workspace-controls{grid-template-columns:1fr;display:grid}.workspace-header{padding:18px}.courseware-job-summary{grid-template-columns:repeat(2,1fr)}.courseware-job-summary>div:nth-child(3n){border-right:1px solid #e4ebf3}.courseware-job-summary>div:nth-child(2n){border-right:0}.workflow-snake{grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:repeat(6,minmax(58px,1fr))}.workflow-snake-step{grid-column:auto!important;grid-row:auto!important}.workflow-snake-step::after{display:none}.preference-grid{grid-template-columns:1fr}}
.embedded-workspace-controls{display:grid;grid-template-columns:minmax(190px,.85fr) minmax(240px,1.15fr) auto;gap:14px;align-items:end;padding:16px 18px;border:1px solid #cfe0f2;border-radius:12px;background:linear-gradient(100deg,#f7fbff,#f3faf9);box-shadow:0 10px 26px rgba(35,62,94,.05)}.embedded-workspace-controls strong,.embedded-workspace-controls small{display:block}.embedded-workspace-controls strong{margin-top:4px;color:#173654;font-size:16px}.embedded-workspace-controls small{margin-top:4px;color:#6e8199;font-size:12px}.embedded-workspace-controls :deep(.el-select){width:100%}@media(max-width:700px){.embedded-workspace-controls{grid-template-columns:1fr;align-items:stretch}}
.courseware-generation-page{min-height:100%}.empty-workspace{display:flex;flex:1;min-height:280px;flex-direction:column;align-items:center;justify-content:center}
.generation-grid{height:clamp(430px,calc(100vh - 260px),720px)}
 .workflow-snake-step:nth-child(4)::before,.workflow-snake-step:nth-child(8)::before{position:absolute;z-index:0;top:100%;right:50%;height:12px;border-right:1px dashed #bed0e2;content:""}
@media(max-width:1000px){.generation-grid{height:auto}}
@media(max-width:700px){.workflow-snake-step::before{display:none}}
@media(min-width:701px){.workflow-snake{grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:repeat(4,minmax(58px,1fr));gap:16px 12px}.workflow-snake-step::before{display:none}.workflow-snake-step::after{display:none!important}.workflow-snake-step:nth-child(1)::after,.workflow-snake-step:nth-child(2)::after,.workflow-snake-step:nth-child(7)::after,.workflow-snake-step:nth-child(8)::after,.workflow-snake-step:nth-child(4)::after,.workflow-snake-step:nth-child(5)::after,.workflow-snake-step:nth-child(10)::after,.workflow-snake-step:nth-child(11)::after{position:absolute;z-index:3;top:50%;display:block!important;width:auto;border:0;background:#fff;color:#79a1c6;font-size:16px;font-weight:800;line-height:1;transform:translateY(-50%)}.workflow-snake-step:nth-child(1)::after,.workflow-snake-step:nth-child(2)::after,.workflow-snake-step:nth-child(7)::after,.workflow-snake-step:nth-child(8)::after{left:calc(100% + 3px);content:"→"}.workflow-snake-step:nth-child(4)::after,.workflow-snake-step:nth-child(5)::after,.workflow-snake-step:nth-child(10)::after,.workflow-snake-step:nth-child(11)::after{right:calc(100% + 3px);content:"←"}.workflow-snake-step:nth-child(3)::after,.workflow-snake-step:nth-child(6)::after,.workflow-snake-step:nth-child(9)::after{position:absolute;z-index:3;right:50%;bottom:calc(-1 * 16px);display:block!important;width:auto;border:0;background:#fff;color:#79a1c6;font-size:16px;font-weight:800;line-height:1;content:"↓";transform:translateX(50%)}}
@media(min-width:701px){.workflow-snake{grid-template-rows:repeat(4,66px);gap:12px 28px;align-content:start}.workflow-snake-step{padding:6px 8px;border-radius:9px}.workflow-snake-copy strong{font-size:13px}.workflow-snake-copy small{margin-top:2px}.workflow-snake-step:nth-child(1)::after,.workflow-snake-step:nth-child(2)::after,.workflow-snake-step:nth-child(7)::after,.workflow-snake-step:nth-child(8)::after{left:calc(100% + 6px)}.workflow-snake-step:nth-child(4)::after,.workflow-snake-step:nth-child(5)::after,.workflow-snake-step:nth-child(10)::after,.workflow-snake-step:nth-child(11)::after{right:calc(100% + 6px)}.workflow-snake-step:nth-child(3)::after,.workflow-snake-step:nth-child(6)::after,.workflow-snake-step:nth-child(9)::after{top:auto;right:auto;left:50%;bottom:-14px;transform:translateX(-50%)}}
@media(min-width:701px){.workflow-snake{grid-template-rows:repeat(4,56px);gap:22px 34px}.workflow-snake-step{height:56px;min-height:0;padding:5px 8px}.workflow-snake-step:nth-child(1)::after,.workflow-snake-step:nth-child(2)::after,.workflow-snake-step:nth-child(7)::after,.workflow-snake-step:nth-child(8)::after{left:calc(100% + 9px)}.workflow-snake-step:nth-child(4)::after,.workflow-snake-step:nth-child(5)::after,.workflow-snake-step:nth-child(10)::after,.workflow-snake-step:nth-child(11)::after{right:calc(100% + 9px)}.workflow-snake-step:nth-child(3)::after,.workflow-snake-step:nth-child(6)::after,.workflow-snake-step:nth-child(9)::after{bottom:-19px}}
@media(min-width:701px){.workflow-snake{grid-template-rows:repeat(4,52px);gap:30px 34px}.workflow-snake-step{width:calc(100% - 32px);height:52px;justify-self:center;padding:4px 8px}.workflow-snake-step::after{display:none!important;content:none}.workflow-snake-step:nth-child(1)::after,.workflow-snake-step:nth-child(2)::after,.workflow-snake-step:nth-child(7)::after,.workflow-snake-step:nth-child(8)::after,.workflow-snake-step:nth-child(4)::after,.workflow-snake-step:nth-child(5)::after,.workflow-snake-step:nth-child(10)::after,.workflow-snake-step:nth-child(11)::after{position:absolute;z-index:0;top:50%;display:block!important;width:66px;height:0;border:0;border-top:1px solid #a9c4df;background:transparent;content:"";transform:translateY(-50%)}.workflow-snake-step:nth-child(1)::after,.workflow-snake-step:nth-child(2)::after,.workflow-snake-step:nth-child(7)::after,.workflow-snake-step:nth-child(8)::after{left:100%}.workflow-snake-step:nth-child(4)::after,.workflow-snake-step:nth-child(5)::after,.workflow-snake-step:nth-child(10)::after,.workflow-snake-step:nth-child(11)::after{right:100%}.workflow-snake-step:nth-child(3)::after,.workflow-snake-step:nth-child(6)::after,.workflow-snake-step:nth-child(9)::after{position:absolute;z-index:0;top:100%;right:auto;bottom:auto;left:50%;display:block!important;width:0;height:30px;border:0;border-left:1px solid #a9c4df;background:transparent;content:"";transform:translateX(-50%)}}
</style>
