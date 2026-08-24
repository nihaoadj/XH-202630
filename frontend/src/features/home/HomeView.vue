<template>
  <div class="home-page">
    <section class="home-hero">
      <div class="hero-copy">
        <span class="page-kicker">DOMAIN SKILL LEARNING WORKBENCH</span>
        <h2>让领域技能学习更清晰地进入下一步</h2>
        <p>从学习方向、资源阅读、练习反馈和学习记录进入对应流程。当前可通过不同领域知识库组织个性化学习闭环。</p>
        <div class="hero-actions">
          <el-button class="app-primary-button" type="primary" :icon="Plus" @click="$router.push('/learning/new')">新建学习方向</el-button>
          <el-button class="app-secondary-button" :icon="Clock" @click="$router.push('/learning/history')">查看学习历史</el-button>
        </div>
      </div>
      <aside class="hero-status" aria-label="当前学习状态">
        <span class="status-kicker">TODAY'S FOCUS</span>
        <strong>{{ currentDirection?.name || '创建你的第一个学习方向' }}</strong>
        <p>{{ generatedResourceCount ? `已准备 ${generatedResourceCount} 份学习资源，完成练习后可获得下一轮建议。` : '从学习方向和初始诊断开始，系统会为你建立个性化学习路径。' }}</p>
        <div class="status-tags">
          <span>阶段：{{ profileStage }}</span>
          <span>资源：{{ generatedResourceCount }} 份</span>
        </div>
      </aside>
    </section>

    <section class="learning-summary" :aria-busy="loadingSummary">
      <div class="summary-heading">
        <span class="page-kicker">CURRENT LEARNING</span>
        <strong>当前学习摘要</strong>
      </div>
      <article v-for="item in learningSummary" :key="item.label" class="summary-item">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </article>
    </section>

    <section class="dashboard-grid">
      <article class="next-action-panel">
        <div>
          <span class="page-kicker">RECOMMENDED NEXT STEP</span>
          <h3>{{ nextAction.title }}</h3>
          <p>{{ nextAction.description }}</p>
        </div>
        <el-button class="app-primary-button" type="primary" @click="$router.push(nextAction.to)">{{ nextAction.button }}</el-button>
      </article>
      <article class="learning-route-panel">
        <div class="route-heading"><span class="page-kicker">LEARNING LOOP</span><strong>你的学习闭环</strong></div>
        <ol class="route-list">
          <li><b>01</b><span>阅读资源</span><small>学习当前批次内容</small></li>
          <li><b>02</b><span>完成反馈</span><small>记录正式测评结果</small></li>
          <li><b>03</b><span>选择下一步</span><small>强化薄弱点或学习新知识</small></li>
        </ol>
      </article>
    </section>

    <div class="quick-entry-heading">
      <div><span class="page-kicker">QUICK ENTRY</span><h3>学习快捷入口</h3></div>
      <span>按当前学习进度继续</span>
    </div>

    <section class="tool-grid">
      <button v-for="tool in tools" :key="tool.title" type="button" class="tool-card" @click="$router.push(tool.to)">
        <span class="tool-index">{{ tool.index }}</span>
        <span class="tool-icon"><el-icon><component :is="tool.icon" /></el-icon></span>
        <span class="tool-copy">
          <strong>{{ tool.title }}</strong>
          <small>{{ tool.description }}</small>
        </span>
        <i>→</i>
      </button>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Clock, DataAnalysis, Document, Plus, Reading } from '@element-plus/icons-vue'
import { generateApi, knowledgeApi, profileApi, resourceApi } from '../../api'
import { useAppStore } from '../../stores/app'
import { formatDateTime } from '../../utils/generationDisplay'

const store = useAppStore()
const profiles = ref([])
const tracks = ref([])
const resources = ref([])
const jobs = ref([])
const loadingSummary = ref(false)

const currentProfile = computed(() =>
  profiles.value.find((profile) => profile.learner_id === store.currentLearnerId) || store.currentProfile || profiles.value[0] || null,
)
const currentDirection = computed(() => {
  const directionId = currentProfile.value?.knowledge_base_id || store.currentLearningDirectionId
  return tracks.value.find((track) => track.track_id === directionId || track.knowledge_base_id === directionId) || null
})
const profileStage = computed(() => currentProfile.value?.skill_level || (currentProfile.value ? '待诊断' : '未建立'))
const generatedResourceCount = computed(() => resources.value.length || jobs.value.reduce((total, job) => total + (job.resource_ids?.length || 0), 0))
const latestLearningTime = computed(() => {
  const values = [
    ...resources.value.map((resource) => resource.created_at),
    ...jobs.value.map((job) => job.finished_at || job.created_at),
  ].filter(Boolean)
  if (!values.length) return '暂无记录'
  return formatDateTime(values.sort((left, right) => String(right).localeCompare(String(left)))[0])
})

const learningSummary = computed(() => [
  { label: '当前方向', value: currentDirection.value?.name || store.currentLearningDirectionName || '未选择' },
  { label: '当前画像阶段', value: profileStage.value },
  { label: '已生成资源数量', value: `${generatedResourceCount.value} 份` },
  { label: '最近一次学习时间', value: latestLearningTime.value },
])
const nextAction = computed(() => {
  if (!currentProfile.value) return {
    title: '先建立学习方向', description: '选择学习目标并完成初始诊断，系统会据此生成第一批学习资源。',
    button: '新建学习方向', to: '/learning/new',
  }
  if (!generatedResourceCount.value) return {
    title: '生成第一批学习资源', description: '当前画像已就绪，选择资源类型后即可开始生成个性化学习材料。',
    button: '去生成资源', to: '/generate',
  }
  return {
    title: '继续阅读本轮学习资源', description: '完成资源学习后提交练习反馈，即可获得强化薄弱点或学习新知识的下一步选择。',
    button: '进入学习资源', to: '/resources',
  }
})

async function loadSummary() {
  loadingSummary.value = true
  try {
    const [profileResult, domainResult] = await Promise.all([
      profileApi.list({ page: 1, page_size: 50 }),
      knowledgeApi.listDomains(),
    ])
    profiles.value = profileResult.data.items || profileResult.data.profiles || []
    tracks.value = (domainResult.data.domains || []).flatMap((domain) => domain.tracks || [])

    const learnerId = currentProfile.value?.learner_id || store.currentLearnerId || profiles.value[0]?.learner_id
    if (!learnerId) return
    const profile = profiles.value.find((item) => item.learner_id === learnerId)
    if (profile && learnerId !== store.currentLearnerId) {
      const track = tracks.value.find((item) => item.track_id === profile.knowledge_base_id || item.knowledge_base_id === profile.knowledge_base_id)
      store.resumeProfile(profile, profile.knowledge_base_id, track?.name || '')
    }
    const [resourceResult, jobResult] = await Promise.allSettled([
      resourceApi.listByLearner(learnerId),
      generateApi.listJobs(learnerId),
    ])
    if (resourceResult.status === 'fulfilled') resources.value = resourceResult.value.data.resources || []
    if (jobResult.status === 'fulfilled') jobs.value = jobResult.value.data.items || []
  } catch (error) {
    console.error(error)
    ElMessage.error('当前学习摘要加载失败')
  } finally {
    loadingSummary.value = false
  }
}

const tools = [
  { index: '01', title: '学习资源', description: '进入资源学习与阅读', to: '/resources', icon: Reading },
  { index: '02', title: '练习反馈', description: '记录练习结果', to: '/feedback', icon: ChatDotRound },
  { index: '03', title: '学习报告', description: '回看诊断与进步', to: '/report', icon: DataAnalysis },
  { index: '04', title: '学习历史', description: '按画像查看内容', to: '/learning/history', icon: Document },
]

onMounted(loadSummary)
</script>

<style scoped>
.home-page {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding-bottom: 16px;
}

.home-hero,
.tool-card {
  border: 1px solid var(--rag-line);
  border-radius: 8px;
  background: #ffffff;
  box-shadow: var(--rag-shadow-soft);
}

.home-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(280px, .65fr);
  gap: 28px;
  align-items: center;
  min-height: 238px;
  padding: 28px 36px;
  background: linear-gradient(115deg, #ffffff 0%, #f6f9ff 58%, #eef5ff 100%);
}

.hero-copy h2 {
  margin: 9px 0 0;
  max-width: 760px;
  color: var(--rag-ink);
  font-size: 32px;
  line-height: 1.18;
}

.hero-copy p {
  max-width: 720px;
  margin: 11px 0 0;
  color: var(--rag-muted);
  font-size: 15px;
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  gap: 10px;
  margin-top: 20px;
  flex-wrap: wrap;
}

.hero-status {
  padding: 22px;
  border: 1px solid #d5e4f8;
  border-radius: 14px;
  background: rgba(255, 255, 255, .78);
}

.status-kicker { display:block; color:#2c68c8; font-size:11px; font-weight:800; letter-spacing:.08em; }
.hero-status > strong { display:block; margin-top:10px; color:var(--rag-ink); font-size:19px; line-height:1.35; }
.hero-status p { margin:9px 0 0; color:var(--rag-muted); font-size:13px; line-height:1.6; }
.status-tags { display:flex; flex-wrap:wrap; gap:8px; margin-top:15px; }
.status-tags span { padding:6px 9px; border-radius:999px; background:#edf5ff; color:#2d609e; font-size:12px; font-weight:700; }

.tool-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  align-items: stretch;
}

.dashboard-grid { display:grid; grid-template-columns:minmax(0, 1fr) minmax(0, 1fr); gap:14px; }
.next-action-panel,.learning-route-panel { min-width:0; padding:20px 22px; border:1px solid var(--rag-line); border-radius:12px; background:#fff; box-shadow:var(--rag-shadow-soft); }
.next-action-panel { display:flex; align-items:center; justify-content:space-between; gap:20px; background:linear-gradient(125deg,#ffffff,#f1f7ff); }
.next-action-panel h3,.quick-entry-heading h3 { margin:6px 0 0; color:var(--rag-ink); font-size:20px; }
.next-action-panel p { max-width:580px; margin:8px 0 0; color:var(--rag-muted); font-size:13px; line-height:1.6; }
.route-heading { display:flex; flex-direction:column; }.route-heading strong { margin-top:6px; color:var(--rag-ink); font-size:18px; }
.route-list { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:16px 0 0; padding:0; list-style:none; }
.route-list li { display:grid; gap:3px; min-width:0; padding-left:10px; border-left:2px solid #d7e7fb; }.route-list b { color:var(--rag-blue-700); font-size:11px; }.route-list span { color:#244563; font-size:13px; font-weight:800; }.route-list small { color:#74879b; font-size:11px; line-height:1.4; }
.quick-entry-heading { display:flex; align-items:end; justify-content:space-between; gap:16px; }.quick-entry-heading > span { color:#74879b; font-size:12px; }

.learning-summary {
  display: grid;
  grid-template-columns: minmax(150px, 0.8fr) repeat(4, minmax(0, 1fr));
  gap: 10px;
  align-items: stretch;
  padding: 14px;
  border: 1px solid var(--rag-line);
  border-radius: 8px;
  background: #ffffff;
  box-shadow: var(--rag-shadow-soft);
}

.summary-heading,
.summary-item {
  min-width: 0;
  padding: 9px 12px;
}

.summary-heading {
  display: flex;
  flex-direction: column;
  justify-content: center;
  border-right: 1px solid var(--rag-line);
}

.summary-heading strong {
  margin-top: 6px;
  color: var(--rag-ink);
  font-size: 16px;
}

.summary-item {
  border-left: 1px solid #edf2f7;
}

.summary-item span,
.summary-item strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.summary-item span {
  color: #72839a;
  font-size: 11px;
}

.summary-item strong {
  margin-top: 7px;
  color: #1b3857;
  font-size: 14px;
}

.tool-card {
  display: grid;
  grid-template-columns: 34px 42px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 12px;
  min-height: clamp(118px, 14vh, 160px);
  padding: 18px;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.tool-card:hover {
  border-color: var(--rag-blue-500);
  box-shadow: var(--rag-shadow);
  transform: translateY(-2px);
}

.tool-index {
  align-self: start;
  color: var(--rag-blue-700);
  font-size: 12px;
  font-weight: 850;
}

.tool-icon {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 8px;
  background: var(--rag-blue-100);
  color: var(--rag-blue-800);
  font-size: 19px;
}

.tool-copy {
  min-width: 0;
}

.tool-copy strong,
.tool-copy small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-copy strong {
  color: var(--rag-ink);
  font-size: 17px;
}

.tool-copy small {
  margin-top: 7px;
  color: var(--rag-muted);
  font-size: 13px;
}

.tool-card i {
  color: var(--rag-blue-700);
  font-size: 18px;
  font-style: normal;
}

@media (max-width: 1180px) {
  .home-hero { grid-template-columns:1fr; }
  .dashboard-grid { grid-template-columns:1fr; }
  .learning-summary {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .summary-heading {
    grid-column: 1 / -1;
    padding: 0 4px 4px;
    border-right: 0;
  }

  .summary-item:first-of-type {
    border-left: 0;
  }

  .tool-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .home-page {
    gap: 16px;
    padding-bottom: 0;
  }

  .home-hero { min-height:0; padding:22px; }
  .dashboard-grid { gap:12px; }
  .next-action-panel { align-items:flex-start; flex-direction:column; }
  .route-list { grid-template-columns:1fr; }
  .quick-entry-heading { align-items:flex-start; flex-direction:column; gap:6px; }

  .home-hero {
    padding: 20px;
  }

  .hero-copy h2 {
    font-size: 27px;
  }

  .tool-grid {
    grid-template-columns: 1fr;
  }

  .learning-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .summary-item:nth-of-type(odd) {
    border-left: 0;
  }

  .tool-card {
    grid-template-columns: 30px 40px minmax(0, 1fr) 16px;
    min-height: 96px;
  }
}
</style>
