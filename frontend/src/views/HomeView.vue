<template>
  <div class="dashboard">
    <section class="hero">
      <div class="hero-copy">
        <span class="eyebrow">教学培训总览</span>
        <h2>围绕学习方向、画像、诊断、资源与反馈组织完整训练流程</h2>
        <p>
          这里是培训系统的主工作台。你可以从当前方向继续生成资源，也可以新建学习方向，或回到历史学习记录继续推进。
        </p>
      </div>
      <div class="hero-stats">
        <div class="stat-card">
          <strong>{{ domains.length }}</strong>
          <span>领域</span>
        </div>
        <div class="stat-card">
          <strong>{{ totalTracks }}</strong>
          <span>学习方向</span>
        </div>
        <div class="stat-card">
          <strong>{{ profiles.length }}</strong>
          <span>历史画像</span>
        </div>
      </div>
    </section>

    <section class="module-grid">
      <article class="module-card current-card">
        <div class="module-header">
          <div>
            <span class="module-kicker">当前学习方向</span>
            <h3>{{ currentDirection?.name || store.currentLearningDirectionName || '尚未选择学习方向' }}</h3>
          </div>
          <el-tag type="success">{{ store.currentLearnerId || '未设置学习者' }}</el-tag>
        </div>
        <p class="module-description">
          {{ currentDirection?.description || '当前尚未建立可继续推进的学习方向。建议先新建学习方向并完成画像与诊断。' }}
        </p>
        <div class="module-actions">
          <el-button type="primary" @click="$router.push('/generate')" :disabled="!store.currentLearningDirectionId">
            继续生成资源
          </el-button>
          <el-button @click="$router.push('/resources')" :disabled="!store.currentLearnerId">
            查看资源
          </el-button>
          <el-button @click="$router.push('/report')" :disabled="!store.currentLearnerId">
            查看报告
          </el-button>
        </div>
      </article>

      <article class="module-card">
        <span class="module-kicker">新建学习方向</span>
        <h3>从领域选择开始建立新的学习训练链路</h3>
        <p class="module-description">
          先选择领域和学习方向，再通过问卷构建初始画像，随后跳转到诊断题页面完成真实能力测评。
        </p>
        <div class="module-actions">
          <el-button type="primary" @click="$router.push('/learning/new')">开始新建</el-button>
        </div>
      </article>

      <article class="module-card">
        <span class="module-kicker">历史学习方向</span>
        <h3>回看过去的画像与学习记录</h3>
        <p class="module-description">
          历史方向页面集中展示既有画像、当前能力层级、学习目标与方向上下文，适合续学与回顾。
        </p>
        <div class="module-actions">
          <el-button type="primary" plain @click="$router.push('/learning/history')">查看历史</el-button>
        </div>
      </article>

      <article class="module-card">
        <span class="module-kicker">资源查看</span>
        <h3>查看已经生成的教学资源与证据引用</h3>
        <p class="module-description">
          将讲义、实操指南、测试题和知识点覆盖放在同一处浏览，方便培训内容复盘与复用。
        </p>
        <div class="module-actions">
          <el-button type="primary" plain @click="$router.push('/resources')">进入资源库</el-button>
        </div>
      </article>
    </section>

    <section class="section-head">
      <div>
        <h3>近期学习记录</h3>
        <p>从最近画像快速继续进入某一条学习方向。</p>
      </div>
      <el-button text @click="$router.push('/learning/history')">查看全部</el-button>
    </section>

    <div class="history-grid">
      <el-empty v-if="!profiles.length" description="暂时还没有历史学习记录" />
      <article
        v-for="profile in recentProfiles"
        :key="profile.learner_id"
        class="history-card"
      >
        <div class="history-top">
          <div>
            <h4>{{ profile.learner_id }}</h4>
            <p>{{ resolveTrackName(profile.knowledge_base_id) }}</p>
          </div>
          <el-tag>{{ profile.skill_level }}</el-tag>
        </div>
        <p class="history-goal">{{ profile.learning_goal || '暂无学习目标' }}</p>
        <div class="history-meta">
          <span>{{ profile.education }}</span>
          <span>{{ profile.major }}</span>
        </div>
        <div class="history-actions">
          <el-button size="small" type="primary" @click="resumeLearning(profile)">继续学习</el-button>
          <el-button size="small" @click="openReport(profile)">报告</el-button>
          <el-button size="small" @click="openResources(profile)">资源</el-button>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { knowledgeApi, profileApi } from '../api'
import { useAppStore } from '../stores/app'

const router = useRouter()
const store = useAppStore()
const domains = ref([])
const profiles = ref([])

const totalTracks = computed(() => domains.value.reduce((sum, domain) => sum + (domain.tracks?.length || 0), 0))
const allTracks = computed(() => domains.value.flatMap((domain) => domain.tracks || []))
const recentProfiles = computed(() => profiles.value.slice(0, 6))
const currentDirection = computed(() =>
  allTracks.value.find(
    (item) => item.track_id === store.currentLearningDirectionId || item.knowledge_base_id === store.currentLearningDirectionId
  )
)

function resolveTrackName(trackId) {
  return allTracks.value.find((item) => item.track_id === trackId || item.knowledge_base_id === trackId)?.name || trackId || '未命名方向'
}

function resumeLearning(profile) {
  const trackName = resolveTrackName(profile.knowledge_base_id)
  store.resumeProfile(profile, profile.knowledge_base_id, trackName)
  router.push('/generate')
}

function openReport(profile) {
  const trackName = resolveTrackName(profile.knowledge_base_id)
  store.resumeProfile(profile, profile.knowledge_base_id, trackName)
  router.push('/report')
}

function openResources(profile) {
  const trackName = resolveTrackName(profile.knowledge_base_id)
  store.resumeProfile(profile, profile.knowledge_base_id, trackName)
  router.push('/resources')
}

async function loadDashboard() {
  try {
    const [domainRes, profileRes] = await Promise.all([
      knowledgeApi.listDomains(),
      profileApi.list({ page: 1, page_size: 12 }),
    ])
    domains.value = domainRes.data.domains || []
    profiles.value = profileRes.data.items || profileRes.data.profiles || []
  } catch (error) {
    console.error(error)
    ElMessage.error('工作台数据加载失败')
  }
}

onMounted(loadDashboard)
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 26px;
}

.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.8fr);
  gap: 18px;
  padding: 28px;
  border-radius: 18px;
  background:
    linear-gradient(135deg, rgba(14, 165, 233, 0.14), rgba(52, 211, 153, 0.12)),
    #ffffff;
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.eyebrow,
.module-kicker {
  display: inline-block;
  margin-bottom: 10px;
  font-size: 12px;
  font-weight: 700;
  color: #1d4ed8;
}

.hero h2 {
  margin: 0;
  font-size: 32px;
  line-height: 1.2;
}

.hero p {
  margin: 14px 0 0;
  color: #526277;
  line-height: 1.7;
}

.hero-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 128px;
  padding: 18px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.stat-card strong {
  font-size: 28px;
}

.stat-card span {
  margin-top: 8px;
  color: #5f6b7a;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.module-card,
.history-card {
  padding: 22px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.05);
}

.module-card h3,
.history-card h4,
.section-head h3 {
  margin: 0;
}

.current-card {
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98));
}

.module-header,
.history-top,
.section-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.module-description,
.history-goal,
.section-head p,
.history-top p {
  color: #5a6878;
  line-height: 1.65;
}

.module-actions,
.history-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 18px;
}

.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

.history-goal {
  min-height: 52px;
}

.history-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  color: #667085;
  font-size: 13px;
}

@media (max-width: 960px) {
  .hero,
  .module-grid {
    grid-template-columns: 1fr;
  }

  .hero-stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .hero {
    padding: 20px;
  }

  .hero h2 {
    font-size: 26px;
  }

  .hero-stats {
    grid-template-columns: 1fr;
  }
}
</style>
