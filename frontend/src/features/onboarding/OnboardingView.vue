<template>
  <div ref="setupRoot" class="onboarding-page" :class="{ 'is-fit-layout': fitLayout, 'is-contained-layout': containedLayout }">
    <header class="setup-intro">
      <div><span class="setup-eyebrow">BUILD YOUR LEARNING PATH</span><h2>让目标，成为你的学习路径。</h2></div>
      <p>选定方向，了解起点，开启专属于你的技能学习。</p>
    </header>
    <section class="wizard-layout" aria-label="新建学习方向">
      <aside class="progress-panel" aria-label="学习方向创建步骤">
        <div class="progress-heading"><el-icon aria-hidden="true"><Connection /></el-icon><div><span>LEARNING SETUP</span><strong>构建学习方向</strong></div></div>
        <nav class="progress-list" aria-label="五步创建流程">
          <button v-for="step in steps" :key="step.stage" type="button" class="progress-card"
            :class="{ active: stepStage === step.stage, done: completedStepCount >= step.index, disabled: !canEnter(step.stage) }"
            :disabled="!canEnter(step.stage)" :aria-current="stepStage === step.stage ? 'step' : undefined"
            :aria-label="step.title + '：' + step.description()" @click="goStep(step.stage)">
            <span class="progress-index" aria-hidden="true"><el-icon v-if="completedStepCount >= step.index && stepStage !== step.stage"><Check /></el-icon><span v-else>{{ String(step.index).padStart(2, '0') }}</span></span>
            <span class="progress-copy"><span class="progress-title">{{ step.title }}</span><span class="progress-desc">{{ step.description() }}</span></span>
            <span v-if="stepStage === step.stage" class="progress-current" aria-hidden="true"></span>
          </button>
        </nav>
        <div class="progress-footer"><span class="progress-footer-mark" aria-hidden="true"><el-icon><Aim /></el-icon></span><p>以目标定义方向<br />以诊断找到起点</p><span>KNOWLEDGE → SKILL</span></div>
      </aside>
      <div class="step-panel" v-module-motion="{ key: stepStage, order: steps.findIndex(step => step.stage === stepStage), slideTarget: '.card-head' }">
        <el-card v-if="stepStage === 'domain'" class="work-card domain-stage-card" shadow="never">
          <template #header><div class="card-head"><div><span class="card-kicker">01 / EXPLORE</span><h3 class="card-title" tabindex="-1">你想探索哪个领域？</h3><p class="card-subtitle">从最想应用的领域出发，下一步选择具体的训练方向。</p></div><span class="step-coordinate" aria-hidden="true">01<span>/ 05</span></span></div></template>
          <div class="overview-strip">
            <div class="overview-chip"><span>培训领域</span><strong>{{ domains.length }}<small> 个</small></strong></div>
            <div class="overview-chip"><span>学习方向</span><strong>{{ totalTrackCount }}<small> 个</small></strong></div>
            <div class="overview-chip overview-person"><span>为你创建</span><strong>{{ currentUser?.display_name || currentUser?.username || '未设置' }}</strong></div>
          </div>
          <div class="card-grid domain-grid" role="group" aria-label="选择培训领域">
            <button v-for="(item, index) in domains" :key="item.domain_id" type="button" class="choice-card" :class="{ selected: selectedDomainId === item.domain_id }" :aria-pressed="selectedDomainId === item.domain_id" @click="selectDomain(item)">
              <span class="choice-topline"><el-icon class="choice-icon" aria-hidden="true"><component :is="domainIcons[index % domainIcons.length]" /></el-icon><span class="choice-code" aria-hidden="true">FIELD / {{ String(index + 1).padStart(2, '0') }}</span><span class="choice-selector" aria-hidden="true"><el-icon v-if="selectedDomainId === item.domain_id"><Check /></el-icon></span></span>
              <span class="choice-title">{{ item.name }}</span><span class="choice-description">{{ item.description || '暂无描述' }}</span>
              <span class="choice-bottom"><span class="choice-meta">{{ item.tracks?.length || 0 }} 个学习方向</span><el-icon aria-hidden="true"><ArrowRight /></el-icon></span>
            </button>
          </div>
          <section class="insight-card" aria-label="选择提示"><el-icon aria-hidden="true"><MagicStick /></el-icon><div><strong>从你想解决的问题开始</strong><p>优先选择接下来想落地实践的业务领域。已有具体目标？你可以在后续补充个性化要求。</p></div></section>
          <div class="action-row"><span class="action-hint">{{ selectedDomain ? '已选择：' + selectedDomain.name : '选择一个领域，继续探索' }}</span><el-button type="primary" :disabled="!selectedDomainId" @click="goStep('track')">下一步<el-icon aria-hidden="true"><ArrowRight /></el-icon></el-button></div>
        </el-card>

        <el-card v-else-if="stepStage === 'track'" class="work-card track-stage-card" shadow="never">
          <template #header><div class="card-head"><div><span class="card-kicker">02 / FOCUS</span><h3 class="card-title" tabindex="-1">找到你的训练方向</h3><p class="card-subtitle">围绕具体目标，让知识、诊断与练习形成一条清晰的路径。</p></div><span class="step-coordinate" aria-hidden="true">02<span>/ 05</span></span></div></template>
          <div class="overview-strip"><div class="overview-chip overview-person"><span>当前领域</span><strong>{{ selectedDomain?.name || '-' }}</strong></div><div class="overview-chip"><span>可选方向</span><strong>{{ tracks.length }}<small> 个</small></strong></div><div class="overview-chip"><span>资料总量</span><strong>{{ selectedDomainDocumentCount }}<small> 份</small></strong></div></div>
          <div class="card-grid track-grid" role="group" aria-label="选择学习方向">
            <button v-for="(item, index) in tracks" :key="item.track_id" type="button" class="choice-card" :class="{ selected: selectedDirectionId === item.track_id, unavailable: !isTrackAvailable(item) }" :disabled="!isTrackAvailable(item)" :aria-pressed="selectedDirectionId === item.track_id" @click="selectDirection(item)">
              <span class="choice-topline"><span class="track-number" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span><span class="choice-code">{{ isTrackAvailable(item) ? 'TRAINING TRACK' : '暂不可用' }}</span><span class="choice-selector" aria-hidden="true"><el-icon v-if="selectedDirectionId === item.track_id"><Check /></el-icon></span></span>
              <span class="choice-title">{{ item.name }}</span><span class="choice-description">{{ item.description || '暂无描述' }}</span>
              <span class="choice-bottom"><span class="choice-meta">{{ item.metadata?.document_count || 0 }} 份资料<span class="meta-divider">/</span>{{ item.metadata?.skill_node_count || 0 }} 个能力节点</span><el-icon aria-hidden="true"><ArrowRight /></el-icon></span>
            </button>
          </div>
          <section class="insight-card" aria-label="选择建议"><el-icon aria-hidden="true"><Aim /></el-icon><div><strong>聚焦一个具体的学习目标</strong><p>选择接下来最想训练的方向。系统会围绕该方向建立独立画像，持续记录你的学习与进步。</p></div></section>
          <div class="action-row"><el-button class="back-button" :icon="ArrowLeft" @click="goStep('domain')">上一步</el-button><span class="action-hint">{{ selectedDirection ? '已选择：' + selectedDirection.name : '选择一个方向，开始建立画像' }}</span><el-button type="primary" :disabled="!selectedDirectionId" @click="prepareQuestionnaire">下一步<el-icon aria-hidden="true"><ArrowRight /></el-icon></el-button></div>
        </el-card>

        <el-card v-else-if="stepStage === 'questionnaire'" class="work-card questionnaire-stage-card" shadow="never" :aria-busy="submittingProfile">
          <template #header><div class="card-head"><div><span class="card-kicker">03 / PROFILE</span><h3 class="card-title" tabindex="-1">让学习更了解你</h3><p class="card-subtitle">告诉我们你的目标与学习偏好，为当前方向建立初始画像。</p></div><span class="step-coordinate" aria-hidden="true">03<span>/ 05</span></span></div></template>
          <div class="form-context"><el-icon aria-hidden="true"><Aim /></el-icon><div><span>正在为此方向建立画像</span><strong>{{ selectedDirection?.name }}</strong></div><span class="form-context-count">{{ visibleQuestions.length }} 个问题</span></div>
          <el-form label-position="top" class="questionnaire-form">
            <el-form-item v-for="question in questions" :key="question.question_id" v-show="shouldShow(question)" class="question-block" :data-question-id="question.question_id" :label="question.title" :required="question.required">
              <template #label><span class="question-number" aria-hidden="true">{{ questionNumber(question) }}</span><span>{{ question.title }}</span><span class="question-kind">{{ questionTypeLabel(question.type) }}</span></template>
              <p v-if="question.hint" :id="'hint-' + question.question_id" class="question-hint">{{ question.hint }}</p>
              <el-input v-if="question.type === 'text'" v-model="form[question.question_id]" :aria-label="question.title" :aria-describedby="question.hint ? 'hint-' + question.question_id : undefined" :placeholder="question.hint || '请输入'" />
              <el-select v-else-if="question.type === 'single_choice' || question.type === 'single_choice_or_other'" v-model="form[question.question_id]" :allow-create="question.type === 'single_choice_or_other'" filterable default-first-option placeholder="请选择" class="full-control" :aria-label="question.title" :aria-describedby="question.hint ? 'hint-' + question.question_id : undefined">
                <el-option v-for="option in normalizedOptions(question)" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
              <el-checkbox-group v-else-if="question.type === 'multiple_choice'" v-model="form[question.question_id]" class="answer-options" :aria-label="question.title" :aria-describedby="question.hint ? 'hint-' + question.question_id : undefined">
                <el-checkbox v-for="option in normalizedOptions(question)" :key="option.value" :label="option.value" :value="option.value">{{ option.label }}</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <div class="action-row"><el-button class="back-button" :icon="ArrowLeft" @click="goStep('track')">上一步</el-button><span class="action-hint">提交后，系统将判断是否需要进一步诊断</span><el-button type="primary" :loading="submittingProfile" @click="submitQuestionnaire">提交问卷<el-icon v-if="!submittingProfile" aria-hidden="true"><ArrowRight /></el-icon></el-button></div>
          </el-form>
        </el-card>

        <el-card v-else-if="stepStage === 'diagnosis'" class="work-card diagnosis-stage-card" shadow="never" :aria-busy="submittingDiagnosis">
          <template #header><div class="card-head"><div><span class="card-kicker">04 / ASSESS</span><h3 class="card-title" tabindex="-1">找到你的能力起点</h3><p class="card-subtitle">通过实际问题了解掌握情况，让后续资源与你的能力相匹配。</p></div><span class="step-coordinate" aria-hidden="true">04<span>/ 05</span></span></div></template>
          <div class="form-context"><el-icon aria-hidden="true"><DataAnalysis /></el-icon><div><span>当前诊断方向</span><strong>{{ selectedDirection?.name }}</strong></div><span class="form-context-count">{{ diagnosticQuestions.length }} 道诊断题</span></div>
          <template v-if="diagnosticQuestions.length">
            <div v-for="(question, index) in diagnosticQuestions" :key="question.question_id" class="diagnostic-item" :data-question-id="question.question_id">
              <div class="diagnostic-heading"><span class="question-number" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span><h4 class="question-title" :id="'diagnosis-' + question.question_id">{{ question.question }}</h4><span class="question-kind">{{ questionTypeLabel(question.question_type) }}</span></div>
              <el-radio-group v-if="question.question_type === 'single_choice'" v-model="diagnosticAnswers[question.question_id]" class="answer-options" :aria-labelledby="'diagnosis-' + question.question_id"><el-radio v-for="option in question.options || []" :key="option" :label="option" :value="option">{{ option }}</el-radio></el-radio-group>
              <el-checkbox-group v-else-if="question.question_type === 'multiple_choice'" v-model="diagnosticAnswers[question.question_id]" class="answer-options" :aria-labelledby="'diagnosis-' + question.question_id"><el-checkbox v-for="option in question.options || []" :key="option" :label="option" :value="option">{{ option }}</el-checkbox></el-checkbox-group>
              <el-input v-else v-model="diagnosticAnswers[question.question_id]" type="textarea" :rows="3" :aria-labelledby="'diagnosis-' + question.question_id" placeholder="写下你的理解或处理思路" />
            </div>
            <div class="action-row"><el-button class="back-button" :icon="ArrowLeft" @click="goStep('questionnaire')">上一步</el-button><span class="action-hint">诊断结果将用于推荐首个学习节点</span><el-button type="primary" :loading="submittingDiagnosis" @click="submitDiagnosis">提交诊断<el-icon v-if="!submittingDiagnosis" aria-hidden="true"><ArrowRight /></el-icon></el-button></div>
          </template>
          <el-empty v-else description="当前没有需要作答的诊断题，提交问卷后系统会自动判断是否需要诊断。" />
        </el-card>

        <el-card v-else class="work-card review-stage-card" shadow="never" :aria-busy="submittingGeneration">
          <template #header><div class="card-head"><div><span class="card-kicker">05 / CREATE</span><h3 class="card-title" tabindex="-1">准备好，开启你的学习</h3><p class="card-subtitle">确认能力画像，选择资源，把你的目标转化为下一步行动。</p></div><span class="step-coordinate" aria-hidden="true">05<span>/ 05</span></span></div></template>
          <section v-if="diagnosisResult" class="result-card diagnosis-result-card" aria-label="诊断结果">
            <div class="result-heading"><div><span class="card-kicker">YOUR LEARNING PROFILE</span><h4>{{ selectedDirection?.name }}</h4><p>{{ currentUser?.display_name || currentUser?.username || '-' }} · 初始能力画像</p></div><div class="ability-stage"><span>能力阶段</span><strong>{{ diagnosisResult.ability_level || '-' }}</strong></div></div>
            <div class="diagnosis-result-body">
              <div class="diagnosis-point-grid"><section class="diagnosis-point-card"><span><el-icon aria-hidden="true"><Aim /></el-icon>优先加强</span><p>{{ (diagnosisResult.weak_points || []).join('、') || '暂无明显薄弱点' }}</p></section><section class="diagnosis-point-card"><span><el-icon aria-hidden="true"><Check /></el-icon>已有优势</span><p>{{ (diagnosisResult.strong_points || []).join('、') || '暂无明确优势点' }}</p></section></div>
              <div v-if="initialRecommendedNodeId" class="initial-node-recommendation"><el-icon aria-hidden="true"><Connection /></el-icon><div><span class="initial-node-recommendation__kicker">首次学习建议 · {{ initialRecommendedNodeTier }}</span><strong class="initial-node-recommendation__node">{{ initialRecommendedNodeLoading ? '正在读取节点名称…' : initialRecommendedNodeLabel }}</strong><p>首批资源将围绕该节点生成。完成学习与后续测评后，系统会继续更新你的学习路径。</p></div></div>
            </div>
          </section>
          <el-form label-position="top" class="questionnaire-form resource-selection-form">
            <el-form-item label="本次要生成的资源类型" required class="resource-type-field"><div class="field-hint resource-hint">按你的学习习惯自由组合，可选择多种。</div><el-checkbox-group class="resource-type-grid" v-model="selectedResourceTypes" aria-label="本次要生成的资源类型"><el-checkbox v-for="item in resourceTypeOptions" :key="item" :label="item" :value="item"><span class="resource-option"><el-icon aria-hidden="true"><component :is="resourceVisuals[item].icon" /></el-icon><strong>{{ item }}</strong><span>{{ resourceVisuals[item].description }}</span></span></el-checkbox></el-checkbox-group></el-form-item>
            <el-form-item label="Claim 强化审查"><div class="claim-review-control"><el-icon class="claim-icon" aria-hidden="true"><Lock /></el-icon><div><strong>对关键事实逐条核对来源证据</strong><p>开启后增加事实审查与必要修订，生成耗时会相应增加。</p></div><el-switch v-model="includeClaimCheck" active-text="开启" inactive-text="关闭" aria-label="Claim 强化审查" /></div></el-form-item>
            <el-form-item label="补充要求" class="supplemental-field"><el-input v-model="supplementalRequirements" type="textarea" :rows="3" aria-label="补充要求" placeholder="可选。例如：更想看案例拆解、增加练习题，或优先覆盖 Embedding 和 Rerank。" /><div class="field-hint">系统会结合方向、诊断结果与资源类型安排生成任务，你可以在此补充具体目标。</div></el-form-item>
            <div class="action-row"><el-button class="back-button" :icon="ArrowLeft" @click="goStep('diagnosis')">上一步</el-button><span class="action-hint">已选择 {{ selectedResourceTypes.length }} 种资源</span><el-button type="primary" :loading="submittingGeneration" @click="submitGeneration">生成并进入状态页<el-icon v-if="!submittingGeneration" aria-hidden="true"><ArrowRight /></el-icon></el-button></div>
          </el-form>
        </el-card>
      </div>
    </section>
    <footer class="setup-footer"><span>让知识有依据，让成长有路径。</span><span>智域匠学 / LEARNING WORKSPACE</span></footer>
  </div>
</template>


<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Aim, ArrowLeft, ArrowRight, Check, Collection, Connection, DataAnalysis, Document, EditPen, List, Lock, MagicStick, Monitor, Reading } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { diagnosisApi, generateApi, knowledgeApi, onboardingApi } from '../../api'
import { useAuthStore } from '../../stores/auth'
import { useAppStore } from '../../stores/app'

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
const supplementalRequirements = ref('')
const initialRecommendedNodeName = ref('')
const initialRecommendedNodeLoading = ref(false)

const form = reactive({})
const diagnosticAnswers = reactive({})

const currentUser = computed(() => auth.currentUser || store.currentUserProfile || null)
const selectedDomain = computed(() => domains.value.find((item) => item.domain_id === selectedDomainId.value))
const tracks = computed(() => selectedDomain.value?.tracks || [])
const selectedDirection = computed(() => tracks.value.find((item) => item.track_id === selectedDirectionId.value))
const totalTrackCount = computed(() => domains.value.reduce((sum, item) => sum + (item.tracks?.length || 0), 0))
const selectedDomainDocumentCount = computed(() =>
  tracks.value.reduce((sum, item) => sum + (item.metadata?.document_count || 0), 0)
)
const currentProfile = computed(() => store.currentProfile)
const diagnosticQuestions = computed(() => store.pendingDiagnosticQuestions || [])
const diagnosisResult = computed(() => store.diagnosisResult)
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
const activeLearnerId = computed(() => currentProfile.value?.learner_id || store.currentLearnerId || '')
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
  const focusSummary = weakPoints.length ? `，重点覆盖 ${weakPoints.join('、')}` : ''
  const levelSummary = abilityLevel ? `${abilityLevel}阶段` : '当前阶段'
  const typeSummary = resourceSummary ? `，输出 ${resourceSummary}` : ''
  return `${directionName}${levelSummary}学习资源${focusSummary}${typeSummary}`
})

const resourceTypeOptions = ['讲义', '实操指南', '分阶测试题', '复习清单', '案例分析']

// Presentation metadata does not participate in the diagnosis or generation payload.
const setupRoot = ref(null)
const fitLayout = ref(false)
const containedLayout = ref(false)
const domainIcons = [Monitor, DataAnalysis, Connection, Lock]
const resourceVisuals = {
  讲义: { icon: Reading, description: '理解概念，建立知识框架' },
  实操指南: { icon: EditPen, description: '跟随步骤，在实践中掌握' },
  分阶测试题: { icon: List, description: '分层练习，检验掌握程度' },
  复习清单: { icon: Collection, description: '回顾重点，巩固学习成果' },
  案例分析: { icon: Document, description: '拆解场景，连接真实应用' },
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
      const fixedRegions = [root, ...root.querySelectorAll('.setup-intro, .wizard-layout, .progress-panel, .step-panel, .work-card, .el-card__header, .setup-footer')]
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
    const regions = [root, ...root.querySelectorAll('.wizard-layout, .progress-panel, .progress-list, .step-panel, .work-card, .el-card__body, .card-grid, .choice-card, .overview-strip, .action-row')]
    const overflow = regions.some((node) => node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1)
    const clipped = [...root.querySelectorAll('h2, h3, p, strong, .choice-title, .choice-description, .choice-meta, .progress-copy, .action-row button, .setup-footer')].some((node) => {
      if (!node.getClientRects().length) return false
      const rect = node.getBoundingClientRect()
      return rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1
    })
    if (overflow || clipped) fitLayout.value = false
  })
}

watch([stepStage, domains, tracks], scheduleSetupLayout, { flush: 'post' })
watch(stepStage, async () => {
  fitLayout.value = false
  containedLayout.value = false
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
  if (!currentUser.value) return stage === 'domain'
  if (stage === 'domain') return true
  if (stage === 'track') return Boolean(selectedDomainId.value)
  if (stage === 'questionnaire') return Boolean(selectedDirectionId.value)
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
  return (question.options || []).map((option) => {
    if (typeof option === 'object' && option !== null) {
      return {
        label: option.label ?? option.value ?? '',
        value: option.value ?? option.label ?? '',
      }
    }
    return { label: option, value: option }
  })
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

function isTrackAvailable(track) {
  return track.metadata?.available !== false
}

function selectDomain(item) {
  selectedDomainId.value = item.domain_id
  selectedDirectionId.value = ''
  questions.value = []
  stepStage.value = 'domain'
  store.setLearningDirectionId('')
  store.setLearningDirectionName('')
  store.setCurrentProfile(null)
  store.setPendingDiagnosis([])
  store.setDiagnosisResult(null)
  initialRecommendedNodeName.value = ''
  initialRecommendedNodeLoading.value = false
}

function selectDirection(item) {
  selectedDirectionId.value = item.track_id
  store.setLearningDirectionId(item.track_id)
  store.setLearningDirectionName(item.name)
  store.setCurrentProfile(null)
  store.setPendingDiagnosis([])
  store.setDiagnosisResult(null)
  initialRecommendedNodeName.value = ''
  initialRecommendedNodeLoading.value = false
}

async function loadDomains() {
  const res = await knowledgeApi.listDomains()
  domains.value = res.data.domains || []
}

async function loadQuestions() {
  if (!selectedDirectionId.value) {
    questions.value = []
    return
  }
  const res = await onboardingApi.getQuestions(selectedDirectionId.value)
  questions.value = res.data.questions || []
  resetFormValues()
}

async function prepareQuestionnaire() {
  if (!selectedDirectionId.value) return
  await loadQuestions()
  stepStage.value = 'questionnaire'
}

async function loadInitialRecommendedNodeName(result = diagnosisResult.value) {
  const nodeId = String(result?.initial_recommended_node_id || '').trim()
  initialRecommendedNodeName.value = ''
  initialRecommendedNodeLoading.value = false
  if (!nodeId || !selectedDirectionId.value) return

  initialRecommendedNodeLoading.value = true
  try {
    const res = await knowledgeApi.listNodes(selectedDirectionId.value)
    const nodes = Array.isArray(res.data?.nodes) ? res.data.nodes : []
    const matchedNode = nodes.find((node) => String(node.node_id || '').trim() === nodeId)
    initialRecommendedNodeName.value = matchedNode?.name || ''
  } catch (error) {
    // 节点名称只是展示增强，接口不可用时仍保留节点 ID 作为可识别的兜底。
    console.warn('加载初始推荐节点名称失败', error)
  } finally {
    initialRecommendedNodeLoading.value = false
  }
}

async function submitQuestionnaire() {
  if (!currentUser.value || !learnerId.value) {
    ElMessage.warning('请先选择学习方向')
    return
  }

  submittingProfile.value = true
  try {
    const answers = questions.value.reduce((acc, question) => {
      acc[question.question_id] = form[question.question_id]
      return acc
    }, {})

    const res = await onboardingApi.createInitialProfile({
      learner_id: learnerId.value,
      learning_direction_id: selectedDirectionId.value,
      answers,
    })

    store.setLearnerId(res.data.learner_id)
    store.setCurrentProfile(res.data.profile)
    store.setPendingDiagnosis(res.data.diagnostic_questions || [])
    store.setDiagnosisResult(null)
    initDiagnosticAnswers()
    stepStage.value = diagnosticQuestions.value.length ? 'diagnosis' : 'review'
    if (!diagnosticQuestions.value.length) {
      store.setDiagnosisResult({
        ability_level: res.data.profile.skill_level,
        weak_points: res.data.profile.weak_points || [],
        strong_points: res.data.profile.strong_points || [],
        knowledge_states: res.data.profile.knowledge_states || {},
        diagnostic_result_id: '',
      })
    }
    ElMessage.success('问卷已提交')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '问卷提交失败')
  } finally {
    submittingProfile.value = false
  }
}

async function submitDiagnosis() {
  if (!currentProfile.value) return
  submittingDiagnosis.value = true
  try {
    const answers = diagnosticQuestions.value.map((question) => ({
      question_id: question.question_id,
      answer: diagnosticAnswers[question.question_id],
    }))

    const res = await diagnosisApi.submit({
      learner_id: currentProfile.value.learner_id,
      learning_direction_id: selectedDirectionId.value,
      answers,
    })

    store.setDiagnosisResult(res.data)
    store.setCurrentProfile({
      ...currentProfile.value,
      skill_level: res.data.ability_level,
      weak_points: res.data.weak_points,
      strong_points: res.data.strong_points,
      knowledge_states: {
        ...(currentProfile.value.knowledge_states || {}),
        ...(res.data.knowledge_states || {}),
      },
    })

    if (res.data.initial_diagnostic_status === 'retest') {
      store.setPendingDiagnosis(res.data.next_diagnostic_questions || [])
      initDiagnosticAnswers()
      stepStage.value = 'diagnosis'
      ElMessage.info('本阶段校准未通过，已自动进入下一阶段复测')
      return
    }

    store.setPendingDiagnosis([])
    stepStage.value = 'review'
    await loadInitialRecommendedNodeName(res.data)
    ElMessage.success('诊断已完成')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '诊断提交失败')
  } finally {
    submittingDiagnosis.value = false
  }
}

async function submitGeneration() {
  if (submittingGeneration.value) return
  if (!selectedResourceTypes.value.length) {
    ElMessage.warning('请至少选择一种资源类型')
    return
  }
  if (!activeLearnerId.value) {
    ElMessage.warning('当前学习画像不存在，请重新提交方向问卷')
    return
  }
  submittingGeneration.value = true
  try {
    const payload = {
      learner_id: activeLearnerId.value,
      knowledge_base_id: selectedDirectionId.value,
      topic: generatedTopic.value,
      diagnostic_result_id: diagnosisResult.value?.diagnostic_result_id,
      resource_types: selectedResourceTypes.value,
      include_claim_check: includeClaimCheck.value,
      constraints: {
        supplemental_requirements: supplementalRequirements.value.trim(),
      },
    }
    localStorage.setItem('last_generation_request', JSON.stringify(payload))
    const responses = await generateApi.createJobsForClaim(payload)
    const res = responses[0]
    localStorage.setItem('current_generation_run_ids', JSON.stringify(responses.map((item) => item.data?.run_id).filter(Boolean)))
    router.push({
      path: '/generate',
      query: {
        runId: res.data.run_id,
        learnerId: activeLearnerId.value,
      },
    })
  } catch (error) {
    console.error(error)
    ElMessage({
      message: error?.response?.data?.message || '生成任务提交失败',
      type: 'error',
      grouping: true,
    })
  } finally {
    submittingGeneration.value = false
  }
}

watch(diagnosticQuestions, initDiagnosticAnswers)

onMounted(async () => {
  try {
    store.setCurrentProfile(null)
    store.setPendingDiagnosis([])
    store.setDiagnosisResult(null)
    initialRecommendedNodeName.value = ''
    initialRecommendedNodeLoading.value = false
    await loadDomains()
  } catch (error) {
    console.error(error)
    ElMessage.error('初始化学习方向页面失败')
  }
})
</script>

<style scoped>
.onboarding-page {
  --setup-ink:#172c45; --setup-muted:#59697b; --setup-line:#dce3e9;
  --setup-accent:#176b70; --setup-mint:#9cf2e0;
  --el-color-primary:#176b70; --el-color-primary-light-9:#eef8f6;
  --el-color-primary-light-3:#6a9fa2;
  display:flex; flex-direction:column; min-width:0; gap:22px;
  padding-top:24px; color:var(--setup-ink);
}
.setup-intro { display:flex; align-items:center; justify-content:space-between; gap:24px; }
.setup-eyebrow,.card-kicker,.choice-code,.setup-footer,.progress-heading span,.progress-footer > span:last-child { font-family:Consolas,'SFMono-Regular',monospace; font-size:10px; line-height:1.6; }
.setup-eyebrow { color:var(--setup-muted); }
.setup-intro h2 { margin:6px 0 0; font-size:24px; font-weight:650; line-height:1.4; }
.setup-intro > p { margin:0; color:var(--setup-muted); font-size:13px; line-height:1.7; }
.wizard-layout { display:grid; grid-template-columns:208px minmax(0,1fr); align-items:start; gap:24px; min-width:0; }
.progress-panel { position:sticky; top:16px; display:flex; flex-direction:column; min-width:0; min-height:590px; padding:26px 18px 23px; border:1px solid #213b51; border-radius:6px; background:#102339; color:#eaf2f9; }
.progress-heading { display:flex; align-items:center; gap:12px; padding:0 5px 24px; border-bottom:1px solid #354b60; }
.progress-heading > .el-icon { font-size:25px; color:var(--setup-mint); }
.progress-heading span { display:block; color:#b8cadb; font-size:9px; }
.progress-heading strong { display:block; margin-top:5px; font-size:15px; font-weight:600; }
.progress-list { display:flex; flex-direction:column; gap:5px; margin:25px -4px 20px; }
.progress-card { position:relative; display:grid; grid-template-columns:32px minmax(0,1fr); align-items:start; gap:12px; min-width:0; min-height:76px; padding:12px 8px; border:0; border-radius:4px; background:transparent; color:#d6e1ec; text-align:left; cursor:pointer; transition:background-color 180ms ease; }
.progress-card:not(:last-child)::after { position:absolute; top:47px; bottom:-13px; left:24px; width:1px; background:#40586e; content:''; }
.progress-index { position:relative; z-index:1; display:flex; justify-content:center; align-items:center; width:32px; height:32px; border:1px solid #658095; border-radius:50%; background:#102339; color:#d1deea; font:11px/1 Consolas,monospace; }
.progress-index .el-icon { font-size:16px; }
.progress-copy { display:flex; flex-direction:column; min-width:0; }
.progress-title { display:block; font-size:14px; font-weight:600; line-height:1.65; }
.progress-desc { display:block; margin-top:4px; color:#b8cadb; font-size:11px; line-height:1.6; overflow-wrap:anywhere; }
.progress-card.active { background:#203b50; color:#b3f6e9; }
.progress-card.active .progress-index { border-color:var(--setup-mint); background:var(--setup-mint); color:#102339; }
.progress-card.done:not(.active) .progress-index { border-color:#8ecec6; color:#adf1e4; }
.progress-card.done::after { background:#689e9b; }
.progress-card:disabled { cursor:not-allowed; }
.progress-card:disabled .progress-title,.progress-card:disabled .progress-index { color:#adc0d1; }
.progress-card:hover:not(:disabled) { background:#203b50; }
.progress-current { position:absolute; right:6px; top:25px; width:4px; height:4px; border-radius:50%; background:var(--setup-mint); }
.progress-footer { display:grid; grid-template-columns:22px minmax(0,1fr); gap:10px; align-items:start; margin-top:auto; padding:20px 5px 0; border-top:1px solid #354b60; }
.progress-footer-mark { color:#a2e8df; font-size:20px; }
.progress-footer p { margin:0; color:#c2d2e0; font-size:11px; line-height:1.9; }
.progress-footer > span:last-child { grid-column:1/-1; color:#b8cadb; font-size:9px; }
.step-panel { min-width:0; }
.work-card { border:1px solid var(--setup-line); border-radius:6px; background:#fff; box-shadow:none; overflow:visible; }
.work-card :deep(.el-card__header) { padding:26px 30px 23px; border-bottom:1px solid var(--setup-line); }
.work-card :deep(.el-card__body) { min-width:0; padding:22px 30px 0; }
.card-head { display:flex; justify-content:space-between; align-items:center; gap:20px; }
.card-head > div { min-width:0; }
.card-kicker { display:block; margin-bottom:8px; color:var(--setup-accent); }
.card-title { margin:0; color:var(--setup-ink); font-size:26px; font-weight:650; line-height:1.4; text-wrap:balance; }
.card-subtitle { margin:9px 0 0; color:var(--setup-muted); font-size:13px; line-height:1.75; }
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
.choice-card { position:relative; display:flex; flex-direction:column; gap:9px; min-width:0; min-height:180px; padding:18px 20px 16px; border:1px solid var(--setup-line); border-radius:4px; background:#fff; color:var(--setup-ink); text-align:left; cursor:pointer; transition:background-color 180ms ease,border-color 180ms ease; }
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
.insight-card { display:flex; gap:12px; align-items:flex-start; margin-top:22px; padding:16px 0 0; border-top:1px solid var(--setup-line); color:var(--setup-accent); }
.insight-card > .el-icon { flex:0 0 auto; margin-top:2px; font-size:19px; }
.insight-card strong { color:var(--setup-ink); font-size:12px; font-weight:600; }
.insight-card p { margin:5px 0 0; color:var(--setup-muted); font-size:12px; line-height:1.75; }
.action-row { display:flex; align-items:center; justify-content:flex-end; gap:14px; margin-top:24px; padding:20px 0; border-top:1px solid var(--setup-line); }
.action-hint { flex:1; min-width:0; color:var(--setup-muted); font-size:11px; line-height:1.6; overflow-wrap:anywhere; }
.action-row :deep(.el-button) { flex:0 0 auto; min-width:112px; min-height:44px; height:auto; margin:0; padding:12px 20px; border-radius:4px; color:var(--setup-ink); font-size:13px; font-weight:600; line-height:1.4; }
.action-row :deep(.el-button > span) { gap:16px; }
.action-row :deep(.el-button--primary) { border-color:#102f3f; background:#102f3f; color:var(--setup-mint); }
.action-row :deep(.el-button--primary:hover:not(.is-disabled)) { border-color:#194557; background:#194557; }
.action-row :deep(.el-button--primary.is-disabled) { border-color:#d5e0e5; background:#eaf0f2; color:#677d89; }
.action-row :deep(.back-button) { min-width:90px; padding-inline:8px; border-color:transparent; background:transparent; color:var(--setup-muted); }
.action-row :deep(.back-button:hover) { background:#f1f5f7; color:var(--setup-ink); }
/* Element Plus input/select wrappers and textareas already provide their focus border. */
.onboarding-page :deep(button:focus-visible),.onboarding-page :deep(.el-checkbox:focus-within),.onboarding-page :deep(.el-radio:focus-within) { outline:2px solid #176b70; outline-offset:3px; }
.progress-panel button:focus-visible { outline-color:var(--setup-mint); }
.form-context { display:flex; align-items:center; gap:12px; padding:0 0 21px; border-bottom:1px solid var(--setup-line); }
.form-context > .el-icon { flex:0 0 auto; color:var(--setup-accent); font-size:23px; }
.form-context > div { min-width:0; }
.form-context span { color:var(--setup-muted); font-size:11px; line-height:1.6; }
.form-context strong { display:block; margin-top:4px; color:var(--setup-ink); font-size:14px; font-weight:600; line-height:1.6; overflow-wrap:anywhere; }
.form-context .form-context-count { margin-left:auto; flex:0 0 auto; font:11px/1.5 Consolas,'Microsoft YaHei',sans-serif; }
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
.questionnaire-form :deep(.el-input__wrapper),.questionnaire-form :deep(.el-select__wrapper),.diagnostic-item :deep(.el-input__wrapper) { min-height:46px; padding:8px 14px; border-radius:4px; background:#f8fafb; box-shadow:0 0 0 1px #c8d4dd inset; }
.questionnaire-form :deep(.el-textarea__inner),.diagnostic-item :deep(.el-textarea__inner) { padding:12px 14px; border-radius:4px; background:#f8fafb; color:var(--setup-ink); line-height:1.7; box-shadow:0 0 0 1px #c8d4dd inset; }
.questionnaire-form :deep(.el-input__inner),.questionnaire-form :deep(.el-select__selected-item) { color:var(--setup-ink); font-size:13px; }
.questionnaire-form :deep(.el-input__inner::placeholder),.questionnaire-form :deep(.el-textarea__inner::placeholder),.questionnaire-form :deep(.el-select__placeholder) { color:#647689; }
.questionnaire-form :deep(.el-input__wrapper.is-focus),.questionnaire-form :deep(.el-select__wrapper.is-focused),.questionnaire-form :deep(.el-textarea__inner:focus),.diagnostic-item :deep(.el-textarea__inner:focus) { box-shadow:0 0 0 2px var(--setup-accent) inset; }
.answer-options { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; width:100%; }
.answer-options :deep(.el-checkbox),.answer-options :deep(.el-radio) { display:flex; align-items:center; min-width:0; height:auto; min-height:46px; margin:0; padding:12px 14px; border:1px solid #cbd7df; border-radius:4px; background:#f8fafb; color:var(--setup-ink); }
.answer-options :deep(.el-checkbox__label),.answer-options :deep(.el-radio__label) { min-width:0; padding-left:10px; color:var(--setup-ink); font-size:12px; line-height:1.7; white-space:normal; overflow-wrap:anywhere; }
.answer-options :deep(.is-checked) { border-color:var(--setup-accent); background:#eef8f6; }
.answer-options :deep(.el-checkbox__input.is-checked .el-checkbox__inner),.answer-options :deep(.el-radio__input.is-checked .el-radio__inner) { background:var(--setup-accent); border-color:var(--setup-accent); }
.answer-options :deep(.el-checkbox__inner),.answer-options :deep(.el-radio__inner) { border-color:#879eaf; }
.diagnostic-heading { display:flex; align-items:flex-start; gap:12px; margin-bottom:18px; }
.question-title { min-width:0; margin:0; font-size:14px; font-weight:600; line-height:1.8; overflow-wrap:anywhere; }
.questionnaire-form .action-row { margin-top:0; border-top:0; }
.result-card { overflow:hidden; border:1px solid var(--setup-line); border-radius:4px; box-shadow:none; }
.result-heading { display:flex; justify-content:space-between; align-items:center; gap:20px; padding:22px; background:#102339; color:#f1f6fb; }
.result-heading > div:first-child { min-width:0; }
.result-heading .card-kicker { color:#a5e9df; font-size:9px; }
.result-heading h4 { margin:0; font-size:19px; font-weight:600; line-height:1.6; overflow-wrap:anywhere; }
.result-heading p { margin:5px 0 0; color:#c0d1df; font-size:11px; line-height:1.7; }
.ability-stage { flex:0 0 auto; padding-left:22px; border-left:1px solid #4b667b; }
.ability-stage span { display:block; color:#c0d1df; font-size:10px; }
.ability-stage strong { display:block; margin-top:7px; color:var(--setup-mint); font-size:24px; font-weight:600; }
.diagnosis-result-body { padding:20px 22px; }
.diagnosis-point-grid { display:grid; grid-template-columns:1fr 1fr; gap:24px; }
.diagnosis-point-card { min-width:0; }
.diagnosis-point-card > span { display:flex; align-items:center; gap:7px; color:var(--setup-muted); font-size:11px; }
.diagnosis-point-card > span > .el-icon { color:var(--setup-accent); font-size:15px; }
.diagnosis-point-card p { margin:9px 0 0; color:var(--setup-ink); font-size:13px; line-height:1.75; overflow-wrap:anywhere; }
.initial-node-recommendation { display:flex; align-items:flex-start; gap:11px; margin-top:18px; padding-top:18px; border-top:1px solid var(--setup-line); }
.initial-node-recommendation > .el-icon { flex:0 0 auto; margin-top:2px; color:var(--setup-accent); font-size:22px; }
.initial-node-recommendation__kicker { display:block; color:var(--setup-muted); font-size:11px; }
.initial-node-recommendation__node { display:block; margin-top:7px; color:var(--setup-accent); font-size:15px; font-weight:600; overflow-wrap:anywhere; }
.initial-node-recommendation p { margin:6px 0 0; color:var(--setup-muted); font-size:12px; line-height:1.8; }
.resource-selection-form { margin-top:26px; }
.resource-selection-form :deep(.el-form-item) { margin-bottom:25px; }
.resource-selection-form :deep(.el-form-item__label) { height:auto; margin-bottom:10px; padding:0; color:var(--setup-ink); font-size:14px; font-weight:600; line-height:1.7; }
.resource-selection-form :deep(.el-form-item__content) { min-width:0; }
.field-hint { margin-top:9px; color:var(--setup-muted); font-size:12px; line-height:1.75; }
.resource-hint { width:100%; margin:0 0 13px; }
.resource-type-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; width:100%; }
.resource-type-grid :deep(.el-checkbox) { position:relative; min-width:0; min-height:103px; height:auto; margin:0; padding:15px; align-items:flex-start; border:1px solid #cbd7df; border-radius:4px; background:#f8fafb; }
.resource-type-grid :deep(.el-checkbox__input) { position:absolute; top:17px; right:14px; }
.resource-type-grid :deep(.el-checkbox__label) { min-width:0; width:100%; padding:0; color:var(--setup-ink); white-space:normal; }
.resource-type-grid :deep(.el-checkbox.is-checked) { border-color:var(--setup-accent); background:#eef8f6; }
.resource-type-grid :deep(.el-checkbox__inner) { border-color:#879eaf; }
.resource-type-grid :deep(.el-checkbox__input.is-checked .el-checkbox__inner) { border-color:var(--setup-accent); background:var(--setup-accent); }
.resource-option { display:grid; grid-template-columns:24px minmax(0,1fr); align-items:center; column-gap:9px; row-gap:10px; }
.resource-option > .el-icon { grid-column:1/-1; font-size:22px; color:var(--setup-accent); }
.resource-option strong { grid-column:1/-1; font-size:13px; font-weight:600; line-height:1.6; }
.resource-option > span { grid-column:1/-1; color:var(--setup-muted); font-size:11px; line-height:1.7; }
.claim-review-control { display:flex; gap:13px; align-items:center; width:100%; padding:15px; border:1px solid var(--setup-line); border-radius:4px; background:#f8fafb; }
.claim-icon { flex:0 0 auto; color:var(--setup-accent); font-size:23px; }
.claim-review-control > div { flex:1; min-width:0; }
.claim-review-control strong { color:var(--setup-ink); font-size:12px; font-weight:600; line-height:1.7; }
.claim-review-control p { margin:4px 0 0; color:var(--setup-muted); font-size:11px; line-height:1.7; }
.claim-review-control :deep(.el-switch) { flex:0 0 auto; --el-switch-on-color:#176b70; --el-switch-off-color:#758897; }
.claim-review-control :deep(.el-switch__label) { color:var(--setup-muted); }
.claim-review-control :deep(.el-switch__label.is-active) { color:var(--setup-accent); }
.setup-footer { display:flex; justify-content:space-between; gap:16px; padding-top:2px; color:var(--setup-muted); font-size:9px; line-height:1.8; }
.onboarding-page:is(.is-fit-layout,.is-contained-layout) { height:100%; min-height:0; display:grid; grid-template-rows:auto minmax(0,1fr) auto; gap:clamp(12px,1.6dvh,18px); padding-top:clamp(14px,2.1dvh,22px); }
:is(.is-fit-layout,.is-contained-layout) .setup-intro { min-width:0; }
:is(.is-fit-layout,.is-contained-layout) .setup-intro h2 { font-size:clamp(21px,2.7dvh,26px); }
:is(.is-fit-layout,.is-contained-layout) .wizard-layout { min-height:0; align-items:stretch; }
:is(.is-fit-layout,.is-contained-layout) .progress-panel { position:static; height:100%; min-height:0; padding-block:clamp(16px,2.7dvh,28px); }
:is(.is-fit-layout,.is-contained-layout) .progress-heading { padding-bottom:clamp(16px,2dvh,24px); }
:is(.is-fit-layout,.is-contained-layout) .progress-list { flex:1; justify-content:space-evenly; min-height:0; gap:0; margin-block:clamp(14px,2dvh,22px); }
:is(.is-fit-layout,.is-contained-layout) .progress-card { min-height:0; padding-block:10px; }
:is(.is-fit-layout,.is-contained-layout) .progress-card:not(:last-child)::after { top:44px; bottom:-20px; }
:is(.is-fit-layout,.is-contained-layout) .progress-footer { flex:0 0 auto; padding-top:16px; }
:is(.is-fit-layout,.is-contained-layout) .step-panel { height:100%; min-height:0; }
:is(.is-fit-layout,.is-contained-layout) .work-card { display:flex; flex-direction:column; height:100%; min-height:0; }
:is(.is-fit-layout,.is-contained-layout) .work-card :deep(.el-card__header) { flex:0 0 auto; padding:clamp(15px,2dvh,22px) 24px; }
:is(.is-fit-layout,.is-contained-layout) .work-card :deep(.el-card__body) { display:flex; flex:1; flex-direction:column; min-height:0; padding:16px 24px 0; }
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
:is(.is-fit-layout,.is-contained-layout) .insight-card { flex:0 0 auto; margin-top:14px; padding-top:12px; }
:is(.is-fit-layout,.is-contained-layout) .insight-card p { margin-top:3px; font-size:11px; line-height:1.65; }
:is(.is-fit-layout,.is-contained-layout) .action-row { flex:0 0 auto; margin-top:16px; padding-block:15px; }
:is(.is-fit-layout,.is-contained-layout) .setup-footer { padding:0; }
.card-title:focus-visible { outline:2px solid var(--setup-accent); outline-offset:5px; }
@media (min-width:1100px) and (max-height:760px) {
  .onboarding-page:is(.is-fit-layout,.is-contained-layout) { gap:10px; padding-top:12px; }
  :is(.is-fit-layout,.is-contained-layout) .setup-intro { display:grid; grid-template-columns:minmax(0,1fr) auto; }
  :is(.is-fit-layout,.is-contained-layout) .setup-intro > div { display:flex; align-items:center; gap:14px; }
  :is(.is-fit-layout,.is-contained-layout) .setup-eyebrow { font-size:9px; }
  :is(.is-fit-layout,.is-contained-layout) .setup-intro h2 { margin:0; font-size:20px; }
  :is(.is-fit-layout,.is-contained-layout) .setup-intro > p { font-size:11px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-panel { padding:16px 12px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-heading { padding-bottom:12px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-list { margin-block:12px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-card { padding-block:7px; }
  :is(.is-fit-layout,.is-contained-layout) .progress-card:not(:last-child)::after { top:40px; bottom:-14px; }
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
  :is(.is-fit-layout,.is-contained-layout) .insight-card { align-items:center; padding-top:9px; margin-top:9px; gap:9px; }
  :is(.is-fit-layout,.is-contained-layout) .insight-card > div { display:flex; align-items:baseline; gap:10px; }
  :is(.is-fit-layout,.is-contained-layout) .insight-card strong { flex:0 0 auto; font-size:11px; }
  :is(.is-fit-layout,.is-contained-layout) .insight-card p { margin:0; font-size:10px; line-height:1.6; }
  :is(.is-fit-layout,.is-contained-layout) .action-row { margin-top:10px; padding-block:11px; }
}
@media (min-width:1600px) {
  .wizard-layout { grid-template-columns:224px minmax(0,1fr); gap:30px; }
  .work-card :deep(.el-card__header),.work-card :deep(.el-card__body) { padding-inline:36px; }
  .choice-card { min-height:192px; padding:22px 24px; }
}
@media (max-width:1300px) and (min-width:1081px) {
  .wizard-layout { grid-template-columns:186px minmax(0,1fr); gap:18px; }
  .progress-panel { padding-inline:12px; }
  .work-card :deep(.el-card__header) { padding:22px; }
  .work-card :deep(.el-card__body) { padding-inline:22px; }
  .setup-intro > p { max-width:210px; }
}
@media (max-width:1080px) {
  .onboarding-page { gap:18px; padding-top:20px; }
  .wizard-layout { grid-template-columns:1fr; gap:18px; }
  .progress-panel { position:static; min-height:0; padding:13px 16px; }
  .progress-heading,.progress-footer,.progress-desc,.progress-current { display:none; }
  .progress-list { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:0; margin:0; }
  .progress-card { display:flex; flex-direction:column; align-items:center; gap:6px; min-height:64px; padding:4px; text-align:center; }
  .progress-card:not(:last-child)::after { top:19px; bottom:auto; left:calc(50% + 22px); width:calc(100% - 44px); height:1px; }
  .progress-index { width:30px; height:30px; }
  .progress-title { font-size:12px; }
  .progress-card.active { background:transparent; }
  .setup-intro > p { max-width:260px; }
}
@media (max-width:720px) {
  .setup-intro { display:block; }
  .setup-intro h2 { font-size:22px; }
  .setup-intro > p { max-width:none; margin-top:8px; font-size:12px; }
  .work-card :deep(.el-card__header) { padding:22px 20px 18px; }
  .work-card :deep(.el-card__body) { padding:20px 20px 0; }
  .card-title { font-size:23px; }
  .step-coordinate { font-size:29px; }
  .card-subtitle { font-size:12px; }
  .resource-type-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .setup-footer > span:last-child { display:none; }
}
@media (max-width:600px) {
  .onboarding-page { gap:16px; padding-top:19px; }
  .progress-panel { padding:11px 8px; }
  .progress-title { font-size:11px; }
  .progress-index { width:28px; height:28px; font-size:10px; }
  .progress-card { min-height:58px; }
  .progress-card:not(:last-child)::after { top:18px; left:calc(50% + 18px); width:calc(100% - 36px); }
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
  .form-context { flex-wrap:wrap; gap:10px; }
  .form-context > div { flex:1; }
  .form-context .form-context-count { flex:1 0 100%; padding-left:33px; }
  .question-block,.diagnostic-item { padding-block:22px; }
  .question-block :deep(.el-form-item__label),.diagnostic-heading { gap:9px; }
  .question-kind { font-size:9px; }
  .result-heading { padding:18px; gap:12px; }
  .result-heading h4 { font-size:17px; }
  .ability-stage { padding-left:13px; }
  .ability-stage strong { font-size:21px; }
  .diagnosis-result-body { padding:18px; }
  .diagnosis-point-grid { grid-template-columns:1fr; gap:18px; }
  .claim-review-control { flex-wrap:wrap; gap:10px; }
  .claim-review-control > div { flex-basis:calc(100% - 36px); }
  .claim-review-control :deep(.el-switch) { margin-left:33px; }
}
@media (max-width:600px) {
  .review-stage-card .action-row { display:grid; grid-template-columns:minmax(0,1fr); }
  .review-stage-card .action-hint { order:0; grid-row:1; }
  .review-stage-card .back-button { grid-row:2; justify-self:start; }
  .review-stage-card .action-row :deep(.el-button--primary) { grid-row:3; width:100%; }
  .claim-review-control :deep(.el-switch) { min-height:44px; }
}
.is-contained-layout .work-card :deep(.el-card__body) { display:block; overflow:auto; overscroll-behavior:contain; scrollbar-gutter:stable; scrollbar-width:thin; scrollbar-color:#9db8c2 transparent; }
.is-contained-layout .work-card :deep(.el-card__body:focus-visible) { outline:2px solid var(--setup-accent); outline-offset:-2px; }
@media (max-width:1080px) {
  .is-contained-layout .wizard-layout { grid-template-rows:auto minmax(0,1fr); gap:14px; }
  .is-contained-layout .progress-panel { height:auto; padding:10px 12px; }
  .is-contained-layout .progress-list { flex:none; margin:0; }
  .is-contained-layout .progress-card { padding:4px; }
}
@media (max-width:600px) and (max-height:760px) {
  .onboarding-page.is-contained-layout { gap:10px; padding-top:12px; }
  .is-contained-layout .setup-intro h2 { margin-top:4px; font-size:20px; }
  .is-contained-layout .setup-intro > p { margin-top:5px; font-size:11px; }
  .is-contained-layout .wizard-layout { gap:10px; }
  .is-contained-layout .progress-panel { padding:8px 10px; }
  .is-contained-layout .progress-card { min-height:52px; gap:4px; }
  .is-contained-layout .work-card :deep(.el-card__header) { padding:12px 16px; }
  .is-contained-layout .work-card :deep(.el-card__body) { padding:12px 16px 0; }
  .is-contained-layout .card-kicker { margin-bottom:4px; font-size:9px; }
  .is-contained-layout .card-title { font-size:20px; }
  .is-contained-layout .card-subtitle { margin-top:5px; font-size:11px; line-height:1.6; }
}
@media (prefers-reduced-motion:reduce) {
  .onboarding-page *, .onboarding-page *::before, .onboarding-page *::after { transition:none !important; animation:none !important; }
}
</style>
