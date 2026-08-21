<template>
  <div class="history-page">
    <section class="archive-hero">
      <div class="archive-copy">
        <span class="archive-kicker">LEARNING ARCHIVE</span>
        <h2>学习历史档案</h2>
        <p>每次创建学习方向都会形成独立学习画像，在这里回看诊断、资源生成与练习反馈的完整足迹。</p>
      </div>
      <div class="archive-filter">
        <span>按能力层级筛选</span>
        <el-select v-model="skillFilter" clearable placeholder="全部层级">
          <el-option label="初级" value="初级" />
          <el-option label="中级" value="中级" />
          <el-option label="进阶" value="进阶" />
        </el-select>
        <b>{{ filteredProfiles.length }} 个学习画像</b>
      </div>
    </section>

    <section class="history-layout">
      <aside class="profile-archive">
        <div class="archive-list-head">
          <div><span class="archive-kicker">LEARNING PROFILES</span><h3>选择学习画像</h3></div>
          <el-button text @click="loadProfiles">刷新</el-button>
        </div>
        <el-empty v-if="!filteredProfiles.length" description="没有匹配的学习画像" :image-size="70" />
        <div v-else class="profile-scroll">
          <button v-for="profile in filteredProfiles" :key="profile.learner_id" type="button" class="profile-item" :class="{ active: activeLearnerId === profile.learner_id }" @click="selectProfile(profile)">
            <span class="profile-state">{{ activeLearnerId === profile.learner_id ? '当前查看' : profile.skill_level || '待诊断' }}</span>
            <strong>{{ profileDisplayName(profile) }}</strong>
            <span class="profile-direction">{{ resolveTrackName(profile.knowledge_base_id) }}</span>
            <span class="profile-goal">{{ profile.learning_goal || '尚未设置学习目标' }}</span>
          </button>
        </div>
      </aside>

      <main class="timeline-workspace">
        <template v-if="timeline">
          <header class="timeline-hero">
            <div>
              <span class="archive-kicker">LEARNING TIMELINE</span>
              <h3>本轮学习足迹</h3>
              <p>{{ timeline.profile.learning_goal || '本轮学习目标尚未设置' }}</p>
            </div>
            <div class="timeline-actions">
              <el-button @click="toResources">查看资源</el-button>
              <el-button type="primary" @click="toGenerate">资源生成状态</el-button>
            </div>
          </header>

          <section class="timeline-summary">
            <article><span>学习者</span><strong>{{ profileDisplayName(timeline.profile) }}</strong></article>
            <article><span>学习方向</span><strong>{{ resolveTrackName(timeline.profile.knowledge_base_id) }}</strong></article>
            <article><span>当前层级</span><strong>{{ timeline.profile.skill_level || '待诊断' }}</strong></article>
            <article><span>学习事件</span><strong>{{ timeline.events?.length || 0 }} 条</strong></article>
          </section>

          <section class="event-panel">
            <div class="event-panel-head"><span class="archive-kicker">ACTIVITY TRACE</span><h4>学习进程记录</h4></div>
            <el-empty v-if="!timeline.events?.length" description="尚未记录学习事件" :image-size="80" />
            <div v-else class="timeline-list">
              <article v-for="event in timeline.events" :key="event.event_id" class="timeline-item" :class="eventTone(event)">
                <div class="timeline-rail"><i /></div>
                <div class="timeline-content">
                  <div class="timeline-head"><strong>{{ event.title }}</strong><span v-if="event.status" class="event-status">{{ event.status }}</span></div>
                  <p>{{ eventDescription(event) }}</p>
                  <time>{{ formatTime(event.occurred_at) }}</time>
                </div>
              </article>
            </div>
          </section>
        </template>
        <el-empty v-else class="timeline-empty" description="请选择一个学习画像查看本轮学习足迹" :image-size="96" />
      </main>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { knowledgeApi, learningHistoryApi, profileApi } from '../api'
import { useAppStore } from '../stores/app'
import { formatDateTime } from '../utils/generationDisplay'

const router = useRouter()
const store = useAppStore()
const profiles = ref([])
const tracks = ref([])
const skillFilter = ref('')
const timeline = ref(null)
const activeLearnerId = ref('')
const filteredProfiles = computed(() => profiles.value.filter((profile) => !skillFilter.value || profile.skill_level === skillFilter.value))

function resolveTrackName(trackId) { return tracks.value.find((item) => item.track_id === trackId || item.knowledge_base_id === trackId)?.name || trackId || '未命名方向' }
function profileDisplayName(profile) { const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot; return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未命名画像' }
function formatTime(value) { return value ? formatDateTime(value) : '时间未知' }
function eventTone(event) {
  const text = `${event.event_type || ''} ${event.status || ''}`.toLowerCase()
  if (text.includes('fail') || text.includes('error')) return 'warning'
  if (text.includes('feedback') || text.includes('diagnos')) return 'mint'
  if (text.includes('generat') || text.includes('resource')) return 'blue'
  return 'slate'
}
function eventDescription(event) {
  const knowledgeBaseId = event?.payload?.knowledge_base_id
  if (knowledgeBaseId && ['initial_profile_created', 'questionnaire_submitted'].includes(event?.event_type)) return `学习方向 ${resolveTrackName(knowledgeBaseId)} 的问卷已提交。`
  return event?.description || '学习进度已更新。'
}
function applyProfile(profile) { store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id)) }
async function loadProfiles() {
  const [profileRes, domainRes] = await Promise.all([profileApi.list({ page: 1, page_size: 50 }), knowledgeApi.listDomains()])
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
}
async function loadTimeline(learnerId) { const res = await learningHistoryApi.timeline(learnerId); timeline.value = res.data }
async function selectProfile(profile) {
  try { activeLearnerId.value = profile.learner_id; applyProfile(profile); await loadTimeline(profile.learner_id) }
  catch (error) { console.error(error); ElMessage.error(error?.response?.data?.message || '学习时间线加载失败') }
}
function toGenerate() { if (timeline.value) router.push({ path: '/generate', query: { learnerId: timeline.value.learner_id } }) }
function toResources() { if (timeline.value) router.push({ path: '/resources', query: { learnerId: timeline.value.learner_id } }) }
onMounted(async () => {
  try { await loadProfiles(); const initial = profiles.value.find((item) => item.learner_id === store.currentLearnerId) || profiles.value[0]; if (initial) await selectProfile(initial) }
  catch (error) { console.error(error); ElMessage.error('历史学习记录加载失败') }
})
</script>

<style scoped>
.history-page { --ink:#10233f; --muted:#627692; --line:#dbe6f2; height:100%; min-height:0; display:flex; flex-direction:column; gap:16px; overflow:hidden; }.archive-hero,.profile-archive,.timeline-workspace { border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.96); box-shadow:0 12px 28px rgba(24,60,96,.06); }
.archive-hero { position:relative; flex:0 0 auto; display:grid; grid-template-columns:minmax(0,1fr) minmax(280px,.46fr); gap:24px; align-items:center; min-height:140px; padding:22px 28px; overflow:hidden; background:radial-gradient(circle at 86% 12%,rgba(48,203,174,.18),transparent 30%),linear-gradient(115deg,#eff6ff,#fcfdff 60%,#edf4ff); }.archive-hero::after { position:absolute; right:-25px; bottom:-70px; width:200px; height:150px; border:1px solid rgba(66,172,148,.15); border-radius:50%; content:''; }.archive-copy,.archive-filter { position:relative; z-index:1; }.archive-kicker { display:block; color:#2058a7; font-size:12px; font-weight:800; letter-spacing:.09em; line-height:1; }.archive-copy h2 { margin:8px 0 0; color:var(--ink); font-size:clamp(30px,2.2vw,39px); font-weight:800; letter-spacing:-.045em; line-height:1.08; }.archive-copy p { max-width:720px; margin:10px 0 0; color:#536d8d; font-size:14px; line-height:1.55; }.archive-filter { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:9px 10px; align-items:center; padding:15px; border:1px solid rgba(255,255,255,.85); border-radius:14px; background:rgba(255,255,255,.75); backdrop-filter:blur(8px); }.archive-filter > span { grid-column:1/-1; color:#617892; font-size:12px; font-weight:700; }.archive-filter b { color:#2b715f; font-size:12px; white-space:nowrap; }
.history-layout { flex:1; min-height:0; display:grid; grid-template-columns:278px minmax(0,1fr); gap:16px; overflow:hidden; }.profile-archive { min-height:0; display:flex; flex-direction:column; padding:18px 14px 14px; overflow:hidden; background:linear-gradient(165deg,#fbfdff,#f6f9ff); }.archive-list-head { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; padding:0 5px 13px; }.archive-list-head h3,.timeline-hero h3 { margin:7px 0 0; color:var(--ink); font-size:22px; font-weight:800; letter-spacing:-.035em; line-height:1.1; }.profile-scroll { min-height:0; display:flex; flex:1; flex-direction:column; gap:9px; overflow-y:auto; padding:2px 3px; scrollbar-width:thin; }.profile-item { width:100%; min-width:0; display:flex; flex-direction:column; align-items:flex-start; gap:5px; padding:13px; border:1px solid #dbe6f0; border-radius:13px; background:rgba(255,255,255,.82); color:#1b3857; text-align:left; cursor:pointer; transition:transform .2s ease,border-color .2s ease,box-shadow .2s ease; }.profile-item:hover { border-color:#9fc8ea; box-shadow:0 8px 18px rgba(39,88,140,.08); transform:translateY(-1px); }.profile-item.active { border-color:#46a98e; background:linear-gradient(145deg,#f2fbf8,#eff7ff); box-shadow:0 0 0 3px rgba(55,174,143,.1); }.profile-state { padding:4px 7px; border-radius:999px; background:#eef4fb; color:#55728e; font-size:10px; font-weight:800; }.profile-item.active .profile-state { background:#dff5ec; color:#168168; }.profile-item strong,.profile-direction,.profile-goal { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.profile-item strong { margin-top:3px; font-size:15px; }.profile-direction { color:#386c9e; font-size:12px; font-weight:700; }.profile-goal { max-width:100%; color:#718399; font-size:12px; }
.timeline-workspace { min-width:0; min-height:0; display:flex; flex-direction:column; overflow:hidden; }.timeline-hero { flex:0 0 auto; display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding:21px 25px 18px; border-bottom:1px solid #e2eaf2; background:linear-gradient(100deg,#fff,#fbfdff); }.timeline-hero p { margin:8px 0 0; overflow:hidden; color:#617792; font-size:14px; text-overflow:ellipsis; white-space:nowrap; }.timeline-actions { display:flex; flex:0 0 auto; gap:10px; }.timeline-actions :deep(.el-button) { height:36px; border-radius:8px; font-weight:700; }
.timeline-summary { flex:0 0 auto; display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:18px 24px 0; }.timeline-summary article { min-width:0; padding:12px 13px; border:1px solid #dce8f2; border-radius:11px; background:#f8fbff; }.timeline-summary article:nth-child(2n) { border-color:#cfe2ff; background:#f5f9ff; }.timeline-summary span,.timeline-summary strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.timeline-summary span { color:#71839a; font-size:11px; }.timeline-summary strong { margin-top:6px; color:#1b3857; font-size:15px; }
.event-panel { min-height:0; flex:1; margin:16px 24px 24px; padding:18px; overflow:auto; border:1px solid #e0e9f1; border-radius:14px; background:#fcfdff; scrollbar-width:thin; }.event-panel-head h4 { margin:7px 0 16px; color:#1a3756; font-size:18px; letter-spacing:-.02em; }.timeline-list { display:flex; flex-direction:column; }.timeline-item { display:grid; grid-template-columns:22px minmax(0,1fr); gap:12px; min-height:100px; }.timeline-rail { position:relative; display:flex; justify-content:center; }.timeline-rail::after { position:absolute; top:18px; bottom:-1px; width:1px; background:#dce7f0; content:''; }.timeline-item:last-child .timeline-rail::after { display:none; }.timeline-rail i { position:relative; z-index:1; width:12px; height:12px; margin-top:5px; border:3px solid #fff; border-radius:50%; background:#6d829a; box-shadow:0 0 0 2px #cfdae6; }.timeline-item.mint .timeline-rail i { background:#4a90ff; box-shadow:0 0 0 2px #b9d6fa; }.timeline-item.blue .timeline-rail i { background:#347fd2; box-shadow:0 0 0 2px #b9d6fa; }.timeline-item.warning .timeline-rail i { background:#cf8a29; box-shadow:0 0 0 2px #f2d7ab; }.timeline-content { min-width:0; padding:0 0 18px; }.timeline-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }.timeline-head strong { overflow:hidden; color:#1b3857; font-size:16px; text-overflow:ellipsis; white-space:nowrap; }.event-status { padding:4px 7px; border-radius:999px; background:#eef4fb; color:#55728e; font-size:10px; font-weight:700; white-space:nowrap; }.timeline-content p { margin:7px 0; color:#5d738e; font-size:13px; line-height:1.55; }.timeline-content time { color:#8190a3; font-size:12px; }.timeline-empty { height:100%; }
@media (max-width:1100px) { .archive-hero { grid-template-columns:1fr; }.archive-filter { max-width:480px; }.history-layout { grid-template-columns:250px minmax(0,1fr); }.timeline-summary { grid-template-columns:repeat(2,minmax(0,1fr)); } } @media (max-width:820px) { .history-page { height:auto; overflow:visible; }.history-layout { grid-template-columns:1fr; overflow:visible; }.profile-archive { max-height:320px; }.timeline-workspace { min-height:600px; }.timeline-hero { flex-direction:column; }.timeline-actions { width:100%; }.timeline-actions :deep(.el-button) { flex:1; } } @media (max-width:560px) { .archive-hero { padding:20px; }.archive-copy h2 { font-size:30px; }.archive-filter { grid-template-columns:1fr; }.archive-filter b { white-space:normal; }.timeline-hero,.event-panel { margin-left:16px; margin-right:16px; }.timeline-hero { padding-left:18px; padding-right:18px; }.timeline-summary { margin-left:16px; margin-right:16px; }.timeline-summary { grid-template-columns:1fr; }.event-panel { margin-bottom:16px; padding:16px; } }
</style>

