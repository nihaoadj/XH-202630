<template>
  <div ref="setupRoot" class="onboarding-page" :class="{ 'is-fit-layout': fitLayout, 'is-contained-layout': containedLayout, 'is-domain-stage': stepStage === 'domain', 'is-track-stage': stepStage === 'track' }">
    <el-alert v-if="recoveryError" :title="recoveryError" type="error" :closable="false"><el-button @click="initializeFlow">重试恢复</el-button></el-alert>
    <section class="wizard-layout" aria-label="新建学习方向">
      <aside class="progress-panel" aria-label="学习方向创建步骤">
        <ProgressPanelAtmosphere />
        <div class="progress-heading"><el-icon aria-hidden="true"><Connection /></el-icon><div><span>LEARNING SETUP</span><strong>构建学习方向</strong></div></div>
        <nav class="progress-list" aria-label="五步创建流程">
          <button v-for="step in steps" :key="step.stage" type="button" class="progress-card"
            :class="{ active: stepStage === step.stage, done: completedStepCount >= step.index, disabled: !canEnter(step.stage) }"
            :disabled="!canEnter(step.stage)" :aria-current="stepStage === step.stage ? 'step' : undefined"
            :aria-label="step.title + '：' + step.description()" @click="goStep(step.stage)">
            <span class="progress-index" aria-hidden="true"><el-icon v-if="completedStepCount >= step.index && stepStage !== step.stage"><Check /></el-icon><span v-else>{{ String(step.index).padStart(2, '0') }}</span></span>
            <span class="progress-copy"><span class="progress-title">{{ step.title }}</span><span class="progress-desc">{{ step.description() }}</span></span>
          </button>
        </nav>
        <div class="progress-footer"><span class="progress-footer-mark" aria-hidden="true"><el-icon><Aim /></el-icon></span><p>以目标定义方向<br />以诊断找到起点</p><span>KNOWLEDGE → SKILL</span></div>
      </aside>
      <div class="step-panel" v-module-motion="{ key: stepStage, order: steps.findIndex(step => step.stage === stepStage), slideTarget: '.card-head' }">
        <el-card v-if="stepStage === 'domain'" class="work-card domain-stage-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div><span class="card-kicker">01 / EXPLORE</span><h3 class="card-title" tabindex="-1"><el-icon class="stage-heading-icon" aria-hidden="true"><MagicStick /></el-icon><span>你想探索哪个领域？</span></h3><p class="card-subtitle">从最想应用的领域出发，下一步选择具体的训练方向。</p></div>
              <span class="step-coordinate" aria-hidden="true">01<span>/ 05</span></span>
            </div>
          </template>
          <div class="overview-strip">
            <div class="overview-chip"><span>培训领域</span><strong>{{ domains.length }}<small> 个</small></strong></div>
            <div class="overview-chip"><span>学习方向</span><strong>{{ totalTrackCount }}<small> 个</small></strong></div>
          </div>
          <div class="card-grid domain-grid" role="group" aria-label="选择培训领域">
            <button v-for="(item, index) in domains" :key="item.domain_id" type="button" class="choice-card" :class="{ selected: selectedDomainId === item.domain_id, unavailable: !isDomainAvailable(item) }" :disabled="!isDomainAvailable(item) || busy" :aria-pressed="selectedDomainId === item.domain_id" @click="selectDomain(item)">
              <span class="choice-topline"><el-icon class="choice-icon" aria-hidden="true"><component :is="domainIcons[index % domainIcons.length]" /></el-icon><span class="choice-code" aria-hidden="true">FIELD / {{ String(index + 1).padStart(2, '0') }}</span><span class="choice-selector" aria-hidden="true"><el-icon v-if="selectedDomainId === item.domain_id"><Check /></el-icon></span></span>
              <span class="choice-title">{{ item.name }}</span><span class="choice-description">{{ item.description || '暂无描述' }}</span>
              <span class="choice-bottom"><span class="choice-meta">{{ isDomainAvailable(item) ? (item.tracks?.length || 0) + ' 个学习方向' : '暂不可用' }}</span><el-icon aria-hidden="true"><ArrowRight /></el-icon></span>
              <el-icon class="domain-emblem" aria-hidden="true"><component :is="domainIcons[index % domainIcons.length]" /></el-icon>
            </button>
          </div>
          <div class="action-row"><span class="action-hint">{{ selectedDomain ? '已选择：' + selectedDomain.name : '选择一个领域，继续探索' }}</span><el-button type="primary" :disabled="!isDomainAvailable(selectedDomain) || busy" @click="goStep('track')">下一步<el-icon aria-hidden="true"><ArrowRight /></el-icon></el-button></div>
        </el-card>

        <el-card v-else-if="stepStage === 'track'" class="work-card track-stage-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div><span class="card-kicker">02 / FOCUS</span><h3 class="card-title" tabindex="-1"><el-icon class="stage-heading-icon" aria-hidden="true"><Aim /></el-icon><span>找到你的训练方向</span></h3><p class="card-subtitle">围绕具体目标，让知识、诊断与练习形成一条清晰的路径。</p></div>
              <span class="step-coordinate" aria-hidden="true">02<span>/ 05</span></span>
            </div>
          </template>
          <div class="overview-strip"><div class="overview-chip overview-person"><span>当前领域</span><strong>{{ selectedDomain?.name || '-' }}</strong></div><div class="overview-chip"><span>可选方向</span><strong>{{ tracks.length }}<small> 个</small></strong></div><div class="overview-chip"><span>资料总量</span><strong>{{ selectedDomainDocumentCount }}<small> 份</small></strong></div></div>
          <div class="card-grid track-grid" role="group" aria-label="选择学习方向">
            <button v-for="(item, index) in tracks" :key="item.track_id" type="button" class="choice-card" :class="[{ selected: selectedDirectionId === item.track_id, unavailable: !isTrackAvailable(item) }, trackArtworkKind(item) ? 'track-' + trackArtworkKind(item) : '']" :disabled="!isTrackAvailable(item) || busy" :aria-pressed="selectedDirectionId === item.track_id" @click="selectDirection(item)">
              <span class="choice-topline"><el-icon class="choice-icon" aria-hidden="true"><TrackArtwork v-if="trackArtworkKind(item)" :kind="trackArtworkKind(item)" /><component v-else :is="trackIcons[index % trackIcons.length]" /></el-icon><span class="choice-code">{{ String(index + 1).padStart(2, '0') }} / {{ isTrackAvailable(item) ? 'TRAINING TRACK' : '暂不可用' }}</span><span class="choice-selector" aria-hidden="true"><el-icon v-if="selectedDirectionId === item.track_id"><Check /></el-icon></span></span>
              <span class="choice-title">{{ item.name }}</span><span class="choice-description">{{ item.description || '暂无描述' }}</span>
              <span class="choice-bottom"><span class="choice-meta">{{ item.metadata?.document_count || 0 }} 份资料<span class="meta-divider">/</span>{{ item.metadata?.skill_node_count || 0 }} 个能力节点</span><el-icon aria-hidden="true"><ArrowRight /></el-icon></span>
              <TrackArtwork v-if="trackArtworkKind(item)" class="track-artwork" :kind="trackArtworkKind(item)" detail aria-hidden="true" />
              <el-icon v-else class="domain-emblem" aria-hidden="true"><component :is="trackIcons[index % trackIcons.length]" /></el-icon>
            </button>
          </div>
          <div class="action-row"><el-button class="back-button" :icon="ArrowLeft" @click="goStep('domain')">上一步</el-button><span class="action-hint">{{ selectedDirection ? '已选择：' + selectedDirection.name : '选择一个方向，开始建立画像' }}</span><el-button v-if="currentProfile" class="manage-progress-button" link :disabled="busy" @click="prepareQuestionnaire({ force: true })">管理已有进度 / 重新开始</el-button><el-button type="primary" :disabled="!selectedDirectionId || busy" :loading="preparingQuestionnaire" @click="prepareQuestionnaire">下一步<el-icon aria-hidden="true"><ArrowRight /></el-icon></el-button></div>
        </el-card>

        <el-card v-else-if="stepStage === 'questionnaire'" class="work-card questionnaire-stage-card" shadow="never" :aria-busy="submittingProfile">
          <template #header>
            <div class="card-head">
              <div><div class="stage-heading-meta"><span class="card-kicker">03 / PROFILE</span><span v-if="selectedDirection" class="stage-context">{{ selectedDirection.name }} · {{ visibleQuestions.length }} 个问题</span></div><h3 class="card-title" tabindex="-1"><el-icon class="stage-heading-icon" aria-hidden="true"><Aim /></el-icon><span>让学习更了解你</span></h3><p class="card-subtitle">告诉我们你的目标与学习偏好，为当前方向建立初始画像。</p></div>
              <span class="step-coordinate" aria-hidden="true">03<span>/ 05</span></span>
            </div>
          </template>
          <el-form label-position="top" class="questionnaire-form" :disabled="busy">
            <el-form-item v-for="question in questions" :key="question.question_id" v-show="shouldShow(question)" class="question-block" :data-question-id="question.question_id" :label="question.title" :required="question.required">
              <template #label><span class="question-number" aria-hidden="true">{{ questionNumber(question) }}</span><span>{{ question.title }}</span><span class="question-kind">{{ questionTypeLabel(question.type) }}</span></template>
              <p v-if="question.hint" :id="'hint-' + question.question_id" class="question-hint">{{ question.hint }}</p>
              <el-input v-if="question.type === 'text'" v-model="form[question.question_id]" :aria-label="question.title" :aria-describedby="question.hint ? 'hint-' + question.question_id : undefined" :placeholder="question.hint || '请输入'" />
              <el-select v-else-if="question.type === 'single_choice' || question.type === 'single_choice_or_other'" v-model="form[question.question_id]" :allow-create="question.type === 'single_choice_or_other'" filterable default-first-option placeholder="请选择" class="full-control" :aria-label="question.title" :aria-describedby="question.hint ? 'hint-' + question.question_id : undefined">
                <el-option v-for="option in normalizedOptions(question)" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
              <el-checkbox-group v-else-if="question.type === 'multiple_choice'" :model-value="form[question.question_id]" @update:model-value="updateMultiple(form, question, $event)" class="answer-options" :aria-label="question.title" :aria-describedby="question.hint ? 'hint-' + question.question_id : undefined">
                <el-checkbox v-for="option in normalizedOptions(question)" :key="option.value" :label="option.value" :value="option.value">{{ option.label }}</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <div class="action-row"><el-button class="back-button" :icon="ArrowLeft" @click="goStep('track')">上一步</el-button><span class="action-hint">提交后，系统将判断是否需要进一步诊断</span><el-button type="primary" :loading="submittingProfile" @click="submitQuestionnaire">提交问卷<el-icon v-if="!submittingProfile" aria-hidden="true"><ArrowRight /></el-icon></el-button></div>
          </el-form>
        </el-card>

        <el-card v-else-if="stepStage === 'diagnosis'" class="work-card diagnosis-stage-card" shadow="never" :aria-busy="submittingDiagnosis">
          <template #header>
            <div class="card-head">
              <div><div class="stage-heading-meta"><span class="card-kicker">04 / ASSESS</span><span v-if="selectedDirection" class="stage-context">{{ selectedDirection.name }} · {{ diagnosticQuestions.length }} 道诊断题</span></div><h3 class="card-title" tabindex="-1"><el-icon class="stage-heading-icon" aria-hidden="true"><DataAnalysis /></el-icon><span>找到你的能力起点</span></h3><p class="card-subtitle">通过实际问题了解掌握情况，让后续资源与你的能力相匹配。</p></div>
              <span class="step-coordinate" aria-hidden="true">04<span>/ 05</span></span>
            </div>
          </template>
          <template v-if="diagnosticQuestions.length">
            <div v-for="(question, index) in diagnosticQuestions" :key="question.question_id" class="diagnostic-item" :data-question-id="question.question_id">
              <div class="diagnostic-heading"><span class="question-number" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span><h4 class="question-title" :id="'diagnosis-' + question.question_id">{{ question.question }}</h4><span class="question-kind">{{ questionTypeLabel(question.question_type) }}</span></div>
              <el-radio-group v-if="question.question_type === 'single_choice'" v-model="diagnosticAnswers[question.question_id]" class="answer-options" :aria-labelledby="'diagnosis-' + question.question_id"><el-radio v-for="option in question.options || []" :key="option" :label="option" :value="option">{{ option }}</el-radio></el-radio-group>
              <el-checkbox-group v-else-if="question.question_type === 'multiple_choice'" :model-value="diagnosticAnswers[question.question_id]" @update:model-value="updateMultiple(diagnosticAnswers, question, $event)" class="answer-options" :aria-labelledby="'diagnosis-' + question.question_id"><el-checkbox v-for="option in question.options || []" :key="option" :label="option" :value="option">{{ option }}</el-checkbox></el-checkbox-group>
              <el-input v-else v-model="diagnosticAnswers[question.question_id]" type="textarea" :rows="3" :aria-labelledby="'diagnosis-' + question.question_id" placeholder="写下你的理解或处理思路" />
            </div>
            <div class="action-row"><el-button class="back-button" :icon="ArrowLeft" @click="goStep('questionnaire')">上一步</el-button><span class="action-hint">诊断结果将用于推荐首个学习节点</span><el-button type="primary" :loading="submittingDiagnosis" @click="submitDiagnosis">提交诊断<el-icon v-if="!submittingDiagnosis" aria-hidden="true"><ArrowRight /></el-icon></el-button></div>
          </template>
          <el-empty v-else description="当前没有需要作答的诊断题，提交问卷后系统会自动判断是否需要诊断。" />
        </el-card>

        <el-card v-else class="work-card review-stage-card" shadow="never" :aria-busy="submittingGeneration">
          <template #header>
            <div class="card-head">
              <div><span class="card-kicker">05 / CREATE</span><h3 class="card-title" tabindex="-1"><el-icon class="stage-heading-icon" aria-hidden="true"><Collection /></el-icon><span>准备好，开启你的学习</span></h3><p class="card-subtitle">确认能力画像，选择资源，把你的目标转化为下一步行动。</p></div>
              <span class="step-coordinate" aria-hidden="true">05<span>/ 05</span></span>
            </div>
          </template>
          <div class="review-stage-layout">
            <section v-if="diagnosisResult" class="result-card diagnosis-result-card workspace-filter-surface" aria-label="诊断结果">
              <div class="diagnosis-identity-row"><div class="diagnosis-identity"><span class="card-kicker">学习方向 <em>DIRECTION</em></span><strong>{{ selectedDirection?.name }}</strong></div><div class="ability-stage"><span>能力阶段 <em>STAGE</em></span><strong>{{ diagnosisResult.ability_level || '-' }}</strong></div></div>
              <div class="diagnosis-point-grid"><section v-if="initialRecommendedNodeId" class="diagnosis-point-card diagnosis-point-recommend"><span><el-icon aria-hidden="true"><Connection /></el-icon>首次学习建议<em v-if="initialRecommendedNodeTier">{{ initialRecommendedNodeTier }}</em></span><p><strong>{{ initialRecommendedNodeLoading ? '正在读取节点名称…' : initialRecommendedNodeLabel }}</strong><small>系统根据初诊结果推荐这个学习起点。</small></p></section><section class="diagnosis-point-card"><span><el-icon aria-hidden="true"><Aim /></el-icon>优先加强</span><p>{{ (diagnosisResult.weak_points || []).join('、') || '暂无明显薄弱点' }}</p></section><section class="diagnosis-point-card"><span><el-icon aria-hidden="true"><Check /></el-icon>已有优势</span><p>{{ (diagnosisResult.strong_points || []).join('、') || '暂无明确优势点' }}</p></section></div>
            </section>
            <el-form label-position="top" class="questionnaire-form resource-selection-form">
              <el-form-item
                v-if="initialRecommendedNodeId && (initialNodeCandidates.length || initialRecommendedNodeLoading || initialNodeCandidatesError)"
                label="首批学习节点"
              >
                <el-select
                  v-if="initialNodeCandidates.length || initialRecommendedNodeLoading"
                  v-model="selectedInitialNodeId"
                  aria-label="首批学习节点"
                  :loading="initialRecommendedNodeLoading"
                  :disabled="busy || initialRecommendedNodeLoading"
                  class="full-control"
                >
                  <el-option
                    v-for="node in initialNodeCandidates"
                    :key="node.node_id"
                    :value="node.node_id"
                    :label="initialNodeOptionLabel(node)"
                  />
                </el-select>
                <small v-if="initialNodeCandidates.some(node => node.metadata?.initial_diagnostic_passed)" class="initial-node-fallback">初诊通过的节点也可选择学习。</small>
                <small v-if="initialNodeCandidates.length === 1" class="initial-node-fallback">当前阶段只有一个符合首批学习条件的节点。</small>
                <div v-else-if="initialNodeCandidatesError" class="initial-node-fallback">
                  <span>暂时无法读取可选节点，生成时将使用诊断推荐。</span>
                  <el-button link type="primary" :disabled="busy" @click="loadInitialNodeCandidates()">重试</el-button>
                </div>
              </el-form-item>
              <el-form-item label="本次要生成的资源类型" required class="resource-type-field"><el-checkbox-group class="resource-type-grid" v-model="selectedResourceTypes" aria-label="本次要生成的资源类型"><el-checkbox v-for="item in resourceTypeOptions" :key="item" :label="item" :value="item"><span class="resource-option"><el-icon aria-hidden="true"><component :is="resourceVisuals[item].icon" /></el-icon><strong>{{ item }}</strong><span>{{ resourceVisuals[item].description }}</span></span></el-checkbox></el-checkbox-group></el-form-item>
              <el-form-item v-if="selectedResourceTypes.some(type => type !== '实操指南')" label="审查选项"><div class="claim-review-row"><div class="claim-review-control"><el-icon class="claim-icon" aria-hidden="true"><Lock /></el-icon><div><strong>Claim 强化审查</strong><p>对关键事实逐条核对来源证据</p></div><el-switch v-model="includeClaimCheck" aria-label="Claim 强化审查" /></div><div class="claim-review-control"><el-icon class="claim-icon" aria-hidden="true"><Search /></el-icon><div><strong>缺证补检知识库</strong><p>证据不足时补检来源并复核</p></div><el-switch v-model="includeClaimEvidenceRetrieval" :disabled="!includeClaimCheck" aria-label="证据不足时补检知识库" /></div></div></el-form-item>
            </el-form>
            <div class="action-row review-actions"><el-button class="back-button" :icon="ArrowLeft" @click="goStep('diagnosis')">上一步</el-button><span class="action-hint">已选择 {{ selectedResourceTypes.length }} 种资源</span><el-button type="primary" :loading="submittingGeneration" :disabled="initialRecommendedNodeLoading" @click="submitGeneration">生成并进入状态页<el-icon v-if="!submittingGeneration" aria-hidden="true"><ArrowRight /></el-icon></el-button></div>
          </div>
        </el-card>
      </div>
    </section>
    <el-dialog v-model="existingProgressVisible" title="此方向已有学习记录" width="min(620px, calc(100vw - 24px))" :close-on-click-modal="false" :close-on-press-escape="!deletingProgress" :show-close="!deletingProgress" :before-close="closeExistingProgress">
      <p>“{{ selectedDirection?.name }}”已有 {{ existingProfiles.length }} 份学习记录。请选择一份继续学习，或删除所选记录后重新开始；其他记录不会删除。</p>
      <el-radio-group v-model="selectedExistingId" class="existing-progress-list" :disabled="deletingProgress" aria-label="选择已有学习记录">
        <el-radio v-for="profile in existingProfiles" :key="profile.learner_id" :value="profile.learner_id" :label="profile.learner_id"><span>{{ currentProfileRating(profile) || '未诊断' }} · {{ profile.updated_at || profile.created_at || '时间未记录' }}</span><small>{{ profile.learner_id }}</small></el-radio>
      </el-radio-group>
      <el-alert v-if="existingProgressError" :title="existingProgressError" type="error" :closable="false" />
      <template #footer><div class="existing-progress-actions"><el-button :disabled="deletingProgress" @click="existingProgressVisible = false">取消</el-button><el-button :disabled="!selectedExistingId || deletingProgress" @click="continueExistingProgress">保留进度并继续</el-button><el-button type="danger" :disabled="!selectedExistingId" :loading="deletingProgress" @click="restartSelectedProgress">删除所选记录并重新开始</el-button></div></template>
    </el-dialog>
  </div>
</template>


<script setup>
import { currentProfileRating } from '../../utils/profileRating.js'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import ProgressPanelAtmosphere from './ProgressPanelAtmosphere.vue'
import AiDomainIcon from './AiDomainIcon.vue'
import TrackArtwork from './TrackArtwork.vue'
import SoftwareDomainIcon from './SoftwareDomainIcon.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Aim, ArrowLeft, ArrowRight, Check, Collection, Connection, DataAnalysis, EditPen, Lock, MagicStick, Search } from '@element-plus/icons-vue'
import { resourceTypeVisuals as resourceVisuals } from '../../components/resourceTypeVisuals.js'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { diagnosisApi, profileApi } from '../learners/api.js'
import { coursewareApi } from '../courseware/api.js'
import { generateApi } from '../generation/api.js'
import { roundGenerationApi } from '../generation/roundApi.js'
import { knowledgeApi } from '../knowledge/api.js'
import { onboardingApi } from './api.js'
import { useAuthStore } from '../../stores/auth'
import { useAppStore } from '../../stores/app'
import { answersFor, clearDraft, exclusiveSelection, findDirectionProfiles, isDomainAvailable, isTrackAvailable, jobsAllowRestart, optionsFor, profileMatchesDirection, readDraft, writeDraft } from './onboardingState.js'

const router = useRouter()
const auth = useAuthStore()
const store = useAppStore()

const domains = ref([])
const questions = ref([])
const selectedDomainId = ref('')
const selectedDirectionId = ref('')
const stepStage = ref('domain')
const submittingProfile = ref(false)
const submittingDiagnosis = ref(false)
const submittingGeneration = ref(false)
const selectedResourceTypes = ref(['讲义', '实操指南', '分阶测试题'])
const includeClaimCheck = ref(false)
const includeClaimEvidenceRetrieval = ref(false)
const supplementalRequirements = ref('')
const preparingQuestionnaire = ref(false)
const deletingProgress = ref(false)
const existingProgressVisible = ref(false)
const existingProfiles = ref([])
const selectedExistingId = ref('')
const existingProgressError = ref('')
const initializing = ref(true)
const recoveryError = ref('')
const busy = computed(() => Boolean(recoveryError.value) || initializing.value || preparingQuestionnaire.value || submittingProfile.value || submittingDiagnosis.value || submittingGeneration.value || deletingProgress.value)
let requestVersion = 0
let draftReady = false
let draftCompleted = false
let draftOwner = ''
const restartAcknowledged = ref(false)
const initialRecommendedNodeName = ref('')
const initialRecommendedNodeLoading = ref(false)
const initialNodeCandidates = ref([])
const selectedInitialNodeId = ref('')
const initialNodeCandidatesError = ref(false)
function initialNodeOptionLabel(node) {
  const labels = []
  if (node.node_id === initialRecommendedNodeId.value) labels.push('诊断推荐')
  if (node.metadata?.initial_diagnostic_passed) labels.push('可选择')
  return labels.length ? `${node.name}（${labels.join(' · ')}）` : node.name
}

const form = reactive({})
const diagnosticAnswers = reactive({})

const currentUser = computed(() => auth.currentUser || store.currentUserProfile || null)
const selectedDomain = computed(() => domains.value.find((item) => item.domain_id === selectedDomainId.value))
const tracks = computed(() => selectedDomain.value?.tracks || [])
const selectedDirection = computed(() => tracks.value.find((item) => item.track_id === selectedDirectionId.value))
const totalTrackCount = computed(() => domains.value.reduce((sum, item) => sum + (item.tracks?.length || 0), 0))
const selectedDomainDocumentCount = computed(() => {
  const counts = new Map()
  for (const item of tracks.value) {
    if (!isTrackAvailable(item)) continue
    const key = item.knowledge_base_id || item.track_id
    counts.set(key, Math.max(counts.get(key) || 0, item.metadata?.document_count || 0))
  }
  return [...counts.values()].reduce((sum, count) => sum + count, 0)
})
const flowProfile = ref(null)
const flowQuestions = ref([])
const flowDiagnosis = ref(null)
const currentProfile = computed(() => flowProfile.value)
const diagnosticQuestions = computed(() => flowQuestions.value)
const diagnosisResult = computed(() => flowDiagnosis.value)
function setProfile(profile) { flowProfile.value = profile; store.setCurrentProfile(profile) }
function setPendingQuestions(value) { flowQuestions.value = value || []; store.setPendingDiagnosis(value) }
function setDiagnosis(value) { flowDiagnosis.value = value; store.setDiagnosisResult(value) }
const initialRecommendedNodeId = computed(() => String(diagnosisResult.value?.initial_recommended_node_id || '').trim())
const initialRecommendedNodeLabel = computed(() => initialRecommendedNodeName.value || initialRecommendedNodeId.value)
const initialRecommendedNodeTier = computed(() => ({
  1: '第一阶',
  2: '第二阶',
  3: '第三阶',
}[diagnosisResult.value?.final_tier || diagnosisResult.value?.assessed_tier || diagnosisResult.value?.questionnaire_tier] || '当前学习阶'))
const questionnaireCompleted = computed(() => Boolean(currentProfile.value && selectedDirectionId.value))
const learnerId = computed(() => {
  if (!currentUser.value?.user_id || !selectedDirectionId.value) return ''
  return `${currentUser.value.user_id}__${selectedDirectionId.value}`
})
const activeLearnerId = computed(() => currentProfile.value?.learner_id || '')
const learnerLabel = computed(() => {
  const userName = currentUser.value?.display_name || '当前用户'
  const directionName = selectedDirection.value?.name || '未选择方向'
  return `${userName} / ${directionName}`
})
const generatedTopic = computed(() => {
  const directionName = selectedDirection.value?.name || '当前学习方向'
  const abilityLevel = diagnosisResult.value?.ability_level || currentProfile.value?.skill_level || ''
  const weakPoints = (
    diagnosisResult.value?.weak_points ||
    currentProfile.value?.weak_points ||
    []
  )
    .filter(Boolean)
    .slice(0, 3)
  const resourceSummary = selectedResourceTypes.value.filter(Boolean).join('、')
  const target = initialNodeCandidates.value.find(node => node.node_id === selectedInitialNodeId.value)
  const focusSummary = target ? `，学习节点 ${target.name}` : weakPoints.length ? `，重点覆盖 ${weakPoints.join('、')}` : ''
  const levelSummary = abilityLevel ? `${abilityLevel}阶段` : '当前阶段'
  const typeSummary = resourceSummary ? `，输出 ${resourceSummary}` : ''
  return `${directionName}${levelSummary}学习资源${focusSummary}${typeSummary}`
})

const resourceTypeOptions = ['讲义', '实操指南', '分阶测试题', '复习清单', '案例分析']

// Presentation metadata does not participate in the diagnosis or generation payload.
const setupRoot = ref(null)
const fitLayout = ref(false)
const containedLayout = ref(false)
const domainIcons = [AiDomainIcon, DataAnalysis, SoftwareDomainIcon, Lock]
const trackIcons = [Collection, EditPen, Connection, SoftwareDomainIcon]
function trackArtworkKind(item) {
  const name = item.name || ''
  if (/prompt|提示词/i.test(name)) return ''
  if (/rag/i.test(name)) return 'rag'
  if (/agent|智能体/i.test(name)) return 'agent'
  if (/api/i.test(name)) return 'api'
  return ''
}
const visibleQuestions = computed(() => questions.value.filter(shouldShow))
function questionNumber(question) {
  return String(visibleQuestions.value.indexOf(question) + 1).padStart(2, '0')
}
function questionTypeLabel(type) {
  return ({ text: '简答', single_choice: '单选', single_choice_or_other: '单选 / 可自填', multiple_choice: '多选' })[type] || '简答'
}

let setupLayoutObserver
let setupLayoutFrame = 0
let setupLayoutVersion = 0
let setupMounted = false
function scheduleSetupLayout() {
  const version = ++setupLayoutVersion
  cancelAnimationFrame(setupLayoutFrame)
  setupLayoutFrame = requestAnimationFrame(async () => {
    setupLayoutFrame = 0
    if (!setupMounted || !setupRoot.value) return
    const selectionStage = ['domain', 'track'].includes(stepStage.value)
    fitLayout.value = selectionStage && window.innerWidth >= 1100 && window.innerHeight >= 640
    containedLayout.value = !selectionStage && window.innerHeight >= 640
    await nextTick()
    if (!setupMounted || version !== setupLayoutVersion) return
    const root = setupRoot.value
    const area = root.closest('.content-area')
    const body = root.querySelector('.work-card > .el-card__body')
    if (body) {
      body.removeAttribute('tabindex')
      body.removeAttribute('role')
      body.removeAttribute('aria-label')
    }
    if (!fitLayout.value && !containedLayout.value) return
    area.scrollTop = 0
    const bounds = area.getBoundingClientRect()
    if (containedLayout.value) {
      const fixedRegions = [root, ...root.querySelectorAll('.setup-intro, .wizard-layout, .progress-panel, .step-panel, .work-card, .el-card__header')]
      const invalid = !body || body.clientHeight < 80 || fixedRegions.some((node) => {
        if (!node.getClientRects().length) return false
        const rect = node.getBoundingClientRect()
        return node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1 || rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1
      })
      if (invalid) containedLayout.value = false
      else {
        body.tabIndex = 0
        body.setAttribute('role', 'region')
        body.setAttribute('aria-label', ({ questionnaire: '问卷内容', diagnosis: '诊断题目', review: '资源确认内容' })[stepStage.value])
      }
      return
    }
  })
}

watch([stepStage, domains, tracks], scheduleSetupLayout, { flush: 'post' })
watch(stepStage, async () => {
  await nextTick()
  if (!setupMounted || !setupRoot.value) return
  const root = setupRoot.value
  const area = root.closest('.content-area')
  if (area) area.scrollTop = 0
  const body = root.querySelector('.work-card > .el-card__body')
  if (body) body.scrollTop = 0
  root.querySelector('.card-title')?.focus({ preventScroll: true })
  scheduleSetupLayout()
})
onMounted(() => {
  setupMounted = true
  setupLayoutObserver = new ResizeObserver(scheduleSetupLayout)
  setupLayoutObserver.observe(setupRoot.value.closest('.content-area'), { box: 'border-box' })
  window.addEventListener('resize', scheduleSetupLayout)
  scheduleSetupLayout()
})
onBeforeUnmount(() => {
  saveDraft()
  draftReady = false
  ++requestVersion
  setupMounted = false
  ++setupLayoutVersion
  cancelAnimationFrame(setupLayoutFrame)
  setupLayoutObserver?.disconnect()
  window.removeEventListener('resize', scheduleSetupLayout)
})

const steps = [
  {
    index: 1,
    stage: 'domain',
    title: '领域',
    description: () => selectedDomain.value?.name || '选择一级培训领域',
  },
  {
    index: 2,
    stage: 'track',
    title: '方向',
    description: () => selectedDirection.value?.name || '选择具体学习方向',
  },
  {
    index: 3,
    stage: 'questionnaire',
    title: '问卷',
    description: () => (questionnaireCompleted.value ? '已完成方向问卷' : '填写方向相关动态信息'),
  },
  {
    index: 4,
    stage: 'diagnosis',
    title: '诊断',
    description: () => (diagnosisResult.value ? '已完成能力诊断' : '补齐真实掌握情况'),
  },
  {
    index: 5,
    stage: 'review',
    title: '资源选择',
    description: () => (diagnosisResult.value ? '确认资源类型并生成' : '查看诊断结果后选择资源'),
  },
]

const completedStepCount = computed(() => {
  let count = 0
  if (selectedDomainId.value) count = 1
  if (selectedDirectionId.value) count = 2
  if (questionnaireCompleted.value) count = 3
  if (diagnosisResult.value) count = 4
  if (diagnosisResult.value && selectedResourceTypes.value.length) count = 5
  return count
})

function canEnter(stage) {
  if (busy.value) return false
  if (!currentUser.value) return stage === 'domain'
  if (stage === 'domain') return true
  if (!isDomainAvailable(selectedDomain.value)) return false
  if (stage === 'track') return true
  if (!isTrackAvailable(selectedDirection.value)) return false
  if (stage === 'questionnaire') return Boolean(questions.value.length)
  if (stage === 'diagnosis') return questionnaireCompleted.value
  if (stage === 'review') return Boolean(diagnosisResult.value)
  return false
}

function goStep(target) {
  if (canEnter(target)) {
    stepStage.value = target
  }
}

function initDiagnosticAnswers() {
  Object.keys(diagnosticAnswers).forEach((key) => {
    delete diagnosticAnswers[key]
  })
  for (const question of diagnosticQuestions.value) {
    diagnosticAnswers[question.question_id] = question.question_type === 'multiple_choice' ? [] : ''
  }
}

function resetFormValues() {
  Object.keys(form).forEach((key) => {
    delete form[key]
  })
  for (const question of questions.value) {
    form[question.question_id] = question.type === 'multiple_choice' ? [] : ''
  }
}

function normalizedOptions(question) {
  return optionsFor(question)
}
function updateMultiple(target, question, values) {
  target[question.question_id] = exclusiveSelection(values, target[question.question_id], question)
}

function matchesShowRule(answer, rule) {
  if (typeof rule !== 'object' || rule === null || Array.isArray(rule)) {
    return Array.isArray(answer) ? answer.includes(rule) : answer === rule
  }
  if (Object.prototype.hasOwnProperty.call(rule, 'equals')) return answer === rule.equals
  if (Object.prototype.hasOwnProperty.call(rule, 'not_equals')) return answer !== rule.not_equals
  if (Object.prototype.hasOwnProperty.call(rule, 'includes')) return Array.isArray(answer) && answer.includes(rule.includes)
  if (Array.isArray(rule.any_of)) return rule.any_of.includes(answer)
  if (Array.isArray(rule.all_of)) return Array.isArray(answer) && rule.all_of.every((item) => answer.includes(item))
  return true
}

function shouldShow(question) {
  const condition = question.show_when
  if (!condition || Object.keys(condition).length === 0) return true
  return Object.entries(condition).every(([field, rule]) => {
    if (field.endsWith('_contains')) {
      const actualField = field.slice(0, -'_contains'.length)
      return Array.isArray(form[actualField]) && form[actualField].includes(rule)
    }
    return matchesShowRule(form[field], rule)
  })
}

function resetFlow() {
  ++requestVersion
  flowProfile.value = null
  flowQuestions.value = []
  flowDiagnosis.value = null
  questions.value = []
  Object.keys(form).forEach(key => delete form[key])
  Object.keys(diagnosticAnswers).forEach(key => delete diagnosticAnswers[key])
  store.clearLearnerContext()
  initialRecommendedNodeName.value = ''
  initialNodeCandidates.value = []
  selectedInitialNodeId.value = ''
  initialNodeCandidatesError.value = false
  existingProgressVisible.value = false
  existingProfiles.value = []
  selectedExistingId.value = ''
  existingProgressError.value = ''
  restartAcknowledged.value = false
  selectedResourceTypes.value = ['讲义', '实操指南', '分阶测试题']
  includeClaimCheck.value = false
  includeClaimEvidenceRetrieval.value = false
  supplementalRequirements.value = ''
}

function selectDomain(item) {
  if (busy.value || !isDomainAvailable(item) || selectedDomainId.value === item.domain_id) return
  resetFlow()
  selectedDomainId.value = item.domain_id
  selectedDirectionId.value = ''
  stepStage.value = 'domain'
  initialRecommendedNodeLoading.value = false
}

function selectDirection(item) {
  if (busy.value || !isDomainAvailable(selectedDomain.value) || !isTrackAvailable(item) || selectedDirectionId.value === item.track_id) return
  resetFlow()
  selectedDirectionId.value = item.track_id
  store.setLearningDirectionId(item.track_id)
  store.setLearningDirectionName(item.name)
  initialRecommendedNodeLoading.value = false
}

async function loadDomains() {
  const res = await knowledgeApi.listDomains()
  domains.value = res.data.domains || []
}

async function loadQuestions(preserve = false) {
  if (!selectedDirectionId.value) {
    questions.value = []
    return
  }
  const version = requestVersion
  const res = await onboardingApi.getQuestions(selectedDirectionId.value)
  if (!setupMounted || version !== requestVersion) return false
  if (!Array.isArray(res.data.questions) || !res.data.questions.length) throw new Error('当前方向的问卷尚不可用，请稍后重试')
  questions.value = res.data.questions
  if (preserve) replaceAnswers(form, answersFor(questions.value, form))
  else resetFormValues()
  return true
}

async function prepareQuestionnaire(options = {}) {
  if (busy.value || !isDomainAvailable(selectedDomain.value) || !isTrackAvailable(selectedDirection.value)) return
  if (!options.force && currentProfile.value && questions.value.length) { stepStage.value = 'questionnaire'; return }
  const version = ++requestVersion
  const owner = currentUser.value.user_id
  const isCurrent = () => setupMounted && version === requestVersion && currentUser.value?.user_id === owner
  preparingQuestionnaire.value = true
  try {
    const profiles = await findDirectionProfiles(profileApi.list, selectedDirection.value, owner, isCurrent)
    if (!isCurrent() || profiles === null) return
    existingProfiles.value = profiles
    if (profiles.length) {
      selectedExistingId.value = ''
      existingProgressError.value = ''
      existingProgressVisible.value = true
      return
    }
    if (await loadQuestions(Boolean(questions.value.length))) stepStage.value = 'questionnaire'
  } catch (error) {
    if (isCurrent()) ElMessage.error(error?.response?.data?.message || error.message || '检查已有进度失败，请重试')
  } finally { if (isCurrent()) preparingQuestionnaire.value = false }
}

function closeExistingProgress(done) { if (!deletingProgress.value) done() }
async function continueExistingProgress() {
  const profile = existingProfiles.value.find(item => item.learner_id === selectedExistingId.value)
  if (!profile || deletingProgress.value) return
  store.resumeProfile(profile, selectedDirectionId.value, selectedDirection.value.name)
  existingProgressVisible.value = false
  await router.push('/learning/history')
}

async function restartSelectedProgress() {
  const profile = existingProfiles.value.find(item => item.learner_id === selectedExistingId.value)
  if (!profile || deletingProgress.value) return
  const direction = selectedDirection.value
  const owner = currentUser.value.user_id
  deletingProgress.value = true
  existingProgressError.value = ''
  try {
    try {
      await ElMessageBox.confirm(`将永久删除所选记录“${profile.learner_id}”及其关联的问卷、诊断、学习进度、资源、反馈与运行记录。此操作无法恢复，其他记录不会删除。确认重新开始吗？`, '确认删除旧进度', { type: 'warning', confirmButtonText: '永久删除并重新开始', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger', closeOnClickModal: false })
    } catch { return }
    const [latest, textJobs, coursewareJobs] = await Promise.all([profileApi.get(profile.learner_id), generateApi.listJobs(profile.learner_id), coursewareApi.listJobs(profile.learner_id)])
    if (!setupMounted || currentUser.value?.user_id !== owner || selectedDirectionId.value !== direction.track_id) return
    if (!profileMatchesDirection(latest.data, direction, owner)) throw new Error('记录归属或方向已变化，请刷新后重试')
    if (!jobsAllowRestart(textJobs, 'job_status') || !jobsAllowRestart(coursewareJobs, 'status')) throw new Error('该记录仍有进行中或状态未确认的任务，请等待任务结束后再重新开始')
    // Read the new questionnaire before the irreversible operation; a fetch failure must not delete progress.
    if (!await loadQuestions(true)) return
    if (!setupMounted || currentUser.value?.user_id !== owner) return
    await profileApi.delete(profile.learner_id)
    if (!setupMounted || currentUser.value?.user_id !== owner) return
    if (store.currentLearnerId === profile.learner_id || store.currentProfile?.learner_id === profile.learner_id) store.clearLearnerContext()
    store.setLearningDirectionId(direction.track_id)
    store.setLearningDirectionName(direction.name)
    existingProfiles.value = existingProfiles.value.filter(item => item.learner_id !== profile.learner_id)
    selectedExistingId.value = ''
    restartAcknowledged.value = true
    flowProfile.value = null
    flowQuestions.value = []
    flowDiagnosis.value = null
    clearDraft(owner)
    resetFormValues()
    existingProgressVisible.value = false
    stepStage.value = 'questionnaire'
    ElMessage.success('所选旧记录已永久删除，请重新填写问卷；其他记录已保留')
  } catch (error) {
    existingProgressError.value = error?.response?.data?.message || error.message || '删除失败，未重新开始'
  } finally { if (currentUser.value?.user_id === owner) { deletingProgress.value = false; saveDraft() } }
}

async function loadInitialNodeCandidates(result = diagnosisResult.value) {
  const version = requestVersion
  const nodeId = String(result?.initial_recommended_node_id || '').trim()
  const profileId = activeLearnerId.value
  const isCurrent = () => setupMounted && version === requestVersion && profileId === activeLearnerId.value
  initialRecommendedNodeName.value = ''
  initialNodeCandidates.value = []
  initialNodeCandidatesError.value = false
  initialRecommendedNodeLoading.value = false
  if (!nodeId || !profileId) return

  initialRecommendedNodeLoading.value = true
  try {
    const res = await profileApi.initialNodeCandidates(profileId)
    if (!isCurrent()) return
    if (!Array.isArray(res.data)) throw new Error('Invalid initial node candidates')
    const nodes = res.data
    initialNodeCandidates.value = nodes
    const matchedNode = nodes.find((node) => String(node.node_id || '').trim() === nodeId)
    initialRecommendedNodeName.value = matchedNode?.name || ''
    if (!nodes.some(node => node.node_id === selectedInitialNodeId.value)) {
      selectedInitialNodeId.value = matchedNode?.node_id || nodes[0]?.node_id || ''
    }
  } catch {
    if (!isCurrent()) return
    initialNodeCandidatesError.value = true
    try {
      const res = await knowledgeApi.listNodes(selectedDirectionId.value)
      if (isCurrent()) initialRecommendedNodeName.value = res.data?.nodes?.find(node => node.node_id === nodeId)?.name || ''
    } catch { /* The recommendation ID remains visible. */ }
  } finally {
    if (isCurrent()) initialRecommendedNodeLoading.value = false
  }
}

async function submitQuestionnaire() {
  if (busy.value || !isDomainAvailable(selectedDomain.value) || !isTrackAvailable(selectedDirection.value)) return
  if (!currentUser.value || !learnerId.value) {
    ElMessage.warning('请先选择学习方向')
    return
  }

  submittingProfile.value = true
  const version = requestVersion
  const owner = currentUser.value.user_id
  try {
    if (currentProfile.value) {
      stepStage.value = diagnosticQuestions.value.length ? 'diagnosis' : diagnosisResult.value ? 'review' : 'questionnaire'
      ElMessage.info('本次问卷已提交，请继续当前诊断；如需重填，请返回方向选择并明确重开旧记录')
      return
    }
    if (!restartAcknowledged.value) {
      const isCurrent = () => setupMounted && version === requestVersion && currentUser.value?.user_id === owner
      const profiles = await findDirectionProfiles(profileApi.list, selectedDirection.value, owner, isCurrent)
      if (!isCurrent() || profiles === null) return
      if (profiles.length) {
        existingProfiles.value = profiles
        selectedExistingId.value = ''
        existingProgressError.value = ''
        existingProgressVisible.value = true
        return
      }
    }
    const answers = answersFor(questions.value, form)

    const res = await onboardingApi.createInitialProfile({
      learner_id: learnerId.value,
      learning_direction_id: selectedDirectionId.value,
      answers,
    })
    if (!setupMounted || version !== requestVersion || currentUser.value?.user_id !== owner) return

    store.setLearnerId(res.data.learner_id)
    setProfile(res.data.profile)
    setPendingQuestions(res.data.diagnostic_questions || [])
    setDiagnosis(null)
    initDiagnosticAnswers()
    stepStage.value = diagnosticQuestions.value.length ? 'diagnosis' : 'review'
    if (!diagnosticQuestions.value.length) {
      setDiagnosis({
        ability_level: res.data.profile.skill_level,
        weak_points: res.data.profile.weak_points || [],
        strong_points: res.data.profile.strong_points || [],
        knowledge_states: res.data.profile.knowledge_states || {},
        diagnostic_result_id: '',
      })
    }
    ElMessage.success('问卷已提交')
  } catch (error) {
    ElMessage.error(error?.response?.data?.message || '问卷提交失败')
  } finally {
    if (version === requestVersion) submittingProfile.value = false
  }
}

async function submitDiagnosis() {
  if (busy.value || !currentProfile.value) return
  submittingDiagnosis.value = true
  const version = requestVersion
  const owner = currentUser.value.user_id
  try {
    const normalized = answersFor(diagnosticQuestions.value, diagnosticAnswers)
    const answers = diagnosticQuestions.value.map((question) => ({
      question_id: question.question_id,
      answer: normalized[question.question_id],
    }))

    const res = await diagnosisApi.submit({
      learner_id: currentProfile.value.learner_id,
      learning_direction_id: selectedDirectionId.value,
      answers,
    })
    if (!setupMounted || version !== requestVersion || currentUser.value?.user_id !== owner) return

    setDiagnosis(res.data)
    setProfile({
      ...currentProfile.value,
      skill_level: res.data.ability_level,
      weak_points: res.data.weak_points,
      strong_points: res.data.strong_points,
      knowledge_states: {
        ...(currentProfile.value.knowledge_states || {}),
        ...(res.data.knowledge_states || {}),
      },
    })
    try {
      const fresh = await profileApi.get(currentProfile.value.learner_id)
      if (!setupMounted || version !== requestVersion || currentUser.value?.user_id !== owner) return
      if (profileMatchesDirection(fresh.data, selectedDirection.value, owner)) setProfile(fresh.data)
    } catch { ElMessage.warning('诊断已保存，画像版本暂未刷新，恢复时会再次核对') }

    if (res.data.initial_diagnostic_status === 'retest') {
      setPendingQuestions(res.data.next_diagnostic_questions || [])
      initDiagnosticAnswers()
      stepStage.value = 'diagnosis'
      ElMessage.info('本阶段校准未通过，已自动进入下一阶段复测')
      return
    }

    setPendingQuestions([])
    stepStage.value = 'review'
    selectedInitialNodeId.value = ''
    await loadInitialNodeCandidates(res.data)
    ElMessage.success('诊断已完成')
  } catch (error) {
    ElMessage.error(error?.response?.data?.message || '诊断提交失败')
  } finally {
    if (version === requestVersion) submittingDiagnosis.value = false
  }
}

let roundSubmissionChoice = null
async function submitGeneration() {
  if (busy.value || initialRecommendedNodeLoading.value) return
  if (!selectedResourceTypes.value.length) {
    ElMessage.warning('请至少选择一种资源类型')
    return
  }
  if (!activeLearnerId.value) {
    ElMessage.warning('当前学习画像不存在，请重新提交方向问卷')
    return
  }
  submittingGeneration.value = true
  const version = requestVersion
  const owner = currentUser.value.user_id
  try {
    const payload = {
      learner_id: activeLearnerId.value,
      knowledge_base_id: selectedDirectionId.value,
      topic: generatedTopic.value,
      diagnostic_result_id: diagnosisResult.value?.diagnostic_result_id,
      ...(initialNodeCandidates.value.some(node => node.node_id === selectedInitialNodeId.value)
        ? { target_skill_nodes: [selectedInitialNodeId.value] } : {}),
      resource_types: selectedResourceTypes.value,
      include_claim_check: includeClaimCheck.value,
      include_claim_evidence_retrieval: includeClaimCheck.value && includeClaimEvidenceRetrieval.value,
      constraints: {
        supplemental_requirements: supplementalRequirements.value.trim(),
      },
    }
    localStorage.setItem('last_generation_request', JSON.stringify(payload))
    const fingerprint = JSON.stringify(payload)
    if (!roundSubmissionChoice || roundSubmissionChoice.fingerprint !== fingerprint) {
      const capabilities = await roundGenerationApi.capabilities().catch(() => null)
      if (!setupMounted || version !== requestVersion || currentUser.value?.user_id !== owner) return
      roundSubmissionChoice = { fingerprint, enabled: capabilities?.data?.round_creation_enabled === true, key: `round-${crypto.randomUUID()}` }
    }
    let round = null
    let responses
    if (roundSubmissionChoice.enabled) {
      const response = await roundGenerationApi.create({ ...payload, selection_key: roundSubmissionChoice.key })
      round = response.data
      const primary = round.members.find(member => member.role === 'primary')
      responses = [{ data: { run_id: round.primary_default_run_id || primary?.job_ids[0] } }]
    } else responses = await generateApi.createJobsForClaim(payload)
    if (!setupMounted || version !== requestVersion || currentUser.value?.user_id !== owner) return
    const res = responses[0]
    localStorage.setItem('current_generation_run_ids', JSON.stringify(round ? round.members.flatMap(member => member.job_ids) : responses.map((item) => item.data?.run_id).filter(Boolean)))
    draftCompleted = true
    clearDraft(draftOwner)
    if (version === requestVersion) submittingGeneration.value = false
    await router.push({
      path: '/generate',
      query: {
        runId: res.data.run_id,
        learnerId: activeLearnerId.value,
        ...(round ? { roundId: round.round_id, stageId: round.stage_id, memberId: round.members.find(member => member.role === 'primary')?.member_id } : {}),
      },
    })
  } catch (error) {
    ElMessage({
      message: error?.response?.data?.message || '生成任务提交失败',
      type: 'error',
      grouping: true,
    })
  } finally {
    if (version === requestVersion) submittingGeneration.value = false
  }
}

watch(diagnosticQuestions, initDiagnosticAnswers, { flush: 'sync' })

function replaceAnswers(target, values) {
  Object.keys(target).forEach(key => delete target[key])
  Object.assign(target, values)
}
function saveDraft() {
  if (!draftReady || draftCompleted || !draftOwner || draftOwner !== currentUser.value?.user_id) return
  writeDraft(draftOwner, { stage: stepStage.value, domainId: selectedDomainId.value, directionId: selectedDirectionId.value, questionnaireLoaded: Boolean(questions.value.length),
    form, diagnosticAnswers, profile: flowProfile.value, diagnosticQuestions: flowQuestions.value, diagnosis: flowDiagnosis.value,
    resourceTypes: selectedResourceTypes.value, initialNodeId: selectedInitialNodeId.value, includeClaimCheck: includeClaimCheck.value,
    includeClaimEvidenceRetrieval: includeClaimEvidenceRetrieval.value,
    supplementalRequirements: supplementalRequirements.value, restartAcknowledged: restartAcknowledged.value })
}
watch([stepStage, selectedDomainId, selectedDirectionId, form, diagnosticAnswers, flowProfile, flowQuestions, flowDiagnosis, selectedResourceTypes, selectedInitialNodeId, includeClaimCheck, includeClaimEvidenceRetrieval, supplementalRequirements], saveDraft, { deep: true })
watch(includeClaimCheck, (enabled) => { if (!enabled) includeClaimEvidenceRetrieval.value = false })
watch(selectedResourceTypes, (types) => {
  if (types.length === 1 && types[0] === '实操指南') includeClaimCheck.value = false
})
watch(() => currentUser.value?.user_id, (next, previous) => {
  if (!previous || next === previous) return
  draftReady = false
  ++requestVersion
  flowProfile.value = null
  flowQuestions.value = []
  flowDiagnosis.value = null
  selectedDomainId.value = ''
  selectedDirectionId.value = ''
  questions.value = []
  replaceAnswers(form, {})
  replaceAnswers(diagnosticAnswers, {})
  existingProgressVisible.value = false
  existingProfiles.value = []
  selectedExistingId.value = ''
  initialRecommendedNodeName.value = ''
  initialRecommendedNodeLoading.value = false
  initialNodeCandidates.value = []
  selectedInitialNodeId.value = ''
  initialNodeCandidatesError.value = false
  selectedResourceTypes.value = ['讲义', '实操指南', '分阶测试题']
  includeClaimCheck.value = false
  includeClaimEvidenceRetrieval.value = false
  supplementalRequirements.value = ''
  preparingQuestionnaire.value = false
  submittingProfile.value = false
  submittingDiagnosis.value = false
  submittingGeneration.value = false
  deletingProgress.value = false
  restartAcknowledged.value = false
  stepStage.value = 'domain'
  if (next) initializeFlow()
})

async function initializeFlow() {
  const version = ++requestVersion
  const owner = currentUser.value?.user_id
  const isCurrent = () => setupMounted && version === requestVersion && owner === currentUser.value?.user_id
  initializing.value = true
  recoveryError.value = ''
  draftReady = false
  draftOwner = owner || ''
  try {
    await loadDomains()
    if (!isCurrent()) return
    const draft = readDraft(owner)
    if (draft) {
      const domain = domains.value.find(item => item.domain_id === draft.domainId)
      if (isDomainAvailable(domain)) {
        selectedDomainId.value = domain.domain_id
        const direction = domain.tracks?.find(item => item.track_id === draft.directionId)
        if (isTrackAvailable(direction)) {
          selectedDirectionId.value = direction.track_id
          restartAcknowledged.value = draft.restartAcknowledged === true
          if (draft.questionnaireLoaded || ['questionnaire', 'diagnosis', 'review'].includes(draft.stage)) {
            await loadQuestions()
            if (!isCurrent()) return
            replaceAnswers(form, answersFor(questions.value, draft.form))
          }
          if (!isCurrent()) return
          stepStage.value = draft.stage === 'domain' ? 'domain' : 'track'
          let profile = null
          if (draft.profile && profileMatchesDirection(draft.profile, direction, owner)) {
            try {
              const response = await profileApi.get(draft.profile.learner_id)
              if (!isCurrent()) return
              if (profileMatchesDirection(response.data, direction, owner) && response.data.profile_version === draft.profile.profile_version) profile = response.data
              else ElMessage.warning('学习记录已更新，已保留问卷答案，请重新确认')
            } catch (error) {
              if (error?.response?.status !== 404) throw error
              ElMessage.warning('原学习记录已不存在，已恢复问卷答案')
            }
          }
          if (profile) {
            store.setLearnerId(profile.learner_id)
            store.setLearningDirectionId(direction.track_id)
            store.setLearningDirectionName(direction.name)
            setProfile(profile)
            setPendingQuestions(Array.isArray(draft.diagnosticQuestions) ? draft.diagnosticQuestions : [])
            setDiagnosis(draft.diagnosis && typeof draft.diagnosis === 'object' ? draft.diagnosis : null)
            replaceAnswers(diagnosticAnswers, answersFor(diagnosticQuestions.value, draft.diagnosticAnswers))
          }
          if (questions.value.length && ['questionnaire', 'diagnosis', 'review'].includes(draft.stage)) {
            stepStage.value = draft.stage === 'review' && diagnosisResult.value ? 'review'
              : draft.stage === 'diagnosis' && profile && diagnosticQuestions.value.length ? 'diagnosis' : 'questionnaire'
            if (draft.profile && !profile) stepStage.value = 'track'
          }
          selectedResourceTypes.value = Array.isArray(draft.resourceTypes) ? draft.resourceTypes.filter(type => resourceTypeOptions.includes(type)) : selectedResourceTypes.value
          includeClaimCheck.value = draft.includeClaimCheck === true
          includeClaimEvidenceRetrieval.value = includeClaimCheck.value && draft.includeClaimEvidenceRetrieval === true
          supplementalRequirements.value = typeof draft.supplementalRequirements === 'string' ? draft.supplementalRequirements : ''
          selectedInitialNodeId.value = typeof draft.initialNodeId === 'string' ? draft.initialNodeId : ''
          if (stepStage.value === 'review') await loadInitialNodeCandidates()
        } else stepStage.value = 'track'
      } else clearDraft(owner)
    }
    if (isCurrent()) draftReady = true
  } catch {
    if (isCurrent()) recoveryError.value = '初始化或恢复草稿失败，旧草稿已保留，请重试。'
  } finally { if (isCurrent()) initializing.value = false }
}
onMounted(initializeFlow)
onBeforeRouteLeave(() => {
  if (submittingProfile.value || submittingDiagnosis.value || submittingGeneration.value || deletingProgress.value) {
    ElMessage.warning('正在提交或删除，请完成后再离开')
    return false
  }
  saveDraft()
})
</script>

<style scoped>
.existing-progress-list { display:grid; width:100%; gap:10px; max-height:300px; overflow:auto; margin:16px 0; }
.existing-progress-list :deep(.el-radio) { height:auto; margin:0; padding:12px; border:1px solid #dce3e9; border-radius:6px; white-space:normal; }
.existing-progress-list :deep(.el-radio__label) { display:grid; gap:6px; min-width:0; overflow-wrap:anywhere; line-height:1.7; }
.existing-progress-list small { color:#59697b; }
.existing-progress-actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.existing-progress-actions :deep(.el-button) { margin:0; }
.onboarding-page {
  --setup-ink:#172c45; --setup-muted:#59697b; --setup-line:#dce3e9;
  --setup-accent:#176b70; --setup-mint:#9cf2e0;
  --el-color-primary:#176b70; --el-color-primary-light-9:#eef8f6;
  --el-color-primary-light-3:#6a9fa2;
  display:flex; flex-direction:column; min-width:0; gap:22px;
  padding-top:24px; color:var(--setup-ink);
}
.card-kicker,.choice-code,.progress-heading span,.progress-footer > span:last-child { font-family:Consolas,'SFMono-Regular',monospace; font-size:10px; line-height:1.6; }
.wizard-layout { display:grid; grid-template-columns:232px minmax(0,1fr); align-items:stretch; gap:0; min-width:0; }
.progress-panel { position:sticky; isolation:isolate; top:16px; display:flex; flex-direction:column; min-width:0; min-height:590px; padding:26px 18px 23px; border:1px solid #213b51; border-radius:0; background:linear-gradient(150deg,#112840 0%,#0d2238 58%,#0b1d31 100%); color:#eaf2f9; overflow:hidden; }
.progress-heading { display:flex; align-items:center; gap:12px; padding:0 5px 24px; border-bottom:1px solid #354b60; }
.progress-heading > .el-icon { display:grid; place-items:center; flex:0 0 34px; width:34px; height:34px; border:1px solid #8bded640; border-radius:3px; background:#a2e8df0b; font-size:19px; color:var(--setup-mint); }
.progress-heading span { display:block; color:#b8cadb; font-size:9px; }
.progress-heading strong { display:block; margin-top:5px; font-size:15px; font-weight:600; }
.progress-list { display:flex; flex:1; flex-direction:column; justify-content:space-evenly; align-items:stretch; gap:8px; min-height:0; margin:20px -4px 18px; }
.progress-card { position:relative; display:grid; flex:0 0 auto; grid-template-columns:32px minmax(0,1fr); align-items:center; gap:12px; width:100%; min-width:0; min-height:62px; padding:10px 9px; border:1px solid transparent; border-radius:0; background:transparent; color:#d6e1ec; text-align:left; cursor:pointer; transition:background-color 180ms ease,border-color 180ms ease,box-shadow 180ms ease,transform 180ms ease; }
.progress-index { position:relative; z-index:1; display:flex; justify-content:center; align-items:center; width:32px; height:32px; border:1px solid #658095; border-radius:50%; background:#102339; color:#d1deea; font:11px/1 Consolas,monospace; }
.progress-index .el-icon { font-size:16px; }
.progress-copy { position:relative; z-index:1; display:flex; flex-direction:column; min-width:0; }
.progress-title { display:block; font-size:14px; font-weight:600; line-height:1.65; }
.progress-desc { display:block; margin-top:4px; color:#b8cadb; font-size:11px; line-height:1.6; overflow-wrap:anywhere; }
.progress-card.active { align-self:flex-start; flex:0 0 auto; width:100%; max-width:100%; border-color:#8fe3d633; border-radius:10px; background:#274657; color:#b3f6e9; box-shadow:inset 0 0 0 1px #8fe3d61a,0 4px 12px #06172740; }
.progress-card.active .progress-index { border-color:var(--setup-mint); background:var(--setup-mint); color:#102339; }
.progress-card.done:not(.active) .progress-index { border-color:#8ecec6; background:#a1e7df0c; color:#adf1e4; }
.progress-card:disabled { cursor:not-allowed; }
.progress-card:disabled .progress-title,.progress-card:disabled .progress-index { color:#adc0d1; }
.progress-card:hover:not(.active):not(:disabled) { border-color:#8fe3d622; background-color:#b0ebe20b; transform:translateX(2px); }
.progress-card.active:hover:not(:disabled) { border-color:#9ce9df70; background:#2c5263; }
.progress-footer { position:relative; z-index:1; display:grid; grid-template-columns:22px minmax(0,1fr); gap:10px; align-items:start; margin-top:auto; padding:18px 5px 0; border-top:1px solid #8db6c125; }
.progress-footer-mark { color:#a2e8df; font-size:20px; }
.progress-footer p { margin:0; color:#c2d2e0; font-size:11px; line-height:1.9; }
.progress-footer > span:last-child { grid-column:1/-1; color:#b8cadb; font-size:9px; }
.step-panel { display:flex; flex-direction:column; min-width:0; }
@media (min-width:1081px) {
  .onboarding-page:not(.is-fit-layout):not(.is-contained-layout) { padding-top:0; }
  .onboarding-page:not(.is-fit-layout):not(.is-contained-layout) .wizard-layout { align-items:stretch; }
  .onboarding-page:not(.is-fit-layout):not(.is-contained-layout) .progress-panel { position:relative; top:auto; align-self:stretch; }
  .onboarding-page:not(.is-fit-layout):not(.is-contained-layout) .work-card { min-height:100%; }
}
.work-card { flex:1; border:1px solid var(--setup-line); border-left:0; border-radius:0; background:#fff; box-shadow:none; overflow:visible; }
.work-card :deep(.el-card__header) { padding:26px 30px 23px; border-bottom:1px solid var(--setup-line); }
.work-card :deep(.el-card__body) { min-width:0; padding:22px 30px 0; }
.card-head { display:flex; justify-content:space-between; align-items:center; gap:20px; }
.card-head > div { min-width:0; }
.card-head .card-title { display:flex; align-items:center; gap:9px; }
.stage-heading-icon.el-icon {
  flex:0 0 auto;
  width:20px;
  color:var(--setup-accent);
  font-size:20px;
}
.stage-heading-meta { display:flex; flex-wrap:wrap; align-items:baseline; gap:2px 10px; margin-bottom:6px; }
.stage-heading-meta .card-kicker { margin-bottom:0; }
.stage-context { color:var(--setup-muted); font-size:11px; overflow-wrap:anywhere; }
.card-kicker { display:block; margin-bottom:8px; color:var(--setup-accent); }
.card-title { margin:0; color:var(--setup-ink); font-size:26px; font-weight:650; line-height:1.4; text-wrap:balance; }
.card-subtitle { margin:9px 0 0; padding-inline-start:29px; color:var(--setup-muted); font-size:13px; line-height:1.75; }
.step-coordinate { flex:0 0 auto; align-self:flex-start; color:#b6c6ce; font:34px/1.2 Consolas,monospace; }
.step-coordinate > span { display:block; margin-top:5px; color:var(--setup-muted); font-size:10px; text-align:right; }
.overview-strip { display:grid; grid-template-columns:1fr 1fr minmax(0,1.5fr); margin-bottom:22px; padding-bottom:18px; border-bottom:1px solid var(--setup-line); }
.overview-chip { min-width:0; padding:0 22px; border-left:1px solid var(--setup-line); }
.overview-chip:first-child { padding-left:0; border-left:0; }
.overview-chip span { display:block; color:var(--setup-muted); font-size:11px; line-height:1.6; }
.overview-chip strong { display:block; margin-top:5px; color:var(--setup-ink); font:600 23px/1.4 Consolas,'Microsoft YaHei',sans-serif; overflow-wrap:anywhere; }
.overview-chip strong small { color:var(--setup-muted); font-size:12px; font-weight:400; }
.overview-person strong { font-family:inherit; font-size:14px; line-height:1.7; }
.card-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
.choice-card { position:relative; display:flex; flex-direction:column; gap:9px; min-width:0; min-height:180px; padding:18px 20px 16px; border:1px solid var(--setup-line); border-radius:0; background:#fff; color:var(--setup-ink); text-align:left; cursor:pointer; transition:background-color 180ms ease,border-color 180ms ease; }
.choice-topline { display:flex; align-items:center; gap:11px; margin-bottom:4px; }
.choice-icon { width:31px; height:31px; color:var(--setup-accent); font-size:26px; }
.choice-code { color:var(--setup-muted); font-size:9px; }
.choice-selector { display:flex; align-items:center; justify-content:center; width:18px; height:18px; margin-left:auto; border:1px solid #a7b8c5; border-radius:50%; color:#fff; }
.choice-selector .el-icon { font-size:12px; }
.choice-title { font-size:18px; font-weight:650; line-height:1.5; overflow-wrap:anywhere; }
.choice-description { flex:1; color:var(--setup-muted); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.choice-bottom { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-top:5px; }
.choice-bottom > .el-icon { flex:0 0 auto; color:var(--setup-accent); font-size:16px; }
.choice-meta { color:var(--setup-muted); font-size:11px; line-height:1.7; }
.meta-divider { margin-inline:8px; color:#8d9baa; }
.choice-card:hover:not(:disabled) { border-color:#639ca1; background:#f8fbfb; }
.choice-card.selected { border-color:var(--setup-accent); background:#f1f8f7; box-shadow:inset 3px 0 0 var(--setup-accent); }
.choice-card.selected .choice-selector { border-color:var(--setup-accent); background:var(--setup-accent); }
.choice-card.unavailable { background:#f5f7f9; cursor:not-allowed; }
.choice-card.unavailable .choice-topline,.choice-card.unavailable .choice-bottom > .el-icon { color:var(--setup-muted); }
.track-number { color:var(--setup-accent); font:22px/1.2 Consolas,monospace; }
.track-grid .choice-card { min-height:187px; }
.action-row { display:flex; align-items:center; justify-content:flex-end; gap:14px; margin-top:24px; padding:20px 0; border-top:1px solid var(--setup-line); }
.action-hint { flex:1; min-width:0; color:var(--setup-muted); font-size:11px; line-height:1.6; overflow-wrap:anywhere; }
.action-row :deep(.el-button) { flex:0 0 auto; min-width:112px; min-height:44px; height:auto; margin:0; padding:12px 20px; border-radius:4px; color:var(--setup-ink); font-size:13px; font-weight:600; line-height:1.4; }
.action-row :deep(.el-button > span) { gap:16px; }
.action-row :deep(.el-button--primary) { border-color:#102f3f; background:#102f3f; color:var(--setup-mint); }
.action-row :deep(.el-button--primary:hover:not(.is-disabled)) { border-color:#194557; background:#194557; }
.action-row :deep(.el-button--primary.is-disabled) { border-color:#d5e0e5; background:#eaf0f2; color:#677d89; }
.action-row :deep(.back-button) { min-width:90px; padding-inline:8px; border-color:transparent; background:transparent; color:var(--setup-muted); }
.action-row :deep(.back-button:hover) { background:#f1f5f7; color:var(--setup-ink); }
.action-row :deep(.manage-progress-button.is-link) { color:var(--setup-accent); }
/* Element Plus input/select wrappers and textareas already provide their focus border. */
.onboarding-page :deep(button:focus-visible) { outline:2px solid #176b70; outline-offset:3px; }
/* 选项卡的焦点描边贴合自身边框，避免悬浮空隙。 */
.onboarding-page :deep(.el-checkbox:focus-within),.onboarding-page :deep(.el-radio:focus-within) { outline:2px solid #176b70; outline-offset:0; }
.progress-panel button:focus-visible { outline-color:var(--setup-mint); }
.questionnaire-form { width:100%; }
.question-block,.diagnostic-item { min-width:0; padding:25px 0; margin:0; border-bottom:1px solid var(--setup-line); }
.question-block :deep(.el-form-item__label) { display:flex; align-items:flex-start; gap:12px; width:100%; height:auto; padding:0; margin-bottom:14px; color:var(--setup-ink); font-size:14px; font-weight:600; line-height:1.7; }
.question-block :deep(.el-form-item__label::before) { display:none; }
.question-block.is-required :deep(.el-form-item__label > span:nth-child(2)::after) { margin-left:5px; color:#b42318; content:'*'; }
.question-number { flex:0 0 auto; padding-top:2px; color:var(--setup-accent); font:11px/1.8 Consolas,monospace; }
.question-kind { flex:0 0 auto; margin-left:auto; padding-top:2px; color:var(--setup-muted); font-size:10px; font-weight:400; line-height:1.7; }
.question-block :deep(.el-form-item__content) { display:flex; flex-direction:column; align-items:stretch; min-width:0; line-height:1.5; }
.question-hint { margin:0 0 12px; color:var(--setup-muted); font-size:12px; line-height:1.75; }
.full-control { width:100%; }
.questionnaire-form :deep(.el-select) { --select-height:46px; }
.questionnaire-form :deep(.el-input__wrapper),.diagnostic-item :deep(.el-input__wrapper) { min-height:46px; padding:8px 14px; border-radius:4px; background:#f8fafb; box-shadow:0 0 0 1px #c8d4dd inset; }
.questionnaire-form :deep(.el-textarea__inner),.diagnostic-item :deep(.el-textarea__inner) { padding:12px 14px; border-radius:4px; background:#f8fafb; color:var(--setup-ink); line-height:1.7; box-shadow:0 0 0 1px #c8d4dd inset; }
.questionnaire-form :deep(.el-input__inner) { color:var(--setup-ink); font-size:13px; }
.questionnaire-form :deep(.el-input__inner::placeholder),.questionnaire-form :deep(.el-textarea__inner::placeholder) { color:#647689; }
.questionnaire-form :deep(.el-input__wrapper.is-focus),.questionnaire-form :deep(.el-textarea__inner:focus),.diagnostic-item :deep(.el-textarea__inner:focus) { box-shadow:0 0 0 2px var(--setup-accent) inset; }
.answer-options { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; width:100%; }
.answer-options :deep(:is(.el-checkbox,.el-radio)) {
  display:flex;
  align-items:center;
  min-width:0;
  height:auto;
  min-height:46px;
  margin:0;
  padding:10px 14px;
  border:1px solid #cddde5;
  border-radius:9px;
  background:linear-gradient(155deg,#fff 10%,#f0f6f8);
  box-shadow:inset 0 1px 0 #fff,0 2px 3px rgb(31 65 85 / 8%),0 7px 15px -11px rgb(31 65 85 / 28%);
  color:var(--setup-ink);
  transition:border-color 180ms ease,box-shadow 180ms ease;
}
.answer-options :deep(:is(.el-checkbox__input,.el-radio__input)) { flex-shrink:0; }
.answer-options :deep(:is(.el-checkbox__label,.el-radio__label)) { min-width:0; padding-left:10px; color:var(--setup-ink); font-size:13px; line-height:1.6; white-space:normal; overflow-wrap:anywhere; }
@media (hover:hover) {
  .answer-options :deep(:is(.el-checkbox,.el-radio):not(.is-disabled):hover) {
    border-color:#77aab0;
    box-shadow:inset 0 1px 0 #fff,0 3px 6px rgb(31 83 93 / 12%),0 8px 16px -10px rgb(31 83 93 / 32%);
  }
}
.answer-options :deep(:is(.el-checkbox,.el-radio).is-checked) {
  border-color:#6ba5a8;
  background:linear-gradient(120deg,#f1faf9,#dcefeb);
  box-shadow:inset 0 1px 0 #fff,0 2px 4px rgb(23 107 112 / 15%),0 8px 16px -12px rgb(23 107 112 / 32%);
}
.answer-options :deep(:is(.el-checkbox,.el-radio).is-checked :is(.el-checkbox__label,.el-radio__label)) { font-weight:600; }
.onboarding-page .answer-options :deep(:is(.el-checkbox,.el-radio):focus-within) { outline:0; }
.onboarding-page .answer-options :deep(:is(.el-checkbox,.el-radio):has(input:focus-visible)) { outline:2px solid var(--setup-accent); outline-offset:2px; }
.answer-options :deep(.el-checkbox__input.is-checked .el-checkbox__inner),.answer-options :deep(.el-radio__input.is-checked .el-radio__inner) { background:var(--setup-accent); border-color:var(--setup-accent); }
.answer-options :deep(.el-checkbox__inner),.answer-options :deep(.el-radio__inner) { border-color:#879eaf; }
.diagnostic-heading { display:flex; align-items:flex-start; gap:12px; margin-bottom:18px; }
.question-title { min-width:0; margin:0; font-size:14px; font-weight:600; line-height:1.8; overflow-wrap:anywhere; }
.questionnaire-form .action-row { margin-top:0; border-top:0; }
.diagnosis-result-card { flex:1 1 auto; display:flex; flex-direction:column; justify-content:center; gap:14px; overflow:hidden; border:0; border-radius:18px; }
.diagnosis-identity-row { display:flex; justify-content:space-between; align-items:center; gap:14px; padding:16px 20px 0; }
.diagnosis-identity { flex:1 1 auto; min-width:0; padding:12px 14px; border:1px solid rgba(255,255,255,.85); border-radius:12px; background:rgba(255,255,255,.72); box-shadow:0 2px 6px -2px rgba(23,107,112,.14); }
.diagnosis-identity .card-kicker { color:#7d939c; font-size:9px; letter-spacing:.08em; }
.diagnosis-identity strong { display:block; margin-top:2px; color:#172c45; font-size:15px; font-weight:600; line-height:1.4; overflow-wrap:anywhere; }
.ability-stage { flex:0 0 auto; padding:10px 14px; border:1px solid rgba(255,255,255,.85); border-radius:12px; background:rgba(255,255,255,.72); box-shadow:0 2px 6px -2px rgba(23,107,112,.14); text-align:right; }
.ability-stage span { display:block; color:#59697b; font-size:10px; }
.ability-stage span em { margin-left:2px; color:#8ba2ad; font:9px Consolas,monospace; font-style:normal; }
.ability-stage strong { display:block; margin-top:2px; color:#176b70; font-size:16px; font-weight:600; }
.diagnosis-point-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:0; margin:0 20px; padding:14px 0 18px; border-top:1px solid #dce4eb; }
.diagnosis-point-card { min-width:0; padding:0 14px; }
.diagnosis-point-card:first-child { padding-left:0; }
.diagnosis-point-card:last-child { padding-right:0; }
.diagnosis-point-card + .diagnosis-point-card { border-left:1px solid #dce4eb; }
.diagnosis-point-card > span { display:flex; align-items:center; gap:7px; color:#59697b; font-size:11px; }
.diagnosis-point-card > span > .el-icon { color:#176b70; font-size:15px; }
.diagnosis-point-card > span em { margin-left:auto; color:#8ba2ad; font-size:10px; font-style:normal; }
.diagnosis-point-card p { margin:4px 0 0; color:#172c45; font-size:13px; font-weight:600; line-height:1.5; overflow-wrap:anywhere; }
.diagnosis-point-card p small { display:block; margin-top:3px; color:#59697b; font-size:10.5px; font-weight:400; line-height:1.55; }
.review-stage-card :deep(.el-card__body) { display:flex; flex-direction:column; gap:16px; padding-bottom:18px; }
.resource-selection-form { display:flex; flex:0 0 auto; flex-direction:column; margin-top:0; }
.resource-selection-form .action-row { margin-top:16px; padding-top:0; }
.resource-selection-form :deep(.el-form-item) { margin-bottom:14px; }
.resource-selection-form :deep(.el-form-item__label) { height:auto; margin-bottom:6px; padding:0; color:var(--setup-ink); font-size:13px; font-weight:600; line-height:1.6; }
.resource-selection-form :deep(.el-form-item__content) { min-width:0; }
.field-hint { margin-top:9px; color:var(--setup-muted); font-size:12px; line-height:1.75; }
.resource-type-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px; width:100%; }
.resource-type-grid :deep(.el-checkbox) { position:relative; min-width:0; height:auto; margin:0; padding:10px 10px 9px; align-items:flex-start; border:1px solid rgba(23,107,112,.18); border-radius:9px; background:linear-gradient(165deg, rgba(23,107,112,.045), rgba(255,255,255,.55)); box-shadow:inset 0 1px 0 rgba(255,255,255,.75); transition:background .18s ease, border-color .18s ease, box-shadow .18s ease; cursor:pointer; }
.resource-type-grid :deep(.el-checkbox:hover) { border-color:rgba(23,107,112,.4); background:linear-gradient(165deg, rgba(23,107,112,.08), rgba(255,255,255,.6)); }
.resource-type-grid :deep(.el-checkbox__input) { position:absolute; top:8px; right:8px; }
.resource-type-grid :deep(.el-checkbox__label) { min-width:0; width:100%; padding:0; color:var(--setup-ink); white-space:normal; }
.resource-type-grid :deep(.el-checkbox.is-checked) { border-color:rgba(23,107,112,.6); background:linear-gradient(165deg, rgba(23,107,112,.12), rgba(156,242,224,.14)); box-shadow:inset 0 1px 0 rgba(255,255,255,.8), 0 6px 14px -8px rgba(23,107,112,.35); }
.resource-type-grid :deep(.el-checkbox__inner) { border-color:#879eaf; }
.resource-type-grid :deep(.el-checkbox__input.is-checked .el-checkbox__inner) { border-color:var(--setup-accent); background:var(--setup-accent); }
.resource-option { display:grid; grid-template-columns:18px minmax(0,1fr); align-items:center; column-gap:7px; padding-right:16px; }
.resource-option > .el-icon { grid-column:1; grid-row:1; font-size:16px; color:var(--setup-accent); }
.resource-option strong { grid-column:2; grid-row:1; font-size:12.5px; font-weight:600; line-height:1.3; }
.resource-option > span { grid-column:1/-1; grid-row:2; margin-top:5px; color:var(--setup-muted); font-size:10px; line-height:1.45; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.claim-review-row { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; width:100%; }
.claim-review-control { display:flex; gap:9px; align-items:center; width:100%; padding:9px 12px; border:1px solid rgba(23,107,112,.18); border-radius:9px; background:linear-gradient(165deg, rgba(23,107,112,.045), rgba(255,255,255,.55)); box-shadow:inset 0 1px 0 rgba(255,255,255,.75); }
.claim-icon { flex:0 0 auto; color:var(--setup-accent); font-size:16px; }
.claim-review-control > div { flex:1; min-width:0; }
.claim-review-control strong { display:block; color:var(--setup-ink); font-size:12px; font-weight:600; line-height:1.4; }
.claim-review-control p { margin:2px 0 0; color:var(--setup-muted); font-size:10.5px; line-height:1.5; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.claim-review-control :deep(.el-switch) { flex:0 0 auto; --el-switch-on-color:#176b70; --el-switch-off-color:#758897; }
.claim-review-control :deep(.el-switch__label) { color:var(--setup-muted); }
@media (max-width:1080px) { .resource-type-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }
@media (max-width:600px) { .resource-type-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .claim-review-row { grid-template-columns:1fr; } }
.claim-review-control :deep(.el-switch__label.is-active) { color:var(--setup-accent); }
.onboarding-page:is(.is-fit-layout,.is-contained-layout) { height:100%; min-height:0; display:grid; grid-template-rows:minmax(0,1fr); gap:0; padding-top:0; }
.onboarding-page.is-fit-layout { padding-top:0; }
.onboarding-page:is(.is-fit-layout,.is-contained-layout):has(> .el-alert) { grid-template-rows:auto minmax(0,1fr); }
:is(.is-fit-layout,.is-contained-layout) .wizard-layout { min-height:0; align-items:stretch; }
:is(.is-fit-layout,.is-contained-layout) .progress-panel { position:relative; top:auto; height:100%; min-height:0; padding-block:clamp(16px,2.7dvh,28px); }
:is(.is-fit-layout,.is-contained-layout) .progress-heading { padding-bottom:clamp(16px,2dvh,24px); }
:is(.is-fit-layout,.is-contained-layout) .progress-list { flex:1; min-height:0; gap:8px; margin-block:clamp(14px,2dvh,22px); }
:is(.is-fit-layout,.is-contained-layout) .progress-card { flex:0 0 auto; min-height:62px; padding-block:10px; }
:is(.is-fit-layout,.is-contained-layout) .progress-footer { flex:0 0 auto; padding-top:16px; }
:is(.is-fit-layout,.is-contained-layout) .step-panel { height:100%; min-height:0; }
:is(.is-fit-layout,.is-contained-layout) .work-card { display:flex; flex-direction:column; height:100%; min-height:0; }
:is(.is-fit-layout,.is-contained-layout) .work-card :deep(.el-card__header) { flex:0 0 auto; padding:clamp(15px,2dvh,22px) 24px; }
:is(.is-fit-layout,.is-contained-layout) .work-card :deep(.el-card__body) { display:flex; flex:1; flex-direction:column; min-height:0; padding:16px 24px 0; }
.onboarding-page.is-fit-layout .work-card :deep(.el-card__body) { overflow-x:hidden; overflow-y:auto; overscroll-behavior:contain; scrollbar-width:thin; scrollbar-color:#9db8c2 transparent; }
:is(.is-fit-layout,.is-contained-layout) .card-kicker { margin-bottom:6px; font-size:10px; line-height:1.4; }
:is(.is-fit-layout,.is-contained-layout) .card-title { font-size:clamp(22px,2.8dvh,27px); line-height:1.3; }
:is(.is-fit-layout,.is-contained-layout) .card-subtitle { margin-top:7px; font-size:12px; line-height:1.7; }
:is(.is-fit-layout,.is-contained-layout) .overview-strip { flex:0 0 auto; margin-bottom:16px; padding-bottom:13px; }
:is(.is-fit-layout,.is-contained-layout) .overview-chip strong { font-size:21px; line-height:1.3; }
:is(.is-fit-layout,.is-contained-layout) .overview-person strong { font-size:13px; line-height:1.7; }
:is(.is-fit-layout,.is-contained-layout) .card-grid { flex:1; min-height:0; grid-auto-rows:minmax(0,1fr); gap:12px; }
:is(.is-fit-layout,.is-contained-layout) .choice-card { min-height:0; padding:12px 16px; gap:6px; }
:is(.is-fit-layout,.is-contained-layout) .choice-topline { margin:0; }
:is(.is-fit-layout,.is-contained-layout) .choice-icon { width:25px; height:25px; font-size:23px; }
:is(.is-fit-layout,.is-contained-layout) .choice-title { font-size:16px; line-height:1.4; }
:is(.is-fit-layout,.is-contained-layout) .choice-description { font-size:12px; line-height:1.65; }
:is(.is-fit-layout,.is-contained-layout) .choice-bottom { margin-top:0; }
:is(.is-fit-layout,.is-contained-layout) .action-row { flex:0 0 auto; margin-top:16px; padding-block:15px; }
.card-title:focus-visible { outline:2px solid var(--setup-accent); outline-offset:5px; }
@media (min-width:1100px) and (max-height:760px) {
  .onboarding-page:is(.is-fit-layout,.is-contained-layout) { gap:0; padding-top:0; }
  :is(.is-fit-layout,.is-contained-layout) .progress-panel { padding:16px 12px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-heading { padding-bottom:12px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-list { margin-block:12px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-card { min-height:58px; padding-block:7px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-title { font-size:13px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-desc { margin-top:2px; font-size:10px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-footer { padding-top:12px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-footer p { font-size:10px; }
  :is(.is-fit-layout,.is-contained-layout) .work-card :deep(.el-card__header) { padding:14px 20px; }
  :is(.is-fit-layout,.is-contained-layout) .work-card :deep(.el-card__body) { padding:12px 20px 0; }
  :is(.is-fit-layout,.is-contained-layout) .card-kicker { margin-bottom:4px; font-size:9px; }
  :is(.is-fit-layout,.is-contained-layout) .card-title { font-size:22px; }
  :is(.is-fit-layout,.is-contained-layout) .card-subtitle { margin-top:5px; font-size:11px; }
  :is(.is-fit-layout,.is-contained-layout) .step-coordinate { font-size:28px; }
  :is(.is-fit-layout,.is-contained-layout) .overview-strip { padding-bottom:10px; margin-bottom:12px; }
  :is(.is-fit-layout,.is-contained-layout) .overview-chip { display:flex; align-items:baseline; gap:10px; padding-inline:16px; }
  :is(.is-fit-layout,.is-contained-layout) .overview-chip:first-child { padding-left:0; }
  :is(.is-fit-layout,.is-contained-layout) .overview-chip strong { margin:0; font-size:18px; }
  :is(.is-fit-layout,.is-contained-layout) .overview-person strong { font-size:12px; }
  :is(.is-fit-layout,.is-contained-layout) .card-grid { gap:10px; }
  :is(.is-fit-layout,.is-contained-layout) .choice-card { padding:10px 12px; gap:5px; }
  :is(.is-fit-layout,.is-contained-layout) .choice-topline { position:absolute; top:10px; left:12px; right:12px; }
  :is(.is-fit-layout,.is-contained-layout) .choice-icon,:is(.is-fit-layout,.is-contained-layout) .track-number { width:22px; height:22px; font-size:20px; }
  :is(.is-fit-layout,.is-contained-layout) .choice-code { display:none; }
  :is(.is-fit-layout,.is-contained-layout) .choice-title { padding-inline:30px 20px; font-size:14px; line-height:1.6; }
  :is(.is-fit-layout,.is-contained-layout) .choice-description { font-size:11px; line-height:1.6; }
  :is(.is-fit-layout,.is-contained-layout) .choice-meta { font-size:10px; }
  :is(.is-fit-layout,.is-contained-layout) .action-row { margin-top:10px; padding-block:11px; }
}
@media (min-width:1600px) {
  .wizard-layout { grid-template-columns:254px minmax(0,1fr); }
  .work-card :deep(.el-card__header),.work-card :deep(.el-card__body) { padding-inline:36px; }
  .choice-card { min-height:192px; padding:22px 24px; }
}
@media (max-width:1300px) and (min-width:1081px) {
  .wizard-layout { grid-template-columns:204px minmax(0,1fr); }
  .progress-panel { padding-inline:12px; }
  .work-card :deep(.el-card__header) { padding:22px; }
  .work-card :deep(.el-card__body) { padding-inline:22px; }
}
@media (max-width:1080px) {
  .onboarding-page { gap:18px; padding-top:20px; }
  .wizard-layout { grid-template-columns:1fr; }
  .progress-panel { position:relative; top:auto; min-height:0; padding:13px 16px; border-radius:0; }
  .work-card { border-left:1px solid var(--setup-line); border-top:0; border-radius:0; }
  .progress-heading,.progress-footer,.progress-desc { display:none; }
  .progress-list { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:0; margin:0; }
  .progress-card { display:flex; flex-direction:column; align-items:center; gap:6px; min-height:64px; padding:4px; text-align:center; }
  .progress-index { width:30px; height:30px; }
  .progress-title { font-size:12px; }
  .progress-card.active { align-self:stretch; width:100%; }
}
@media (max-width:720px) {
  .work-card :deep(.el-card__header) { padding:22px 20px 18px; }
  .work-card :deep(.el-card__body) { padding:20px 20px 0; }
  .card-title { font-size:23px; }
  .step-coordinate { font-size:29px; }
  .card-subtitle { font-size:12px; }
  .resource-type-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
@media (max-width:600px) {
  .onboarding-page { gap:16px; padding-top:19px; }
  .progress-panel { padding:11px 8px; }
  .progress-title { font-size:11px; }
  .progress-index { width:28px; height:28px; font-size:10px; }
  .progress-card { min-height:58px; }
  .card-head { gap:10px; }
  .card-title { font-size:21px; }
  .card-subtitle { margin-top:7px; }
  .step-coordinate { font-size:25px; }
  .overview-chip { padding-inline:12px; }
  .overview-strip { grid-template-columns:1fr 1fr; row-gap:14px; }
  .overview-chip.overview-person { grid-column:1/-1; grid-row:2; padding:12px 0 0; border-left:0; border-top:1px solid var(--setup-line); }
  .track-stage-card .overview-strip .overview-person { grid-row:1; padding:0 0 12px; border-top:0; border-bottom:1px solid var(--setup-line); }
  .track-stage-card .overview-chip:nth-child(2) { padding-left:0; border-left:0; }
  .card-grid,.answer-options { grid-template-columns:1fr; }
  .choice-card,.track-grid .choice-card { min-height:165px; }
  .action-row { flex-wrap:wrap; gap:10px; padding-block:18px; }
  .action-hint { flex:1 0 100%; order:-1; }
  .action-row :deep(.el-button--primary) { flex:1; min-width:0; }
  .action-row :deep(.el-button > span) { justify-content:center; gap:10px; }
  .question-block,.diagnostic-item { padding-block:22px; }
  .question-block :deep(.el-form-item__label),.diagnostic-heading { gap:9px; }
  .question-kind { font-size:9px; }
  .diagnosis-identity-row { flex-direction:column; align-items:stretch; padding:12px 16px 10px; }
  .ability-stage { text-align:left; }
  .diagnosis-point-grid { grid-template-columns:1fr; margin:2px 16px 12px; }
  .diagnosis-point-card + .diagnosis-point-card { margin-top:10px; padding:10px 0 0; border-left:0; border-top:1px solid #dce4eb; }
  .claim-review-control { flex-wrap:wrap; gap:10px; }
  .claim-review-control > div { flex-basis:calc(100% - 36px); }
  .claim-review-control :deep(.el-switch) { margin-left:33px; }
}
@media (max-width:600px) {
  .review-stage-card .action-row { display:grid; grid-template-columns:minmax(0,1fr); }
  .review-stage-card .action-hint { order:0; grid-row:1; }
  .review-stage-card .action-row :deep(.el-button--primary) { grid-row:2; width:100%; }
  .claim-review-control :deep(.el-switch) { min-height:44px; }
}
.is-contained-layout .work-card :deep(.el-card__body) { display:block; overflow-x:hidden; overflow-y:auto; overscroll-behavior:contain; scrollbar-gutter:stable; scrollbar-width:thin; scrollbar-color:#9db8c2 transparent; }
.is-contained-layout .work-card :deep(.el-card__body:focus-visible) { outline:2px solid var(--setup-accent); outline-offset:-2px; }
@media (max-width:1080px) {
  .is-contained-layout .wizard-layout { grid-template-rows:auto minmax(0,1fr); }
  .is-contained-layout .progress-panel { height:auto; padding:10px 12px; }
  .is-contained-layout .progress-list { flex:none; margin:0; }
  .is-contained-layout .progress-card { padding:4px; }
}
@media (max-width:600px) and (max-height:760px) {
  .onboarding-page.is-contained-layout { gap:0; padding-top:0; }
  .is-contained-layout .progress-panel { padding:8px 10px; }
  .is-contained-layout .progress-card { min-height:52px; gap:4px; }
  .is-contained-layout .work-card :deep(.el-card__header) { padding:12px 16px; }
  .is-contained-layout .work-card :deep(.el-card__body) { padding:12px 16px 0; }
  .is-contained-layout .card-kicker { margin-bottom:4px; font-size:9px; }
  .is-contained-layout .card-title { font-size:20px; }
  .is-contained-layout .card-subtitle { margin-top:5px; font-size:11px; line-height:1.6; }
}
/* Compact only the direction step; the domain step keeps its existing sizing. */
@media (min-width:1081px) {
  .onboarding-page.is-track-stage:not(.is-fit-layout) { gap:12px; padding-top:12px; }
  .is-track-stage:not(.is-fit-layout) .track-stage-card :deep(.el-card__header) { padding:14px 24px; }
  .is-track-stage:not(.is-fit-layout) .track-stage-card :deep(.el-card__body) { padding:12px 24px 0; }
  .is-track-stage:not(.is-fit-layout) .track-stage-card .card-kicker { margin-bottom:4px; }
  .is-track-stage:not(.is-fit-layout) .track-stage-card .card-title { font-size:23px; line-height:1.3; }
  .is-track-stage:not(.is-fit-layout) .track-stage-card .card-subtitle { margin-top:5px; font-size:12px; line-height:1.5; }
  .is-track-stage:not(.is-fit-layout) .track-stage-card .overview-strip { margin-bottom:12px; padding-bottom:10px; }
  .is-track-stage:not(.is-fit-layout) .track-stage-card .overview-chip { display:flex; align-items:baseline; gap:10px; }
  .is-track-stage:not(.is-fit-layout) .track-stage-card .overview-chip strong { margin:0; font-size:20px; }
  .is-track-stage:not(.is-fit-layout) .track-stage-card .overview-person strong { font-size:13px; }
  .is-track-stage:not(.is-fit-layout) .track-grid { flex:0 0 auto; gap:10px; grid-auto-rows:auto; }
  .is-track-stage:not(.is-fit-layout) .track-grid .choice-card { min-height:142px; padding:12px 16px; gap:6px; }
  .is-track-stage:not(.is-fit-layout) .track-grid .choice-topline { position:static; margin:0; }
  .is-track-stage:not(.is-fit-layout) .track-grid .track-number { font-size:19px; }
  .is-track-stage:not(.is-fit-layout) .track-grid .choice-title { padding:0; font-size:16px; line-height:1.4; }
  .is-track-stage:not(.is-fit-layout) .track-grid .choice-description { font-size:12px; line-height:1.55; }
  .is-track-stage:not(.is-fit-layout) .track-grid .choice-bottom { margin-top:0; }
  .is-track-stage:not(.is-fit-layout) .track-stage-card .action-row { margin-top:12px; padding-block:10px; }
}
@media (prefers-reduced-motion:reduce) {
  .onboarding-page *, .onboarding-page *::before, .onboarding-page *::after { transition:none !important; animation:none !important; }
}
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .card-kicker { font-size:10px; letter-spacing:.1em; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .card-title { font-size:25px; font-weight:700; line-height:1.3; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .card-subtitle { color:#536b80; font-size:14px; line-height:1.6; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-chip span { font-size:12px; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-chip strong { font-size:21px; line-height:1.35; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-person strong { font-size:14px; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-strip {
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:14px;
  padding-bottom:18px;
  margin-bottom:18px;
}
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-chip {
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding:12px 18px;
  border:0;
  border-radius:12px;
  background:
    linear-gradient(90deg,transparent,#fff 20%,rgb(255 255 255 / 45%) 80%,transparent) 14px 1px / 70% 1px no-repeat,
    radial-gradient(ellipse at 90% 0%,rgb(214 238 239 / 80%),transparent 70%),
    linear-gradient(180deg,rgb(249 252 254 / 94%),rgb(232 241 246 / 88%));
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 90%),
    inset 0 -1px 1px rgb(111 142 167 / 20%),
    0 3px 5px -4px rgb(33 64 86 / 28%),
    0 10px 20px -14px rgb(33 64 86 / 34%);
}
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-chip span { color:#506b7e; font-size:14px; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-chip strong { margin:0; font-size:26px; line-height:1.3; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-person strong { font-family:inherit; font-size:20px; font-weight:600; line-height:1.3; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card {
  --domain-accent:#247d83;
  --domain-tint:#e9f5f3;
  display:flex;
  justify-content:space-between;
  gap:12px;
  padding:24px 26px;
  overflow:hidden;
  border-color:#d6e1e8;
  border-radius:10px;
  background:radial-gradient(ellipse at 100% 0%,var(--domain-tint),transparent 72%),linear-gradient(145deg,#fff,#f6f9fb);
  box-shadow:inset 0 1px 0 #fff,0 5px 14px -11px rgb(29 63 86 / 28%);
  transition:background 180ms ease,border-color 180ms ease,box-shadow 180ms ease;
}
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card:nth-child(2) { --domain-accent:#466db0; --domain-tint:#edf2fc; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card:nth-child(3) { --domain-accent:#7161a4; --domain-tint:#f1edfa; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card:nth-child(4) { --domain-accent:#416c8c; --domain-tint:#eaf2f7; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card > :not(.domain-emblem) { position:relative; z-index:1; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-topline { position:relative; inset:auto; gap:14px; margin:0; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-icon {
  width:48px;
  height:48px;
  border:1px solid rgb(125 156 181 / 18%);
  border-radius:12px;
  background:linear-gradient(150deg,#fff,var(--domain-tint));
  box-shadow:inset 0 1px 0 #fff,0 4px 9px -7px rgb(35 70 90 / 35%);
  color:var(--domain-accent);
  font-size:31px;
}
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .domain-emblem {
  position:absolute;
  right:30px;
  top:50%;
  width:104px;
  height:104px;
  font-size:104px;
  color:var(--domain-accent);
  opacity:.085;
  transform:translateY(-30%) rotate(-8deg);
  pointer-events:none;
}
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-code { color:#61798b; font-size:10px; letter-spacing:.08em; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-title { max-width:85%; padding:0; font-size:26px; font-weight:700; line-height:1.35; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-description { flex:0 0 auto; max-width:82%; color:#526b80; font-size:16px; line-height:1.75; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-bottom { margin:0; padding-top:12px; border-top:1px solid rgb(142 170 189 / 18%); }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-meta { color:#5d7387; font-size:13px; line-height:1.5; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-bottom > .el-icon { font-size:17px; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-selector { border-color:#9eb4c1; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card:hover:not(:disabled) {
  border-color:#83afb2;
  background:radial-gradient(ellipse at 100% 0%,var(--domain-tint),transparent 85%),linear-gradient(145deg,#fff,#f4faf9);
  box-shadow:inset 0 1px 0 #fff,0 8px 18px -15px rgb(25 94 101 / 45%);
}
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card.selected {
  border-color:#217e7b;
  background:radial-gradient(ellipse at 100% 0%,#d6eeea,transparent 72%),linear-gradient(135deg,#eef9f6,#f8fcfb);
  box-shadow:inset 0 0 0 1px rgb(33 126 123 / 20%),0 9px 20px -16px rgb(18 99 100 / 48%);
}
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card.selected .choice-selector { border-color:#176b70; background:#176b70; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card.unavailable {
  border-color:#e0e7eb;
  background:radial-gradient(ellipse at 100% 0%,var(--domain-tint),transparent 72%),linear-gradient(145deg,#f9fbfc,#f4f7f9);
  box-shadow:inset 0 1px 0 rgb(255 255 255 / 90%);
}
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card:focus-visible { outline:2px solid #176b70; outline-offset:3px; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .action-hint { color:#526b80; font-size:13px; }
.onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .action-row :deep(.el-button) { font-size:14px; }
@media (max-width:720px) {
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .card-title { font-size:23px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .card-subtitle { font-size:13px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card { padding:18px; gap:10px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-title { font-size:22px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-description { max-width:90%; font-size:14px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .domain-emblem { font-size:80px; right:15px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-strip { gap:8px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-chip { flex-direction:column; align-items:flex-start; gap:8px; padding:12px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-stage-card,.track-stage-card) .overview-person { grid-column:auto; grid-row:auto; border:0; }
}
@media (min-width:1081px) and (max-height:760px) {
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-card { padding:16px 20px; gap:8px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-icon { width:36px; height:36px; font-size:25px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-title { font-size:22px; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-description { font-size:14px; line-height:1.6; }
  .onboarding-page:is(.is-domain-stage,.is-track-stage) :is(.domain-grid,.track-grid) .choice-bottom { padding-top:8px; }
}
.onboarding-page.is-track-stage .track-stage-card .overview-strip { grid-template-columns:repeat(3,minmax(0,1fr)); }
.onboarding-page.is-track-stage .track-grid .choice-card.selected { border-left-width:1px; }
.onboarding-page.is-track-stage .track-grid .choice-card { gap:8px; padding-block:20px; }
.onboarding-page.is-track-stage .track-grid .choice-card .choice-bottom { flex:0 0 auto; margin-top:auto; }
.onboarding-page.is-track-stage .track-grid .choice-card.track-rag {
  --domain-accent:#277f85;
  --domain-tint:#e8f5f2;
  background:linear-gradient(150deg,#fff 25%,#e7f3f2 100%);
}
.onboarding-page.is-track-stage .track-grid .choice-card.track-agent {
  --domain-accent:#7862a3;
  --domain-tint:#f0ecf8;
  background:radial-gradient(ellipse at 90% 60%,#e9e2f4,transparent 65%),linear-gradient(135deg,#fff,#f8f6fc);
}
.onboarding-page.is-track-stage .track-grid .choice-card.track-api {
  --domain-accent:#3a71a0;
  --domain-tint:#eaf2fa;
  background:linear-gradient(115deg,#fff 30%,#eaf2fa);
}
.onboarding-page.is-track-stage .track-grid .choice-card:is(.track-rag,.track-agent,.track-api) .choice-icon {
  border:0;
  border-radius:0;
  background:none;
  box-shadow:none;
  width:42px;
  height:42px;
  font-size:36px;
}
.onboarding-page.is-track-stage .track-grid .choice-card > .track-artwork {
  position:absolute;
  z-index:0;
  right:10px;
  bottom:36px;
  width:180px;
  height:113px;
  color:var(--domain-accent);
  opacity:.22;
  pointer-events:none;
}
.onboarding-page.is-track-stage .track-grid .choice-card:is(.track-rag,.track-agent,.track-api) .choice-title { max-width:100%; }
.onboarding-page.is-track-stage .track-grid .choice-card:is(.track-rag,.track-agent,.track-api) .choice-description { max-width:78%; }
.onboarding-page.is-track-stage .track-grid .choice-card.track-agent .choice-bottom { border-top-color:rgb(120 98 163 / 18%); }
.onboarding-page.is-track-stage .track-grid .choice-card.track-api .choice-bottom { border-top-style:dashed; border-top-color:rgb(58 113 160 / 24%); }
.onboarding-page.is-track-stage .track-grid .choice-card:is(.track-rag,.track-agent,.track-api).selected { border-color:var(--domain-accent); box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--domain-accent) 18%,transparent),0 7px 16px -13px var(--domain-accent); }
@media (max-width:720px), (max-height:760px) {
  .onboarding-page.is-track-stage .track-grid .choice-card > .track-artwork { width:130px; height:82px; right:0; opacity:.15; }
  .onboarding-page.is-track-stage .track-grid .choice-card:is(.track-rag,.track-agent,.track-api) .choice-description { max-width:95%; }
}
.review-stage-card :deep(.el-card__body) { display:flex; flex:1; flex-direction:column; min-height:0; padding:16px 20px 20px; }
.review-stage-layout { display:grid; flex:1 1 0%; min-height:0; grid-template-columns:minmax(285px,.82fr) minmax(0,1.45fr); grid-template-rows:minmax(0,1fr) auto; grid-template-areas:"summary resources" "actions actions"; align-content:stretch; align-items:stretch; gap:18px; }
.review-stage-layout > * { min-height:0; }
.review-stage-layout > .resource-selection-form:first-child { grid-area:resources; grid-column:1/-1; }
.review-stage-card .diagnosis-result-card {
  grid-area:summary;
  width:100%;
  height:100%;
  min-height:0;
  align-self:stretch;
  box-sizing:border-box;
  justify-content:flex-start;
  gap:0;
  border-radius:14px;
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 85%),
    inset 0 -1px 1px rgb(111 142 167 / 22%),
    0 4px 8px -4px rgb(33 64 86 / 25%),
    0 13px 25px -14px rgb(33 64 86 / 32%);
}
.review-stage-card .diagnosis-identity-row {
  align-items:stretch;
  gap:12px;
  padding:20px 20px 18px;
}
.review-stage-card .diagnosis-identity,
.review-stage-card .ability-stage {
  display:flex;
  flex-direction:column;
  justify-content:center;
  border:0;
  border-radius:14px;
  background:
    linear-gradient(90deg,transparent,#fff 20%,rgb(255 255 255 / 45%) 80%,transparent) 14px 1px / 70% 1px no-repeat,
    radial-gradient(ellipse at 90% 0%,rgb(214 238 239 / 80%),transparent 70%),
    linear-gradient(180deg,rgb(249 252 254 / 94%),rgb(232 241 246 / 88%));
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 90%),
    inset 0 -1px 1px rgb(111 142 167 / 20%),
    0 3px 5px -4px rgb(33 64 86 / 28%),
    0 10px 20px -14px rgb(33 64 86 / 34%);
}
.review-stage-card .diagnosis-identity { padding:16px; }
.review-stage-card .diagnosis-identity .card-kicker { margin-bottom:8px; color:#526e7e; font-family:inherit; font-size:12px; font-weight:400; line-height:1.5; letter-spacing:normal; white-space:nowrap; }
.review-stage-card .diagnosis-identity .card-kicker em { display:inline; margin:0 0 0 5px; color:#607f8e; font:normal 12px/1.5 Consolas,monospace; letter-spacing:.02em; }
.review-stage-card .diagnosis-identity strong { margin:0; font-size:20px; font-weight:650; line-height:1.45; }
.review-stage-card .ability-stage { min-width:112px; padding:16px 12px; text-align:center; }
.review-stage-card .ability-stage span { color:#526e7e; font-size:12px; line-height:1.5; white-space:nowrap; }
.review-stage-card .ability-stage span em { display:inline; margin:0 0 0 5px; color:#607f8e; font:normal 12px/1.5 Consolas,monospace; letter-spacing:.02em; }
.review-stage-card .ability-stage strong { margin-top:6px; color:#176b70; font-size:20px; font-weight:650; line-height:1.45; }
.review-stage-card .diagnosis-point-grid {
  display:grid;
  flex:1;
  grid-template-columns:minmax(0,1fr);
  grid-template-rows:1.15fr .9fr .95fr;
  min-height:0;
  align-content:stretch;
  margin:0 20px;
  padding:0 0 12px;
}
.review-stage-card .diagnosis-point-card { display:flex; flex-direction:column; justify-content:center; gap:9px; min-height:0; padding:20px 0; }
.review-stage-card .diagnosis-point-card + .diagnosis-point-card { border-top:1px solid rgb(124 157 178 / 20%); border-left:0; }
.review-stage-card .diagnosis-point-card > span { gap:10px; color:#4b697b; font-size:14px; line-height:1.5; }
.review-stage-card .diagnosis-point-card > span > .el-icon { flex:0 0 auto; font-size:24px; color:#247e84; }
.review-stage-card .diagnosis-point-card > span em {
  display:inline-flex;
  flex:0 0 auto;
  align-items:center;
  justify-content:center;
  min-height:28px;
  padding:4px 11px;
  border:1px solid rgb(93 158 166 / 25%);
  border-radius:8px;
  background:linear-gradient(145deg,rgb(255 255 255 / 92%),rgb(219 240 239 / 80%));
  box-shadow:inset 0 1px 0 #fff,0 3px 7px -5px rgb(33 95 108 / 32%);
  color:#286b76;
  font-size:12px;
  font-weight:600;
  line-height:1.4;
  letter-spacing:.04em;
  white-space:nowrap;
}
.review-stage-card .diagnosis-point-card p { margin:0; padding-inline-start:34px; color:#18364a; font-size:20px; font-weight:650; line-height:1.45; }
.review-stage-card .diagnosis-point-recommend p > strong { font-size:inherit; font-weight:inherit; line-height:inherit; }
.review-stage-card .diagnosis-point-card p small { margin-top:8px; color:#587484; font-size:12px; line-height:1.7; }
.review-stage-card .resource-selection-form { grid-area:resources; display:flex; flex:1; flex-direction:column; min-height:0; margin:0; }
.review-stage-card .resource-selection-form :deep(.el-form-item) { min-width:0; margin-bottom:12px; }
.review-stage-card .resource-selection-form > :deep(.el-form-item:last-child) { margin-bottom:0; }
.review-stage-card .resource-selection-form :deep(.el-form-item__label) { font-size:15px; font-weight:650; line-height:1.6; margin-bottom:8px; }
.review-stage-card .resource-selection-form :deep(.resource-type-field) { display:flex; flex:1; flex-direction:column; min-height:0; }
.review-stage-card .resource-selection-form :deep(.resource-type-field .el-form-item__content) { display:flex; flex:1; min-height:0; align-items:stretch; }
.review-stage-card .resource-selection-form .resource-type-grid { flex:1; min-height:0; grid-template-columns:repeat(2,minmax(0,1fr)); grid-auto-rows:minmax(72px,1fr); align-content:stretch; gap:10px; }
.review-stage-card .resource-selection-form .resource-type-grid :deep(.el-checkbox),
.review-stage-card .resource-selection-form .claim-review-control {
  border:1px solid rgb(158 184 198 / 26%);
  border-radius:13px;
  background:
    radial-gradient(ellipse at 95% 0%,rgb(218 239 240 / 65%),transparent 64%),
    linear-gradient(160deg,#fbfdfe,#edf4f8);
  box-shadow:inset 0 1px 0 #fff,inset 0 -1px 1px rgb(109 143 161 / 12%),
    0 3px 5px -4px rgb(33 64 86 / 25%),0 10px 20px -17px rgb(33 64 86 / 32%);
}
.review-stage-card .resource-selection-form .resource-type-grid :deep(.el-checkbox) { display:flex; align-items:stretch; margin-block:7px; padding:12px 18px; }
.review-stage-card .resource-selection-form .resource-type-grid :deep(.el-checkbox:hover) {
  border-color:rgb(49 127 136 / 45%);
  box-shadow:inset 0 1px 0 #fff,0 5px 16px -10px rgb(29 98 112 / 35%);
}
.review-stage-card .resource-selection-form .resource-type-grid :deep(.el-checkbox.is-checked) {
  border-color:rgb(44 134 137 / 44%);
  background:radial-gradient(ellipse at 95% 0%,rgb(190 234 227 / 65%),transparent 70%),
    linear-gradient(150deg,#f6fcfb,#e7f3f2);
  box-shadow:inset 0 1px 0 #fff,inset 0 -1px 1px rgb(58 127 130 / 18%),
    0 4px 7px -5px rgb(22 101 107 / 30%),0 12px 20px -18px rgb(22 101 107 / 35%);
}
.review-stage-card .resource-selection-form .resource-type-grid :deep(.el-checkbox__input) { top:13px; right:13px; }
.review-stage-card .resource-selection-form .resource-type-grid :deep(.el-checkbox__label) { display:flex; align-items:stretch; }
.review-stage-card .resource-selection-form .resource-option { width:100%; height:100%; grid-template-columns:32px minmax(0,1fr); column-gap:12px; align-content:center; padding-right:12px; }
.review-stage-card .resource-selection-form .resource-option > .el-icon { font-size:29px; color:#237c84; }
.review-stage-card .resource-selection-form .resource-option strong { font-size:19px; font-weight:650; line-height:1.4; }
.review-stage-card .resource-selection-form .resource-option > span { margin-top:11px; font-size:13px; line-height:1.65; white-space:normal; overflow:visible; text-overflow:clip; }
.review-stage-card .resource-selection-form .claim-review-row { gap:10px; }
.review-stage-card .resource-selection-form .claim-review-control { min-height:78px; padding:15px 16px; gap:12px; }
.review-stage-card .resource-selection-form .claim-icon { font-size:24px; }
.review-stage-card .resource-selection-form .claim-review-control strong { font-size:15px; line-height:1.5; }
.review-stage-card .resource-selection-form .claim-review-control p { margin-top:5px; font-size:12px; line-height:1.6; white-space:normal; }
.review-stage-layout > .review-actions { grid-area:actions; display:flex; flex:0 0 auto; width:100%; align-items:center; gap:14px; margin:0; padding:14px 0 10px; border-top:1px solid #dce4eb; }
.review-stage-layout > .review-actions .action-hint { font-size:12px; }
.initial-node-fallback { display:flex; flex-wrap:wrap; align-items:center; gap:8px; color:var(--setup-muted); }
@media (min-width:1081px) and (min-height:760px) {
  .onboarding-page.is-contained-layout .review-stage-card :deep(.el-card__body) {
    display:flex;
    flex-direction:column;
    overflow:hidden;
    scrollbar-gutter:auto;
  }
}
@media (max-width:1080px) {
  .review-stage-card :deep(.el-card__body) { display:block; overflow-x:hidden; overflow-y:auto; padding:14px 18px 18px; }
  .review-stage-layout { display:flex; height:auto; flex-direction:column; gap:14px; min-height:auto; }
  .review-stage-layout > .resource-selection-form:first-child { width:100%; }
  .review-stage-card .diagnosis-result-card { height:auto; min-height:0; }
  .review-stage-card .diagnosis-point-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); grid-template-rows:auto; gap:0; margin:0 18px; padding:14px 0 16px; }
  .review-stage-card .diagnosis-point-card { display:block; padding:0 12px; }
  .review-stage-card .diagnosis-point-card:first-child { padding-left:0; }
  .review-stage-card .diagnosis-point-card:last-child { padding-right:0; }
  .review-stage-card .diagnosis-point-card + .diagnosis-point-card { border-top:0; border-left:1px solid #dce4eb; }
  .review-stage-card .resource-selection-form { height:auto; flex:none; }
  .review-stage-card .resource-selection-form :deep(.resource-type-field) { flex:none; }
  .review-stage-card .resource-selection-form :deep(.resource-type-field .el-form-item__content) { flex:none; }
  .review-stage-card .resource-selection-form .resource-type-grid { grid-template-columns:repeat(3,minmax(0,1fr)); grid-auto-rows:auto; }
  .review-stage-layout > .review-actions { margin-top:0; }
}
@media (max-width:600px) {
  .review-stage-card :deep(.el-card__body) { padding:12px 14px 16px; }
  .review-stage-layout { gap:12px; }
  .review-stage-card .diagnosis-identity-row { align-items:stretch; padding:12px 14px 10px; }
  .review-stage-card .ability-stage { min-width:82px; padding:8px 10px; }
  .review-stage-card .diagnosis-point-grid { display:grid; grid-template-columns:minmax(0,1fr); grid-template-rows:auto; margin:0 14px; padding:4px 0 12px; }
  .review-stage-card .diagnosis-point-card { padding:10px 0; }
  .review-stage-card .diagnosis-point-card + .diagnosis-point-card { border-top:1px solid #dce4eb; border-left:0; }
  .review-stage-card .resource-selection-form .resource-type-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .review-stage-card .resource-selection-form .resource-type-grid :deep(.el-checkbox) { padding:16px 12px; }
  .review-stage-card .resource-selection-form .resource-option { grid-template-columns:24px minmax(0,1fr); gap:8px; }
  .review-stage-card .resource-selection-form .resource-option > .el-icon { font-size:23px; }
  .review-stage-card .resource-selection-form .resource-option strong { font-size:16px; }
  .review-stage-card .resource-selection-form .resource-option > span { font-size:12px; }
  .review-stage-card .resource-selection-form .claim-review-row { grid-template-columns:1fr; }
  .review-stage-layout > .review-actions { display:grid; grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr); grid-template-rows:auto auto; gap:8px; }
  .review-stage-layout > .review-actions .action-hint { grid-column:1/-1; grid-row:1; order:0; }
  .review-stage-layout > .review-actions .back-button { grid-column:1; grid-row:2; justify-self:start; }
  .review-stage-layout > .review-actions :deep(.el-button--primary) { grid-column:2; grid-row:2; width:100%; }
}
</style>
