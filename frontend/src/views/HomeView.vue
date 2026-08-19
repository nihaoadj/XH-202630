<template>
  <div class="dashboard">
    <section class="hero-panel">
      <div class="hero-copy">
        <span class="eyebrow">MY LEARNING SPACE</span>
        <h2>让学习持续前进</h2>
        <p>从能力诊断到资源练习，每一轮学习都围绕你的目标持续迭代。</p>
        <div class="hero-actions">
          <el-button class="dashboard-primary-button" type="primary" :icon="Plus" @click="$router.push('/learning/new')">新建学习方向</el-button>
          <el-button class="dashboard-secondary-button" :icon="Clock" @click="$router.push('/learning/history')">查看学习历史</el-button>
        </div>
      </div>

      <article class="current-focus">
        <div class="focus-state"><i />正在学习</div>
        <strong>{{ currentDirection?.name || store.currentLearningDirectionName || '选择一个学习方向' }}</strong>
        <span>{{ currentProfile?.skill_level || '待诊断' }} · {{ currentProfile?.learning_goal || '开始你的学习计划' }}</span>
        <div class="focus-profile">
          <span>当前学习画像</span>
          <b>{{ profileDisplayName(currentProfile) }}</b>
        </div>
      </article>
    </section>

    <section class="journey-panel">
      <div class="section-head">
        <div>
          <span class="eyebrow">LEARNING JOURNEY</span>
          <h3>我的学习进程</h3>
        </div>
        <span class="status-chip" :class="`status-${journeyStatus.key}`">{{ journeyStatus.label }}</span>
      </div>

      <div class="journey-content">
        <article class="profile-card">
          <div class="profile-card-head">
            <span>学习画像</span>
            <el-dropdown trigger="click" @command="switchProfile">
              <button class="switch-button" type="button" :disabled="loadingProfileContext" aria-label="切换学习画像" title="切换学习画像"><Switch /></button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="profile in profiles"
                    :key="profile.learner_id"
                    :command="profile.learner_id"
                    :disabled="profile.learner_id === selectedLearnerId"
                  >
                    {{ profileOptionLabel(profile) }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div class="profile-person">
            <span class="profile-avatar">{{ profileInitial(currentProfile) }}</span>
            <div>
              <strong>{{ profileDisplayName(currentProfile) }}</strong>
              <small>{{ currentDirection?.name || store.currentLearningDirectionName || '未选择学习方向' }}</small>
            </div>
          </div>
          <p>{{ currentProfile?.skill_level || '待诊断' }} · {{ currentProfile?.learning_goal || '待设定学习目标' }}</p>
        </article>

        <div class="journey-steps" aria-label="学习流程">
          <article
            v-for="(item, index) in journeySteps"
            :key="item.key"
            class="journey-step"
            :class="{ complete: item.complete, active: item.active, repeat: item.repeat }"
          >
            <span class="step-index">{{ item.complete ? '✓' : index + 1 }}</span>
            <div>
              <small>{{ item.state }}</small>
              <strong>{{ item.title }}</strong>
              <span>{{ item.description }}</span>
            </div>
          </article>
        </div>
      </div>
    </section>

    <section class="study-grid">
      <article class="next-card">
        <div class="section-head compact">
          <div>
            <span class="eyebrow">NEXT STEP</span>
            <h3>{{ nextAction.title }}</h3>
          </div>
          <span class="step-number">0{{ nextAction.order }}</span>
        </div>
        <p class="next-description">{{ nextAction.description }}</p>
        <div class="action-facts">
          <div><span>当前阶段</span><strong>{{ journeyStatus.label }}</strong></div>
          <div><span>资源批次</span><strong>{{ completedJobs.length }} 个已完成</strong></div>
          <div><span>最近动态</span><strong>{{ latestEvent?.title || '等待新的学习记录' }}</strong></div>
        </div>
        <el-button class="dashboard-primary-button next-action-button" type="primary" :icon="ArrowRight" @click="$router.push(nextAction.to)">{{ nextAction.button }}</el-button>
      </article>

      <article class="tools-card">
        <div class="section-head compact">
          <div>
            <span class="eyebrow">LEARNING TOOLS</span>
            <h3>继续学习</h3>
          </div>
          <span class="resource-count">{{ completedJobs.length }} 个资源批次</span>
        </div>
        <div class="tool-grid">
          <button v-for="tool in tools" :key="tool.title" type="button" class="tool-button" @click="$router.push(tool.to)">
            <span class="tool-index" :class="tool.tone">{{ tool.index }}</span>
            <span class="tool-copy"><strong>{{ tool.title }}</strong><small>{{ tool.description }}</small></span>
            <i>→</i>
          </button>
        </div>
      </article>
    </section>

    <section class="insight-grid">
      <article class="insight-card">
        <div class="insight-intro">
          <div class="section-head compact">
            <div><span class="eyebrow">LEARNING OVERVIEW</span><h3>当前学习数据</h3></div>
          </div>
          <p>汇总学习方向、学习画像与资源完成情况，帮助你掌握当前学习进度。</p>
        </div>
        <div class="metric-grid">
          <div><span>可选领域</span><strong>{{ domains.length }}</strong></div>
          <div><span>学习方向</span><strong>{{ totalTracks }}</strong></div>
          <div><span>学习画像</span><strong>{{ profiles.length }}</strong></div>
          <div><span>已完成资源</span><strong>{{ completedJobs.length }}</strong></div>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight, Clock, Plus, Switch } from '@element-plus/icons-vue'
import { feedbackApi, generateApi, knowledgeApi, learningHistoryApi, profileApi } from '../api'
import { useAppStore } from '../stores/app'

const store = useAppStore()
const domains = ref([])
const profiles = ref([])
const jobs = ref([])
const events = ref([])
const feedbackAttempts = ref(0)
const selectedLearnerId = ref('')
const loadingProfileContext = ref(false)

const totalTracks = computed(() => domains.value.reduce((total, domain) => total + (domain.tracks?.length || 0), 0))
const allTracks = computed(() => domains.value.flatMap((domain) => domain.tracks || []))
const currentProfile = computed(() =>
  profiles.value.find((profile) => profile.learner_id === store.currentLearnerId) || store.currentProfile || null
)
const currentDirection = computed(() => {
  const directionId = currentProfile.value?.knowledge_base_id || store.currentLearningDirectionId
  return allTracks.value.find((track) => track.track_id === directionId || track.knowledge_base_id === directionId)
})
const completedJobs = computed(() => jobs.value.filter((job) => job.job_status === 'completed'))
const latestJob = computed(() => jobs.value[0] || null)
const latestEvent = computed(() => events.value[0] || null)
const hasFeedback = computed(() =>
  feedbackAttempts.value > 0 || events.value.some((event) => /feedback|学习反馈|练习反馈/i.test(`${event.event_type || ''} ${event.title || ''}`))
)

const journeySteps = computed(() => {
  const hasProfile = Boolean(currentProfile.value)
  const hasDirection = Boolean(currentDirection.value || store.currentLearningDirectionId)
  const hasDiagnosis = Boolean(currentProfile.value?.skill_level || store.diagnosisResult)
  const hasJob = Boolean(latestJob.value)
  const hasResources = latestJob.value?.job_status === 'completed'
  const activeIndex = !hasProfile ? 0 : !hasDirection ? 1 : !hasDiagnosis ? 2 : !hasJob || !hasResources ? 3 : !hasFeedback.value ? 4 : 5
  const items = [
    { key: 'profile', title: '建立画像', description: '记录学习起点', ready: hasProfile },
    { key: 'direction', title: '选择方向', description: '明确学习主题', ready: hasDirection },
    { key: 'diagnosis', title: '能力诊断', description: '了解掌握情况', ready: hasDiagnosis },
    { key: 'resources', title: '生成资源', description: '准备学习材料', ready: hasResources },
    { key: 'feedback', title: '练习反馈', description: '记录学习结果', ready: hasFeedback.value },
    { key: 'iterate', title: '下一轮生成', description: '结合反馈巩固', ready: false, repeat: true },
  ]
  return items.map((item, index) => ({
    ...item,
    complete: item.ready && index < activeIndex,
    active: index === activeIndex,
    state: item.ready && index < activeIndex ? '已完成' : index === activeIndex ? '进行中' : '下一步',
  }))
})

const journeyStatus = computed(() => {
  if (hasFeedback.value) return { key: 'iterate', label: '准备下一轮学习' }
  if (latestJob.value?.job_status === 'completed') return { key: 'ready', label: '资源已准备好' }
  if (latestJob.value) return { key: 'running', label: '资源生成中' }
  return { key: 'setup', label: '正在规划学习路径' }
})

const nextAction = computed(() => {
  if (!store.currentUserProfile) return { order: 1, title: '完善个人资料', description: '补充稳定的个人信息，之后创建学习方向时就无需重复填写。', button: '维护个人资料', to: '/user/profile' }
  if (!currentProfile.value || !currentDirection.value) return { order: 2, title: '开启新的学习方向', description: '选择你想学习的领域与方向，为本次学习建立独立记录。', button: '新建学习方向', to: '/learning/new' }
  if (!latestJob.value || latestJob.value.job_status === 'failed') return { order: 3, title: '生成专属学习资源', description: '根据本次学习画像选择资源，形成适合当前阶段的学习材料。', button: '查看资源生成', to: '/generate' }
  if (latestJob.value.job_status !== 'completed') return { order: 4, title: '等待资源准备完成', description: '资源正在生成中，可以随时查看当前任务的处理进度。', button: '查看生成进度', to: '/generate' }
  if (!hasFeedback.value) return { order: 5, title: '开始练习并记录反馈', description: '学习资源已准备完成，通过练习确认掌握情况。', button: '进入学习反馈', to: '/feedback' }
  return { order: 6, title: '开启下一轮资源生成', description: '结合本轮反馈调整学习重点，继续巩固薄弱环节。', button: '查看资源生成', to: '/generate' }
})

const tools = [
  { index: '01', title: '学习资源', description: '进入资源学习与阅读', to: '/resources', tone: 'blue' },
  { index: '02', title: '练习反馈', description: '记录练习结果', to: '/feedback', tone: 'mint' },
  { index: '03', title: '学习报告', description: '回看诊断与进步', to: '/report', tone: 'amber' },
  { index: '04', title: '历史资源', description: '按画像查阅内容', to: '/resources', tone: 'slate' },
]

function profileDisplayName(profile) {
  const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot
  return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未选择学习画像'
}

function profileInitial(profile) {
  return profileDisplayName(profile).slice(0, 1) || '我'
}

function resolveTrackName(trackId) {
  return allTracks.value.find((track) => track.track_id === trackId || track.knowledge_base_id === trackId)?.name || trackId || '未选择学习方向'
}

function profileOptionLabel(profile) {
  return `${profileDisplayName(profile)} / ${resolveTrackName(profile.knowledge_base_id)}`
}

async function loadProfileContext(learnerId) {
  if (!learnerId) return
  loadingProfileContext.value = true
  jobs.value = []
  events.value = []
  feedbackAttempts.value = 0
  try {
    const [jobResult, timelineResult, feedbackResult] = await Promise.allSettled([
      generateApi.listJobs(learnerId),
      learningHistoryApi.timeline(learnerId),
      feedbackApi.listAttempts(learnerId, { page: 1, page_size: 1 }),
    ])
    if (jobResult.status === 'fulfilled') jobs.value = jobResult.value.data.items || jobResult.value.data.jobs || []
    if (timelineResult.status === 'fulfilled') events.value = timelineResult.value.data.events || []
    if (feedbackResult.status === 'fulfilled') {
      const attempts = feedbackResult.value.data.items || feedbackResult.value.data.attempts || []
      feedbackAttempts.value = feedbackResult.value.data.total ?? attempts.length
    }
  } finally {
    loadingProfileContext.value = false
  }
}

async function switchProfile(learnerId) {
  const profile = profiles.value.find((item) => item.learner_id === learnerId)
  if (!profile) return
  selectedLearnerId.value = learnerId
  store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id))
  await loadProfileContext(learnerId)
}

async function loadDashboard() {
  try {
    const [domainResult, profileResult] = await Promise.all([
      knowledgeApi.listDomains(),
      profileApi.list({ page: 1, page_size: 50 }),
    ])
    domains.value = domainResult.data.domains || []
    profiles.value = profileResult.data.items || profileResult.data.profiles || []
    const learnerId = store.currentLearnerId || profiles.value[0]?.learner_id
    if (!learnerId) return
    await switchProfile(learnerId)
  } catch (error) {
    console.error(error)
    ElMessage.error('总览数据加载失败')
  }
}

onMounted(loadDashboard)
</script>

<style scoped>
.dashboard {
  --ink: #10233f;
  --muted: #637692;
  --line: #dbe5f1;
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(132px, 0.8fr) minmax(156px, 0.95fr) minmax(258px, 1.25fr) minmax(128px, 0.65fr);
  gap: 16px;
  overflow: hidden;
}

.hero-panel,
.journey-panel,
.next-card,
.tools-card,
.insight-card {
  min-height: 0;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 28px rgba(19, 45, 77, 0.05);
}

.hero-panel {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(300px, 0.6fr);
  gap: 28px;
  padding: 22px 28px;
  overflow: hidden;
  background:
    radial-gradient(circle at 88% 8%, rgba(45, 212, 191, 0.2), transparent 30%),
    linear-gradient(120deg, #eff6ff, #fbfdff 58%, #f2fcf9);
}

.eyebrow { display: block; color: #1d6c5d; font-size: 12px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }
.hero-copy h2 { margin: 7px 0 0; color: var(--ink); font-size: clamp(25px, 2.2vw, 37px); letter-spacing: -0.04em; line-height: 1.12; }
.hero-copy p { margin: 8px 0 0; overflow: hidden; color: #536a89; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.hero-actions { display: flex; gap: 10px; margin-top: 15px; }

.current-focus { align-self: center; min-width: 0; padding: 17px 19px; border: 1px solid rgba(255, 255, 255, 0.86); border-radius: 14px; background: rgba(255, 255, 255, 0.72); backdrop-filter: blur(8px); }
.focus-state { display: flex; align-items: center; gap: 7px; color: #58708c; font-size: 12px; }.focus-state i { width: 8px; height: 8px; border-radius: 50%; background: #12aa85; box-shadow: 0 0 0 5px rgba(18, 170, 133, 0.12); }.current-focus > strong { display: block; margin-top: 10px; overflow: hidden; color: var(--ink); font-size: 20px; text-overflow: ellipsis; white-space: nowrap; }.current-focus > span { display: block; margin-top: 5px; overflow: hidden; color: var(--muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.focus-profile { display: flex; justify-content: space-between; gap: 14px; margin-top: 13px; padding-top: 10px; border-top: 1px solid #dce6ef; color: #6d8199; font-size: 11px; }.focus-profile b { color: #203752; font-size: 12px; }

.journey-panel { padding: 16px 20px; overflow: hidden; }.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }.section-head h3,.section-head.compact h3 { margin: 6px 0 0; color: var(--ink); font-size: 22px; font-weight: 800; letter-spacing: -0.035em; line-height: 1.1; }.status-chip,.resource-count { padding: 6px 9px; border-radius: 999px; background: #edf7f2; color: #14815e; font-size: 11px; font-weight: 700; white-space: nowrap; }.status-running { background: #fff4df; color: #a56a15; }.status-setup { background: #edf4ff; color: #3967b1; }.status-iterate { background: #f2edff; color: #6d54b1; }
.journey-content { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 14px; margin-top: 11px; }.profile-card { min-width: 0; padding: 11px 13px; border-radius: 12px; background: linear-gradient(145deg, #102b4d, #1e4a7b); color: #fff; }.profile-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: rgba(224, 238, 255, 0.78); font-size: 11px; font-weight: 700; }.switch-button { display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px; border: 1px solid rgba(183, 222, 255, 0.28); border-radius: 7px; background: rgba(116, 178, 234, 0.18); color: #e4f2ff; font: inherit; cursor: pointer; }.switch-button:disabled { cursor: wait; opacity: 0.7; }.switch-button i { font-size: 14px; font-style: normal; line-height: 1; }.profile-person { display: flex; align-items: center; gap: 9px; min-width: 0; margin-top: 9px; }.profile-avatar { display: grid; width: 31px; height: 31px; flex: 0 0 31px; place-items: center; border: 1px solid rgba(216, 239, 255, 0.44); border-radius: 9px; background: linear-gradient(135deg, #55a8e9, #34bfa2); font-size: 16px; font-weight: 800; }.profile-person div { min-width: 0; }.profile-person strong,.profile-person small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.profile-person strong { font-size: 16px; }.profile-person small { margin-top: 2px; color: rgba(223, 238, 255, 0.76); font-size: 10px; }.profile-card > p { margin: 8px 0 0; overflow: hidden; color: rgba(229, 240, 255, 0.82); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.journey-steps { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; min-width: 0; }.journey-step { position: relative; display: flex; align-items: center; min-width: 0; padding: 10px 8px; border: 1px solid #e0e8f1; border-radius: 12px; background: #f9fbfd; }.journey-step:not(:last-child)::after { position: absolute; top: 50%; right: -9px; z-index: 2; width: 9px; height: 1px; background: #cedae8; content: ''; }.journey-step.complete { border-color: #cce9dc; background: #f5fcf8; }.journey-step.active { border-color: #98b9fa; background: #f1f6ff; box-shadow: 0 7px 16px rgba(37, 99, 235, 0.08); }.journey-step.repeat { border-style: dashed; background: #fbfcff; }.step-index { display: grid; width: 27px; height: 27px; flex: 0 0 27px; margin-right: 7px; place-items: center; border: 1px solid #cbd8e8; border-radius: 50%; background: #fff; color: #71839a; font-size: 12px; font-weight: 800; }.complete .step-index { border-color: #49b98d; background: #e9f8f0; color: #14815e; }.active .step-index { border-color: #2563eb; background: #2563eb; box-shadow: 0 0 0 5px rgba(37, 99, 235, 0.1); color: #fff; }.journey-step div { min-width: 0; }.journey-step small,.journey-step strong,.journey-step span:not(.step-index) { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.journey-step small { color: #73849a; font-size: 10px; }.complete small { color: #14815e; }.active small { color: #2563eb; }.journey-step strong { margin-top: 3px; color: #1b304c; font-size: 14px; }.journey-step span:not(.step-index) { margin-top: 3px; color: #75869d; font-size: 10px; }

.study-grid { min-height: 0; display: grid; grid-template-columns: minmax(380px, 0.7fr) minmax(0, 1.3fr); gap: 16px; }.next-card,.tools-card { min-height: 0; padding: 20px; overflow: hidden; }.next-card { display: flex; flex-direction: column; }.tools-card { display: flex; flex-direction: column; }.next-card > .el-button { height: 40px; flex: 0 0 40px; }.step-number { color: #d1deee; font-size: 40px; font-weight: 800; letter-spacing: -0.08em; }.next-description { margin: 10px 0 14px; color: #62758e; font-size: 14px; line-height: 1.55; }.action-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; margin: 0 0 15px; }.action-facts div { display: flex; flex-direction: column; justify-content: center; min-width: 0; min-height: 68px; padding: 10px; border-radius: 10px; background: #f5f8fc; }.action-facts span,.action-facts strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.action-facts span { color: #8190a4; font-size: 12px; }.action-facts strong { margin-top: 5px; color: #243954; font-size: 13px; }
.tool-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; align-content: start; margin-top: 14px; }.tool-button { display: grid; grid-template-columns: 34px minmax(0, 1fr) 18px; align-items: center; gap: 9px; min-width: 0; min-height: 68px; padding: 12px; border: 1px solid #e0e7f0; border-radius: 11px; background: #fff; color: inherit; text-align: left; cursor: pointer; transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease; }.tool-button:hover { border-color: #92b9ef; box-shadow: 0 6px 13px rgba(32, 79, 133, 0.08); transform: translateY(-1px); }.tool-index { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 9px; font-size: 12px; font-weight: 800; }.tool-index.blue { background: #eaf2ff; color: #2563eb; }.tool-index.mint { background: #e6f8f2; color: #088166; }.tool-index.amber { background: #fff3dd; color: #bd7618; }.tool-index.slate { background: #eef2f6; color: #516c87; }.tool-copy { min-width: 0; }.tool-copy strong,.tool-copy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.tool-copy strong { color: #203650; font-size: 15px; }.tool-copy small { margin-top: 3px; color: #74859a; font-size: 12px; }.tool-button > i { color: #98a8ba; font-size: 17px; font-style: normal; }.study-tip { display: flex; flex-direction: column; justify-content: center; min-height: 0; margin-top: 10px; padding: 10px 12px; border-left: 3px solid #5a9cf1; border-radius: 8px; background: #f5f9ff; }.study-tip span { color: #356db4; font-size: 10px; font-weight: 800; }.study-tip p { margin: 4px 0 0; overflow: hidden; color: #586e89; font-size: 11px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }

.insight-grid { min-height: 0; display: block; }.insight-card { position: relative; height: 100%; min-height: 0; padding: 16px 22px; overflow: hidden; display: grid; grid-template-columns: minmax(250px, 0.68fr) minmax(0, 1.32fr); align-items: center; gap: 24px; border-color: #d5e4ed; background: linear-gradient(115deg, #ffffff 0%, #fbfefd 58%, #f0faf7 100%); box-shadow: 0 12px 26px rgba(19, 72, 88, 0.06); }.insight-card::after { position: absolute; top: -52px; right: 8%; width: 170px; height: 120px; border-radius: 50%; background: radial-gradient(circle, rgba(39, 176, 143, 0.12), transparent 68%); content: ''; pointer-events: none; }.insight-intro { position: relative; z-index: 1; min-width: 0; }.insight-card .section-head { padding: 0; border: 0; }.insight-card .section-head .eyebrow { font-size: 12px; letter-spacing: 0.08em; }.insight-card .section-head h3 { font-size: 22px; }.insight-intro > p { margin: 8px 0 0; color: #4f6c87; font-size: 13px; line-height: 1.5; }.metric-grid { position: relative; z-index: 1; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }.metric-grid > div { min-width: 0; padding: 11px 14px; border: 1px solid #dce9ef; border-radius: 11px; background: rgba(255, 255, 255, 0.82); box-shadow: 0 5px 12px rgba(34, 85, 102, 0.035); }.metric-grid > div:nth-child(1) { border-color: #cce8df; background: #f4fbf8; }.metric-grid > div:nth-child(2) { border-color: #d6e4fa; background: #f5f9ff; }.metric-grid > div:nth-child(3) { border-color: #e1e7ee; background: #fafcff; }.metric-grid > div:nth-child(4) { border-color: #d5ece5; background: #f6fcfa; }.metric-grid span,.metric-grid strong { display: block; }.metric-grid span { overflow: hidden; color: #6f859c; font-size: 11px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.metric-grid strong { margin-top: 5px; color: #193655; font-size: 22px; line-height: 1; }

@media (max-width: 1180px) {
  .dashboard { height: auto; overflow: visible; }.hero-panel { grid-template-columns: 1fr; }.journey-content { grid-template-columns: 220px minmax(0, 1fr); }.journey-steps { overflow-x: auto; grid-template-columns: repeat(6, minmax(150px, 1fr)); }.study-grid { grid-template-columns: 1fr; }.next-card,.tools-card { min-height: 190px; }
}

@media (max-width: 900px) {
  .dashboard { grid-template-rows: none; }.hero-panel,.journey-panel,.next-card,.tools-card,.insight-card { padding: 18px; }.journey-content { grid-template-columns: 1fr; }.profile-card { min-height: 100px; }.insight-card { display: flex; flex-direction: column; align-items: stretch; gap: 12px; }.metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 620px) {
  .hero-panel { padding: 18px; }.hero-copy h2 { font-size: 26px; }.hero-copy p { white-space: normal; }.hero-actions { flex-wrap: wrap; }.action-facts { grid-template-columns: 1fr; }.tool-grid { grid-template-columns: 1fr; }.metric-grid { grid-template-columns: 1fr; }
}

/* Dashboard actions and context controls use the same restrained teal command style. */
.hero-actions { gap: 9px; margin-top: 13px; }
.dashboard-primary-button {
  min-width: 122px;
  border-color: #236e62 !important;
  color: #fff !important;
  background: #236e62 !important;
  box-shadow: 0 7px 14px rgb(35 110 98 / 18%);
  font-weight: 750 !important;
}
.dashboard-primary-button:hover, .dashboard-primary-button:focus-visible {
  border-color: #194f48 !important;
  background: #194f48 !important;
  box-shadow: 0 8px 18px rgb(25 79 72 / 26%);
}
.dashboard-secondary-button {
  border-color: #b8ced8;
  color: #315a6b;
  background: rgb(255 255 255 / 80%);
  font-weight: 720 !important;
}
.dashboard-secondary-button:hover, .dashboard-secondary-button:focus-visible {
  border-color: #6da397;
  color: #1d6156;
  background: #f1faf7;
}
.next-action-button { width: 100%; }
.current-focus {
  align-self: center;
  max-width: 650px;
  margin: 0 8px;
  padding: 14px 18px;
  transform: translateY(-7px);
}
.current-focus > strong { margin-top: 8px; font-size: 19px; }
.current-focus > span { margin-top: 4px; }
.focus-profile { margin-top: 10px; padding-top: 9px; }
.switch-button {
  display: grid;
  width: 30px;
  height: 30px;
  padding: 0;
  place-items: center;
  border-color: rgb(188 225 247 / 42%);
  border-radius: 9px;
  background: rgb(117 183 231 / 18%);
  color: #e7f5ff;
  transition: border-color .18s ease, background .18s ease, transform .18s ease;
}
.switch-button:hover:not(:disabled), .switch-button:focus-visible:not(:disabled) {
  border-color: rgb(191 236 222 / 72%);
  background: rgb(59 170 147 / 30%);
  transform: translateY(-1px);
}
.switch-button :deep(svg) { width: 15px; height: 15px; }
.switch-button:disabled { opacity: .58; }
</style>
