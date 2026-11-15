<template>
  <div ref="productionPage" class="generate-page" :class="{ 'is-courseware-workspace': isCoursewareWorkspace, 'is-fit-layout': isFitLayout }">
    <section class="control-panel workspace-filter-surface" aria-label="资源任务控制">
      <div class="task-selector">
        <div class="selector-field">
          <label>学习画像 <span>PROFILE</span></label>
          <el-select v-model="selectedLearnerId" aria-label="学习画像" filterable placeholder="选择学习画像" class="task-select workspace-glass-select" popper-class="refined-select-dropdown profile-select-dropdown" @change="handleProfileChange">
            <el-option v-for="item in profileOptions" :key="item.learner_id" :label="item.label" :value="item.learner_id">
              <div class="profile-option"><span>{{ item.label }}</span><el-tooltip content="删除学习画像" placement="right"><el-button class="profile-delete" text circle :icon="Delete" aria-label="删除学习画像" @mousedown.stop @click.stop="deleteProfile(item)" /></el-tooltip></div>
            </el-option>
          </el-select>
        </div>
        <div class="selector-field">
          <label>资源批次 <span>BATCH</span></label>
          <el-select v-model="selectedRunId" aria-label="资源批次" filterable :disabled="!taskItems.length" :placeholder="taskItems.length ? '选择要查看的生成任务' : '暂无资源批次'" class="task-select batch-select workspace-glass-select" popper-class="refined-select-dropdown generation-batch-dropdown" @change="handleTaskChange">
            <template #label="{ value }">
              <span v-if="batchOptionsById.get(value)" class="batch-selected">
                <span class="batch-selected-copy" :class="{ 'has-source': batchOptionsById.get(value).sourceTitle }">
                  <strong class="batch-option-title" :title="batchOptionsById.get(value).title">{{ batchOptionsById.get(value).title }}</strong>
                  <span v-if="batchOptionsById.get(value).sourceTitle" class="batch-selected-source" :title="batchOptionsById.get(value).sourceTitle">原资源：{{ batchOptionsById.get(value).sourceTitle }}</span>
                  <span v-else-if="batchOptionsById.get(value).compactTypes.length" class="batch-selected-types" :title="batchOptionsById.get(value).typeLabel">
                    <span v-for="type in batchOptionsById.get(value).compactTypes" :key="type" class="batch-resource-type">{{ type }}</span>
                  </span>
                </span>
                <span class="batch-badges">
                  <span v-if="batchOptionsById.get(value).tier" class="batch-tier">{{ batchOptionsById.get(value).tier }}</span>
                  <span class="batch-status" :class="batchOptionsById.get(value).tone">{{ batchOptionsById.get(value).status }}</span>
                </span>
              </span>
            </template>
            <el-option v-for="option in batchOptions" :key="option.id" :data-run-id="option.id" :label="option.search" :value="option.id">
              <div class="batch-option">
                <strong class="batch-option-title" :title="option.title">{{ option.title }}</strong>
                <span class="batch-badges">
                  <span v-if="option.tier" class="batch-tier">{{ option.tier }}</span>
                  <span class="batch-status" :class="option.tone">{{ option.status }}</span>
                </span>
                <span v-if="option.sourceTitle" class="batch-option-source" :title="option.sourceTitle">原资源：{{ option.sourceTitle }}</span>
                <span class="batch-option-meta">
                  <span v-for="type in option.types" :key="type" class="batch-resource-type">{{ type }}</span>
                  <span v-if="option.count" class="batch-published-count">{{ option.count }}</span>
                </span>
                <time v-if="option.date" class="batch-option-time">{{ option.date }}</time>
              </div>
            </el-option>
          </el-select>
        </div>
      </div>

      <div class="job-summary">
        <div class="summary-item"><span>任务编号 <small>RUN ID</small></span><strong class="summary-code">{{ shortRunId }}</strong></div>
        <div class="summary-item"><span>任务状态 <small>STATUS</small></span><strong class="production-status" :class="`is-${productionTone}`" role="status" aria-live="polite" aria-atomic="true"><el-icon aria-hidden="true"><component :is="productionIcon" /></el-icon>{{ selectedTask ? taskSummaryLabel(selectedTask) : (loadingJobs ? '加载中' : '未开始') }}</strong></div>
        <div class="summary-item"><span>创建时间 <small>CREATED</small></span><strong>{{ selectedTask ? formatDateTime(selectedTask.created_at) : '—' }}</strong></div>
        <div class="summary-item"><span>完成时间 <small>FINISHED</small></span><strong>{{ selectedTask?.finished_at ? formatDateTime(selectedTask.finished_at) : (selectedTask ? '等待完成' : '—') }}</strong></div>
      </div>
      <p v-if="selectedTask?.error_message" class="error-message"><el-icon><WarningFilled /></el-icon>{{ selectedTask.error_message }}</p>
      <p v-if="jobsError" class="error-message" role="alert">{{ jobsError }}<el-button @click="refreshJobs">重新加载</el-button></p>
      <p v-if="roundError" class="error-message" role="alert">{{ roundError }}</p>

    </section>

    <CoursewareGenerationWorkspace v-if="coursewareComposerVisible || selectedCoursewareJob" ref="coursewareWorkspace" embedded hide-controls :learner-id="selectedLearnerId" :active-run-id="selectedCoursewareJob?.run_id || ''" :source-resources="resources" @created="handleCoursewareCreated" @published="handleCoursewarePublished" @open-resource="openCoursewareResource">
      <template #task-actions>
        <div v-if="selectedCoursewareJob" class="task-actions" role="group" aria-label="课件任务操作">
          <el-button class="status-action status-action-refresh" :icon="Refresh" @click="coursewareWorkspace?.refreshCurrentJob()">刷新状态</el-button>
          <el-dropdown trigger="click" @command="handleAppendCommand">
            <el-button class="status-action status-action-append" :icon="Plus" :loading="appendingResources" :disabled="Boolean(roundDetail && !roundPrimaryJob)">追加资源<el-icon><ArrowDown /></el-icon></el-button>
            <template #dropdown><el-dropdown-menu><el-dropdown-item command="text" :disabled="!selectedJob">文本学习资源</el-dropdown-item><el-dropdown-item command="courseware" :disabled="!resources.length">HTML 互动课件</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
        </div>
      </template>
    </CoursewareGenerationWorkspace>

    <section v-if="selectedJob" class="studio-grid">
      <div class="process-panel">
        <div class="panel-title compact process-panel-heading"><div class="panel-heading-copy"><span class="panel-section-number">01</span><h3>生成协作轨迹</h3><span class="eyebrow">/ WORKFLOW</span><LearningRoundNodeSwitcher v-if="roundDetail" :detail="roundDetail" :selection="roundSelection" @select="selectRoundMember" /></div><span class="connection-state" :class="`is-${connectionStatus}`"><i aria-hidden="true" />{{ productionConnectionLabel }}</span></div>
        <div ref="processScroll" class="process-scroll" role="region" aria-label="生成协作轨迹" tabindex="0">
          <AgentVisualization
            v-if="selectedRunId" :key="selectedRunId" :run-id="selectedRunId"
            :trace="timelineState.steps" :child-runs="timelineState.childRuns"
            :legacy-partial="timelineState.replayCompleteness === 'legacy_partial'"
            :resource-executions="timelineState.resourceExecutions"
            :resource-events="timelineState.resourceEvents" :resource-versions="timelineState.resourceVersions" :resource-reviews="timelineState.resourceReviews"
            :requested-resource-types="selectedJob.request_payload?.resource_types || []"
            :job-status="selectedJob.job_status" :published-resources="resources"
            :review-enabled="selectedJob.request_payload?.include_review !== false"
            :retry-enabled="['completed', 'failed'].includes(selectedJob.job_status)"
            :claim-reports="claimReports" @open-child-run="openChildRun" @open-resource="openGeneratedResource"
            @open-claim-report="openClaimReport"
            @inspect-step="openAuditStep" @inspect-resource="openAuditResource"
            @resource-change="closeAudit" @select-resource="selectProcessResource"
          />
        </div>
      </div>
      <div class="resources-panel" v-module-motion="{ key: selectedRunId + ':' + selectedResourceId, ready: !loadingResources }">
        <div class="panel-title compact resource-panel-heading">
          <div class="panel-heading-copy"><span class="panel-section-number">02</span><h3>{{ selectedJob.job_status === 'completed' ? '任务资源' : '资源预览' }}</h3><span class="eyebrow">/ OUTPUT</span></div>
          <div class="resource-heading-actions">
            <div v-if="selectedResource" class="reader-toolbar-actions" role="group" aria-label="阅读工具">
              <div id="generation-reader-actions" class="reader-resource-actions" role="group" aria-label="资源文件操作" />
            </div>
            <div v-if="selectedResourceCanRetry || selectedResourceCanPublish" class="selected-resource-actions" role="group" aria-label="当前资源操作">
              <el-button v-if="selectedResourceCanRetry" class="status-action status-action-retry" :icon="RefreshRight" :loading="retryingResourceKey === activeProcessResource.key" :disabled="Boolean(retryingResourceKey)" title="从当前资源可恢复环节继续，最多修订一次正文" @click="retryResource(activeProcessResource)">重试</el-button>
              <el-button v-if="selectedResourceCanPublish" class="status-action status-action-publish" :icon="CircleCheck" :loading="claimDecisionLoading" title="查看当前版本的审核报告后确认发布" @click="openClaimReport(activeProcessResource.resource_id)">发布</el-button>
            </div>
            <div class="task-actions" role="group" aria-label="资源任务操作">
              <el-button v-if="selectedJob.job_status === 'running' || selectedJob.job_status === 'queued'" class="status-action status-action-refresh" :icon="Refresh" @click="refreshStatus">刷新状态</el-button>
              <el-button v-if="selectedJob.job_status === 'failed' && !resourceRetryAvailable" title="重新尝试原任务请求的全部资源" class="status-action status-action-retry" :icon="RefreshRight" @click="retryGeneration" :loading="retrying">重试</el-button>
              <el-dropdown trigger="click" @command="handleAppendCommand">
                <el-button class="status-action status-action-append" :icon="Plus" :loading="appendingResources" :disabled="Boolean(roundDetail && !roundPrimaryJob)">追加资源<el-icon><ArrowDown /></el-icon></el-button>
                <template #dropdown><el-dropdown-menu><el-dropdown-item command="text" :disabled="!selectedJob">文本学习资源</el-dropdown-item><el-dropdown-item command="courseware" :disabled="!resources.length">HTML 互动课件</el-dropdown-item></el-dropdown-menu></template>
              </el-dropdown>
            </div>
            <el-button v-if="selectedResource" class="learning-mode-action" :icon="Reading" @click="enterLearningMode">学习模式<el-icon class="mode-arrow"><ArrowRight /></el-icon></el-button>
          </div>
        </div>
        <div ref="resourceScroll" v-loading="loadingResources" class="resource-stage" role="region" aria-label="学习资源预览" :aria-busy="loadingResources" tabindex="0">
          <PreparationPanel
            v-if="!selectedResource"
            class="resource-placeholder"
            :class="{ 'is-failed': selectedJob.job_status === 'failed' }"
            compact
            eyebrow="RESOURCE OUTPUT"
            :pending="['queued', 'running'].includes(selectedJob.job_status)"
            :title="activeProcessResource ? `${activeProcessResource.resource_type}尚未发布` : selectedJob.job_status === 'failed' ? '本次生成暂未完成' : (selectedJob.job_status === 'completed' ? '等待资源同步' : '你的学习资源正在准备中')"
            :description="activeProcessResource ? '所选资源暂无可阅读的发布版本，可在左侧查看生成与校验进展。' : selectedJob.job_status === 'failed' ? '查看左侧协作记录了解原因，重新生成后可继续阅读。' : (selectedJob.job_status === 'completed' ? '任务已完成，暂未查到已发布内容。可刷新页面查看最新结果。' : '跟随左侧真实轨迹查看进展，审核发布后的材料会在这里展开。')"
            :steps="[
              { title: '生成学习材料', description: '根据学习画像与本轮目标组织内容。' },
              { title: '校验与发布', description: '通过相应审核与校验的资源才进入阅读区。' },
              { title: '阅读与专注学习', description: '材料就绪后，在左侧切换资源或进入学习模式。' },
            ]"
          >
            <template #context><div class="output-preparation-context"><span>当前任务</span><strong>{{ taskStatusLabel(selectedJob) }}</strong><span>以实际发布结果为准</span></div></template>
          </PreparationPanel>
          <ResourceViewer v-if="selectedResource" :resources="[selectedResource]">
            <template #header="{ resource, download }">
              <Teleport to="#generation-reader-actions">
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
      <p class="append-resource-hint">{{ roundDetail ? appendTargetLabel : '请选择要加入当前资源批次的资源类型。' }}</p>
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
      <div v-if="selectedAppendResourceTypes.some(type => type !== '实操指南')" class="append-claim-option">
        <el-checkbox v-model="appendIncludeClaimCheck" :disabled="!appendReviewEnabled">
          启用 Claim 审核
        </el-checkbox>
        <p>
          实操指南仅进行普通审核；其他资源可开启事实核验与定向纠错。
          <template v-if="!appendReviewEnabled">当前源任务未启用普通审核，不能单独开启 Claim 审核。</template>
        </p>
        <el-checkbox v-model="appendIncludeClaimEvidenceRetrieval" :disabled="!appendIncludeClaimCheck">
          证据不足时补检知识库
        </el-checkbox>
        <p>
          仅对首次缺少证据的事实陈述追加一次知识库检索并重新核对；关闭 Claim 审核时一并关闭。
        </p>
      </div>
      <template #footer>
        <el-button @click="appendDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="appendingResources" @click="confirmAppendResources">开始追加</el-button>
      </template>
    </el-dialog>

    <WorkflowDetailDialog v-model:visible="auditVisible" v-model:resource-id="auditResourceId" :loading="auditLoading" :error="auditError" :claims-error="auditClaimsError" :snapshot="auditSnapshot" :claims="auditClaims" :claim-retrieval="auditClaimRetrieval" :quality="auditQualityItem" :step="auditStep" :run-id="selectedRunId" :claim-enabled="selectedJob?.request_payload?.include_claim_check !== false" @refresh="refreshQualityAudit" />
    <el-dialog v-model="claimReportVisible" title="资源 Claim 审核报告" class="production-dialog claim-report-dialog" width="min(1040px, calc(100vw - 32px))">
      <template #header="{ titleId }">
        <div class="claim-report-header">
          <div class="claim-report-heading">
            <span class="claim-report-icon" aria-hidden="true"><DocumentChecked /></span>
            <div>
              <h3 :id="titleId">资源 Claim 审核报告</h3>
              <p>对照冻结来源核验已抽取的事实陈述。</p>
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
              <strong>{{ claimAuditSummary(selectedClaimReport, selectedJob?.request_payload?.include_claim_check !== false) }}</strong>
              <p>
                共检查 {{ selectedClaimReport.factual_claim_total || 0 }} 条事实 Claim，
                {{ selectedClaimReport.supported_claim_total || 0 }} 条获得证据支持。
                仅覆盖已抽取的事实，不代表全文正确率。
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
        <section class="claim-issues-section" aria-label="事实与证据">
          <el-alert v-if="selectedClaimReport.sourceError" :title="selectedClaimReport.sourceError" type="warning" :closable="false" />
          <ClaimEvidenceList class="claim-evidence-glass" :rows="selectedClaimReport.rows" fold-evidence />
        </section>

        <div v-if="selectedClaimReport.claim_publish_decision_pending" class="claim-report-actions">
          <div><strong>准备好决定资源去向了吗？</strong><span>你可以发布当前版本，或先保留资源继续处理。</span></div>
          <div class="claim-report-action-buttons">
            <el-button :loading="claimDecisionLoading" @click="decideClaimPublication(false)">暂不发布</el-button>
            <el-button type="primary" :loading="claimDecisionLoading" @click="decideClaimPublication(true)">发布</el-button>
          </div>
        </div>
      </template>
      <el-empty v-else description="暂无可展示的 Claim 审核数据，可关闭后重试。" />
    </el-dialog>
  </div>
</template>

<script setup>
import { currentProfileRating } from '../../utils/profileRating.js'
import { coursewareTaskSource } from './coursewareTaskPresentation.js'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Aim, ArrowDown, Download, ArrowRight, CircleCheck, Clock, Delete, DocumentChecked, Plus, Reading, Refresh, RefreshRight, WarningFilled } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { generateApi } from './api.js'
import { knowledgeApi } from '../knowledge/api.js'
import { profileApi } from '../learners/api.js'
import { resourceApi } from '../learning-documents/api.js'
import { runApi } from '../runs/queryApi.js'
import { coursewareApi } from '../courseware/api'
import { resourceLibraryApi } from '../resource-library/api'
import { useGenerationProgress } from './useGenerationProgress.js'
import { useGenerationResources } from './useGenerationResources.js'
import { useGenerationCommands } from './useGenerationCommands.js'
import { planRetryGeneration, planAppendResources, planRetryResource, executeGenerationPlan, canRetryResource } from './generationCommands.js'
import { useGenerationClaims } from './useGenerationClaims.js'
import { useGenerationAudit } from './useGenerationAudit.js'
import { resolvePublicationView } from './publicationPresentation.js'
import WorkflowDetailDialog from './WorkflowDetailDialog.vue'
import { useResourceQuality } from './useResourceQuality.js'
import ClaimEvidenceList from './ClaimEvidenceList.vue'
import { useProductionLayout } from './useProductionLayout.js'
import ResourceViewer from '../learning-documents/ResourceViewer.vue'
import PreparationPanel from '../../components/PreparationPanel.vue'
import PreparationWorkspace from '../../components/PreparationWorkspace.vue'
import CoursewareGenerationWorkspace from '../courseware/CoursewareGenerationWorkspace.vue'
import AgentVisualization from './AgentVisualization.vue'
import LearningRoundNodeSwitcher from './LearningRoundNodeSwitcher.vue'
import { useLearningRoundWorkspace } from './useLearningRoundWorkspace.js'
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
let statusRequestVersion = 0
let claimsRequestVersion = 0
let qualityRequestVersion = 0
let profileChangeVersion = 0
let taskChangeVersion = 0
let generationMounted = true
const appendDialogVisible = ref(false)
const selectedAppendResourceTypes = ref([])
const appendIncludeClaimCheck = ref(true)
const appendIncludeClaimEvidenceRetrieval = ref(false)
const coursewareComposerVisible = ref(false)
const coursewareWorkspace = ref(null)
const selectedRunId = ref(initialRunId)
const roundContextGeneration = ref(0)
const { retrying, retryingResourceKey, appendingResources, run: runGenerationCommand, dispose: disposeGenerationCommands } = useGenerationCommands({
  getContext: () => ({ learnerId: selectedLearnerId.value, runId: selectedRunId.value, roundContextGeneration: roundContextGeneration.value }),
  selectRun: runId => { selectedRunId.value = runId },
  refreshJobs: isCurrent => loadJobs(false, isCurrent),
  startRealtime: runId => startRealtime(runId),
})
const profiles = ref([])
const tracks = ref([])
const coursewareJobs = ref([])
const timelineState = ref(createInitialTimelineState())
const connectionStatus = ref('idle')
const claimReports = ref({})
const resourceQuality = ref({})
const claimReportVisible = ref(false)
const claimDecisionLoading = ref(false)
const selectedClaimReportId = ref('')




const activeProfile = computed(
  () => profiles.value.find((item) => item.learner_id === selectedLearnerId.value) || null
)
const profileOptions = computed(() =>
  profiles.value.map((profile) => ({
    ...profile,
    label: `${profileDisplayName(profile)} / ${resolveTrackName(profile.knowledge_base_id)} / ${currentProfileRating(profile) || '未分级'} / 创建于 ${profileCreatedAt(profile)}`,
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
const { detail: roundDetail, selection: roundSelection, primaryJob: roundPrimaryJob, error: roundError, select: selectRoundMemberImpl } = useLearningRoundWorkspace({
  learnerId: selectedLearnerId, selectedJob, selectedRunId, jobs, route, router,
  enabled: computed(() => !selectedRunId.value || Boolean(selectedJob.value)),
  activateRun: async runId => { selectedRunId.value = runId; await handleTaskChange() },
})
const appendTargetJob = computed(() => roundDetail.value ? roundPrimaryJob.value : selectedJob.value)
const appendTargetLabel = computed(() => {
  const primary = roundDetail.value?.members.find(member => member.role === 'primary')
  return primary ? `为主节点 ${primary.node_name || primary.node_id} 追加资源` : '追加资源'
})
function selectRoundMember(changes) {
  roundContextGeneration.value += 1
  return selectRoundMemberImpl(changes)
}


const {
  resources, nodeTiers, nodeNames, loadingResources, resourcesLoaded, selectedResourceId,
  loadNodeTiers, loadResourcesForSelectedJob, loadCoursewareSourceResources,
  invalidateResources, invalidateNodeTiers,
} = useGenerationResources({
  getContext: () => ({
    learnerId: selectedLearnerId.value, runId: selectedRunId.value,
    textRunId: selectedJob.value?.run_id,
    knowledgeBaseId: activeProfile.value?.knowledge_base_id,
    sourceBatchId: selectedCoursewareJob.value?.source_batch_id,
  }),
  isMounted: () => generationMounted,
  listNodes: knowledgeBaseId => knowledgeApi.listNodes(knowledgeBaseId),
  listRunResources: (learnerId, params) => resourceApi.listByLearner(learnerId, params),
  listLibraryResources: learnerId => resourceLibraryApi.listByLearner(learnerId),
  messages: ElMessage,
})
const batchOptions = computed(() => taskItems.value.map(presentBatchOption))
const batchOptionsById = computed(() => new Map(batchOptions.value.map(option => [option.id, option])))
const isCoursewareWorkspace = computed(() => coursewareComposerVisible.value || Boolean(selectedCoursewareJob.value))
const shortRunId = computed(() => (selectedTask.value?.run_id ? selectedTask.value.run_id.slice(0, 8).toUpperCase() : '-'))
// Courseware keeps its own task contract; text tasks read the authoritative
// publication summary instead of counting the currently loaded page.
const publicationView = computed(() => resolvePublicationView({
  publishSummary: selectedJob.value?.publish_summary || null,
  jobStatus: selectedJob.value?.job_status || '',
  fallbackPublished: selectedJob.value?.resource_progress_summary?.published || 0,
  fallbackTotal: selectedJob.value?.resource_progress_summary?.total || 0,
}))
const processResourceSelection = ref(null)
const activeProcessResource = computed(() => processResourceSelection.value?.runId === selectedRunId.value
  ? processResourceSelection.value.resource : null)
const selectedResourceCanRetry = computed(() => canRetryResource(selectedJob.value, activeProcessResource.value))
const selectedResourceCanPublish = computed(() => {
  const item = activeProcessResource.value
  return Boolean(item && !item.request_placeholder && item.publication_status !== 'published'
    && item.claim_publish_decision_pending && claimReports.value[item.resource_id]?.claim_publish_decision_pending)
})
const selectedResource = computed(() => {
  const resourceId = activeProcessResource.value
    ? activeProcessResource.value.readable_resource_id : selectedResourceId.value
  return resources.value.find(item => item.resource_id === resourceId) || null
})
function selectProcessResource(selection) {
  if (selection.runId !== selectedRunId.value) return
  processResourceSelection.value = selection
  if (selection.resource) selectedResourceId.value = selection.resource.readable_resource_id || ''
}
const selectedClaimReport = computed(() => claimReports.value[selectedClaimReportId.value] || null)
const auditQualityItem = computed(() => resourceQuality.value[auditResourceId.value] || null)
const {
  visible: auditVisible, loading: auditLoading, error: auditError, claimsError: auditClaimsError,
  snapshot: auditSnapshot, claims: auditClaims, step: auditStep, resourceId: auditResourceId,
  claimRetrieval: auditClaimRetrieval,
  refresh: refreshAudit, openStep: openAuditStep, openResource: openAuditResource, close: closeAudit,
} = useGenerationAudit({ selectedRunId, selectedLearnerId })
const resourceRetryAvailable = computed(() => (timelineState.value.resourceExecutions || []).some(item =>
  canRetryResource(selectedJob.value, item)))
const supportedAppendResourceTypes = ['讲义', '实操指南', '分阶测试题', '复习清单', '案例分析']
const appendResourceOptions = computed(() => {
  const primary = roundDetail.value?.members.find(member => member.role === 'primary')
  const initialScope = roundDetail.value?.stages.find(stage => stage.kind === 'initial')?.members.find(member => member.member_id === primary?.member_id)
  const existingTypes = new Set(initialScope?.resource_types || appendTargetJob.value?.request_payload?.resource_types || [])
  return supportedAppendResourceTypes.map((type) => ({
    type,
    alreadyIncluded: existingTypes.has(type),
  }))
})
const appendReviewEnabled = computed(() => appendTargetJob.value?.request_payload?.include_review !== false)

// Presentation only: task copy and viewport containment never alter workflow state.
const productionPage = ref(null)
const processScroll = ref(null)
const resourceScroll = ref(null)
const isFitLayout = ref(false)
const productionTone = computed(() => {
  const status = selectedTask.value?.job_status
  if (['failed', 'rejected_admission', 'release_blocked', 'quarantined', 'timed_out'].includes(status)) return 'error'
  if (publicationView.value.tone === 'warning' || ['published_with_warnings', 'cancelled'].includes(status)) return 'warning'
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

function taskSummaryLabel(task) {
  if (task?.job_status === 'completed' && task.task_kind !== 'interactive_courseware') {
    const view = publicationView.value
    if (view.hasSummary && view.completeness !== 'complete') return '待确认'
    if (view.hasSummary && view.published === 0) return '未发布'
    if (view.hasSummary && view.published < view.total) return '部分发布'
    return view.hasSummary ? '已发布' : '已完成'
  }
  if (task?.task_kind === 'interactive_courseware') return taskStatusLabel(task)
  return statusLabel(task?.job_status)
}

function taskStatusLabel(task) {
  if (task?.task_kind !== 'interactive_courseware') {
    const executionLabel = statusLabel(task?.job_status)
    const publication = task?.run_id && task.run_id === selectedJob.value?.run_id
      ? publicationView.value.label
      : resolvePublicationView({
        publishSummary: task?.publish_summary || null,
        jobStatus: task?.job_status || '',
        fallbackPublished: task?.resource_progress_summary?.published || 0,
        fallbackTotal: task?.resource_progress_summary?.total || 0,
      }).label
    // Keep the real execution result and append the publication fact separately;
    // one never replaces the other.
    return publication ? `${executionLabel} · ${publication}` : executionLabel
  }
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
  const resourceId = item?.readable_resource_id || item?.resource_id
  if (!resourceId || !selectedJob.value) return
  if (!resources.value.some((resource) => resource.resource_id === resourceId)) {
    await loadResourcesForSelectedJob()
  }
  if (resources.value.some((resource) => resource.resource_id === resourceId)) {
    selectedResourceId.value = resourceId
  }
}

function profileCreatedAt(profile) {
  return profile?.created_at ? formatDateTime(profile.created_at) : '时间未知'
}

function presentBatchOption(task) {
  const courseware = task.task_kind === 'interactive_courseware'
  const source = coursewareTaskSource(task, nodeNames.value, nodeTiers.value)
  const request = task.request_payload || {}
  const nodeIds = [
    request.constraints?.target_skill_node_ids,
    request.target_skill_nodes,
    task.focus_snapshot?.adopted_node_ids,
  ].find(ids => Array.isArray(ids) && ids.length) || []
  const nodeLabels = [...new Set(nodeIds.map(id => nodeNames.value[id] || id))]
  const title = courseware ? source.title : (nodeLabels.join('、') || task.topic || request.topic || '学习资源')
  const catalogTiers = nodeIds.map(id => nodeTiers.value[id])
  const tierNumber = request.constraints?.target_tier
    ?? (catalogTiers.length && catalogTiers.every(tier => tier === catalogTiers[0]) ? catalogTiers[0] : null)
  const displayTier = courseware ? source.tier : tierNumber
  const tier = Number.isInteger(displayTier) && displayTier > 0 ? `第 ${displayTier} 阶` : ''
  const types = [...new Set((Array.isArray(request.resource_types) && request.resource_types.length ? request.resource_types
    : (task.resource_progress_summary?.items || []).map(item => item.resource_type)).filter(Boolean))]
  const view = resolvePublicationView({
    publishSummary: task.publish_summary || null,
    jobStatus: task.job_status || '',
    fallbackPublished: task.resource_progress_summary?.published || 0,
    fallbackTotal: task.resource_progress_summary?.total || 0,
  })
  let status = courseware ? taskStatusLabel(task) : statusLabel(task.job_status)
  if (!courseware && task.job_status === 'completed' && view.hasSummary) {
    if (view.completeness !== 'complete') status = '待确认'
    else if (view.published === 0) status = '未发布'
    else status = view.published < view.total ? '部分发布' : '已发布'
  }
  const tone = status === '已发布' ? 'is-published'
    : ['部分发布', '待确认', '生成中', '已发布（有警告）'].includes(status) ? 'is-pending'
      : status === '失败' ? 'is-failed' : ''
  const typeLabel = courseware ? '互动课件' : (types.join('、') || '学习资源')
  const displayTypes = courseware ? ['互动课件'] : (types.length ? types : ['学习资源'])
  const compactTypes = displayTypes.length > 2 ? [displayTypes[0], `另 ${displayTypes.length - 1} 类`] : displayTypes
  const count = !courseware && view.hasSummary && view.completeness === 'complete' && view.published > 0
    ? `已发布 ${view.published} 份` : ''
  const timestamp = task.finished_at || (courseware && task.updated_at) || task.created_at
  const date = timestamp ? formatDateTime(timestamp).replace(/\//g, '-') : ''
  return {
    id: task.run_id, title, sourceTitle: courseware ? source.sourceTitle : '', tier, status, tone, date, count, typeLabel,
    types: displayTypes, compactTypes: compactTypes.filter(type => type !== title),
    search: [title, ...(courseware ? [source.sourceTitle, ...source.nodeIds] : nodeIds), tier, typeLabel, status, date, timestamp, task.run_id].filter(Boolean).join(' '),
  }
}

/** True when the accepted job already has readable published output. */
function jobHasPublication(job) {
  const published = job?.publish_summary?.published ?? job?.resource_progress_summary?.published
  return Number(published || 0) > 0
}

function persistSelectedJob() {
  localStorage.setItem('current_generation_run_id', selectedTask.value?.run_id || '')
  localStorage.setItem('current_generation_status', selectedTask.value?.job_status || '')
}

const { stopPolling, closeRealtime, cancelPublishedResourceRefresh, startRealtime, startPolling } = useGenerationProgress({
  selectedRunId, selectedJob, timelineState, connectionStatus,
  isMounted: () => generationMounted,
  refreshStatus: (...args) => refreshStatus(...args),
  loadClaimReports: (...args) => loadClaimReports(...args),
  loadResourceQuality: (...args) => loadResourceQuality(...args),
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

async function loadJobs(preferDefault = false, commandIsCurrent = () => true) {
  if (!generationMounted || !commandIsCurrent()) return false
  const version = ++jobsRequestVersion
  const learnerId = selectedLearnerId.value
  const ownsLoading = () => generationMounted && version === jobsRequestVersion
  const isCurrent = () => ownsLoading() && learnerId === selectedLearnerId.value && commandIsCurrent()
  jobsError.value = ''
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
      return isCurrent()
    }

    if (
      preferDefault ||
      !selectedRunId.value ||
      !taskItems.value.some((item) => item.run_id === selectedRunId.value)
    ) {
      selectedRunId.value = pickDefaultRunId(taskItems.value)
    }

    if (!isCurrent()) return false
    persistSelectedJob()
    return true
  } catch (error) {
    if (!isCurrent()) return false
    jobsError.value = error?.response?.data?.message || '任务列表加载失败'
    ElMessage.error(jobsError.value)
    return false
  } finally {
    if (ownsLoading()) loadingJobs.value = false
  }
}

const {
  loadClaimReports, openClaimReport, claimPassRateLabel, claimAuditSummary,
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

const { loadResourceQuality } = useResourceQuality({
  selectedRunId, selectedLearnerId, resourceQuality,
  isMounted: () => generationMounted,
  requestVersion: () => qualityRequestVersion,
  nextRequestVersion: () => ++qualityRequestVersion,
})















async function refreshQualityAudit() {
  const runId = selectedRunId.value
  await refreshAudit()
  if (runId === selectedRunId.value) await loadResourceQuality(runId)
}

async function refreshStatus({ forceResources = false, forceClaims = false } = {}) {
  if (!selectedJob.value?.run_id) return
  const learnerId = selectedLearnerId.value
  const runId = selectedJob.value.run_id
  const version = ++statusRequestVersion
  const jobsVersion = jobsRequestVersion
  const requestWatermark = timelineState.value.lastSequence
  const isCurrent = () => generationMounted && learnerId === selectedLearnerId.value && runId === selectedJob.value?.run_id
    && version === statusRequestVersion && jobsVersion === jobsRequestVersion
  try {
    const res = await generateApi.getJobStatus(runId)
    if (!isCurrent()) return
    const nextJob = res.data
    if (nextJob.run_id !== runId) return
    let resourceOptions = {}
    const items = nextJob.resource_progress_summary?.items || []
    if (items.some(item => !item.updated_at) && timelineState.value.resourceExecutions.length) {
      // Legacy projections lack an execution timestamp. Bound their authority
      // by events observed before this request, never by an invented infinity.
      const timeline = await runApi.timeline(runId, { limit: 1 })
      if (!isCurrent()) return
      if (timeline.data.run?.run_id && timeline.data.run.run_id !== runId) return
      resourceOptions = { authoritative: true,
        watermark: Math.min(requestWatermark, Number(timeline.data.run?.last_event_sequence || 0)) }
    }
    jobs.value = jobs.value.map((item) => (item.run_id === nextJob.run_id ? nextJob : item))
    timelineState.value = applyRunSnapshot(timelineState.value, nextJob, resourceOptions)
    persistSelectedJob()
    if (!isCurrent()) return

    const publishedCount = Number(
      nextJob.publish_summary?.published ?? nextJob.resource_progress_summary?.published ?? 0,
    ) || 0
    // A terminal job must stop ordinary polling whether or not it published
    // anything; resource and Claim reads are decided independently below so a
    // failed run with readable output still refreshes them.
    if (nextJob.job_status === 'completed' || nextJob.job_status === 'failed') stopPolling()
    const readResources = forceResources || nextJob.job_status === 'completed' || publishedCount > 0
    const readClaims = forceClaims || nextJob.job_status === 'completed'
    if (readResources) {
      await loadResourcesForSelectedJob()
      if (!isCurrent()) return
    }
    if (readClaims) {
      await loadClaimReports(nextJob.run_id)
      if (!isCurrent()) return
    }
    await loadResourceQuality(nextJob.run_id)
    if (!isCurrent()) return
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
  const runId = selectedRunId.value
  const taskVersion = taskChangeVersion
  const isCurrent = () => generationMounted && version === jobsRequestVersion && taskVersion === taskChangeVersion && runId === selectedRunId.value
  if (selectedJob.value?.job_status === 'completed' || jobHasPublication(selectedJob.value)) {
    await loadResourcesForSelectedJob()
  }
  if (!isCurrent()) return
  await loadResourceQuality(runId)
  if (!isCurrent()) return
  await startRealtime(runId)
}

async function handleTaskChange() {
  const learnerId = selectedLearnerId.value
  const runId = selectedRunId.value
  const version = ++taskChangeVersion
  invalidateResources(); ++claimsRequestVersion
  const isCurrent = () => generationMounted && version === taskChangeVersion && learnerId === selectedLearnerId.value && runId === selectedRunId.value
  closeRealtime()
  persistSelectedJob()
  stopPolling()
  timelineState.value = createInitialTimelineState()
  resources.value = []
  resourcesLoaded.value = false
  selectedResourceId.value = ''

  // The batch picker is the single task entry. Persist the job's own binding
  // so reloading a correction does not reopen the previously selected Run.
  const binding = selectedJob.value?.round_binding
  const query = { ...route.query, learnerId, runId: runId || undefined,
    roundId: binding?.round_id, memberId: binding?.member_id, stageId: binding?.stage_id }
  if (['learnerId', 'runId', 'roundId', 'memberId', 'stageId'].some(key => (route.query[key] || '') !== (query[key] || ''))) {
    await router.replace({ query })
    if (!isCurrent()) return
  }

  if (selectedCoursewareJob.value) {
    closeRealtime()
    if (!selectedCoursewareJob.value.source_batch_id) void loadNodeTiers()
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
  if (selectedJob.value.job_status === 'completed' || jobHasPublication(selectedJob.value)) {
    await loadResourcesForSelectedJob()
    if (!isCurrent()) return
    await loadClaimReports(selectedRunId.value)
    if (!isCurrent()) return
  } else {
    resourcesLoaded.value = true
  }
  if (!isCurrent()) return
  await loadResourceQuality(runId)
  if (!isCurrent()) return
  await startRealtime(runId)
}

async function handleProfileChange() {
  const version = ++profileChangeVersion
  invalidateResources(); ++claimsRequestVersion; invalidateNodeTiers(); ++taskChangeVersion
  syncProfileContext()
  jobs.value = []; coursewareJobs.value = []; nodeTiers.value = {}; claimReports.value = {}; resourceQuality.value = {}
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
  if (selectedCoursewareJob.value) { await handleTaskChange(); return }
  const runId = selectedRunId.value
  const taskVersion = taskChangeVersion
  const isCurrent = () => generationMounted && version === profileChangeVersion && taskVersion === taskChangeVersion && runId === selectedRunId.value
  if (selectedJob.value?.job_status === 'completed' || jobHasPublication(selectedJob.value)) {
    await loadResourcesForSelectedJob()
  } else {
    resourcesLoaded.value = true
    if (taskItems.value.length) void loadNodeTiers()
  }
  if (!isCurrent()) return
  await loadResourceQuality(runId)
  if (!isCurrent()) return
  await startRealtime(runId)
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
  const plan = planRetryGeneration(failedJob)
  if (!plan) {
    ElMessage.warning('该任务缺少原始生成参数，无法保证重试内容一致')
    return
  }

  return runGenerationCommand({
    channel: 'retry',
    beforeSubmit: () => {
      resources.value = []
      resourcesLoaded.value = false
      selectedResourceId.value = ''
      stopPolling()
    },
    execute: () => executeGenerationPlan(plan, generateApi.continueBatch),
    succeeded: () => ElMessage.success('已在原资源批次中重新发起生成任务'),
    failed: error => {
      console.error(error)
      ElMessage.error(apiErrorMessage(error, '重新生成失败'))
    },
  })
}

function appendResources() {
  const sourceJob = appendTargetJob.value
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
  appendIncludeClaimEvidenceRetrieval.value = appendIncludeClaimCheck.value
    && sourceJob.request_payload?.include_claim_evidence_retrieval === true
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

async function handleCoursewarePublished() {
  await loadJobs(false)
  ElMessage.success('HTML 互动课件已追加到当前资源批次。')
}

async function openCoursewareResource(coursewareJob) {
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

function applyAcceptedGeneration(runId) {
  localStorage.setItem('current_generation_run_id', runId)
  resources.value = []
  resourcesLoaded.value = false
  selectedResourceId.value = ''
}

async function confirmAppendResources() {
  const sourceJob = appendTargetJob.value
  const resourceTypes = [...new Set(selectedAppendResourceTypes.value)]
  const plan = planAppendResources(
    sourceJob, resourceTypes, appendIncludeClaimCheck.value,
    appendIncludeClaimEvidenceRetrieval.value,
  )
  if (!plan) {
    ElMessage.warning('请至少选择一种要追加的资源类型')
    return
  }
  return runGenerationCommand({
    channel: 'append',
    execute: () => executeGenerationPlan(plan, generateApi.continueBatch),
    accepted: applyAcceptedGeneration,
    succeeded: () => {
      appendDialogVisible.value = false
      ElMessage.success(`已追加：${resourceTypes.join('、')}`)
    },
    failed: error => {
      console.error(error)
      ElMessage.error(apiErrorMessage(error, '追加资源失败'))
    },
  })
}

async function retryResource(item) {
  const sourceJob = selectedJob.value
  const plan = planRetryResource(sourceJob, item)
  if (!plan) {
    ElMessage.warning('该资源缺少可恢复上下文，无法重试；请检查过程详情')
    return
  }

  const key = item.key || `${item.resource_spec_id}:${item.representation || 'text'}`
  return runGenerationCommand({
    channel: 'resource', busyValue: key,
    execute: () => executeGenerationPlan(plan, generateApi.continueBatch, generateApi.retryResourceRepresentation),
    accepted: applyAcceptedGeneration,
    succeeded: () => ElMessage.success(`已为${item.resource_type}创建重试任务`),
    failed: error => {
      console.error(error)
      ElMessage.error(apiErrorMessage(error, '重新生成资源失败'))
    },
  })
}

onMounted(async () => {
  try {
    await loadProfiles()
    const version = profileChangeVersion
    if (!generationMounted || !await loadJobs(true) || version !== profileChangeVersion) return
    if (selectedCoursewareJob.value) { await handleTaskChange(); return }
    const runId = selectedRunId.value
    const taskVersion = taskChangeVersion
    const isCurrent = () => generationMounted && version === profileChangeVersion && taskVersion === taskChangeVersion && runId === selectedRunId.value
    if (selectedJob.value?.job_status === 'completed' || jobHasPublication(selectedJob.value)) {
      await loadResourcesForSelectedJob()
    } else {
      resourcesLoaded.value = true
      if (taskItems.value.length) void loadNodeTiers()
    }
    if (!isCurrent()) return
    await loadResourceQuality(runId)
    if (!isCurrent()) return
    await startRealtime(runId)
  } catch (error) {
    if (generationMounted) jobsError.value = error?.response?.data?.message || '学习画像加载失败，请刷新页面重试'
  }
})

onBeforeUnmount(() => {
  generationMounted = false
  disposeGenerationCommands()
  ++jobsRequestVersion; invalidateResources(); invalidateNodeTiers(); ++claimsRequestVersion; ++profileChangeVersion; ++taskChangeVersion
  cancelPublishedResourceRefresh()
  closeRealtime()
  stopPolling()
})
</script>

<style scoped>
.generate-page { --prod-ink:#172c45; --prod-muted:#59697b; --prod-line:#dce4eb; --prod-navy:#102339; --prod-accent:#176b70; --prod-mint:#9cf2e0; display:flex; flex-direction:column; gap:14px; min-width:0; padding-top:16px; color:var(--prod-ink); }
.generate-page * { box-sizing:border-box; }
.eyebrow { color:var(--prod-muted); font:10px/1.5 Consolas,monospace; letter-spacing:.04em; }
.control-panel { display:grid; grid-template-columns:minmax(0,1fr); overflow:hidden; }
.task-selector { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; padding:14px 20px 12px; }
.selector-field { min-width:0; }
.selector-field label { display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; gap:8px; color:var(--prod-muted); font-size:12px; }
.selector-field label span { font:9px Consolas,monospace; }
.profile-option { display:flex; align-items:center; justify-content:space-between; gap:12px; min-width:0; }
.profile-option > span { min-width:0; white-space:normal; overflow-wrap:anywhere; }
.profile-delete { width:30px; height:30px; flex:none; margin:0; color:#a93434; }
.job-summary { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0; margin:0 20px 14px; padding-top:12px; border-top:1px solid var(--prod-line); }
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
.panel-heading-copy { display:flex; align-items:baseline; gap:8px; min-width:0; white-space:nowrap; }
.process-panel-heading { flex-wrap:wrap; gap:6px 10px; padding-block:8px; }
.process-panel-heading .panel-heading-copy { flex-wrap:wrap; align-items:center; gap:6px; white-space:normal; }
.process-panel-heading h3 { white-space:nowrap; }
.panel-section-number { flex:none; color:var(--prod-accent); font:12px/1.5 Consolas,monospace; }
:deep(.production-dialog .el-button), .generate-page :deep(.el-button) { min-height:44px; height:auto; border-radius:3px; font-size:12px; font-weight:600; transition:background .16s ease,border-color .16s ease,color .16s ease; }
.generate-page :deep(.el-button + .el-button) { margin-left:0; }
.generate-page :deep(.el-button > span) { gap:7px; white-space:normal; line-height:1.5; }
.status-action { margin:0; border-color:#cdd9e2; background:#fff; color:var(--prod-ink); padding:10px 12px; }
.status-action:hover { border-color:#7b9baf; background:#f1f6f8; color:var(--prod-accent); }
.status-action-append,.primary-action,.learning-mode-action { background:var(--prod-navy); border-color:var(--prod-navy); color:#fff; }
.status-action-append:hover,.primary-action:hover,.learning-mode-action:hover { background:#1d3d56; border-color:#1d3d56; color:var(--prod-mint); }
.status-action-retry {
  min-height:44px;
  padding:10px 16px;
  border:1px solid #a9c6d7;
  border-radius:10px;
  color:#245a80;
  background:linear-gradient(145deg,#ffffffed,#e0eefbcf);
  box-shadow:inset 0 1px #fff,0 3px 8px #254a6426;
}
.status-action-retry:not(.is-disabled,.is-loading):hover { border-color:#799fbe; color:#19466b; background:linear-gradient(145deg,#f7fbff,#cfe4f8); }
.status-action-retry:focus-visible { outline:2px solid #3977a5; outline-offset:3px; }
.status-action-retry.is-disabled { opacity:.65; box-shadow:inset 0 1px #fff; }
.studio-grid { display:grid; grid-template-columns:minmax(280px,.3fr) minmax(0,.7fr); gap:20px; min-width:0; }
.process-panel,.resources-panel { min-width:0; display:flex; flex-direction:column; }
.resources-panel { border-left:1px solid var(--prod-line); padding-left:20px; }
.panel-title { display:flex; flex:none; min-height:40px; align-items:center; justify-content:space-between; gap:8px; padding:0 0 8px; border-bottom:1px solid var(--prod-line); }
.panel-title h3 { margin:0; font-size:18px; line-height:1.4; }
.connection-state { display:flex; align-items:center; gap:6px; color:var(--prod-muted); font-size:11px; }
.connection-state i { width:6px; height:6px; flex:none; border-radius:50%; background:#64748b; }
.connection-state.is-live { color:#176b70; }
.connection-state.is-live i { background:#176b70; }
.connection-state:is(.is-error,.is-fallback) { color:#935719; }
.connection-state:is(.is-error,.is-fallback) i { background:#935719; }
.process-scroll { padding:8px 8px 0 0; min-width:0; }
.process-scroll :deep(.workflow-timeline) { border:0; border-radius:0; box-shadow:none; background:transparent; }
.process-scroll :deep(.execution-graph) { margin:0 3px 8px 4px; }
.process-scroll :deep(.el-card__header) { display:none; }
.process-scroll :deep(.el-card__body) { padding:0; }
.resource-panel-heading { gap:12px; align-items:center; flex-wrap:wrap; }
.resource-heading-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:12px; min-width:0; max-width:100%; margin-left:auto; }
.resource-heading-actions .task-actions { flex-wrap:wrap; }
.selected-resource-actions { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.selected-resource-actions .status-action-publish { border-color:#167781; background:#167781; color:#fff; }
.selected-resource-actions .status-action-publish:hover { border-color:#105f67; background:#105f67; }
.resource-panel-heading > .task-actions { flex:0 0 auto; justify-content:flex-end; margin-left:auto; }
.resource-panel-heading :deep(.el-button) { margin:0; min-height:44px; padding:7px 11px; }
.resource-panel-heading .status-action-append { width:auto; }
@media (min-width:1100px) {
  .studio-grid > :is(.process-panel,.resources-panel) > .panel-title { min-height:53px; }
}
.reader-toolbar-actions,.reader-resource-actions { display:flex; min-width:0; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.status-action-append,.learning-mode-action { width:112px; flex:none; padding:10px; }
.resource-panel-heading :deep(.el-button:is(.toolbar-download-action,.learning-mode-action,.status-action-append)) {
  --action-top:#fbfdff;
  --action-bottom:#edf3f8;
  --action-edge:#c8d8e5;
  --action-ink:#274963;
  border-radius:9px;
  border-color:var(--action-edge);
  background:linear-gradient(155deg,var(--action-top),var(--action-bottom));
  color:var(--action-ink);
  box-shadow:inset 0 1px 0 #fff,0 3px 7px -5px rgb(30 68 90 / 32%);
}
.resource-panel-heading :deep(.el-button.learning-mode-action) {
  --action-top:#effafa;
  --action-bottom:#d5edee;
  --action-edge:#a3ced1;
  --action-ink:#175861;
}
.resource-panel-heading :deep(.el-button:is(.toolbar-download-action,.learning-mode-action,.status-action-append):not(.is-disabled):hover) {
  border-color:color-mix(in srgb,var(--action-edge) 65%,var(--action-ink));
  background:linear-gradient(155deg,var(--action-top),color-mix(in srgb,var(--action-bottom) 91%,var(--action-ink)));
  box-shadow:inset 0 1px 0 #fff,0 4px 9px -5px rgb(30 68 90 / 42%);
}
.resource-panel-heading :deep(.el-button:is(.toolbar-download-action,.learning-mode-action,.status-action-append).is-disabled) {
  opacity:.6;
  box-shadow:none;
}
.resource-stage { min-width:0; background:linear-gradient(#fff,#fff) padding-box,linear-gradient(112deg,color-mix(in srgb,var(--prod-accent) 44%,#fff),color-mix(in srgb,var(--prod-line) 72%,#fff) 47%,color-mix(in srgb,var(--prod-accent) 36%,#fff)) border-box; border:1px solid transparent; border-radius:0; box-shadow:inset 0 -1px 1px rgb(111 142 167 / 15%),0 3px 5px -4px rgb(33 64 86 / 24%),0 12px 24px -17px rgb(33 64 86 / 30%); }
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
.empty-studio :deep(.preparation-workspace::before) { content:none; }
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
:deep(.production-dialog.claim-report-dialog) {
  --claim-glass:linear-gradient(145deg,#fff,#edf6fc);
  --claim-glass-edge:#c5d9e7;
  --claim-glass-shadow:inset 0 1px 0 #fff, 0 3px 7px rgb(36 76 110 / 9%), 0 12px 22px -14px rgb(36 76 110 / 35%);
  border-radius:20px;
  border-color:var(--claim-glass-edge);
  background:linear-gradient(155deg,#fff 12%,#f5faff 75%,#edf6fb);
  box-shadow:0 24px 70px rgb(17 47 72 / 27%);
}
:deep(.claim-report-dialog .el-dialog__header) {
  border-color:var(--claim-glass-edge);
  background:radial-gradient(ellipse at 95% 0%,#d9eff4,transparent 62%),linear-gradient(120deg,#fff,#f0f7fc);
}
:deep(.claim-report-dialog .el-dialog__body) { min-height:0; }
:deep(.claim-report-dialog .el-dialog__headerbtn:hover) {
  border-radius:12px;
  background:#e6f1f8;
}
.claim-report-heading { min-width:0; }
.claim-report-icon,.claim-metric-icon,.claim-empty-icon { display:grid; place-items:center; flex:none; width:44px; height:44px; background:var(--claim-glass); color:var(--prod-accent); border:1px solid var(--claim-glass-edge); border-radius:13px; box-shadow:var(--claim-glass-shadow); }
.claim-report-icon svg,.claim-metric-icon svg,.claim-empty-icon svg { width:21px; height:21px; }
.claim-report-heading h3 { margin:5px 0; color:var(--prod-ink); font-size:20px; }
.claim-report-heading p { margin:0; color:var(--prod-muted); font-size:12px; line-height:1.7; }
.claim-report-status { display:flex; align-items:center; gap:6px; flex:none; padding:6px 12px; border:1px solid var(--claim-glass-edge); border-radius:999px; background:var(--claim-glass); box-shadow:var(--claim-glass-shadow); color:var(--prod-accent); font-size:12px; }
.claim-report-status svg { width:18px; height:18px; }
.claim-report-status.is-warning { color:#935719; }
.claim-report-overview { display:grid; grid-template-columns:minmax(0,1fr); gap:14px; }
.claim-rate-panel { padding:16px; }
.claim-rate-panel,.claim-metric { border:1px solid var(--claim-glass-edge); border-radius:14px; background:var(--claim-glass); box-shadow:var(--claim-glass-shadow); }
.claim-rate-ring { display:grid; place-items:center; width:96px; height:96px; flex:none; border-radius:50%; background:conic-gradient(#176b70 var(--claim-rate,0%),#d8e7e2 0%); }
.claim-rate-ring-inner { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:4px; width:80px; height:80px; border-radius:50%; background:var(--claim-glass); box-shadow:inset 0 2px 8px rgb(31 92 117 / 12%); }
.claim-rate-ring-inner strong { color:var(--prod-accent); font:21px Consolas,monospace; }
.claim-rate-ring-inner span { font-size:10px; color:var(--prod-muted); }
.claim-rate-copy strong { display:block; margin:7px 0; color:var(--prod-ink); font-size:18px; }
.claim-rate-copy p { margin:0; font-size:15px; line-height:1.7; }
.claim-metrics-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.claim-metric { padding:12px; }
.claim-metric-icon { width:28px; height:28px; }
.claim-metric-icon svg { width:17px; height:17px; }
.claim-metric small { font-size:13px; }
.claim-metric strong { display:block; margin-top:3px; color:var(--prod-ink); font:26px Consolas,monospace; }
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
  .panel-title { min-height:36px; padding-bottom:6px; }
  .panel-title h3 { font-size:17px; }
  .process-scroll { padding-top:12px; }
  .resource-placeholder { padding:18px; }
  .production-footer { font-size:9px; }
}
@media (max-width:1099px) {
  .job-summary { grid-template-columns:repeat(4,minmax(0,1fr)); gap:18px 0; }
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
  .resource-panel-heading { flex-wrap:wrap; }
  .resource-panel-heading > .task-actions { max-width:100%; }
  .reader-toolbar-actions { max-width:100%; }
  .resource-stage :deep(.reader-content),.resource-stage :deep(.reader-footer) { padding:18px; }
  .production-footer { flex-wrap:wrap; margin-top:-14px; font-size:9px; }
  .claim-report-header { flex-wrap:wrap; }
  .claim-rate-panel { flex-wrap:wrap; }
  .claim-metrics-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .claim-metric { gap:8px; padding:10px; }
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

<style scoped>
.batch-select :deep(.el-select__placeholder > .batch-selected) {
  display:flex;
  align-items:center;
  justify-content:space-between;
  min-width:0;
  gap:12px;
}
.batch-selected-copy {
  display:flex;
  align-items:center;
  gap:clamp(10px,1vw,16px);
  min-width:0;
}
.batch-selected-copy .batch-option-title { flex:0 1 auto; }
.batch-selected-copy.has-source { flex:1; flex-direction:column; align-items:flex-start; gap:2px; }
.batch-selected-source { max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#51697b; font-size:12px; }
.batch-option-source { grid-column:1 / -1; min-width:0; overflow-wrap:anywhere; color:#51697b; font-size:12px; }
.batch-selected-types {
  flex:0 1 auto;
  min-width:0;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  color:#38586d;
  font-size:11px;
}
.batch-resource-type {
  display:inline-block;
  padding:1px 8px;
  border:1px solid #b9cfdc;
  border-radius:5px;
  background:linear-gradient(180deg,#fff,#f1f7fa);
  box-shadow:inset 0 1px 0 #fff,0 1px 2px rgb(41 77 102 / 9%);
  color:#2e5268;
  font-size:11px;
  line-height:1.5;
}
.batch-selected-types .batch-resource-type + .batch-resource-type {
  margin-inline-start:6px;
}
.batch-status,.batch-tier {
  flex:none;
  border-radius:5px;
  padding:2px 6px;
  background:#edf2f7;
  color:#486078;
  font-size:11px;
  line-height:1.5;
}
.batch-status.is-published { background:#e2f3ed; color:#195c4e; }
.batch-status.is-pending { background:#fff2df; color:#855018; }
.batch-status.is-failed { background:#fae9e8; color:#8f382f; }
.batch-option {
  display:grid;
  grid-template-columns:minmax(0,1fr) auto;
  grid-template-rows:minmax(21px,auto) minmax(18px,auto);
  align-items:center;
  gap:4px 14px;
  min-width:0;
  font-weight:400;
}
.batch-badges { display:flex; flex:none; align-items:center; justify-content:flex-end; gap:6px; white-space:nowrap; }
.batch-option-title {
  min-width:0;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}
.batch-option-title { color:#19394e; font-weight:650; }
.batch-option > .batch-badges,.batch-option-time { justify-self:end; white-space:nowrap; }
.batch-option-meta { display:flex; flex-wrap:wrap; align-items:center; gap:4px 5px; min-width:0; }
.batch-published-count,.batch-option-time { color:#51697b; font-size:12px; }
.batch-published-count { margin-inline-start:4px; }
.batch-option-time { font-variant-numeric:tabular-nums; }
:global(.el-select__popper.generation-batch-dropdown.el-popper) {
  background:#fff;
}
:global(.el-select__popper.generation-batch-dropdown .el-select-dropdown__item) {
  height:auto;
  min-height:65px;
  margin:3px 0;
  padding:10px 12px 10px 32px;
  white-space:normal;
  line-height:1.5;
}
:global(.el-select__popper.generation-batch-dropdown .el-select-dropdown__item.is-selected::before) {
  top:15px;
  left:13px;
}
@media (max-width:480px) {
  .batch-option { gap:4px 8px; }
  .batch-option-time { font-size:11px; }
  .batch-resource-type { overflow-wrap:anywhere; }
}
</style>
