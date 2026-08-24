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
  gap: 16px;
}

.home-hero,
.tool-card {
  border: 1px solid var(--rag-line);
  border-radius: 8px;
  background: #ffffff;
  box-shadow: var(--rag-shadow-soft);
}

.home-hero {
  padding: 28px;
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

.tool-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

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
  min-height: 118px;
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
