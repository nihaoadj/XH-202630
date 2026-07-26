<template>
  <div class="history-page">
    <section class="toolbar">
      <el-input v-model="keyword" placeholder="按学习者 ID / 专业 / 目标搜索" clearable class="search" />
      <el-select v-model="skillFilter" clearable placeholder="能力层级">
        <el-option label="初级" value="初级" />
        <el-option label="中级" value="中级" />
        <el-option label="进阶" value="进阶" />
      </el-select>
    </section>

    <div class="history-grid">
      <el-empty v-if="!filteredProfiles.length" description="没有匹配的历史学习记录" />
      <el-card v-for="profile in filteredProfiles" :key="profile.learner_id" class="history-card">
        <template #header>
          <div class="history-head">
            <div>
              <strong>{{ profile.learner_id }}</strong>
              <p>{{ resolveTrackName(profile.knowledge_base_id) }}</p>
            </div>
            <el-tag>{{ profile.skill_level }}</el-tag>
          </div>
        </template>

        <p><strong>背景：</strong>{{ profile.education }} / {{ profile.major }}</p>
        <p><strong>目标：</strong>{{ profile.learning_goal || '暂无目标' }}</p>
        <p><strong>薄弱点：</strong>{{ (profile.weak_points || []).join('、') || '-' }}</p>

        <div class="action-row">
          <el-button size="small" type="primary" @click="resume(profile)">继续生成</el-button>
          <el-button size="small" @click="toResources(profile)">资源</el-button>
          <el-button size="small" @click="toReport(profile)">报告</el-button>
        </div>
      </el-card>
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
const profiles = ref([])
const tracks = ref([])
const keyword = ref('')
const skillFilter = ref('')

const filteredProfiles = computed(() =>
  profiles.value.filter((profile) => {
    const searchable = [profile.learner_id, profile.major, profile.learning_goal].join(' ').toLowerCase()
    const matchesKeyword = !keyword.value || searchable.includes(keyword.value.toLowerCase())
    const matchesSkill = !skillFilter.value || profile.skill_level === skillFilter.value
    return matchesKeyword && matchesSkill
  })
)

function resolveTrackName(trackId) {
  return tracks.value.find((item) => item.track_id === trackId)?.name || trackId || '未命名方向'
}

function applyProfile(profile) {
  store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id))
}

function resume(profile) {
  applyProfile(profile)
  router.push('/generate')
}

function toResources(profile) {
  applyProfile(profile)
  router.push('/resources')
}

function toReport(profile) {
  applyProfile(profile)
  router.push('/report')
}

onMounted(async () => {
  try {
    const [profileRes, domainRes] = await Promise.all([
      profileApi.list({ page: 1, page_size: 50 }),
      knowledgeApi.listDomains(),
    ])
    profiles.value = profileRes.data.items || profileRes.data.profiles || []
    tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
  } catch (error) {
    console.error(error)
    ElMessage.error('历史学习记录加载失败')
  }
})
</script>

<style scoped>
.history-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.toolbar {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.search {
  width: min(420px, 100%);
}

.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}

.history-card {
  border-radius: 10px;
}

.history-head,
.action-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.history-head p {
  margin: 6px 0 0;
  color: #667085;
}

.action-row {
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
