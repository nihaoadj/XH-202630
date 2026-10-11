<template>
  <div ref="productionPage" class="generate-page" :class="{ 'is-courseware-workspace': isCoursewareWorkspace, 'is-fit-layout': isFitLayout }">
    <section class="control-panel" aria-label="资源任务控制">
      <div class="task-selector">
        <div class="selector-field">
          <label>学习画像 <span>PROFILE</span></label>
          <el-select v-model="selectedLearnerId" aria-label="学习画像" filterable placeholder="选择学习画像" class="task-select" popper-class="refined-select-dropdown profile-select-dropdown" @change="handleProfileChange">
            <el-option v-for="item in profileOptions" :key="item.learner_id" :label="item.label" :value="item.learner_id">
              <div class="profile-option"><span>{{ item.label }}</span><el-tooltip content="删除学习画像" placement="right"><el-button class="profile-delete" text circle :icon="Delete" aria-label="删除学习画像" @mousedown.stop @click.stop="deleteProfile(item)" /></el-tooltip></div>
            </el-option>
          </el-select>
        </div>
        <div class="selector-field">
          <label>资源批次 <span>BATCH</span></label>
          <el-select v-model="selectedRunId" aria-label="资源批次" filterable :disabled="!taskItems.length" :placeholder="taskItems.length ? '选择要查看的生成任务' : '暂无资源批次'" class="task-select" popper-class="refined-select-dropdown" @change="handleTaskChange">
            <el-option v-for="task in taskItems" :key="task.run_id" :label="taskLabel(task)" :value="task.run_id" />
          </el-select>
        </div>
      </div>

      <div class="job-summary">
        <div class="summary-item"><span>学习方向 <small>DIRECTION</small></span><strong class="summary-direction">{{ learningDirectionName || '尚未选择' }}</strong></div>
        <div class="summary-item"><span>任务编号 <small>RUN ID</small></span><strong class="summary-code">{{ shortRunId }}</strong></div>
        <div class="summary-item"><span>任务状态 <small>STATUS</small></span><strong class="production-status" :class="`is-${productionTone}`" role="status" aria-live="polite" aria-atomic="true"><el-icon aria-hidden="true"><component :is="productionIcon" /></el-icon>{{ selectedTask ? taskStatusLabel(selectedTask) : (loadingJobs ? '正在加载任务' : '尚未生成') }}</strong></div>
        <div class="summary-item"><span>可读资源 <small>OUTPUT</small></span><strong class="summary-count">{{ taskResourceCount }} <em>份</em></strong></div>
        <div class="summary-item"><span>创建时间 <small>CREATED</small></span><strong>{{ selectedTask ? formatDateTime(selectedTask.created_at) : '—' }}</strong></div>
        <div class="summary-item"><span>完成时间 <small>FINISHED</small></span><strong>{{ selectedTask?.finished_at ? formatDateTime(selectedTask.finished_at) : (selectedTask ? '等待完成' : '—') }}</strong></div>
      </div>
      <p v-if="selectedTask?.error_message" class="error-message"><el-icon><WarningFilled /></el-icon>{{ selectedTask.error_message }}</p>
      <p v-if="jobsError" class="error-message" role="alert">{{ jobsError }}<el-button @click="refreshJobs">重新加载</el-button></p>

    </section>

    <CoursewareGenerationWorkspace v-if="coursewareComposerVisible || selectedCoursewareJob" ref="coursewareWorkspace" embedded hide-controls :learner-id="selectedLearnerId" :active-run-id="selectedCoursewareJob?.run_id || ''" :source-resources="resources" @created="handleCoursewareCreated" @published="handleCoursewarePublished">
      <template #task-actions>
        <div v-if="selectedCoursewareJob" class="task-actions" role="group" aria-label="课件任务操作">
          <el-button class="status-action status-action-refresh" :icon="Refresh" @click="coursewareWorkspace?.refreshCurrentJob()">刷新状态</el-button>
          <el-dropdown trigger="click" @command="handleAppendCommand">
            <el-button class="status-action status-action-append" :icon="Plus" :loading="appendingResources">追加资源<el-icon><ArrowDown /></el-icon></el-button>
            <template #dropdown><el-dropdown-menu><el-dropdown-item command="text" :disabled="!selectedJob">文本学习资源</el-dropdown-item><el-dropdown-item command="courseware" :disabled="!resources.length">HTML 互动课件</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
        </div>
      </template>
    </CoursewareGenerationWorkspace>

    <section v-if="selectedJob" class="studio-grid">
      <div class="process-panel">
        <div class="panel-title compact"><div><span class="eyebrow">01 / WORKFLOW</span><h3>生成协作轨迹</h3></div><span class="connection-state" :class="`is-${connectionStatus}`"><i aria-hidden="true" />{{ productionConnectionLabel }}</span></div>
        <div ref="processScroll" class="process-scroll" role="region" aria-label="生成协作轨迹" tabindex="0">
          <AgentVisualization v-if="selectedRunId" :trace="timelineState.steps" :markers="timelineState.markers" :connection-status="connectionStatus" :legacy-partial="timelineState.replayCompleteness === 'legacy_partial'" :resource-executions="timelineState.resourceExecutions" :resource-progress-summary="selectedJob?.resource_progress_summary || timelineState.resourceProgressSummary" :retrying-resource-key="retryingResourceKey" :retry-enabled="['completed', 'failed'].includes(selectedJob.job_status)" :claim-reports="claimReports" @open-child-run="openChildRun" @open-resource="openGeneratedResource" @retry-resource="retryResource" @open-claim-report="openClaimReport" />
        </div>
      </div>
      <div class="resources-panel" v-module-motion="{ key: selectedRunId + ':' + selectedResourceId, ready: !loadingResources }">
        <div class="panel-title compact resource-panel-heading">
          <div><span class="eyebrow">02 / OUTPUT</span><h3>{{ selectedJob.job_status === 'completed' ? '任务资源' : '资源预览' }}</h3></div>
          <div class="resource-panel-tools">
            <span class="output-count">{{ resources.length }} <small>份资源</small></span>
            <div class="task-actions" role="group" aria-label="资源任务操作">
              <el-button v-if="selectedJob.job_status === 'running' || selectedJob.job_status === 'queued'" class="status-action status-action-refresh" :icon="Refresh" @click="refreshStatus">刷新状态</el-button>
              <el-button v-if="selectedJob.job_status === 'failed'" class="status-action status-action-retry" :icon="RefreshRight" @click="retryGeneration" :loading="retrying">重新生成</el-button>
              <el-button v-if="selectedJob.job_status === 'completed'" class="status-action status-action-resource" :class="{ 'is-retry': hasRetryableResources }" :icon="hasRetryableResources ? RefreshRight : Refresh" @click="hasRetryableResources ? regeneratePendingResources() : loadResourcesForSelectedJob()" :loading="hasRetryableResources ? retrying : loadingResources">{{ hasRetryableResources ? `重新生成失败资源（${retryableResourceTypes.length}）` : '刷新资源' }}</el-button>
              <el-dropdown trigger="click" @command="handleAppendCommand">
                <el-button class="status-action status-action-append" :icon="Plus" :loading="appendingResources">追加资源<el-icon><ArrowDown /></el-icon></el-button>
                <template #dropdown><el-dropdown-menu><el-dropdown-item command="text" :disabled="!selectedJob">文本学习资源</el-dropdown-item><el-dropdown-item command="courseware" :disabled="!resources.length">HTML 互动课件</el-dropdown-item></el-dropdown-menu></template>
              </el-dropdown>
            </div>
          </div>
        </div>
        <div v-if="resources.length" class="resource-toolbar">
          <el-select v-model="selectedResourceId" aria-label="选择要阅读的资源" filterable placeholder="选择要阅读的资源" class="resource-select" popper-class="refined-select-dropdown"><el-option v-for="item in resources" :key="item.resource_id" :label="resourceLabel(item)" :value="item.resource_id" /></el-select>
          <div class="reader-toolbar-actions">
            <div id="generation-reader-actions" class="reader-resource-actions" role="group" aria-label="资源文件操作" />
            <el-button class="learning-mode-action" :icon="Reading" @click="enterLearningMode">学习模式<el-icon class="mode-arrow"><ArrowRight /></el-icon></el-button>
          </div>
        </div>
        <div ref="resourceScroll" v-loading="loadingResources" class="resource-stage" role="region" aria-label="学习资源预览" :aria-busy="loadingResources" tabindex="0">
          <PreparationPanel
            v-if="!resources.length"
            class="resource-placeholder"
            :class="{ 'is-failed': selectedJob.job_status === 'failed' }"
            compact
            eyebrow="RESOURCE OUTPUT"
            :pending="['queued', 'running'].includes(selectedJob.job_status)"
            :title="selectedJob.job_status === 'failed' ? '本次生成暂未完成' : (selectedJob.job_status === 'completed' ? '等待资源同步' : '你的学习资源正在准备中')"
            :description="selectedJob.job_status === 'failed' ? '查看左侧协作记录了解原因，重新生成后可继续阅读。' : (selectedJob.job_status === 'completed' ? '任务已完成，暂未查到已发布内容。可以使用上方刷新资源查看最新结果。' : '跟随左侧真实轨迹查看进展，审核发布后的材料会在这里展开。')"
            :steps="[
              { title: '生成学习材料', description: '根据学习画像与本轮目标组织内容。' },
              { title: '校验与发布', description: '通过相应审核与校验的资源才进入阅读区。' },
              { title: '阅读与专注学习', description: '材料就绪后，在上方切换资源或进入学习模式。' },
            ]"
          >
            <template #context><div class="output-preparation-context"><span>当前任务</span><strong>{{ taskStatusLabel(selectedJob) }}</strong><span>以实际发布结果为准</span></div></template>
          </PreparationPanel>
          <ResourceViewer v-if="selectedResource" :resources="[selectedResource]">
            <template #header="{ resource, download, difficulty }">
              <Teleport to="#generation-reader-actions">
                <el-tag class="resource-difficulty" effect="plain" :type="difficulty">{{ resource.difficulty || '待分级' }}</el-tag>
                <el-button v-if="resource.file_path" class="download-button toolbar-download-action" :icon="Download" @click="download(resource.resource_id)">下载材料</el-button>
              </Teleport>
            </template>
          </ResourceViewer>
        </div>
      </div>
    </section>

    <section v-else-if="!selectedCoursewareJob && !coursewareComposerVisible" class="empty-studio">
      <PreparationWorkspace
        compact
        variant="production"
        :pending="loadingJobs"
        eyebrow="YOUR RESOURCE STUDIO"
        :title="loadingJobs ? '正在获取你的资源任务' : '把学习目标，转化为专属内容。'"
        description="从学习画像出发，由多智能体协作生成、校验与发布，让知识成为可使用的学习材料。"
        :flow-labels="['方向画像', '协作生成', '审核发布']"
        flow-caption="资源生产流程示意"
        capabilities-title="从目标出发，沿着清晰的路径生成资源"
        capabilities-english="PROFILE · GENERATE · VALIDATE"
        :capabilities="[
          { icon: Aim, eyebrow: '01 / PROFILE', title: '确定方向与起点', description: '选择学习目标，完成问卷与诊断，建立专属学习画像。', detail: '学习方向 · 画像诊断' },
          { icon: Connection, eyebrow: '02 / GENERATE', title: '组织本轮资源', description: '选定资源类型，跟随协作轨迹查看生成与审核结果。', detail: '多智能体 · 校验发布' },
          { icon: Reading, eyebrow: '03 / LEARN', title: '进入专注学习', description: '已发布的材料可在这里预览，也会归档至学习资源页。', detail: '资源预览 · 专注学习' },
        ]"
        footer-title="有目标的生成，有依据的学习。"
        footer-description="已有学习方向？可在上方切换画像与资源批次。"
      >
        <template #actions><el-button class="primary-action preparation-primary-action" :icon="Plus" @click="$router.push('/learning/new')">新建学习方向<el-icon><ArrowRight /></el-icon></el-button></template>
      </PreparationWorkspace>
    </section>
    <footer class="production-footer"><span>有据可循的内容，有迹可查的学习。</span><span>智域匠学 <i>/</i> KNOWLEDGE → SKILL</span></footer>

    <el-dialog
      v-model="appendDialogVisible"
      class="production-dialog"
      title="追加学习资源"
      width="min(520px, calc(100vw - 32px))"
      :close-on-click-modal="false"
    >
      <p class="append-resource-hint">请选择要加入当前资源批次的资源类型。</p>
      <el-checkbox-group v-model="selectedAppendResourceTypes" class="append-resource-options">
        <el-checkbox
          v-for="option in appendResourceOptions"
          :key="option.type"
          :label="option.type"
          :disabled="option.alreadyIncluded"
        >
          {{ option.type }}<span v-if="option.alreadyIncluded" class="append-resource-existing">（本批次已有）</span>
        </el-checkbox>
      </el-checkbox-group>
      <div class="append-claim-option">
        <el-checkbox v-model="appendIncludeClaimCheck" :disabled="!appendReviewEnabled">
          启用 Claim 审核
        </el-checkbox>
        <p>
          默认开启。对生成内容中的可验证事实进行证据核验与定向纠错。
          <template v-if="!appendReviewEnabled">当前源任务未启用普通审核，不能单独开启 Claim 审核。</template>
        </p>
      </div>
      <template #footer>
        <el-button @click="appendDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="appendingResources" @click="confirmAppendResources">开始追加</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="claimReportVisible" class="production-dialog claim-report-dialog" width="min(760px, calc(100vw - 32px))">
      <template #header>
        <div class="claim-report-header">
          <div class="claim-report-heading">
            <span class="claim-report-icon" aria-hidden="true"><DocumentChecked /></span>
            <div>
              <span class="claim-report-eyebrow">CLAIM QUALITY CHECK</span>
              <h3>资源 Claim 审核报告</h3>
              <p>核对生成内容中的事实陈述，确保每一条都能被知识来源支持。</p>
            </div>
          </div>
          <div
            v-if="selectedClaimReport"
            class="claim-report-status"
            :class="claimReportStatusClass(selectedClaimReport.metric_status)"
          >
            <CircleCheck v-if="selectedClaimReport.metric_status === 'complete'" />
            <WarningFilled v-else />
            <span>{{ claimReportStatusLabel(selectedClaimReport.metric_status) }}</span>
          </div>
        </div>
      </template>
      <template v-if="selectedClaimReport">
        <section class="claim-report-overview" aria-label="审核概览">
          <div class="claim-rate-panel" :style="claimRateStyle(selectedClaimReport)">
            <div class="claim-rate-ring" aria-hidden="true">
              <div class="claim-rate-ring-inner">
                <strong>{{ claimPassRateLabel(selectedClaimReport) }}</strong>
                <span>事实通过率</span>
              </div>
            </div>
            <div class="claim-rate-copy">
              <span class="claim-report-eyebrow">AUDIT SUMMARY</span>
              <strong>{{ claimIssueCount(selectedClaimReport) ? '发现需要关注的事实' : '事实核验全部通过' }}</strong>
              <p>
                共检查 {{ selectedClaimReport.factual_claim_total || 0 }} 条事实 Claim，
                {{ selectedClaimReport.supported_claim_total || 0 }} 条获得证据支持。
              </p>
            </div>
          </div>

          <div class="claim-metrics-grid">
            <article class="claim-metric is-total">
              <span class="claim-metric-icon"><DocumentChecked /></span>
              <div><small>事实 Claim</small><strong>{{ selectedClaimReport.factual_claim_total || 0 }}</strong></div>
            </article>
            <article class="claim-metric is-supported">
              <span class="claim-metric-icon"><CircleCheck /></span>
              <div><small>已支持</small><strong>{{ selectedClaimReport.supported_claim_total || 0 }}</strong></div>
            </article>
            <article class="claim-metric is-unverified">
              <span class="claim-metric-icon"><WarningFilled /></span>
              <div><small>无证据</small><strong>{{ selectedClaimReport.not_in_evidence_claim_total || 0 }}</strong></div>
            </article>
            <article class="claim-metric is-conflict">
              <span class="claim-metric-icon"><WarningFilled /></span>
              <div><small>矛盾</small><strong>{{ selectedClaimReport.contradicted_claim_total || 0 }}</strong></div>
            </article>
          </div>
        </section>

        <el-alert v-if="selectedClaimReport.claim_warning_publish" title="该资源达到发布阈值，已带 Claim 警告发布。" type="warning" :closable="false" show-icon class="claim-report-alert" />
        <el-alert v-if="selectedClaimReport.claim_publish_decision_pending" title="该资源满足用户审核阈值，请查看报告后决定是否发布。" type="warning" :closable="false" show-icon class="claim-report-alert" />
        <section class="claim-issues-section" aria-label="事实问题">
          <div class="claim-section-heading">
            <div>
              <span class="claim-report-eyebrow">REVIEW NOTES</span>
              <h4>需要关注的事实</h4>
            </div>
            <span class="claim-issue-count">{{ claimIssueCount(selectedClaimReport) }} 条</span>
          </div>

          <div v-if="!claimIssueCount(selectedClaimReport)" class="claim-report-empty">
            <span class="claim-empty-icon" aria-hidden="true"><CircleCheck /></span>
            <div><strong>事实核验通过</strong><p>没有需要提示的事实 Claim，当前内容可以继续使用。</p></div>
          </div>
          <div v-else class="claim-issue-list">
            <article v-for="(issue, index) in selectedClaimReport.issues" :key="issue.claim_id" class="claim-issue-card">
              <div class="claim-issue-marker">{{ String(index + 1).padStart(2, '0') }}</div>
              <div class="claim-issue-content">
                <div class="claim-issue-topline">
                  <el-tag :type="issue.verdict === 'contradicted' ? 'danger' : 'warning'" size="small" effect="plain">
                    {{ issue.verdict === 'contradicted' ? '证据矛盾' : '未获证据支持' }}
                  </el-tag>
                  <span>事实 Claim</span>
                </div>
                <p>{{ issue.claim_text }}</p>
                <small>{{ issue.reason || '未提供审核原因' }}</small>
              </div>
            </article>
          </div>
        </section>

        <div v-if="selectedClaimReport.claim_publish_decision_pending" class="claim-report-actions">
          <div><strong>准备好决定资源去向了吗？</strong><span>你可以发布当前版本，或先保留资源继续处理。</span></div>
          <div class="claim-report-action-buttons">
            <el-button :loading="claimDecisionLoading" @click="decideClaimPublication(false)">暂不发布</el-button>
            <el-button type="primary" :loading="claimDecisionLoading" @click="decideClaimPublication(true)">确认发布</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Aim, ArrowDown, Download, ArrowRight, CircleCheck, Clock, Delete, DocumentChecked, Plus, Reading, Refresh, RefreshRight, WarningFilled } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { generateApi, knowledgeApi, profileApi, resourceApi } from '../../api'
import { coursewareApi } from '../courseware/api'
import { resourceLibraryApi } from '../resource-library/api'
import { useGenerationProgress } from './useGenerationProgress.js'
import { useGenerationClaims } from './useGenerationClaims.js'
import { useProductionLayout } from './useProductionLayout.js'
import ResourceViewer from '../learning-documents/ResourceViewer.vue'
import PreparationPanel from '../../components/PreparationPanel.vue'
import PreparationWorkspace from '../../components/PreparationWorkspace.vue'
import CoursewareGenerationWorkspace from '../courseware/CoursewareGenerationWorkspace.vue'
import AgentVisualization from './AgentVisualization.vue'
import { useAppStore } from '../../stores/app'
import {
  formatDateTime,
  formatSupplementalRequirements,
  formatTaskLabel,
} from '../../utils/generationDisplay'
import {
  applyRunSnapshot,
  createInitialTimelineState,
  hydrateWorkflowTimeline,
  reduceWorkflowEvent,
} from '../../utils/workflowEventReducer'

const store = useAppStore()
const router = useRouter()
const route = useRoute()
const learningDirectionName = computed(
  () => store.currentLearningDirectionName || localStorage.getItem('learning_direction_name') || ''
)

const currentDisplayName = computed(
  () =>
    store.currentUserProfile?.display_name ||
    store.currentProfile?.learning_preferences?.metadata?.user_profile_snapshot?.display_name ||
    '当前用户'
)

const selectedLearnerId = ref(
  new URLSearchParams(window.location.search).get('learnerId') ||
  localStorage.getItem('last_learner_id') ||
  store.currentLearnerId ||
  ''
)
const initialRunId =
  new URLSearchParams(window.location.search).get('runId') ||
  localStorage.getItem('current_generation_run_id') ||
  ''


const jobs = ref([])
const loadingJobs = ref(false)
const jobsError = ref('')
let jobsRequestVersion = 0
let resourcesRequestVersion = 0
let nodeTiersRequestVersion = 0
let claimsRequestVersion = 0
let profileChangeVersion = 0
let taskChangeVersion = 0
let generationMounted = true
const loadingResources = ref(false)
const resourcesLoaded = ref(false)
const resources = ref([])
const nodeTiers = ref({})
const retrying = ref(false)
const retryingResourceKey = ref('')
const appendingResources = ref(false)
const appendDialogVisible = ref(false)
const selectedAppendResourceTypes = ref([])
const appendIncludeClaimCheck = ref(true)
const coursewareComposerVisible = ref(false)
const coursewareWorkspace = ref(null)
const selectedRunId = ref(initialRunId)
const selectedResourceId = ref('')
const profiles = ref([])
const tracks = ref([])
const coursewareJobs = ref([])
const timelineState = ref(createInitialTimelineState())
const connectionStatus = ref('idle')
const claimReports = ref({})
const claimReportVisible = ref(false)
const claimDecisionLoading = ref(false)
const selectedClaimReportId = ref('')




const activeProfile = computed(
  () => profiles.value.find((item) => item.learner_id === selectedLearnerId.value) || null
)
const profileOptions = computed(() =>
  profiles.value.map((profile) => ({
    ...profile,
    label: `${profileDisplayName(profile)} / ${resolveTrackName(profile.knowledge_base_id)} / ${profile.skill_level || '未分级'} / 创建于 ${profileCreatedAt(profile)}`,
  }))
)
const taskItems = computed(() => [
  ...jobs.value.map((job) => ({ ...job, task_kind: 'learning_documents' })),
  ...coursewareJobs.value.map((job) => ({
    ...job,
    task_kind: 'interactive_courseware',
    job_status: job.status,
    finished_at: ['published', 'published_with_warnings'].includes(job.status) ? job.updated_at : null,
  })),
].sort((left, right) => String(right.updated_at || right.created_at || '').localeCompare(String(left.updated_at || left.created_at || ''))))
const selectedTask = computed(
  () => taskItems.value.find((item) => item.run_id === selectedRunId.value) || null
)
const selectedJob = computed(
  () => jobs.value.find((item) => item.run_id === selectedRunId.value) || null
)
const selectedCoursewareJob = computed(
  () => coursewareJobs.value.find((item) => item.run_id === selectedRunId.value) || null
)
const isCoursewareWorkspace = computed(() => coursewareComposerVisible.value || Boolean(selectedCoursewareJob.value))
const shortRunId = computed(() => (selectedTask.value?.run_id ? selectedTask.value.run_id.slice(0, 8).toUpperCase() : '-'))
const taskResourceCount = computed(() => selectedCoursewareJob.value ? (selectedCoursewareJob.value.resource_id ? 1 : 0) : resources.value.length)
const selectedResource = computed(
  () => resources.value.find((item) => item.resource_id === selectedResourceId.value) || null
)
const selectedClaimReport = computed(() => claimReports.value[selectedClaimReportId.value] || null)
const retryableResourceTypes = computed(() => {
  const retryableStates = new Set(['failed', 'human_review', 'revision_requested'])
  const types = (timelineState.value.resourceExecutions || [])
    .filter((item) => retryableStates.has(item.resource_execution_state))
    .map((item) => item.resource_type)
    .filter(Boolean)
  return [...new Set(types)]
})
const hasRetryableResources = computed(() => (
  selectedJob.value?.job_status === 'completed' && retryableResourceTypes.value.length > 0
))
const supportedAppendResourceTypes = ['讲义', '实操指南', '分阶测试题', '复习清单', '案例分析']
const appendResourceOptions = computed(() => {
  const existingTypes = new Set(selectedJob.value?.request_payload?.resource_types || [])
  return supportedAppendResourceTypes.map((type) => ({
    type,
    alreadyIncluded: existingTypes.has(type),
  }))
})
const appendReviewEnabled = computed(() => selectedJob.value?.request_payload?.include_review !== false)

// Presentation only: task copy and viewport containment never alter workflow state.
const productionPage = ref(null)
const processScroll = ref(null)
const resourceScroll = ref(null)
const isFitLayout = ref(false)
const productionTone = computed(() => {
  const status = selectedTask.value?.job_status
  if (['failed', 'rejected_admission', 'release_blocked', 'quarantined', 'timed_out'].includes(status)) return 'error'
  if (hasRetryableResources.value || ['published_with_warnings', 'cancelled'].includes(status)) return 'warning'
  return 'ready'
})
const productionIcon = computed(() => productionTone.value !== 'ready' ? WarningFilled : (
  ['completed', 'published'].includes(selectedTask.value?.job_status) ? CircleCheck : Clock
))
const productionConnectionLabel = computed(() => ({
  connecting: '正在连接', live: '节点级同步', fallback: '轮询降级',
  terminal: '已结束', error: '连接异常',
}[connectionStatus.value] || '等待中'))
useProductionLayout({
  productionPage, processScroll, resourceScroll, isFitLayout, coursewareComposerVisible,
  selectedJob, selectedRunId, selectedResourceId, selectedLearnerId, loadingJobs,
  loadingResources, selectedTask, resources, learningDirectionName,
})
// End presentation-only viewport containment.

function enterLearningMode() {
  if (!selectedJob.value || !selectedResource.value) return
  router.push({
    path: '/resources',
    query: {
      learnerId: selectedLearnerId.value,
      runId: selectedJob.value.batch_id || selectedJob.value.run_id,
    },
  })
}

function statusLabel(status) {
  return (
    {
      queued: '排队中',
      running: '生成中',
      completed: '已完成',
      failed: '失败',
    }[status] || '未开始'
  )
}

function statusTagType(status) {
  return (
    {
      queued: 'info',
      running: 'warning',
      completed: 'success',
      failed: 'danger',
    }[status] || 'info'
  )
}

function taskStatusLabel(task) {
  if (task?.task_kind !== 'interactive_courseware') return statusLabel(task?.job_status)
  return ({
    queued: '排队中', admitting: '校验来源', snapshotting: '冻结来源', design_reviewing: '规划课程', composing: '生成页面',
    trace_reviewing: '来源审核', quality_reviewing: '质量审核', auto_revising: '定向修订', rendering: '渲染课件',
    validating: '发布校验', publishing: '自动发布', published: '已发布', published_with_warnings: '已发布（有警告）',
    failed: '失败', rejected_admission: '来源未通过', release_blocked: '发布受阻', quarantined: '已隔离', cancelled: '已取消', timed_out: '已超时',
  }[task?.job_status] || '未开始')
}

function apiErrorMessage(error, fallback) {
  const data = error?.response?.data || {}
  const detail = data.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (typeof item === 'string' ? item : item?.msg))
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  }
  if (typeof data.message === 'string' && data.message.trim()) return data.message
  return fallback
}

function resolveTrackName(trackId) {
  return tracks.value.find((item) => item.track_id === trackId)?.name || trackId || '未命名方向'
}

function profileDisplayName(profile) {
  const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot
  return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未命名画像'
}

async function openGeneratedResource(item) {
  if (!item?.resource_id || !selectedJob.value) return
  if (!resources.value.some((resource) => resource.resource_id === item.resource_id)) {
    await loadResourcesForSelectedJob()
  }
  if (resources.value.some((resource) => resource.resource_id === item.resource_id)) {
    selectedResourceId.value = item.resource_id
  }
}

function profileCreatedAt(profile) {
  return profile?.created_at ? formatDateTime(profile.created_at) : '时间未知'
}

function taskLabel(task) {
  if (task.task_kind === 'interactive_courseware') {
    return `HTML 课件 / ${taskStatusLabel(task)} / ${task.run_id.slice(0, 8).toUpperCase()} / ${formatDateTime(task.updated_at || task.created_at)}`
  }
  const prefix = task.job_status === 'running' || task.job_status === 'queued' ? '当前' : '历史'
  return `${prefix} / ${task.run_id.slice(0, 8).toUpperCase()} / ${formatDateTime(task.finished_at || task.created_at)}`
}

function persistSelectedJob() {
  localStorage.setItem('current_generation_run_id', selectedTask.value?.run_id || '')
  localStorage.setItem('current_generation_status', selectedTask.value?.job_status || '')
}

function resourceLabel(resource) {
  const resourceName = String(resource?.resource_type || '学习资源').trim()
  const nodes = [...new Set((resource?.knowledge_points || [])
    .map((point) => String(point || '').trim())
    .filter(Boolean))]
  const tierLabel = resource?.tier_label || resourceTierLabel(resource)
  return [resourceName, nodes.join('、'), tierLabel].filter(Boolean).join(' · ')
}

function resourceTierLabel(resource) {
  const tiers = [...new Set((resource?.knowledge_points || [])
    .map((point) => nodeTiers.value[String(point || '').trim()])
    .filter((tier) => Number.isInteger(tier)))]
  return tiers.length ? tiers.map((tier) => `第 ${tier} 阶`).join('、') : ''
}

async function loadNodeTiers() {
  const version = ++nodeTiersRequestVersion
  const learnerId = selectedLearnerId.value
  const knowledgeBaseId = activeProfile.value?.knowledge_base_id
  const isCurrent = () => generationMounted && version === nodeTiersRequestVersion && learnerId === selectedLearnerId.value && knowledgeBaseId === activeProfile.value?.knowledge_base_id
  if (!knowledgeBaseId) {
    nodeTiers.value = {}
    return
  }
  try {
    const nodesRes = await knowledgeApi.listNodes(knowledgeBaseId)
    if (!isCurrent()) return
    nodeTiers.value = Object.fromEntries((nodesRes.data?.nodes || nodesRes.data || [])
      .map((node) => [node.node_id, node.tier])
      .filter(([, tier]) => Number.isInteger(tier)))
  } catch (error) {
    if (!isCurrent()) return
    nodeTiers.value = {}
    console.warn('学习节点阶级加载失败，标题将隐藏阶级信息', error)
  }
}

const { stopPolling, closeRealtime, cancelPublishedResourceRefresh, startRealtime, startPolling } = useGenerationProgress({
  selectedRunId, selectedJob, timelineState, connectionStatus,
  isMounted: () => generationMounted,
  refreshStatus: (...args) => refreshStatus(...args),
  loadClaimReports: (...args) => loadClaimReports(...args),
})













function pickDefaultRunId(items) {
  if (!items.length) return ''
  if (initialRunId && items.some((item) => item.run_id === initialRunId)) return initialRunId
  const currentJob = items.find((item) => item.job_status === 'running' || item.job_status === 'queued')
  if (currentJob) return currentJob.run_id
  return items[0].run_id
}

function syncProfileContext() {
  const profile = activeProfile.value
  if (!profile) return
  store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id))
  localStorage.setItem('last_learner_id', profile.learner_id)
}

async function loadProfiles() {
  const [profileRes, domainRes] = await Promise.all([
    profileApi.list({ page: 1, page_size: 50 }),
    knowledgeApi.listDomains(),
  ])
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  if (!generationMounted) return
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
  if (!profiles.value.length) {
    selectedLearnerId.value = ''
    return
  }
  if (!profiles.value.some((item) => item.learner_id === selectedLearnerId.value)) {
    selectedLearnerId.value = profiles.value[0].learner_id
  }
  syncProfileContext()
}

async function loadJobs(preferDefault = false) {
  const version = ++jobsRequestVersion
  const learnerId = selectedLearnerId.value
  const isCurrent = () => generationMounted && version === jobsRequestVersion && learnerId === selectedLearnerId.value
  jobsError.value = ''
  if (!generationMounted) return false
  if (!learnerId) {
    jobs.value = []
    coursewareJobs.value = []
    selectedRunId.value = ''
    resources.value = []
    resourcesLoaded.value = false
    closeRealtime()
    stopPolling()
    connectionStatus.value = 'idle'
    loadingJobs.value = false
    return true
  }
  loadingJobs.value = true
  try {
    const [res, coursewareRes] = await Promise.all([
      generateApi.listJobs(learnerId),
      coursewareApi.listJobs(learnerId),
    ])
    if (!isCurrent()) return false
    jobs.value = (res.data.items || []).filter((item) => !item.superseded_by_run_id)
    coursewareJobs.value = coursewareRes.data.items || []
    if (!taskItems.value.length) {
      closeRealtime()
      selectedRunId.value = ''
      timelineState.value = createInitialTimelineState()
      connectionStatus.value = 'idle'
      resources.value = []
      resourcesLoaded.value = false
      selectedResourceId.value = ''
      stopPolling()
      return true
    }

    if (
      preferDefault ||
      !selectedRunId.value ||
      !taskItems.value.some((item) => item.run_id === selectedRunId.value)
    ) {
      selectedRunId.value = pickDefaultRunId(taskItems.value)
    }

    persistSelectedJob()
    return true
  } catch (error) {
    if (!isCurrent()) return false
    jobsError.value = error?.response?.data?.message || '任务列表加载失败'
    ElMessage.error(jobsError.value)
    return false
  } finally {
    if (isCurrent()) loadingJobs.value = false
  }
}

async function loadResourcesForSelectedJob() {
  const version = ++resourcesRequestVersion
  const learnerId = selectedLearnerId.value
  const runId = selectedJob.value?.run_id
  const isCurrent = () => generationMounted && version === resourcesRequestVersion && learnerId === selectedLearnerId.value && runId === selectedJob.value?.run_id
  if (!selectedLearnerId.value || !selectedJob.value?.run_id) {
    resources.value = []
    resourcesLoaded.value = true
    selectedResourceId.value = ''
    return
  }

  loadingResources.value = true
  try {
    await loadNodeTiers()
    if (!isCurrent()) return
    const res = await resourceApi.listByLearner(learnerId, {
      // This page is scoped to the selected task Run. Cross-run aggregation
      // belongs to the learner-facing Learning Resources page.
      run_id: runId,
      page: 1,
      page_size: 100,
    })
    if (!isCurrent()) return
    resources.value = (res.data.resources || []).map((resource) => ({
      ...resource,
      tier_label: resource.tier_label || resourceTierLabel(resource),
    }))
    resourcesLoaded.value = true
    if (!resources.value.length) {
      selectedResourceId.value = ''
    } else if (!resources.value.some((item) => item.resource_id === selectedResourceId.value)) {
      selectedResourceId.value = resources.value[0].resource_id
    }
  } catch (error) {
    if (!isCurrent()) return
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '资源列表加载失败')
  } finally {
    if (isCurrent()) loadingResources.value = false
  }
}

async function loadCoursewareSourceResources() {
  const version = ++resourcesRequestVersion
  const learnerId = selectedLearnerId.value
  const runId = selectedRunId.value
  const batchId = selectedCoursewareJob.value?.source_batch_id
  const isCurrent = () => generationMounted && version === resourcesRequestVersion && learnerId === selectedLearnerId.value && runId === selectedRunId.value
  if (!selectedLearnerId.value || !batchId) {
    resources.value = []
    resourcesLoaded.value = true
    return
  }
  loadingResources.value = true
  try {
    await loadNodeTiers()
    if (!isCurrent()) return
    const response = await resourceLibraryApi.listByLearner(learnerId)
    if (!isCurrent()) return
    resources.value = (response.data || []).filter((resource) => (
      resource.resource_kind !== 'interactive_courseware'
      && resource.batch_id === batchId
    )).map((resource) => ({
      ...resource,
      tier_label: resource.tier_label || resourceTierLabel(resource),
    }))
    resourcesLoaded.value = true
  } catch (error) {
    if (!isCurrent()) return
    console.error(error)
    resources.value = []
    resourcesLoaded.value = true
    ElMessage.error(error?.response?.data?.message || '课件来源资源加载失败')
  } finally {
    if (isCurrent()) loadingResources.value = false
  }
}

const {
  loadClaimReports, openClaimReport, claimPassRateLabel, claimIssueCount,
  claimReportStatusLabel, claimReportStatusClass, claimRateStyle, decideClaimPublication,
} = useGenerationClaims({
  selectedRunId, selectedLearnerId, timelineState, resources, claimReports,
  selectedClaimReportId, claimReportVisible, claimDecisionLoading,
  isMounted: () => generationMounted,
  requestVersion: () => claimsRequestVersion,
  nextRequestVersion: () => ++claimsRequestVersion,
  refreshStatus: (...args) => refreshStatus(...args),
  messages: ElMessage,
})















async function refreshStatus() {
  if (!selectedJob.value?.run_id) return
  const learnerId = selectedLearnerId.value
  const runId = selectedJob.value.run_id
  const version = jobsRequestVersion
  const isCurrent = () => generationMounted && learnerId === selectedLearnerId.value && runId === selectedJob.value?.run_id && version === jobsRequestVersion
  try {
    const res = await generateApi.getJobStatus(runId)
    if (!isCurrent()) return
    const nextJob = res.data
    jobs.value = jobs.value.map((item) => (item.run_id === nextJob.run_id ? nextJob : item))
    timelineState.value = applyRunSnapshot(timelineState.value, nextJob)
    persistSelectedJob()

    const hasPublishedResources = Number(nextJob.resource_progress_summary?.published || 0) > 0
    if (nextJob.job_status === 'completed') {
      stopPolling()
      await loadResourcesForSelectedJob()
      if (!isCurrent()) return
      await loadClaimReports(nextJob.run_id)
    } else if (hasPublishedResources) {
      await loadResourcesForSelectedJob()
    } else if (nextJob.job_status === 'failed') {
      stopPolling()
    }
  } catch (error) {
    if (!isCurrent()) return
    console.error(error)
    stopPolling()
    ElMessage.error(error?.response?.data?.message || '任务状态获取失败')
  }
}

async function refreshJobs() {
  if (!await loadJobs(false)) return
  const version = jobsRequestVersion
  if (selectedJob.value?.job_status === 'completed' || selectedJob.value?.resource_progress_summary?.published) {
    await loadResourcesForSelectedJob()
  }
  if (!generationMounted || version !== jobsRequestVersion) return
  await startRealtime(selectedRunId.value)
}

async function handleTaskChange() {
  const learnerId = selectedLearnerId.value
  const runId = selectedRunId.value
  const version = ++taskChangeVersion
  ++resourcesRequestVersion; ++claimsRequestVersion
  const isCurrent = () => generationMounted && version === taskChangeVersion && learnerId === selectedLearnerId.value && runId === selectedRunId.value
  closeRealtime()
  persistSelectedJob()
  stopPolling()
  resources.value = []
  resourcesLoaded.value = false
  selectedResourceId.value = ''

  if (selectedCoursewareJob.value) {
    closeRealtime()
    await loadCoursewareSourceResources()
    if (!isCurrent()) return
    coursewareComposerVisible.value = true
    return
  }
  // The temporary composer is only needed before a new courseware task has
  // been created. Do not keep it mounted when the user returns to a text
  // generation task, otherwise both task workspaces render together.
  coursewareComposerVisible.value = false
  if (!selectedJob.value) return
  if (selectedJob.value.job_status === 'completed' || selectedJob.value.resource_progress_summary?.published) {
    await loadResourcesForSelectedJob()
    if (!isCurrent()) return
    await loadClaimReports(selectedRunId.value)
  } else {
    resourcesLoaded.value = true
  }
  if (!isCurrent()) return
  await startRealtime(selectedRunId.value)
}

async function handleProfileChange() {
  const version = ++profileChangeVersion
  ++resourcesRequestVersion; ++claimsRequestVersion; ++nodeTiersRequestVersion; ++taskChangeVersion
  syncProfileContext()
  jobs.value = []; coursewareJobs.value = []; nodeTiers.value = {}; claimReports.value = {}
  loadingResources.value = false
  coursewareComposerVisible.value = false
  selectedRunId.value = ''
  selectedResourceId.value = ''
  resources.value = []
  resourcesLoaded.value = false
  timelineState.value = createInitialTimelineState()
  closeRealtime()
  stopPolling()
  if (!await loadJobs(true) || version !== profileChangeVersion || !generationMounted) return
  if (selectedJob.value?.job_status === 'completed' || selectedJob.value?.resource_progress_summary?.published) {
    await loadResourcesForSelectedJob()
  } else {
    resourcesLoaded.value = true
  }
  if (version !== profileChangeVersion || !generationMounted) return
  await startRealtime(selectedRunId.value)
}

async function deleteProfile(profile) {
  try {
    await ElMessageBox.confirm(
      `将删除“${profile.label}”及其关联画像数据，此操作无法撤销。`,
      '删除学习画像',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await profileApi.delete(profile.learner_id)
    profiles.value = profiles.value.filter((item) => item.learner_id !== profile.learner_id)
    if (selectedLearnerId.value === profile.learner_id) {
      selectedLearnerId.value = profiles.value[0]?.learner_id || ''
      selectedRunId.value = ''
      selectedResourceId.value = ''
      if (selectedLearnerId.value) {
        syncProfileContext()
        await loadJobs(true)
      } else {
        jobs.value = []
        localStorage.removeItem('last_learner_id')
        localStorage.removeItem('current_generation_run_id')
      }
    }
    ElMessage.success('学习画像已删除')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '删除学习画像失败')
  }
}

async function openChildRun(runId) {
  selectedRunId.value = runId
  localStorage.setItem('current_generation_run_id', runId)
  if (!await loadJobs(false) || runId !== selectedRunId.value) return
  resources.value = []
  resourcesLoaded.value = false
  selectedResourceId.value = ''
  await startRealtime(runId)
}

async function retryGeneration() {
  const failedJob = selectedJob.value
  const payload = failedJob?.request_payload
  if (!failedJob?.run_id || !payload?.learner_id || !Array.isArray(payload?.resource_types) || !payload.resource_types.length) {
    ElMessage.warning('该任务缺少原始生成参数，无法保证重试内容一致')
    return
  }

  retrying.value = true
  resources.value = []
  resourcesLoaded.value = false
  selectedResourceId.value = ''
  stopPolling()

  try {
    const batchId = selectedJob.value?.batch_id || selectedJob.value?.run_id
    const res = await generateApi.continueBatch(batchId, {
      learner_id: failedJob.learner_id,
      resource_types: payload.resource_types,
      instructions: payload.constraints?.continuation_instructions || '重新生成失败任务的学习材料。',
      source_run_id: failedJob.run_id,
    })
    selectedRunId.value = res.data.run_id
    await loadJobs(false)
    await startRealtime(selectedRunId.value)
    ElMessage.success('已在原资源批次中重新发起生成任务')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '重新生成失败')
  } finally {
    retrying.value = false
  }
}

function appendResources() {
  const sourceJob = selectedJob.value
  const payload = sourceJob?.request_payload
  if (!sourceJob?.learner_id || !payload) {
    ElMessage.warning('该任务缺少追加资源所需的原始参数')
    return
  }
  selectedAppendResourceTypes.value = appendResourceOptions.value
    .filter((option) => !option.alreadyIncluded)
    .map((option) => option.type)
  appendIncludeClaimCheck.value = appendReviewEnabled.value
    && sourceJob.request_payload?.include_claim_check !== false
  appendDialogVisible.value = true
}

async function handleAppendCommand(kind) {
  if (kind === 'text') {
    appendResources()
    return
  }
  if (!resources.value.length) {
    ElMessage.info('请先选择一个已发布资源的任务，再追加 HTML 互动课件。')
    return
  }
  coursewareComposerVisible.value = true
  await nextTick()
  coursewareWorkspace.value?.openCreateDialog()
}

async function handleCoursewareCreated(payload) {
  const createdJobs = payload?.jobs || []
  coursewareJobs.value = [
    ...createdJobs,
    ...coursewareJobs.value.filter((job) => !createdJobs.some((created) => created.run_id === job.run_id)),
  ]
  if (payload?.activeJob?.run_id) selectedRunId.value = payload.activeJob.run_id
  // Once the new run is selected, selectedCoursewareJob keeps the workspace
  // mounted; clear the temporary creation-only flag.
  coursewareComposerVisible.value = false
  persistSelectedJob()
}

async function handleCoursewarePublished(coursewareJob) {
  await loadJobs(false)
  ElMessage.success('HTML 互动课件已追加到当前资源批次。')
  const publishedJob = coursewareJob || selectedCoursewareJob.value
  if (!publishedJob?.resource_id) return
  await router.push({
    path: '/resources',
    query: {
      learnerId: selectedLearnerId.value,
      runId: publishedJob.source_batch_id || publishedJob.run_id,
      resourceId: publishedJob.resource_id,
    },
  })
}

async function regeneratePendingResources() {
  const sourceJob = selectedJob.value
  const resourceTypes = retryableResourceTypes.value
  if (!sourceJob?.learner_id || !resourceTypes.length) {
    ElMessage.warning('当前任务没有可重新生成的资源')
    return
  }
  retrying.value = true
  try {
    const batchId = sourceJob.batch_id || sourceJob.run_id
    const response = await generateApi.continueBatch(batchId, {
      learner_id: sourceJob.learner_id,
      resource_types: appendIncludeClaimCheck.value ? [resourceTypes[0]] : resourceTypes,
      source_run_id: sourceJob.run_id,
      replace_existing_types: true,
      instructions: `统一重新生成本任务中未通过审核的资源：${resourceTypes.join('、')}。`,
    })
    selectedRunId.value = response.data.run_id
    localStorage.setItem('current_generation_run_id', selectedRunId.value)
    resources.value = []
    resourcesLoaded.value = false
    selectedResourceId.value = ''
    await loadJobs(false)
    await startRealtime(selectedRunId.value)
    ElMessage.success(`已创建一个新任务，统一重新生成：${resourceTypes.join('、')}`)
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '重新生成失败资源失败')
  } finally {
    retrying.value = false
  }
}

async function confirmAppendResources() {
  const sourceJob = selectedJob.value
  const resourceTypes = [...new Set(selectedAppendResourceTypes.value)]
  if (!sourceJob?.learner_id || !resourceTypes.length) {
    ElMessage.warning('请至少选择一种要追加的资源类型')
    return
  }
  appendingResources.value = true
  try {
    const batchId = sourceJob.batch_id || sourceJob.run_id
    const requestResourceTypes = appendIncludeClaimCheck.value
      ? resourceTypes.map((type) => [type])
      : [resourceTypes]
    const responses = await Promise.all(requestResourceTypes.map((types) =>
      generateApi.continueBatch(batchId, {
        learner_id: sourceJob.learner_id, resource_types: types,
        instructions: '追加指定类型的学习资源，并与本批次已有资源保持衔接。',
        source_run_id: sourceJob.run_id,
        include_claim_check: appendIncludeClaimCheck.value,
      })
    ))
    const response = responses[0]
    selectedRunId.value = response.data.run_id
    localStorage.setItem('current_generation_run_id', selectedRunId.value)
    resources.value = []
    resourcesLoaded.value = false
    selectedResourceId.value = ''
    await loadJobs(false)
    await startRealtime(selectedRunId.value)
    appendDialogVisible.value = false
    ElMessage.success(`已追加：${resourceTypes.join('、')}`)
  } catch (error) {
    console.error(error)
    ElMessage.error(apiErrorMessage(error, '追加资源失败'))
  } finally {
    appendingResources.value = false
  }
}

async function retryResource(item) {
  const sourceJob = selectedJob.value
  const payload = sourceJob?.request_payload
  if (!sourceJob?.learner_id || !payload || !item?.resource_type) {
    ElMessage.warning('该资源缺少重新生成所需的任务参数')
    return
  }

  const key = item.key || `${item.resource_spec_id}:${item.representation || 'text'}`
  retryingResourceKey.value = key
  try {
    const batchId = sourceJob.batch_id || sourceJob.run_id
    const response = await generateApi.continueBatch(batchId, {
      learner_id: sourceJob.learner_id,
      resource_types: [item.resource_type],
      source_run_id: sourceJob.run_id,
      replace_existing_types: true,
      instructions: `重新生成本批次的${item.resource_type}，用新版本替换学习列表中的旧版本。`,
    })
    selectedRunId.value = response.data.run_id
    localStorage.setItem('current_generation_run_id', selectedRunId.value)
    resources.value = []
    resourcesLoaded.value = false
    selectedResourceId.value = ''
    await loadJobs(false)
    await startRealtime(selectedRunId.value)
    ElMessage.success(`已在当前批次重新生成${item.resource_type}`)
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '重新生成资源失败')
  } finally {
    retryingResourceKey.value = ''
  }
}

onMounted(async () => {
  try {
    await loadProfiles()
    const version = profileChangeVersion
    if (!generationMounted || !await loadJobs(true) || version !== profileChangeVersion) return
    if (selectedJob.value?.job_status === 'completed' || selectedJob.value?.resource_progress_summary?.published) {
      await loadResourcesForSelectedJob()
    } else {
      resourcesLoaded.value = true
    }
    if (!generationMounted || version !== profileChangeVersion) return
    await startRealtime(selectedRunId.value)
  } catch (error) {
    if (generationMounted) jobsError.value = error?.response?.data?.message || '学习画像加载失败，请刷新页面重试'
  }
})

onBeforeUnmount(() => {
  generationMounted = false
  ++jobsRequestVersion; ++resourcesRequestVersion; ++nodeTiersRequestVersion; ++claimsRequestVersion; ++profileChangeVersion; ++taskChangeVersion
  cancelPublishedResourceRefresh()
  closeRealtime()
  stopPolling()
})
</script>

<style scoped>
.generate-page { --prod-ink:#172c45; --prod-muted:#59697b; --prod-line:#dce4eb; --prod-navy:#102339; --prod-accent:#176b70; --prod-mint:#9cf2e0; display:flex; flex-direction:column; gap:14px; min-width:0; padding-top:16px; color:var(--prod-ink); }
.generate-page * { box-sizing:border-box; }
.eyebrow { color:var(--prod-muted); font:10px/1.5 Consolas,monospace; letter-spacing:.04em; }
.control-panel { display:grid; grid-template-columns:minmax(0,1fr); overflow:hidden; border:1px solid var(--prod-line); border-top:2px solid var(--prod-navy); border-radius:4px; background:#fff; }
.task-selector { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; padding:14px 20px 12px; }
.selector-field { min-width:0; }
.selector-field label { display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; gap:8px; color:var(--prod-muted); font-size:12px; }
.selector-field label span { font:9px Consolas,monospace; }
.task-select,.resource-select { width:100%; min-width:0; }
.generate-page :deep(.el-select__wrapper) { min-height:44px; border-radius:3px; background:#f7f9fb; box-shadow:0 0 0 1px #cdd9e2 inset; padding-inline:12px; font-size:12px; }
.generate-page :deep(.el-select__wrapper.is-focused) { box-shadow:0 0 0 2px var(--prod-accent) inset; }
.generate-page :deep(.el-select__placeholder) { color:var(--prod-ink); }
.profile-option { display:flex; align-items:center; justify-content:space-between; gap:12px; min-width:0; }
.profile-option > span { overflow:hidden; text-overflow:ellipsis; }
.profile-delete { width:30px; height:30px; flex:none; margin:0; color:#a93434; }
.job-summary { display:grid; grid-template-columns:minmax(0,1.35fr) minmax(0,.7fr) minmax(0,.85fr) minmax(0,.65fr) repeat(2,minmax(0,1fr)); gap:0; margin:0 20px 14px; padding-top:12px; border-top:1px solid var(--prod-line); }
.summary-item { min-width:0; padding:0 12px; border-left:1px solid var(--prod-line); }
.summary-item:first-child { border:0; padding-left:0; }
.summary-item:last-child { padding-right:0; }
.summary-item > span { display:block; color:var(--prod-muted); font-size:11px; }
.summary-item small { display:none; }
.summary-item strong { display:block; margin-top:6px; min-height:22px; color:var(--prod-ink); font-size:12px; line-height:1.6; overflow-wrap:anywhere; }
.summary-item .summary-direction { font-size:13px; }
.summary-item .summary-code { font-family:Consolas,monospace; letter-spacing:.04em; }
.summary-item .summary-count { color:var(--prod-accent); font-size:20px; line-height:1.1; }
.summary-count em { font-style:normal; font-size:11px; }
.summary-item .production-status { display:flex; align-items:center; gap:6px; color:var(--prod-accent); }
.production-status .el-icon { flex:none; font-size:15px; }
.summary-item .production-status.is-warning { color:#935719; }
.summary-item .production-status.is-error { color:#a1322c; }
.error-message { grid-column:1/-1; display:flex; align-items:flex-start; gap:8px; margin:0; padding:12px 22px; color:#a1322c; background:#fff4f1; border-top:1px solid #efcec8; font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
.error-message .el-icon { flex:none; margin-top:3px; }
.task-actions { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-width:0; }
.resource-panel-tools { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:12px; min-width:0; }
.resource-panel-heading { flex-wrap:wrap; }
.resource-panel-heading > div:first-child { flex:none; }
:deep(.production-dialog .el-button), .generate-page :deep(.el-button) { min-height:44px; height:auto; border-radius:3px; font-size:12px; font-weight:600; transition:background .16s ease,border-color .16s ease,color .16s ease; }
.generate-page :deep(.el-button + .el-button) { margin-left:0; }
.generate-page :deep(.el-button > span) { gap:7px; white-space:normal; line-height:1.5; }
.status-action { margin:0; border-color:#cdd9e2; background:#fff; color:var(--prod-ink); padding:10px 12px; }
.status-action:hover { border-color:#7b9baf; background:#f1f6f8; color:var(--prod-accent); }
.status-action-append,.primary-action,.learning-mode-action { background:var(--prod-navy); border-color:var(--prod-navy); color:#fff; }
.status-action-append:hover,.primary-action:hover,.learning-mode-action:hover { background:#1d3d56; border-color:#1d3d56; color:var(--prod-mint); }
.status-action-retry,.status-action-resource.is-retry { background:#e6f7f3; border-color:#84bdb4; color:#125c60; }
.studio-grid { display:grid; grid-template-columns:minmax(280px,.3fr) minmax(0,.7fr); gap:20px; min-width:0; }
.process-panel,.resources-panel { min-width:0; display:flex; flex-direction:column; }
.resources-panel { border-left:1px solid var(--prod-line); padding-left:20px; }
.panel-title { display:flex; flex:none; min-height:60px; align-items:center; justify-content:space-between; gap:12px; padding:0 0 12px; border-bottom:1px solid var(--prod-line); }
.panel-title h3 { margin:4px 0 0; font-size:19px; line-height:1.4; }
.connection-state { display:flex; align-items:center; gap:6px; color:var(--prod-muted); font-size:11px; }
.connection-state i { width:6px; height:6px; flex:none; border-radius:50%; background:#64748b; }
.connection-state.is-live { color:#176b70; }
.connection-state.is-live i { background:#176b70; }
.connection-state:is(.is-error,.is-fallback) { color:#935719; }
.connection-state:is(.is-error,.is-fallback) i { background:#935719; }
.output-count { color:var(--prod-accent); font:20px/1 Consolas,monospace; white-space:nowrap; }
.output-count small { color:var(--prod-muted); font:11px sans-serif; }
.process-scroll { padding:8px 8px 0 0; min-width:0; }
.process-scroll :deep(.workflow-timeline) { border:0; border-radius:0; box-shadow:none; background:transparent; }
.process-scroll :deep(.el-card__header) { display:none; }
.process-scroll :deep(.el-card__body) { padding:0; }
.resource-toolbar { display:grid; grid-template-columns:minmax(0,1fr) auto; flex:none; align-items:center; gap:12px; padding:12px 0; }
.resource-select { flex:1; }
.resource-select :deep(.el-select__selection),.resource-select :deep(.el-select__selected-item) { min-width:0; max-width:100%; }
.resource-select :deep(.el-select__selected-item > span) { display:block; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.reader-toolbar-actions,.reader-resource-actions { display:flex; min-width:0; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.status-action-append,.learning-mode-action { width:112px; flex:none; padding:10px; }
.toolbar-download-action { margin:0; padding:10px 12px; border-color:#cdd9e2; background:#fff; color:var(--prod-ink); }
.toolbar-download-action:hover { border-color:#7b9baf; background:#eaf5f2; color:var(--prod-accent); }
.resource-difficulty { height:auto; min-height:28px; padding:4px 8px; border-radius:3px; font-size:11px; line-height:1.5; white-space:normal; }
.resource-difficulty.el-tag--success { color:#176b70; border-color:#bbd9d2; background:#eef7f4; }
.resource-difficulty.el-tag--warning { color:#935719; border-color:#e4c59f; background:#fff7ed; }
.resource-difficulty.el-tag--danger { color:#a1322c; border-color:#e8c5c0; background:#fff3f0; }
.resource-stage { min-width:0; background:#fff; border:1px solid var(--prod-line); border-radius:4px; }
.resource-stage :deep(.reader-card) { width:100%; min-width:0; border:0; border-radius:0; box-shadow:none; background:transparent; overflow:visible; }
.resource-stage :deep(.reader-content) { padding:20px 22px; }
.resource-stage :deep(.content-label) { color:var(--prod-muted); }
.resource-stage :deep(.reader-footer) { padding:16px 22px; }
.resource-stage :deep(.markdown-body) { overflow-wrap:anywhere; font-size:14px; line-height:1.9; }
.resource-stage :deep(.markdown-body h1) { font-size:25px; line-height:1.5; margin-block:0 20px; }
.resource-stage :deep(.markdown-body h2) { font-size:20px; line-height:1.5; }
.resource-stage :deep(.markdown-body h3) { font-size:17px; line-height:1.6; }
.resource-stage :deep(.el-tag) { height:auto; padding:4px 9px; border-radius:3px; line-height:1.5; white-space:normal; }
.resource-stage :deep(.el-tag--warning) { color:#935719; border-color:#e4c59f; background:#fff7ed; }
.resource-stage :deep(.el-tag--success) { color:#176b70; border-color:#bbd9d2; background:#eef7f4; }
.resource-stage :deep(.el-tag--info) { color:#59697b; }
.resource-placeholder { min-height:0; text-align:left; }
.output-preparation-context { display:flex; align-items:center; flex-wrap:wrap; gap:10px; color:var(--prod-muted); font-size:12px; line-height:1.7; }
.output-preparation-context strong { color:var(--prod-accent); font-weight:600; }
.output-preparation-context > span:last-child { margin-left:auto; }
.resource-placeholder.is-failed :deep(.preparation-mark) { color:#935719; border-color:#e4c59f; background:#fff7ed; }
.empty-studio { overflow:hidden; min-width:0; padding:0; border-radius:6px; background:transparent; }
.empty-studio :deep(.preparation-primary-action) { border-color:#88cfc5 !important; background:#9cecdf !important; color:#123747 !important; }
.empty-studio :deep(.preparation-primary-action:hover) { border-color:#55a89f !important; background:#b4f2e8 !important; color:#123747 !important; }
.production-footer { display:flex; justify-content:space-between; gap:14px; margin-top:-10px; padding-top:0; border-top:0; color:var(--prod-muted); font-size:10px; line-height:1.5; }
.production-footer i { margin-inline:10px; font-style:normal; }
/* Avoid matching the tabindex on select inputs, which have an outer focus border. */
.generate-page :is(button,.process-scroll,.resource-stage):focus-visible,.generate-page :deep(.el-button:focus-visible) { outline:3px solid #147d80; outline-offset:3px; }
.process-scroll,.resource-stage { overscroll-behavior:contain; scrollbar-gutter:stable; scrollbar-width:thin; scrollbar-color:#9db8c2 transparent; }
.process-scroll:focus-visible,.resource-stage:focus-visible { outline-offset:-2px; }
.generate-page.is-fit-layout { height:100%; min-height:0; display:grid; grid-template-rows:auto minmax(0,1fr) auto; gap:14px; padding-top:16px; }
.is-fit-layout .studio-grid { min-height:0; }
.is-fit-layout .process-panel,.is-fit-layout .resources-panel { min-height:0; overflow:hidden; }
.is-fit-layout .process-scroll,.is-fit-layout .resource-stage { flex:1; min-height:0; overflow-y:auto; }
.is-fit-layout .resource-placeholder { min-height:0; }
.is-fit-layout .empty-studio { min-height:0; padding:0; overflow-y:auto; overscroll-behavior:contain; }
.is-fit-layout .empty-studio > .preparation-panel { min-height:100%; }
.generate-page :deep(.courseware-generation-page) { min-height:0; min-width:0; padding:0; gap:14px; }
.generate-page :deep(.generation-grid) { grid-template-columns:minmax(0,.85fr) minmax(0,1.15fr); gap:26px; height:auto; }
.generate-page :deep(.generation-grid .process-panel),.generate-page :deep(.details-panel) { padding:18px; border:1px solid var(--prod-line); border-radius:4px; box-shadow:none; background:#fff; min-width:0; }
.generate-page :deep(.generation-grid .panel-title) { min-height:78px; margin:-18px -18px 0; padding:18px 18px 12px; border-color:var(--prod-line); }
.generate-page :deep(.details-panel > .panel-title) { flex-wrap:wrap; }
.generate-page :deep(.generation-grid .panel-title h3) { font-size:19px; }
.generate-page :deep(.generation-grid .eyebrow) { font:10px Consolas,monospace; color:var(--prod-muted); }
.generate-page :deep(.courseware-generation-page .el-button--primary:not(.is-link):not(.is-text)) { background:var(--prod-navy); border-color:var(--prod-navy); color:#fff; }
.generate-page :deep(.courseware-generation-page .el-button--warning) { background:#fff7ed; border-color:#e4c59f; color:#935719; }
.generate-page :deep(.courseware-generation-page .el-button.is-link) { background:transparent; border-color:transparent; color:var(--prod-accent); }
.generate-page :deep(.courseware-generation-page .el-tag--primary),.generate-page :deep(.courseware-generation-page .el-tag--success) { color:#176b70; border-color:#bbd9d2; background:#eef7f4; }
.generate-page :deep(.courseware-generation-page .el-tag--warning) { color:#935719; border-color:#e4c59f; background:#fff7ed; }
.generate-page :deep(.courseware-generation-page .el-tag--info) { color:#59697b; }
.generate-page :deep(.courseware-generation-page .warnings) { color:#935719; background:#fff7ed; }
.generate-page :deep(.workflow-snake-node) { color:var(--prod-accent); background:#e8f5f1; border-color:#81b4ad; box-shadow:none; }
.generate-page :deep(.workflow-snake-step.is-active .workflow-snake-node) { background:var(--prod-navy); border-color:var(--prod-navy); color:var(--prod-mint); box-shadow:0 0 0 4px #e4f2ef; }
.generate-page :deep(.workflow-snake-copy small),.generate-page :deep(.scene-list small) { color:var(--prod-muted); }
.generate-page :deep(.workflow-snake) { grid-template-rows:repeat(4,minmax(72px,auto)); gap:18px 16px; margin-top:14px; }
.generate-page :deep(.workflow-snake-step) { width:100%; height:auto; min-height:72px; min-width:0; padding:8px; border-radius:3px; }
.generate-page :deep(.workflow-snake-node) { width:24px; height:24px; flex-basis:24px; }
.generate-page :deep(.workflow-snake-copy) { min-width:0; }
.generate-page :deep(.workflow-snake-copy strong),.generate-page :deep(.workflow-snake-copy small) { white-space:normal; overflow:visible; text-overflow:clip; overflow-wrap:anywhere; }
.generate-page :deep(.workflow-snake-step:nth-child(1)::after),.generate-page :deep(.workflow-snake-step:nth-child(2)::after),.generate-page :deep(.workflow-snake-step:nth-child(7)::after),.generate-page :deep(.workflow-snake-step:nth-child(8)::after) { width:16px; }
.generate-page :deep(.workflow-snake-step:nth-child(4)::after),.generate-page :deep(.workflow-snake-step:nth-child(5)::after),.generate-page :deep(.workflow-snake-step:nth-child(10)::after),.generate-page :deep(.workflow-snake-step:nth-child(11)::after) { width:16px; }
.generate-page :deep(.workflow-snake-step:nth-child(3)::after),.generate-page :deep(.workflow-snake-step:nth-child(6)::after),.generate-page :deep(.workflow-snake-step:nth-child(9)::after) { height:18px; }
.generate-page :deep(.frozen-options),.generate-page :deep(.quality-summary),.generate-page :deep(.scene-list) { border-radius:3px; box-shadow:none; background:#f6f9fb; }
.is-fit-layout :deep(.courseware-generation-page),.is-fit-layout :deep(.generation-grid) { height:100%; min-height:0; }
.is-fit-layout :deep(.generation-grid > .process-panel) { overflow:auto; overscroll-behavior:contain; scrollbar-gutter:stable; }
.is-fit-layout :deep(.generation-grid > .process-panel > .panel-title) { position:sticky; top:-18px; z-index:1; background:#fff; }
.generate-page :deep(.generation-grid > .process-panel:focus-visible),.generate-page :deep(.details-scroll:focus-visible) { outline:2px solid var(--prod-accent); outline-offset:-2px; }
.is-fit-layout :deep(.details-panel) { overflow:hidden; }
.is-fit-layout :deep(.details-scroll) { min-height:0; overflow:auto; overscroll-behavior:contain; scrollbar-gutter:stable; }
:deep(.production-dialog) { --prod-ink:#172c45; --prod-muted:#59697b; --prod-line:#dce4eb; --prod-navy:#102339; --prod-accent:#176b70; --prod-mint:#9cf2e0; display:flex; flex-direction:column; max-height:calc(100dvh - 40px); margin-top:20px; border-radius:5px; border:1px solid var(--prod-line); background:#fff; padding:0; overflow:hidden; }
:deep(.production-dialog .el-dialog__header) { flex:none; margin:0; padding:20px 24px; border-bottom:1px solid var(--prod-line); }
:deep(.production-dialog .el-dialog__title) { color:var(--prod-ink); font-size:20px; font-weight:700; }
:deep(.production-dialog .el-dialog__body) { padding:22px 24px; overflow:auto; overscroll-behavior:contain; color:var(--prod-muted); }
:deep(.production-dialog .el-dialog__footer) { flex:none; border-top:1px solid var(--prod-line); padding:14px 24px; }
:deep(.production-dialog .el-button--primary) { background:var(--prod-navy); border-color:var(--prod-navy); color:#fff; }
:deep(.production-dialog .el-dialog__headerbtn) { top:12px; right:12px; width:44px; height:44px; }
:deep(.production-dialog .el-tag--warning) { color:#935719; border-color:#e4c59f; background:#fff7ed; border-radius:3px; }
:deep(.production-dialog .el-checkbox.is-checked .el-checkbox__label) { color:#176b70; }
:deep(.production-dialog .el-checkbox__input.is-checked .el-checkbox__inner) { background:#176b70; border-color:#176b70; }
:deep(.production-dialog .el-checkbox__input.is-focus .el-checkbox__inner),:deep(.production-dialog .el-button:focus-visible) { outline:2px solid #147d80; outline-offset:3px; }
/* Courseware's dialog is teleported; the route guard keeps these rules local to production. */
:global(body:has(.is-generation) .el-dialog:has(.source-list)) { display:flex; flex-direction:column; max-height:calc(100dvh - 40px); margin-top:20px; border-radius:5px; padding:0; overflow:hidden; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-dialog__header) { flex:none; margin:0; padding:20px 24px; border-bottom:1px solid #dce4eb; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-dialog__title) { color:#172c45; font-size:20px; font-weight:700; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-dialog__body) { padding:22px 24px; overflow:auto; overscroll-behavior:contain; color:#59697b; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-dialog__footer) { flex:none; border-top:1px solid #dce4eb; padding:14px 24px; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-button) { min-height:44px; height:auto; border-radius:3px; font-size:12px; font-weight:600; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-button--primary) { background:#102339; border-color:#102339; color:#fff; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-button:focus-visible) { outline:3px solid #147d80; outline-offset:3px; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-dialog__headerbtn) { top:12px; right:12px; width:44px; height:44px; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-checkbox.is-checked .el-checkbox__label) { color:#176b70; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .source-list span) { color:#59697b; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-checkbox__input.is-checked .el-checkbox__inner) { background:#176b70; border-color:#176b70; }
:global(body:has(.is-generation) .el-dialog:has(.source-list) .el-checkbox__input.is-focus .el-checkbox__inner) { outline:2px solid #147d80; outline-offset:3px; }
.append-resource-hint { margin:0 0 18px; font-size:13px; line-height:1.7; }
.append-resource-options { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.append-resource-options :deep(.el-checkbox) { margin:0; min-height:48px; height:auto; padding:12px; border:1px solid var(--prod-line); border-radius:3px; background:#f6f9fb; }
.append-resource-options :deep(.el-checkbox.is-checked) { border-color:#77afa7; background:#e7f5f1; }
.append-resource-options :deep(.el-checkbox__label) { min-width:0; white-space:normal; font-size:12px; color:var(--prod-ink); }
.append-resource-existing { color:var(--prod-muted); font-size:10px; }
.append-claim-option { margin-top:20px; padding-top:16px; border-top:1px solid var(--prod-line); }
.append-claim-option :deep(.el-checkbox) { height:auto; min-height:44px; }
.append-claim-option p { margin:0; font-size:12px; line-height:1.8; }
.claim-report-header,.claim-report-heading,.claim-rate-panel,.claim-metric,.claim-section-heading,.claim-report-empty,.claim-report-actions,.claim-report-action-buttons { display:flex; align-items:center; gap:14px; }
.claim-report-header { justify-content:space-between; padding-right:28px; }
.claim-report-heading { align-items:flex-start; }
.claim-report-icon,.claim-metric-icon,.claim-empty-icon { display:grid; place-items:center; flex:none; width:38px; height:38px; background:#e5f2ef; color:var(--prod-accent); border-radius:3px; }
.claim-report-icon svg,.claim-metric-icon svg,.claim-empty-icon svg { width:21px; height:21px; }
.claim-report-eyebrow { font:10px/1.5 Consolas,monospace; color:var(--prod-accent); }
.claim-report-heading h3 { margin:5px 0; color:var(--prod-ink); font-size:20px; }
.claim-report-heading p { margin:0; color:var(--prod-muted); font-size:12px; line-height:1.7; }
.claim-report-status { display:flex; align-items:center; gap:6px; flex:none; color:var(--prod-accent); font-size:12px; }
.claim-report-status svg { width:18px; height:18px; }
.claim-report-status.is-warning { color:#935719; }
.claim-report-overview { display:grid; grid-template-columns:1fr 1fr; gap:20px; }
.claim-rate-panel { padding:18px; background:#f2f7f6; border-left:2px solid #77b5ad; }
.claim-rate-ring { display:grid; place-items:center; width:96px; height:96px; flex:none; border-radius:50%; background:conic-gradient(#176b70 var(--claim-rate,0%),#d8e7e2 0%); }
.claim-rate-ring-inner { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:4px; width:80px; height:80px; border-radius:50%; background:#f2f7f6; }
.claim-rate-ring-inner strong { color:var(--prod-accent); font:21px Consolas,monospace; }
.claim-rate-ring-inner span { font-size:10px; color:var(--prod-muted); }
.claim-rate-copy strong { display:block; margin:7px 0; color:var(--prod-ink); font-size:14px; }
.claim-rate-copy p { margin:0; font-size:12px; line-height:1.7; }
.claim-metrics-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.claim-metric { padding:12px; border:1px solid var(--prod-line); border-radius:3px; }
.claim-metric-icon { width:28px; height:28px; }
.claim-metric-icon svg { width:17px; height:17px; }
.claim-metric small { font-size:11px; }
.claim-metric strong { display:block; margin-top:3px; color:var(--prod-ink); font:22px Consolas,monospace; }
.claim-metric:is(.is-unverified,.is-conflict) .claim-metric-icon { background:#fff1e8; color:#935719; }
.claim-report-alert { margin-top:16px; }
.claim-issues-section { margin-top:22px; padding-top:18px; border-top:1px solid var(--prod-line); }
.claim-section-heading { justify-content:space-between; margin-bottom:14px; }
.claim-section-heading h4 { margin:4px 0 0; color:var(--prod-ink); font-size:16px; }
.claim-issue-count { font-size:12px; }
.claim-report-empty { padding:18px; background:#f2f7f6; }
.claim-report-empty strong { color:var(--prod-accent); }
.claim-report-empty p { margin:5px 0 0; font-size:12px; }
.claim-issue-list { display:grid; gap:12px; }
.claim-issue-card { display:flex; gap:12px; padding:16px; background:#faf7f4; border-left:2px solid #bf8a5b; }
.claim-issue-marker { color:#935719; font:12px Consolas,monospace; }
.claim-issue-content { min-width:0; }
.claim-issue-topline { display:flex; align-items:center; gap:10px; font-size:10px; }
.claim-issue-content p { margin:10px 0 7px; color:var(--prod-ink); font-size:13px; line-height:1.8; overflow-wrap:anywhere; }
.claim-issue-content small { font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
.claim-report-actions { justify-content:space-between; margin-top:20px; padding-top:18px; border-top:1px solid var(--prod-line); }
.claim-report-actions strong { display:block; color:var(--prod-ink); font-size:13px; }
.claim-report-actions span { display:block; margin-top:5px; font-size:11px; }
.claim-report-action-buttons { flex:none; gap:10px; }
@media (min-width:1100px) and (max-height:760px) {
  .generate-page { gap:10px; padding-top:10px; }
  .generate-page.is-fit-layout { gap:10px; padding-top:10px; }
  .task-selector { padding:12px 16px 10px; gap:12px; }
  .selector-field label { margin-bottom:5px; }
  .job-summary { margin:0 16px 12px; padding-top:10px; }
  .summary-item { padding-inline:9px; }
  .summary-item strong { margin-top:5px; }
  .summary-item .summary-count { font-size:18px; }
  .panel-title { min-height:56px; padding-bottom:8px; }
  .panel-title h3 { font-size:17px; margin-top:2px; }
  .resource-toolbar { padding:9px 0; gap:8px; }
  .process-scroll { padding-top:12px; }
  .resource-placeholder { padding:18px; }
  .production-footer { font-size:9px; }
}
@media (max-width:1099px) {
  .job-summary { grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px 0; }
  .summary-item:nth-child(4) { padding-left:0; border-left:0; }
  .studio-grid { grid-template-columns:1fr; gap:28px; }
  .resources-panel { padding-left:0; border-left:0; }
  .process-scroll { max-height:500px; overflow:auto; }
  .resource-stage { max-height:700px; overflow:auto; }
  .generate-page :deep(.generation-grid) { grid-template-columns:1fr; }
  .generate-page :deep(.workflow-snake) { min-height:400px; }
}
@media (max-width:720px) {
  .generate-page { padding-top:18px; gap:18px; }
  .task-selector { grid-template-columns:1fr; padding:18px; }
  .job-summary { grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px 0; margin:0 18px 18px; }
  .summary-item:nth-child(odd) { padding-left:0; border-left:0; }
  .summary-item:nth-child(4) { padding-left:12px; border-left:1px solid var(--prod-line); }
  .summary-item strong { font-size:12px; }
  .resource-panel-tools { justify-content:flex-start; width:100%; }
  .resource-toolbar { grid-template-columns:minmax(0,1fr); }
  .reader-toolbar-actions { justify-self:end; max-width:100%; }
  .resource-stage :deep(.reader-content),.resource-stage :deep(.reader-footer) { padding:18px; }
  .production-footer { flex-wrap:wrap; margin-top:-14px; font-size:9px; }
  .claim-report-header { flex-wrap:wrap; }
  .claim-report-overview { grid-template-columns:1fr; }
  .claim-report-actions { align-items:flex-start; flex-direction:column; }
  .claim-report-action-buttons { width:100%; }
  .claim-report-action-buttons :deep(.el-button) { flex:1; }
  .append-resource-options { grid-template-columns:1fr; }
  :global(body:has(.is-generation) .el-dialog:has(.source-list) .preference-grid) { grid-template-columns:minmax(0,1fr); }
  :deep(.production-dialog .el-dialog__header),:deep(.production-dialog .el-dialog__body),:deep(.production-dialog .el-dialog__footer) { padding:18px; }
}
@media (prefers-reduced-motion:reduce) {
  .generate-page *, .generate-page :deep(*) { animation:none !important; transition:none !important; scroll-behavior:auto !important; }
  :deep(.production-dialog *) { animation:none !important; transition:none !important; }
  :global(body:has(.is-generation) .el-dialog:has(.source-list) *) { animation:none !important; transition:none !important; }
}
</style>
