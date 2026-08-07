<template>
  <div class="history-page">
    <section class="toolbar">
      <div class="page-title-block">
        <h2>学习历史</h2>
        <p>按时间线查看问卷、诊断、资源生成、学习反馈和重新生成过程。</p>
      </div>
      <el-select v-model="skillFilter" clearable placeholder="能力层级">
        <el-option label="初级" value="初级" />
        <el-option label="中级" value="中级" />
        <el-option label="进阶" value="进阶" />
      </el-select>
    </section>

    <section class="history-layout">
      <el-card class="profile-list">
        <template #header>
          <div class="card-head">
            <span>学习画像</span>
            <el-button text @click="loadProfiles">刷新</el-button>
          </div>
        </template>

        <el-empty v-if="!filteredProfiles.length" description="没有匹配的学习画像" />
        <button
          v-for="profile in filteredProfiles"
          :key="profile.learner_id"
          type="button"
          class="profile-item"
          :class="{ active: activeLearnerId === profile.learner_id }"
          @click="selectProfile(profile)"
        >
          <strong>{{ profileDisplayName(profile) }}</strong>
          <span>{{ resolveTrackName(profile.knowledge_base_id) }}</span>
          <span>{{ profile.skill_level }} · {{ profile.learning_goal || '暂无学习目标' }}</span>
        </button>
      </el-card>

      <el-card class="timeline-card">
        <template #header>
          <div class="card-head">
            <div>
              <span>学习时间线</span>
              <p v-if="timeline">{{ timeline.profile.learning_goal || '暂无学习目标' }}</p>
            </div>
            <div class="header-actions">
              <el-button v-if="timeline" @click="toGenerate">资源</el-button>
              <el-button v-if="timeline" type="primary" @click="toGenerate">生成状态</el-button>
            </div>
          </div>
        </template>

        <el-empty v-if="!timeline" description="请选择左侧学习画像查看时间线" />
        <template v-else>
          <div class="timeline-summary">
            <div>
              <span>用户</span>
              <strong>{{ profileDisplayName(timeline.profile) }}</strong>
            </div>
            <div>
              <span>学习方向</span>
              <strong>{{ resolveTrackName(timeline.profile.knowledge_base_id) }}</strong>
            </div>
            <div>
              <span>当前层级</span>
              <strong>{{ timeline.profile.skill_level || '-' }}</strong>
            </div>
          </div>

          <div class="timeline-list">
            <article v-for="event in timeline.events" :key="event.event_id" class="timeline-item">
              <div class="timeline-dot" />
              <div class="timeline-content">
                <div class="timeline-head">
                  <strong>{{ event.title }}</strong>
                  <el-tag v-if="event.status" size="small">{{ event.status }}</el-tag>
                </div>
                <p>{{ event.description }}</p>
                <span class="timeline-time">{{ formatTime(event.occurred_at) }}</span>
              </div>
            </article>
          </div>
        </template>
      </el-card>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { knowledgeApi, learningHistoryApi, profileApi } from '../api'
import { useAppStore } from '../stores/app'

const router = useRouter()
const store = useAppStore()
const profiles = ref([])
const tracks = ref([])
const skillFilter = ref('')
const timeline = ref(null)
const activeLearnerId = ref('')

const filteredProfiles = computed(() =>
  profiles.value.filter((profile) => {
    const matchesSkill = !skillFilter.value || profile.skill_level === skillFilter.value
    return matchesSkill
  })
)

function resolveTrackName(trackId) {
  return tracks.value.find((item) => item.track_id === trackId)?.name || trackId || '未命名方向'
}

function profileDisplayName(profile) {
  const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot
  return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未命名画像'
}

function formatTime(value) {
  if (!value) return '时间未知'
  return new Date(value).toLocaleString()
}

function applyProfile(profile) {
  store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id))
}

async function loadProfiles() {
  const [profileRes, domainRes] = await Promise.all([
    profileApi.list({ page: 1, page_size: 50 }),
    knowledgeApi.listDomains(),
  ])
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
}

async function loadTimeline(learnerId) {
  const res = await learningHistoryApi.timeline(learnerId)
  timeline.value = res.data
}

async function selectProfile(profile) {
  try {
    activeLearnerId.value = profile.learner_id
    applyProfile(profile)
    await loadTimeline(profile.learner_id)
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '学习时间线加载失败')
  }
}

function toGenerate() {
  if (!timeline.value) return
  router.push({
    path: '/generate',
    query: { learnerId: timeline.value.learner_id },
  })
}

onMounted(async () => {
  try {
    await loadProfiles()
    const initial = profiles.value.find((item) => item.learner_id === store.currentLearnerId) || profiles.value[0]
    if (initial) {
      await selectProfile(initial)
    }
  } catch (error) {
    console.error(error)
    ElMessage.error('历史学习记录加载失败')
  }
})
</script>

<style scoped>
.history-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
  overflow: hidden;
}

.toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 20px 22px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}

.page-title-block h2 {
  margin: 0;
  font-size: 24px;
  line-height: 1.2;
}

.page-title-block p {
  margin: 8px 0 0;
  color: #667085;
}

.history-layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-width: thin;
}

.card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.card-head p {
  margin: 6px 0 0;
  color: #667085;
  font-size: 13px;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.profile-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  margin-bottom: 10px;
  border: 1px solid #d8dee8;
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.profile-item.active {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
}

.profile-item span {
  color: #667085;
  font-size: 13px;
}

.profile-list {
  position: sticky;
  top: 0;
  align-self: start;
  max-height: 100%;
  overflow: hidden;
}

.profile-list :deep(.el-card__body) {
  max-height: calc(100dvh - 244px);
  overflow-y: auto;
  scrollbar-width: thin;
}

.timeline-card :deep(.el-card__header) {
  position: sticky;
  top: 0;
  z-index: 10;
  background: #ffffff;
}

.timeline-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
  padding: 14px;
  border-radius: 12px;
  background: #f8fbff;
  border: 1px solid #e3edf8;
}

.timeline-summary span {
  display: block;
  margin-bottom: 6px;
  color: #667085;
  font-size: 12px;
}

.timeline-summary strong {
  color: #172033;
  font-size: 14px;
}

.timeline-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.timeline-item {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 14px;
}

.timeline-dot {
  width: 12px;
  height: 12px;
  margin-top: 6px;
  border-radius: 999px;
  background: #2563eb;
}

.timeline-content {
  padding-bottom: 14px;
  border-bottom: 1px solid #eef2f7;
}

.timeline-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.timeline-content p {
  margin: 8px 0;
  color: #4b5563;
}

.timeline-time {
  color: #667085;
  font-size: 13px;
}

@media (max-width: 960px) {
  .history-layout {
    grid-template-columns: 1fr;
  }

  .profile-list,
  .timeline-card :deep(.el-card__header) {
    position: static;
  }

  .profile-list {
    max-height: none;
  }

  .profile-list :deep(.el-card__body) {
    max-height: 38dvh;
  }

  .timeline-summary {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .toolbar {
    padding: 18px;
  }

  .toolbar .el-select {
    width: 100%;
  }

  .page-title-block {
    width: 100%;
  }

  .header-actions {
    width: 100%;
  }

  .header-actions .el-button {
    flex: 1;
  }
}
</style>
