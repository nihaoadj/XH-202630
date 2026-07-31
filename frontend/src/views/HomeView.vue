<template>
  <div class="dashboard">
    <section class="hero">
      <div class="hero-copy">
        <span class="eyebrow">学习流程总览</span>
        <h2>先维护用户资料，再用 5 步完成学习方向创建、诊断和资源生成</h2>
        <p>
          当前主流程已经调整为：用户资料 -> 选择领域 -> 选择方向 -> 填写问卷 -> 完成诊断 -> 查看诊断结果并选择资源 -> 进入生成状态页。
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
          <span>学习画像</span>
        </div>
      </div>
    </section>

    <section class="module-grid">
      <article class="module-card current-card">
        <div class="module-header">
          <div>
            <span class="module-kicker">当前用户</span>
            <h3>{{ store.currentUserProfile?.display_name || store.currentUserId || '尚未设置用户资料' }}</h3>
          </div>
          <el-tag type="success">{{ store.currentLearnerId || '暂无学习画像' }}</el-tag>
        </div>
        <p class="module-description">
          {{ currentDirection?.description || '先创建用户资料，再进入新的学习方向流程。完成诊断后，系统会将你带到资源生成状态页。' }}
        </p>
        <div class="module-actions">
          <el-button type="primary" @click="$router.push('/user/profile')">维护用户资料</el-button>
          <el-button @click="$router.push('/learning/new')">新建学习方向</el-button>
          <el-button @click="$router.push('/generate')" :disabled="!store.currentLearnerId">查看生成状态</el-button>
        </div>
      </article>

      <article class="module-card">
        <span class="module-kicker">主流程入口</span>
        <h3>新建学习方向并在第 5 步选择资源类型</h3>
        <p class="module-description">
          问卷只保留方向相关动态信息，学历、专业等固定信息已经拆到用户资料中，不需要每次重复填写。
        </p>
        <div class="module-actions">
          <el-button type="primary" @click="$router.push('/learning/new')">开始新建</el-button>
        </div>
      </article>

      <article class="module-card">
        <span class="module-kicker">学习历史</span>
        <h3>按时间线回看问卷、诊断与资源生成过程</h3>
        <p class="module-description">
          历史页会聚合每个学习画像的关键事件，帮助你排查流程问题，也方便继续进入资源或生成状态页。
        </p>
        <div class="module-actions">
          <el-button type="primary" plain @click="$router.push('/learning/history')">查看历史</el-button>
        </div>
      </article>

      <article class="module-card">
        <span class="module-kicker">资源查看</span>
        <h3>查看已生成资源并按任务过滤结果</h3>
        <p class="module-description">
          资源生成是异步过程，提交后无需原地等待。生成完成后，你可以从状态页跳转到资源页下载和查看结果。
        </p>
        <div class="module-actions">
          <el-button type="primary" plain @click="$router.push('/resources')">进入资源页</el-button>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { knowledgeApi, profileApi } from '../api'
import { useAppStore } from '../stores/app'

const store = useAppStore()
const domains = ref([])
const profiles = ref([])

const totalTracks = computed(() => domains.value.reduce((sum, domain) => sum + (domain.tracks?.length || 0), 0))
const allTracks = computed(() => domains.value.flatMap((domain) => domain.tracks || []))
const currentDirection = computed(() =>
  allTracks.value.find((item) => item.track_id === store.currentLearningDirectionId || item.knowledge_base_id === store.currentLearningDirectionId)
)

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

.module-card {
  padding: 22px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.05);
}

.current-card {
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98));
}

.module-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.module-card h3 {
  margin: 0;
}

.module-description {
  color: #5a6878;
  line-height: 1.65;
}

.module-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 18px;
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
