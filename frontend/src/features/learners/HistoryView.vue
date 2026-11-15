<template>
  <div class="history-page">
    <section class="history-layout" aria-label="学习历史">
      <section class="profile-archive history-overview" aria-labelledby="profile-archive-title">
        <header class="archive-list-head">
          <div class="overview-control profile-control">
            <div class="overview-control-label">
              <h2 id="profile-archive-title">学习画像</h2>
              <span class="profile-count" aria-live="polite"><b>{{ profiles.length }} 个画像</b></span>
              <span class="archive-kicker">PROFILE</span>
            </div>
            <div class="profile-picker-row">
              <el-select :model-value="activeLearnerId" :disabled="!profiles.length" placeholder="请选择学习画像" aria-label="学习画像" popper-class="history-profile-dropdown" @change="selectProfileById">
                <el-option v-for="profile in profiles" :key="profile.learner_id" :label="profileSelectLabel(profile)" :value="profile.learner_id">
                  <div class="profile-option"><strong>{{ resolveTrackName(profile.knowledge_base_id) }}</strong><span>{{ profileDisplayName(profile) }} · {{ currentProfileRating(profile) || '待诊断' }}</span></div>
                </el-option>
              </el-select>
              <el-tooltip v-if="activeLearnerId" content="永久删除当前学习画像">
                <el-button class="profile-delete-action" :icon="Delete" :loading="deletingProfile" aria-label="删除学习画像" @click="deleteSelectedProfile">删除</el-button>
              </el-tooltip>
            </div>
          </div>
          <el-button class="archive-refresh" :icon="Refresh" aria-label="刷新学习记录" @click="refreshHistory">刷新</el-button>
        </header>
        <section v-if="journey" class="state-grid" aria-label="当前学习状态">
          <article>
            <span class="state-label"><span>当前学习节点</span><small class="state-label-en">CURRENT NODE</small></span>
            <strong>{{ nodeLabels(journey.current_state.current_nodes) || '等待学习路径生成' }}</strong>
          </article>
          <article>
            <span class="state-label"><span>最近测评</span><small class="state-label-en">ASSESSMENT</small></span>
            <strong>{{ scoreLabel(journey.current_state.latest_assessment) }}</strong>
          </article>
          <article class="state-completed">
            <span class="state-label"><span>已掌握节点</span><small class="state-label-en">MASTERED</small></span>
            <strong>{{ masteredCountLabel }} <small v-if="masteredCount !== null">个</small></strong>
          </article>
          <article class="state-resource-count" :class="{ 'is-pending': loadingResourceCount, 'is-unavailable': resourceCount === null && !loadingResourceCount }">
            <span class="state-label"><span>当前画像资源</span><small class="state-label-en">PROFILE RESOURCES</small></span>
            <strong aria-live="polite">{{ resourceCountLabel }}<small v-if="resourceCount !== null">份</small></strong>
          </article>
        </section>
      </section>

      <main class="journey-workspace" :aria-busy="loadingJourney" v-module-motion="{ key: activeLearnerId, ready: !loadingJourney && !!journey }">
        <div v-if="loadingJourney && !journey" class="history-empty timeline-empty" role="status">
          <el-icon class="is-loading" aria-hidden="true"><Refresh /></el-icon>
          <h3>正在读取学习记录</h3>
          <p>为当前画像整理学习旅程，请稍候。</p>
        </div>
        <div v-else-if="journeyError && !journey" class="history-empty timeline-empty" role="alert">
          <el-icon aria-hidden="true"><Warning /></el-icon>
          <h3>学习记录暂未载入</h3>
          <p>{{ journeyError }}</p>
          <el-button @click="retryJourney">重新加载</el-button>
        </div>
        <template v-else-if="journey">
          <section class="journey-panel" aria-labelledby="journey-title">
            <header class="panel-head">
              <div class="journey-heading">
                <div class="journey-title-row"><h2 id="journey-title">学习进程链路</h2><span class="archive-kicker">LEARNING JOURNEY</span><span class="round-count">当前显示 <b>{{ orderedRounds.length + learningRounds.length }}</b> 轮</span></div>
              </div>
            </header>

            <div class="journey-scroll" role="region" aria-label="学习进程记录" tabindex="0">
              <p v-if="journeyError" class="journey-error" role="alert">{{ journeyError }}</p>
              <div v-if="!orderedRounds.length && !orderedEvents.length && !learningRounds.length" class="history-empty journey-empty" role="status">
                <el-icon aria-hidden="true"><Clock /></el-icon>
                <span class="archive-kicker">YOUR JOURNEY STARTS HERE</span>
                <h3>尚未记录学习链路</h3>
                <p>完成学习后，这里会优先展示最近的学习记录。</p>
              </div>
              <div v-else class="journey-chain">
                <article v-for="(entry, index) in journeyEntries" :key="entry.key" class="journey-chain-item" :class="entryClasses(entry)" :aria-label="entry.kind === 'legacy' ? `${entry.item.topic} 学习链路` : undefined">
                  <div class="journey-chain-rail"><span>{{ String(journeyEntries.length - index).padStart(2, '0') }}</span></div>
                  <div class="journey-chain-content">
                    <template v-if="entry.kind === 'event'">
                      <div class="history-event-content">
                        <button type="button" class="history-event-trigger" :aria-expanded="expandedEvents.includes(entry.item.event_id)" :aria-controls="`history-event-${entry.item.event_id}`" @click="toggleEvent(entry.item.event_id)">
                          <span class="history-event-copy">
                            <span class="history-event-title-group"><span class="history-event-title" role="heading" aria-level="3">{{ entry.item.title }}</span><span v-if="eventBadge(entry.item)" class="history-event-badge" :class="{ 'is-rating': entry.item.event_type === 'diagnosis_completed' }"><el-icon aria-hidden="true"><DataAnalysis v-if="entry.item.event_type === 'diagnosis_completed'" /><Position v-else /></el-icon>{{ eventBadge(entry.item) }}</span></span>
                            <time class="history-event-time" :datetime="entry.item.occurred_at"><el-icon aria-hidden="true"><Clock /></el-icon>{{ formatTime(entry.item.occurred_at) }}</time>
                          </span>
                          <span class="history-event-expand" aria-hidden="true"><span>{{ expandedEvents.includes(entry.item.event_id) ? '收起' : '展开' }}</span><el-icon><ArrowDown /></el-icon></span>
                        </button>
                        <div v-show="expandedEvents.includes(entry.item.event_id)" :id="`history-event-${entry.item.event_id}`" class="history-event-detail"><p>{{ entry.item.description }}</p></div>
                      </div>
                    </template>
                    <template v-else-if="entry.kind === 'learning'">
                      <LearningRoundHistory :round="entry.item" :learner-id="activeLearnerId" />
                    </template>
                    <template v-else>
                      <div class="round-summary">
                        <el-button class="round-toggle" :aria-expanded="expandedRounds.includes(entry.item.round_id || entry.item.batch_id || entry.item.run_id)" :aria-controls="`history-stages-${entry.item.round_id || entry.item.batch_id || entry.item.run_id} history-round-${entry.item.round_id || entry.item.batch_id || entry.item.run_id}`" @click="toggleRound(entry.item.round_id || entry.item.batch_id || entry.item.run_id)">
                          <span class="round-heading">
                            <span class="round-kicker">{{ entry.item.is_followup ? '反馈后的后续学习' : '学习链路节点' }}</span>
                            <span class="round-title" role="heading" aria-level="3">{{ entry.item.topic }}</span>
                            <span class="round-meta">
                              <span class="round-status"><el-icon aria-hidden="true"><Warning v-if="entry.item.status === 'failed'" /><Clock v-else-if="['running', 'queued'].includes(entry.item.status)" /><CircleCheck v-else /></el-icon>{{ roundStatus(entry.item) }}</span>
                              <time :datetime="entry.item.occurred_at">{{ formatTime(entry.item.occurred_at) }}</time>
                              <span v-if="entry.item.parent_run_id" class="round-parent">由上一轮反馈触发</span>
                            </span>
                          </span>
                          <span class="round-toggle-label">{{ expandedRounds.includes(entry.item.round_id || entry.item.batch_id || entry.item.run_id) ? '收起详情' : '展开详情' }}</span><el-icon aria-hidden="true"><ArrowDown /></el-icon>
                        </el-button>
                      </div>

                      <div v-show="expandedRounds.includes(entry.item.round_id || entry.item.batch_id || entry.item.run_id)" :id="`history-stages-${entry.item.round_id || entry.item.batch_id || entry.item.run_id}`" class="journey-stages" aria-label="本轮六个学习环节">
                        <div class="journey-stage" :class="stageTone(entry.item.status)"><span class="stage-index">01</span><div><b>资源生成</b><small>{{ roundStatus(entry.item) }}</small></div></div>
                        <div class="journey-stage" :class="entry.item.resources.length ? 'done' : 'pending'"><span class="stage-index">02</span><div><b>资源发布</b><small>{{ entry.item.resources.length ? `${entry.item.resources.length} 项资源` : '尚无资源产物' }}</small></div></div>
                        <div class="journey-stage" :class="entry.item.assessment ? 'done' : 'pending'"><span class="stage-index">03</span><div><b>反馈测评</b><small>{{ scoreLabel(entry.item.assessment) }}</small></div></div>
                        <div class="journey-stage" :class="entry.item.feedback ? 'done' : 'pending'"><span class="stage-index">04</span><div><b>反馈决策</b><small>{{ entry.item.feedback ? entry.item.feedback.action : '待形成反馈' }}</small></div></div>
                        <div class="journey-stage" :class="entry.item.path_change ? 'done' : 'pending'"><span class="stage-index">05</span><div><b>路径变化</b><small>{{ pathStageLabel(entry.item.path_change) }}</small></div></div>
                        <div class="journey-stage" :class="entry.item.feedback?.followup_run_ids?.length ? 'done' : 'pending'"><span class="stage-index">06</span><div><b>后续任务</b><small>{{ entry.item.feedback?.followup_run_ids?.length ? `${entry.item.feedback.followup_run_ids.length} 个后续批次` : '暂无后续任务' }}</small></div></div>
                      </div>

                      <div v-show="expandedRounds.includes(entry.item.round_id || entry.item.batch_id || entry.item.run_id)" :id="`history-round-${entry.item.round_id || entry.item.batch_id || entry.item.run_id}`" class="round-detail">
                        <ol class="chain">
                          <li><b>生成</b><span>{{ runDetail(entry.item) }}</span></li>
                          <li><b>资源</b><span v-if="entry.item.resources.length">{{ entry.item.resources.map(resourceLabel).join('、') }}</span><span v-else>尚无可展示的资源产物</span></li>
                          <li><b>测评</b><span>{{ assessmentDetail(entry.item.assessment) }}</span></li>
                          <li><b>反馈</b><span>{{ feedbackDetail(entry.item.feedback) }}</span></li>
                          <li><b>学习路径</b><span>{{ pathDetail(entry.item.path_change) }}</span></li>
                        </ol>
                        <div v-if="entry.item.path_change?.mastery_changes?.length" class="mastery-list"><span v-for="item in entry.item.path_change.mastery_changes" :key="item.knowledge_point_id">{{ item.knowledge_point_id }}：{{ masteryLabel(item) }}</span></div>
                        <div class="round-links">
                          <el-button class="history-primary" :icon="Reading" @click="toResources(entry.item.batch_id || entry.item.run_id)">查看本轮资源<el-icon aria-hidden="true"><Right /></el-icon></el-button>
                          <el-button :icon="Connection" @click="toGenerate(entry.item.run_id)">查看运行进度</el-button>
                        </div>
                      </div>
                    </template>
                  </div>
                </article>
              </div>
              <el-button v-if="journey.next_offset !== null" class="load-more" :loading="loadingMore" @click="loadMore">加载更多轮次<el-icon v-if="!loadingMore" aria-hidden="true"><ArrowDown /></el-icon></el-button>
              <div v-else-if="orderedRounds.length || orderedEvents.length || learningRounds.length" class="journey-end"><span />当前记录已展示完毕<span /></div>
            </div>
          </section>
        </template>
        <div v-else class="history-empty timeline-empty" role="status">
          <el-icon aria-hidden="true"><Connection /></el-icon>
          <span class="archive-kicker">LEARNING ARCHIVE</span>
          <h3>{{ profiles.length ? '请选择一个学习画像查看学习旅程' : '尚未创建学习画像' }}</h3>
          <p>{{ profiles.length ? '从顶部画像选择器开始，回看每一轮学习的来路与进展。' : '创建学习画像后，可在这里查看学习旅程。' }}</p>
        </div>
      </main>
    </section>
  </div>
</template>

<script setup>
import { currentProfileRating } from '../../utils/profileRating.js'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, CircleCheck, Clock, Connection, DataAnalysis, Delete, Position, Reading, Refresh, Right, Warning } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { knowledgeApi } from '../knowledge/api.js'
import { learningHistoryApi, profileApi } from './api.js'
import { resourceApi } from '../learning-documents/api.js'
import { useAppStore } from '../../stores/app'
import LearningRoundHistory from './LearningRoundHistory.vue'
import { formatDateTime } from '../../utils/generationDisplay'

const router = useRouter(); const store = useAppStore()
const profiles = ref([]); const tracks = ref([])
const journey = ref(null); const activeLearnerId = ref(''); const deletingProfile = ref(false); const loadingMore = ref(false); const expandedRounds = ref([]); const expandedEvents = ref([])
const loadingJourney = ref(false)
const journeyError = ref('')
const masteredCount = ref(null); const loadingMasteredCount = ref(false)
let masteryRequestVersion = 0
const masteredCountLabel = computed(() => loadingMasteredCount.value ? '统计中' : masteredCount.value === null ? '暂不可用' : masteredCount.value)
const resourceCount = ref(null); const loadingResourceCount = ref(false)
let journeyRequestVersion = 0
let resourceCountRequestVersion = 0
let historyMounted = true
const resourceCountLabel = computed(() => loadingResourceCount.value ? '统计中' : resourceCount.value === null ? '暂不可用' : resourceCount.value)
const orderedRounds = computed(() => journey.value?.rounds || [])
const learningRounds = computed(() => journey.value?.learning_rounds || [])
const orderedEvents = computed(() => journey.value?.unlinked_events || [])
const journeyEntries = computed(() => [
  ...orderedEvents.value.map(item => ({ kind: 'event', key: `event:${item.event_id}`, item, time: item.occurred_at })),
  ...learningRounds.value.map(item => ({ kind: 'learning', key: `learning:${item.round_id}`, item, time: item.created_at })),
  ...orderedRounds.value.map(item => ({ kind: 'legacy', key: `legacy:${item.round_id || item.batch_id || item.run_id}`, item, time: item.occurred_at })),
].sort((a, b) => historyTime(b.time) - historyTime(a.time) || a.key.localeCompare(b.key)))
function historyTime(value) {
  const time = value ? new Date(value).getTime() : NaN
  return Number.isFinite(time) ? time : -Infinity
}
function entryClasses(entry) {
  if (entry.kind === 'event') return { 'history-event': true }
  if (entry.kind === 'learning') return { failed: entry.item.members.some(member => member.state === 'failed'), running: entry.item.members.some(member => member.state === 'producing') }
  return { failed: entry.item.status === 'failed', running: ['running', 'queued'].includes(entry.item.status), followup: entry.item.is_followup }
}
function resolveTrackName(id) { return tracks.value.find((item) => item.track_id === id || item.knowledge_base_id === id)?.name || id || '未命名方向' }
function eventBadge(event) {
  if (event.event_type === 'initial_profile_created' && event.payload?.knowledge_base_id) return resolveTrackName(event.payload.knowledge_base_id)
  if (event.event_type === 'diagnosis_completed') return event.payload?.ability_level || event.status || ''
  return ''
}
function profileDisplayName(profile) { const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot; return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未命名画像' }
function profileSelectLabel(profile) { return `${profileDisplayName(profile)} / ${resolveTrackName(profile.knowledge_base_id)} / ${currentProfileRating(profile) || '待诊断'}` }
function formatTime(value) { return value ? formatDateTime(value) : '时间未知' }
function nodeLabels(nodes) { return (nodes || []).map((item) => item.name || item.knowledge_point_id || item.node_id).join('、') }
function scoreLabel(assessment) { return assessment ? `正确率 ${Math.round((assessment.score || 0) * 100)}%` : '尚未测评' }
function resourceLabel(item) { return `${item.resource_type}（${item.publication_status === 'published' ? '已发布' : '待发布'}）` }
function roundStatus(round) { return ({ completed: '资源已生成', running: '正在生成', queued: '等待生成', failed: '生成失败' })[round.status] || round.status }
function stageTone(status) { return status === 'failed' ? 'failed' : ['running', 'queued'].includes(status) ? 'active' : 'done' }
function runDetail(round) { const run = round.run_summary || {}; return run.availability === 'available' ? `${roundStatus(round)}；运行节点：${run.current_node || '已完成'}；审核 ${run.review_count || 0} 次${run.revision_count ? `，修订 ${run.revision_count} 次` : ''}` : (run.error_message || '该历史任务未保留完整运行详情') }
function assessmentDetail(item) { if (!item) return '完成本轮资源后可进行正式测评'; const count = Number.isInteger(item.correct_count) && Number.isInteger(item.total_count) ? `${item.correct_count}/${item.total_count} 题正确，` : ''; return `${count}正确率 ${Math.round((item.score || 0) * 100)}%，覆盖 ${item.knowledge_points.length} 个知识点` }
function feedbackDetail(item) { return item ? `策略：${item.action}；${item.reason}${item.next_action ? `；建议：${item.next_action}` : ''}` : '尚未形成反馈决策' }
const pathMutationLabels = Object.freeze({ insert_remedial: '纠错复习', insert_practice: '强化复习', advance: '进阶学习', hold: '保持当前路径' })
function pathNodeItems(item, key) {
  const detailItems = item?.[key]
  if (Array.isArray(detailItems) && detailItems.length) return detailItems
  const idKey = key.replace('_nodes', '_node_ids')
  return (item?.[idKey] || []).map((nodeId) => ({ node_id: nodeId, name: nodeId }))
}
function pathNodeNames(item, key) {
  return pathNodeItems(item, key).map((node) => node?.name || node?.knowledge_point_id || node?.node_id).filter(Boolean).join('、')
}
function pathStageLabel(item) {
  if (!item) return '等待测评结果'
  const actualNext = (item.next_steps || []).map((step) => step.topic).filter(Boolean).join('、')
  if (actualNext) return `下一步：${actualNext}`
  const assessed = pathNodeNames(item, 'assessed_nodes')
  if (assessed) return `本轮测评：${assessed}`
  return pathMutationLabels[item.mutation_type] || '路径未变化'
}
function pathDetail(item) {
  if (!item) return '测评后将据结果更新学习路径'
  const changes = []
  const actualNext = (item.next_steps || []).map((step) => step.topic).filter(Boolean).join('、')
  const assessed = pathNodeNames(item, 'assessed_nodes')
  if (actualNext) changes.push(`下一步：${actualNext}`)
  if (assessed) changes.push(`本轮测评：${assessed}`)
  if (!changes.length) changes.push(pathMutationLabels[item.mutation_type] || '本轮未改变节点')
  return `路径版本 ${item.path_version_before} → ${item.path_version_after}；${changes.join('；')}`
}
function masteryLabel(item) { return `${item.before == null ? '未评估' : `${Math.round(item.before * 100)}%`} → ${Math.round((item.after || 0) * 100)}%（${item.status}）` }
function toggleRound(runId) { expandedRounds.value = expandedRounds.value.includes(runId) ? expandedRounds.value.filter((id) => id !== runId) : [...expandedRounds.value, runId] }
function toggleEvent(eventId) { expandedEvents.value = expandedEvents.value.includes(eventId) ? expandedEvents.value.filter((id) => id !== eventId) : [...expandedEvents.value, eventId] }
function applyProfile(profile) { store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id)) }
async function loadProfiles() {
  const [profileRes, domainRes] = await Promise.all([profileApi.list({ page: 1, page_size: 50 }), knowledgeApi.listDomains()])
  if (!historyMounted) return
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
}
async function refreshProfiles() {
  try { await loadProfiles() }
  catch (error) {
    if (!historyMounted) return
    journeyError.value = error?.response?.data?.message || '学习画像加载失败，请重试'
    ElMessage.error(journeyError.value)
  }
}
async function retryJourney() {
  if (activeLearnerId.value) {
    void loadOverviewCounts(activeLearnerId.value)
    return loadJourney(activeLearnerId.value)
  }
  await refreshProfiles()
  const initial = profiles.value.find((item) => item.learner_id === store.currentLearnerId) || profiles.value[0]
  if (initial) await selectProfile(initial)
}
async function loadJourney(learnerId, offset = 0) {
  if (!learnerId || !historyMounted) return
  const version = ++journeyRequestVersion
  const isCurrent = () => historyMounted && version === journeyRequestVersion && activeLearnerId.value === learnerId
  loadingJourney.value = true
  loadingMore.value = offset > 0
  journeyError.value = ''
  try {
    const res = await learningHistoryApi.journey(learnerId, { offset, limit: 20 })
    if (!isCurrent()) return
    if (res.data.learner_id !== learnerId) throw new Error('学习记录与当前画像不一致，请重新加载')
    if (offset && journey.value?.learner_id !== learnerId) return
    journey.value = offset ? { ...journey.value, rounds: [...journey.value.rounds, ...res.data.rounds], learning_rounds: [...(journey.value.learning_rounds || []), ...(res.data.learning_rounds || [])].filter((round, index, rows) => rows.findIndex(item => item.round_id === round.round_id) === index), next_offset: res.data.next_offset } : res.data
  } catch (error) {
    if (!isCurrent()) return
    journeyError.value = error?.response?.data?.message || error?.message || '学习旅程加载失败'
    ElMessage.error(journeyError.value)
  } finally {
    if (isCurrent()) { loadingJourney.value = false; loadingMore.value = false }
  }
}
async function loadMasteredCount(learnerId) {
  const version = ++masteryRequestVersion
  const isCurrent = () => historyMounted && version === masteryRequestVersion && activeLearnerId.value === learnerId
  masteredCount.value = null
  loadingMasteredCount.value = true
  try {
    const { data } = await profileApi.abilityNodes(learnerId)
    if (!isCurrent()) return
    if (data.learner_id !== learnerId || !Array.isArray(data.nodes)) throw new Error('能力画像数据不匹配')
    masteredCount.value = new Set(data.nodes.filter(node => node.skill_node_id && node.mastery?.status === 'mastered' && node.mastery.objective_evidence_count > 0 && Number.isFinite(node.mastery.mastery_score)).map(node => node.skill_node_id)).size
  } catch {
    if (isCurrent()) masteredCount.value = null
  } finally {
    if (isCurrent()) loadingMasteredCount.value = false
  }
}
async function loadOverviewCounts(learnerId) {
  void loadMasteredCount(learnerId)
  const version = ++resourceCountRequestVersion
  const isCurrent = () => historyMounted && version === resourceCountRequestVersion && activeLearnerId.value === learnerId
  resourceCount.value = null
  loadingResourceCount.value = true
  try {
    const response = await resourceApi.listByLearner(learnerId, { page: 1, page_size: 1, summary_only: true })
    if (!isCurrent()) return
    const total = Number(response.data?.total)
    resourceCount.value = Number.isInteger(total) && total >= 0 ? total : null
  } catch {
    if (isCurrent()) resourceCount.value = null
  } finally {
    if (isCurrent()) loadingResourceCount.value = false
  }
}
async function selectProfile(profile, allowDuringDelete = false) {
  if (!historyMounted || (deletingProfile.value && !allowDuringDelete)) return
  activeLearnerId.value = profile.learner_id
  expandedRounds.value = []
  expandedEvents.value = []
  journey.value = null
  applyProfile(profile)
  void loadOverviewCounts(profile.learner_id)
  await loadJourney(profile.learner_id)
}
async function selectProfileById(learnerId) {
  const profile = profiles.value.find((item) => item.learner_id === learnerId)
  if (profile) await selectProfile(profile)
}
async function refreshHistory() {
  try {
    await loadProfiles()
  } catch (error) {
    if (!historyMounted) return
    journeyError.value = error?.response?.data?.message || '学习画像加载失败，请重试'
    ElMessage.error(journeyError.value)
    return
  }
  if (!historyMounted) return
  const current = profiles.value.find((item) => item.learner_id === activeLearnerId.value)
    || profiles.value.find((item) => item.learner_id === store.currentLearnerId)
    || profiles.value[0]
  if (current) {
    await selectProfile(current)
    return
  }
  ++journeyRequestVersion; ++resourceCountRequestVersion
  activeLearnerId.value = ''; journey.value = null; journeyError.value = ''; resourceCount.value = null; masteredCount.value = null
  loadingJourney.value = false; loadingResourceCount.value = false
}
async function loadMore() {
  if (loadingJourney.value || journey.value?.next_offset == null) return
  await loadJourney(journey.value.learner_id, journey.value.next_offset)
}
async function deleteSelectedProfile() {
  const profile = profiles.value.find((item) => item.learner_id === activeLearnerId.value) || journey.value?.profile
  if (!profile?.learner_id || deletingProfile.value) return
  try {
    await ElMessageBox.confirm(`将永久删除“${profileDisplayName(profile)}”及其学习记录。此操作不可恢复，是否继续？`, '删除学习画像', { type: 'warning', confirmButtonText: '永久删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger', closeOnClickModal: false })
  } catch { return }
  deletingProfile.value = true
  try {
    const learnerId = profile.learner_id
    const index = profiles.value.findIndex((item) => item.learner_id === learnerId)
    await profileApi.delete(learnerId)
    ++journeyRequestVersion
    profiles.value = profiles.value.filter((item) => item.learner_id !== learnerId)
    activeLearnerId.value = ''; journey.value = null; journeyError.value = ''; resourceCount.value = null; masteredCount.value = null
    ++resourceCountRequestVersion; loadingResourceCount.value = false
    loadingJourney.value = false; loadingMore.value = false
    if (store.currentLearnerId === learnerId) store.clearLearnerContext()
    const replacement = profiles.value[index] || profiles.value[index - 1]
    if (replacement) await selectProfile(replacement, true)
    ElMessage.success('学习画像及其相关内容已永久删除')
  } catch (error) {
    ElMessage.error(error?.response?.data?.message || '删除学习画像失败，请稍后重试')
  } finally { deletingProfile.value = false }
}
function toGenerate(runId) { if (journey.value) router.push({ path: '/generate', query: { learnerId: journey.value.learner_id, ...(runId ? { runId } : {}) } }) }
function toResources(batchId) { if (journey.value) router.push({ path: '/resources', query: { learnerId: journey.value.learner_id, ...(batchId ? { runId: batchId } : {}) } }) }
onMounted(retryJourney)
onBeforeUnmount(() => { historyMounted = false; ++journeyRequestVersion; ++resourceCountRequestVersion })
</script>

<style scoped>
.journey-error { margin: 0 0 16px; padding: 12px 16px; border-left: 2px solid #a33b40; border-radius: 4px; background: #fdf8f7; color: #a33b40; font-size: 13px; line-height: 1.7; }
.history-page {
  --history-ink: #132c40;
  --history-muted: #536b7d;
  --history-teal: #086575;
  --history-line: #d9e4eb;
  --history-card-line: #d5e2ea;
  --history-paper: #eef3f6;
  --history-node-done: #167c7c;
  --history-radius: 18px;
  --history-radius-sm: 6px;
  --history-shadow: 0 8px 20px rgba(37, 74, 100, 0.08), inset 0 1px #fff;
  --rag-ink: #132c40;
  --rag-line: #d9e4eb;
  --rag-blue-700: #086575;
  --rag-blue-800: #1d4055;
  --rag-blue-500: #187487;
  --rag-blue-50: #edf8f6;
  --rag-radius: 8px;
  --rag-shadow-soft: 0 18px 36px -28px rgba(19, 44, 64, 0.45);
  --rag-surface: #fff;
  --rag-surface-alt: #f8fafb;
  --el-color-primary: #086575;
  --el-color-primary-light-3: #408895;
  --el-color-primary-light-5: #71a6af;
  --el-color-primary-light-7: #c8e0e2;
  --el-color-primary-light-9: #edf8f6;
  --el-color-primary-dark-2: #054b58;
  --el-border-radius-base: 5px;
  --el-text-color-regular: #132c40;
  --el-border-color: #cbdbe4;
  height: 100%;
  min-height: 0;
  color: var(--history-ink);
}
.history-page > .history-layout {
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr);
  gap: 12px;
  border: 0 !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  overflow: hidden;
}
.history-page .profile-archive {
  display: flex;
  min-height: 0;
  flex-direction: column;
  padding: 16px 18px;
  border: 1px solid rgba(169, 198, 215, 0.72);
  border-radius: var(--history-radius);
  background: linear-gradient(150deg, #f4f9fc 0%, #e1eff3 62%, #edf5f9 100%);
  box-shadow: var(--history-shadow);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  overflow: hidden;
}
.archive-list-head { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 12px; padding: 0 0 10px; border-bottom: 1px solid rgba(179, 204, 213, 0.72); }
.archive-kicker, .state-caption, .profile-number, .round-kicker, .stage-index {
  font-family: Consolas, "SFMono-Regular", monospace;
  font-size: 10px;
  font-weight: 400;
  letter-spacing: .05em;
}
.history-page .archive-kicker { display: block; color: var(--history-teal); line-height: 1.5; }
.archive-list-head h2, .panel-head h2 { margin: 6px 0 0; color: var(--history-ink); font-size: 20px; font-weight: 700; line-height: 1.35; letter-spacing: -.01em; }
.history-page :deep(.el-button) { min-width: 44px; min-height: 44px; height: auto; margin-left: 0; padding: 10px 14px; border-radius: var(--history-radius-sm); color: var(--history-ink); font-size: 12px; font-weight: 600; box-shadow: none; }
.history-page :deep(.el-button > span) { gap: 6px; }
.history-page :deep(.el-button:hover) { border-color: #8fb9be; background: #edf8f6; color: #086575; }
.history-page :deep(.el-button:focus-visible) { outline: 2px solid #167587; outline-offset: 3px; }
.history-page .archive-refresh { padding: 10px 9px; border-color: transparent; background: transparent; color: var(--history-muted); }
.history-page :deep(.el-select) { width: 100%; min-width: 0; }
.overview-control { min-width: 0; }
.overview-control-label { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.overview-control-label label { color: var(--history-muted); font-size: 12px; line-height: 1.5; }
.overview-control-label h2 { margin: 0; color: var(--history-ink); font-size: 15px; font-weight: 650; line-height: 1.5; }
.overview-control-label > .archive-kicker { margin-left: auto; color: var(--history-muted); }
.overview-control-label { padding-right: 92px; }
.profile-count { margin-left: 0; }
.profile-count b { padding: 3px 9px; border: 1px solid rgba(137, 185, 194, 0.46); border-radius: 999px; background: rgba(235, 247, 248, 0.8); color: var(--history-teal); font-size: 10px; font-weight: 650; line-height: 1.5; white-space: nowrap; }
.profile-picker-row { display: grid; grid-template-columns: minmax(0, 1fr) 84px; gap: 8px; }
.history-page :deep(.el-select__wrapper) { min-height: 40px; border: 1px solid rgba(126, 171, 184, 0.54); border-radius: 11px; background: rgba(255, 255, 255, 0.84); box-shadow: 0 8px 18px -14px rgba(19, 60, 78, 0.5), inset 0 1px rgba(255, 255, 255, 0.92); }
.history-page :deep(.el-select__wrapper.is-focused) { border-color: #6ba8b2; box-shadow: 0 0 0 3px rgba(8, 101, 117, 0.1), inset 0 1px rgba(255, 255, 255, 0.92); }
.profile-option { display: flex; min-height: 50px; flex-direction: column; justify-content: center; gap: 2px; padding: 4px 2px; line-height: 1.45; }
.profile-option strong { color: #132c40; font-size: 13px; font-weight: 650; }
.profile-option span { color: #536b7d; font-size: 11px; }
:global(.history-profile-dropdown.el-popper) { border: 1px solid rgba(137, 185, 194, 0.5); border-radius: 12px; background: rgba(248, 252, 253, 0.96); box-shadow: 0 18px 34px -18px rgba(19, 60, 78, 0.46); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); }
:global(.history-profile-dropdown .el-select-dropdown__list) { padding: 6px; }
:global(.history-profile-dropdown .el-select-dropdown__item) { height: auto; min-height: 58px; margin: 3px 0; padding: 4px 10px; border: 1px solid transparent; border-radius: 10px; line-height: normal; }
:global(.history-profile-dropdown .el-select-dropdown__item.hover) { background: rgba(230, 244, 246, 0.82); }
:global(.history-profile-dropdown .el-select-dropdown__item.is-selected) { border-color: rgba(91, 160, 169, 0.42); background: linear-gradient(145deg, rgba(236, 248, 247, 0.96), rgba(220, 240, 241, 0.9)); color: #086575; }
.history-page .profile-delete-action { width: 84px; min-width:84px; min-height:40px; height: 40px; padding: 0; border: 1px solid rgba(137, 185, 194, 0.5); border-radius: 11px; background: linear-gradient(145deg, rgba(255, 255, 255, 0.92), rgba(226, 242, 245, 0.84)); color: var(--history-muted); box-shadow: 0 10px 20px -16px rgba(19, 60, 78, 0.55), inset 0 1px rgba(255, 255, 255, 0.95); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); }
.history-page .profile-delete-action:hover { border-color: #d7aeb0; color: #a33b40; background: linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(255, 238, 238, 0.9)); }
.history-page .archive-refresh { align-self: end; width:84px; height:40px; min-width: 84px; min-height: 40px; padding:7px 10px; border: 1px solid rgba(137, 185, 194, 0.5); border-radius: 11px; background: linear-gradient(145deg, rgba(255, 255, 255, 0.9), rgba(225, 241, 245, 0.82)); color: #145f6d; box-shadow: 0 10px 20px -16px rgba(19, 60, 78, 0.55), inset 0 1px rgba(255, 255, 255, 0.95); }
.history-page .archive-refresh:hover { border-color: #6ba8b2; background: linear-gradient(145deg, #fff, #e3f4f4); color: #086575; }
.history-page .profile-archive .state-grid { margin-top: 0; padding-top: 14px; border-top: 0; }
.journey-workspace { display: flex; min-height: 0; min-width: 0; flex-direction: column; overflow: hidden; }
.state-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  grid-auto-rows: 1fr;
  gap: 0;
}
.state-grid article { position:relative; display:flex; min-width:0; min-height:64px; flex-direction:column; gap:8px; padding:0 20px; border:0; border-left:1px solid rgba(167,194,206,.3); border-radius:0; background:transparent; box-shadow:none; }
.state-grid article:first-child { padding-left:0; border-left:0; }
.state-label { display: flex; align-items: center; gap: 9px; color: var(--history-muted); font-size: 12px; line-height: 1.5; }
.state-label .el-icon { display: inline-flex; flex: 0 0 auto; align-items: center; justify-content: center; width: 24px; height: 24px; border: 1px solid rgba(113, 177, 185, 0.22); border-radius: 8px; background: rgba(220, 240, 242, 0.72); color: var(--history-teal); font-size: 14px; box-shadow: inset 0 1px rgba(255, 255, 255, 0.8); }
.state-label-en { margin-left: auto; color: var(--history-muted); font-family: Consolas, "SFMono-Regular", monospace; font-size: 9px; font-weight: 400; letter-spacing: .04em; white-space: nowrap; }
.state-grid strong { display: -webkit-box; min-height: 0; overflow: hidden; color: var(--history-ink); font-size: 15px; font-weight: 650; line-height: 1.45; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }

.state-grid .state-completed strong, .state-grid .state-resource-count strong { display: flex; align-items: center; gap: 5px; color: var(--history-teal); font-size: 20px; line-height: 1.45; font-variant-numeric: tabular-nums; }
.state-grid .state-completed small, .state-grid .state-resource-count small { font-size: 12px; font-weight: 500; }

.state-grid .state-resource-count.is-pending strong, .state-grid .state-resource-count.is-unavailable strong { color: var(--history-muted); font-size: 14px; font-weight: 600; }
.state-caption { margin-top: auto; color: var(--history-muted); line-height: 1.5; }
.journey-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  margin-top: 0;
  border: 1px solid rgba(169, 198, 215, 0.72);
  border-radius: var(--history-radius);
  background: #fff;
  box-shadow: var(--history-shadow);
  overflow: hidden;
}
.panel-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 14px 22px; align-items: center; padding: 18px 22px; border-bottom: 1px solid rgba(169,198,215,.48); background: linear-gradient(150deg, #f4f9fc 0%, #e1eff3 62%, #edf5f9 100%); box-shadow: inset 0 1px rgba(255,255,255,.96); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); }
.journey-heading { flex: 1 1 300px; min-width: 0; }
.journey-title-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 13px; }
.journey-title-row h2 { margin: 0; }
.round-count { display: inline-flex; align-items: center; gap: 6px; margin-top: 7px; padding: 3px 10px; border: 1px solid #cfe3df; border-radius: 999px; background: #f0f8f7; color: #2f6660; font-size: 11px; white-space: nowrap; }
.journey-title-row .round-count { margin-top: 0; }
.round-count b { color: var(--history-teal); font-family: Consolas, monospace; font-size: 13px; font-weight: 600; }
.journey-scroll { min-width: 0; min-height: 0; flex: 1; padding: 18px 14px 10px; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; background: #fff; }
.journey-scroll:focus-visible { outline: 2px solid #167587; outline-offset: -2px; border-radius: 3px; }
.journey-scroll { scrollbar-width: thin; scrollbar-color: #9ebcc6 transparent; }
.journey-scroll::-webkit-scrollbar { width: 5px; height: 5px; }
.journey-scroll::-webkit-scrollbar-thumb { border-radius: 4px; background: #9ebcc6; }
.journey-chain-item { --node-color: #167c7c; display: grid; grid-template-columns: 38px minmax(0, 1fr); min-width: 0; }
.journey-chain-item.failed { --node-color: #b76165; }
.journey-chain-item.running { --node-color: #537996; }
.journey-chain-rail { --rail-center:36px; position:relative; display:flex; justify-content:center; }
.journey-chain-rail::before { position:absolute; top:var(--rail-center); left:calc(50% + 17px); right:-8px; z-index:0; height:1px; background:linear-gradient(90deg,rgba(74,145,158,.55),rgba(128,182,194,.18)); content:""; }
.journey-chain-rail::after { position:absolute; top:var(--rail-center); bottom:calc(-1 * var(--rail-center)); left:calc(50% - 1px); width:2px; border-radius:999px; background:linear-gradient(180deg,rgba(65,147,157,.65),rgba(133,190,199,.42)); box-shadow:0 0 6px rgba(36,133,143,.1); content:""; }
.journey-chain-item:last-child .journey-chain-rail::after { display:none; }
.journey-chain-rail > span {
  display: flex;
  position: relative;
  z-index: 1;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  margin-top:21px;
  box-sizing:border-box;
  border:1px solid rgba(117,169,181,.6);
  border-radius:11px;
  background:linear-gradient(145deg,rgba(255,255,255,.98),rgba(220,239,242,.92));
  color: #086575;
  font-family: Consolas, monospace;
  font-size:11px;
  font-weight:600;
  font-variant-numeric:tabular-nums;
  line-height:1;
  box-shadow:0 0 0 3px rgba(248,252,253,.96),0 4px 9px -5px rgba(25,87,103,.36),inset 0 1px #fff,inset 0 -1px rgba(116,171,185,.14);
}
.history-event .journey-chain-rail > span { border-color:rgba(137,171,187,.55); background:linear-gradient(145deg,#fff,rgba(231,241,247,.95)); color:#4c7187; }
.failed .journey-chain-rail > span { border-color: #e4b7b8; background: #fff2f1; color: #a33b40; }
.running .journey-chain-rail > span { border-color: #bacddb; background: #eaf1f8; color: #315b80; }
.journey-chain-content {
  min-width: 0;
  margin: 0 0 14px 8px;
  position: relative;
  border: 1px solid rgba(143, 179, 193, 0.48);
  border-left: 3px solid var(--node-color);
  border-radius: 16px;
  background: linear-gradient(142deg, rgba(255, 255, 255, 0.88), rgba(230, 243, 247, 0.74) 58%, rgba(225, 239, 247, 0.7));
  box-shadow: 0 20px 36px -24px rgba(15, 54, 73, 0.58), 0 5px 14px -10px rgba(31, 114, 129, 0.36), inset 0 1px rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  overflow: hidden;
  transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}
.journey-chain-item:hover .journey-chain-content { border-color: rgba(89, 155, 168, 0.58); box-shadow: 0 23px 38px -23px rgba(15, 54, 73, 0.64), 0 8px 18px -14px rgba(31, 114, 129, 0.44), inset 0 1px rgba(255, 255, 255, 0.98); }
.history-event .journey-chain-content { border-left-width: 3px; border-left-color: #6cabb6; background: linear-gradient(142deg, rgba(255, 255, 255, 0.92), rgba(220, 239, 244, 0.8) 58%, rgba(226, 239, 247, 0.78)); }
.history-event-content { padding: 0; }
.history-event-trigger { display: flex; width: 100%; min-width: 0; align-items: center; justify-content: space-between; gap: 16px; padding: 15px 18px; border: 0; background: linear-gradient(110deg, rgba(255,255,255,.3), rgba(226,243,246,.14) 54%, rgba(218,233,245,.25)); color: inherit; font: inherit; text-align: left; cursor: pointer; transition: background 180ms ease; }
.history-event-trigger:hover { background: linear-gradient(110deg, rgba(255,255,255,.78), rgba(211,238,240,.62) 54%, rgba(216,233,247,.66)); }
.history-event-trigger:focus-visible { outline: 2px solid #167587; outline-offset: -3px; }
.history-event-copy { display: grid; flex: 1; min-width: 0; gap: 4px; }
.event-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 3px 12px; }
.round-kicker { display: block; color: var(--history-muted); font-family: inherit; font-size: 11px; line-height: 1.65; }
.history-event-title { color: var(--history-ink); font-size: 15px; font-weight: 680; line-height: 1.55; overflow-wrap: anywhere; }
.history-event-expand { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 7px; padding: 8px 10px; border: 1px solid rgba(108,158,173,.3); border-radius: 999px; background: rgba(245,251,252,.68); color: #176b78; font-size: 11px; line-height: 1; white-space: nowrap; }
.history-event-expand .el-icon { transition: transform 180ms ease; }
.history-event-trigger[aria-expanded="true"] .history-event-expand .el-icon { transform: rotate(180deg); }
.history-event-detail { padding: 0 18px 16px; border-top: 1px solid rgba(134,177,190,.22); background: linear-gradient(150deg, rgba(249,253,254,.62), rgba(225,240,245,.5)); }
.history-event-detail p { margin: 12px 0 0; color: var(--history-muted); font-size: 12px; line-height: 1.8; overflow-wrap: anywhere; }
.event-heading time, .round-meta time { color: var(--history-muted); font-size: 11px; font-variant-numeric: tabular-nums; line-height: 1.65; }
.round-summary { border-bottom: 1px solid rgba(134,177,190,.26); background: linear-gradient(110deg, rgba(255,255,255,.42), rgba(220,239,242,.35) 58%, rgba(225,236,247,.4)); }
.history-page .round-toggle { display: flex; width: 100%; min-width: 0; min-height: 82px; align-items: center; justify-content: space-between; gap: 16px; margin: 0; padding: 14px 18px; border: 0; border-radius: 0; background: transparent; color: var(--history-ink); text-align: left; white-space: normal; box-shadow: none; }
.history-page .round-toggle:hover { border-color: transparent; background: linear-gradient(110deg, rgba(255,255,255,.66), rgba(210,238,239,.48) 58%, rgba(215,232,246,.54)); color: var(--history-ink); }
.history-page .round-toggle:focus-visible { outline: 2px solid #167587; outline-offset: -3px; }
.round-heading { display: grid; flex: 1; min-width: 0; gap: 3px; }
.round-heading .round-title { color: var(--history-ink); font-size: 17px; font-weight: 670; line-height: 1.5; overflow-wrap: anywhere; }
.followup .round-kicker { color: var(--history-teal); }
.round-meta { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; margin: 0; color: var(--history-muted); font-size: 11px; line-height: 1.65; }
.round-status { display: inline-flex; align-items: center; gap: 5px; color: var(--history-teal); }
.round-status .el-icon { font-size: 14px; }
.failed .round-status { color: #a33b40; }
.running .round-status { color: #315b80; }
.round-parent { padding-left: 10px; border-left: 1px solid var(--history-line); }
.round-toggle-label { flex: 0 0 auto; color: #176b78; font-size: 11px; font-weight: 550; white-space: nowrap; }
.round-toggle > .el-icon { flex: 0 0 auto; padding: 7px; border: 1px solid rgba(108,158,173,.3); border-radius: 50%; background: rgba(245,251,252,.72); transition: transform 180ms ease; }
.round-toggle[aria-expanded="true"] .el-icon { transform: rotate(180deg); }
.journey-stages { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); padding: 14px 18px; gap: 12px 0; border-bottom: 1px solid rgba(134,177,190,.22); background: linear-gradient(150deg, rgba(248,253,254,.66), rgba(224,240,245,.48)); }
.journey-stage { display: flex; min-width: 0; gap: 7px; padding: 0 10px; border-left: 1px solid var(--history-line); align-items: flex-start; }
.journey-stage:first-child { padding-left: 0; border-left: 0; }
.stage-index { display: flex; flex: 0 0 auto; justify-content: center; align-items: center; width: 22px; height: 22px; margin-top: 2px; border: 1px solid #ccd8e1; border-radius: 6px; background: #f4f7f9; color: #536b7d; font-size: 9px; line-height: 1; }
.journey-stage > div { min-width: 0; }
.journey-stage b { display: block; color: var(--history-ink); font-size: 12px; font-weight: 600; line-height: 1.8; }
.journey-stage small { display: block; margin-top: 5px; color: var(--history-muted); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.journey-stage.done .stage-index { border-color: #aad1cb; background: #eaf6f3; color: #086575; }
.journey-stage.active .stage-index { border-color: #bacddb; background: #eaf1f8; color: #315b80; }
.journey-stage.failed .stage-index { border-color: #e4b7b8; background: #fff2f1; color: #a33b40; }
.round-detail { padding: 16px 18px; border-top: 1px solid rgba(134,177,190,.22); background: linear-gradient(155deg, rgba(249,253,254,.68), rgba(226,240,245,.6)); }
.chain { display: grid; gap: 13px; margin: 0; padding: 0; list-style: none; }
.chain li { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 14px; padding: 9px 12px; border: 1px solid rgba(151,184,198,.28); border-radius: 10px; background: rgba(255,255,255,.42); color: var(--history-muted); font-size: 12px; line-height: 1.85; box-shadow: inset 0 1px rgba(255,255,255,.75); }
.chain b { color: var(--history-ink); font-weight: 600; }
.chain li > span { overflow-wrap: anywhere; }
.mastery-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.mastery-list span { padding: 5px 10px; border: 1px solid #cfe3df; border-radius: 999px; background: #f0f8f7; color: var(--history-teal); font-size: 11px; line-height: 1.8; overflow-wrap: anywhere; }
.round-links { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.history-page .history-primary { border-color: #11283c; background: #11283c; color: #fff; }
.history-page .history-primary:hover { border-color: #1d4055; background: #1d4055; color: #fff; }
.history-page .load-more { display: flex; margin: 22px auto 8px; border-color: #cbdbe4; background: #fff; }
.journey-end { display: flex; justify-content: center; align-items: center; gap: 12px; padding: 22px 0 8px; color: var(--history-muted); font-size: 11px; }
.journey-end > span { width: 32px; height: 1px; background: #c2d5de; }
.history-empty { display: flex; flex: 1; min-width: 0; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 28px 18px; text-align: center; }
.history-empty > .el-icon { margin-bottom: 7px; color: #167587; font-size: 35px; }
.history-empty h3 { margin: 0; font-size: 16px; font-weight: 600; line-height: 1.6; overflow-wrap: anywhere; }
.history-empty p { max-width: 340px; margin: 0; color: var(--history-muted); font-size: 12px; line-height: 1.8; }
.profile-empty h3 { font-size: 14px; }
.journey-empty { min-height: 260px; height: 100%; }
.timeline-empty { border: 1px solid var(--history-line); border-top: 2px solid #132c40; border-radius: var(--history-radius); background: #fff; box-shadow: var(--history-shadow); }

/* The compact header is scoped by the mounted history page; shared page styles stay untouched. */
:global(.app-shell:has(.history-page)) { background: #f5f7fa; }
:global(.app-shell:has(.history-page) .content-area) { padding: 22px 28px 24px; overflow: hidden; }

@media (max-width: 1500px) {
  .journey-stages { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px 0; }
  .journey-stage:nth-child(4) { padding-left: 0; border-left: 0; }
  .panel-head { gap: 12px 18px; }
  .journey-heading { flex-basis: 270px; }
}
@media (max-width: 1300px) {
  .history-page > .history-layout { gap: 10px; }
  .state-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .state-grid article { padding: 10px 12px 11px; }
}
@media (max-width: 1100px) {
  .state-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
}
@media (max-width: 960px), (max-height: 640px) {
  :global(.app-shell:has(.history-page) .content-area) { overflow: auto; }
  .history-page, .history-page > .history-layout { height: auto; overflow: visible; }
  .journey-workspace { overflow: visible; }
  .journey-scroll { overflow: visible; flex: none; min-height: 260px; }
  .history-page .profile-archive { max-height: none; }
  .journey-panel { min-height: 300px; flex: none; }
  .timeline-empty { min-height: 340px; }
}
@media (max-width: 960px) {
  .history-page > .history-layout { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .history-page .profile-archive { padding: 14px; }
  .archive-list-head { padding-bottom: 12px; gap: 12px; }
  .panel-head { display: flex; }
  .state-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  :global(.app-shell:has(.history-page) .content-area) { padding: 16px 16px 22px; }
  .panel-head { display: block; }
  .state-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .state-grid { gap: 8px; }
  .round-summary { padding: 0; }
  .history-page .round-toggle { gap: 10px; padding: 13px 12px; font-size: 11px; }
  .round-heading .round-title { font-size: 16px; }
  .journey-stages { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 0; }
  .panel-head { padding: 16px 14px; }
  .journey-stage:nth-child(4) { border-left: 1px solid var(--history-line); padding-left: 10px; }
  .journey-stage:nth-child(odd) { border-left: 0; padding-left: 0; }
}
@media (max-width: 600px) {
  .archive-list-head { grid-template-columns: minmax(0, 1fr); }
  .profile-control, .history-page .archive-refresh { grid-column: 1; }
  .history-page .archive-refresh { justify-self: stretch; }
  .state-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .state-grid article { min-height: 88px; padding: 10px 12px; }
  .state-grid .state-label { flex-wrap: wrap; gap: 6px; }
  .state-grid .state-label-en { flex-basis: 100%; margin-left: 30px; }
  :global(.app-shell:has(.history-page) .sidebar) { padding: 0; }
  :global(.app-shell:has(.history-page) .sidebar .sidebar-inner) { gap: 4px; padding: 8px 10px; }
  :global(.app-shell:has(.history-page) .sidebar .brand-block) { display: none; }
  :global(.app-shell:has(.history-page) .sidebar .nav-list) { gap: 6px; align-items: stretch; }
  :global(.app-shell:has(.history-page) .sidebar .nav-item) { display: flex; min-width: 44px; min-height: 44px; align-items: center; justify-content: center; padding: 8px; }
  :global(.app-shell:has(.history-page) .sidebar .nav-item .nav-icon) { display: inline-flex; }
  :global(.app-shell:has(.history-page) .sidebar .nav-item .nav-text) { display: none; }
  .round-summary { padding: 0; }
  .history-page .round-toggle { gap: 8px; padding: 12px 10px; }
  .round-toggle-label { font-size: 10px; }
  .journey-chain-item { grid-template-columns: 30px minmax(0, 1fr); }
  .journey-chain-rail { --rail-center:33px; }
  .journey-chain-rail > span { width:26px; height:26px; margin-top:20px; border-radius:9px; font-size:10px; }
  .journey-chain-rail::before { left:calc(50% + 15px); }
  .journey-chain-content { margin-left: 8px; }
  .journey-scroll { padding: 14px 8px 8px; }
  .journey-stages, .round-detail { padding: 14px; }
  .history-event-trigger { gap: 9px; padding: 14px; }
  .history-event-detail { padding: 0 14px 14px; }
  .history-event-expand { gap: 4px; padding: 7px 8px; }
  .chain li { grid-template-columns: minmax(0, 1fr); gap: 2px; }
  .round-links { flex-direction: column; align-items: stretch; }
  .history-page .round-links .el-button { width: 100%; }
  .round-parent { padding-left: 0; border: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .history-page .journey-chain-content, .history-page .round-toggle .el-icon, .history-page .history-event-trigger, .history-page .history-event-expand .el-icon, .history-page :deep(.el-button) { transition: none; }
}
.history-event-copy { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px 18px; }
.history-event-title-group { display:flex; align-items:center; flex-wrap:wrap; min-width:0; gap:7px 10px; }
.history-event-badge { display:inline-flex; align-items:center; gap:5px; max-width:100%; padding:3px 9px; border:1px solid rgba(104,154,179,.28); border-radius:999px; background:linear-gradient(135deg,rgba(255,255,255,.88),rgba(226,239,249,.75)); color:#365d75; box-shadow:0 4px 10px -7px rgba(23,67,88,.45),inset 0 1px rgba(255,255,255,.96); font-size:11px; font-weight:400; line-height:1.65; overflow-wrap:anywhere; }
.history-event-badge .el-icon { flex-shrink:0; color:#43869b; }
.history-event-badge.is-rating { border-color:rgba(52,143,139,.3); background:linear-gradient(135deg,rgba(245,255,252,.94),rgba(208,239,230,.8)); color:#25655f; }
.history-event-time { display:inline-flex; align-self:center; align-items:center; justify-content:center; gap:7px; padding:6px 10px; border:1px solid rgba(111,160,180,.46); border-radius:9px; background:linear-gradient(135deg,rgba(255,255,255,.88),rgba(233,243,248,.76)); box-shadow:inset 0 1px rgba(255,255,255,.96),0 3px 8px -6px rgba(30,76,98,.32); color:var(--history-muted, #536b7d); font-size:11px; font-variant-numeric:tabular-nums; white-space:nowrap; }
.state-label > span { white-space:nowrap; }
.state-grid article { box-sizing:border-box; justify-content:center; gap:8px; }
.state-grid article > strong { margin-left:0; min-height:29px; font-size:18px; line-height:29px; }
.state-grid .state-completed strong, .state-grid .state-resource-count strong { align-items:baseline; font-size:18px; line-height:29px; }

/* Keep the reference glass surface above the global theme's panel reset. */
.history-page .profile-archive.history-overview {
  border:1px solid rgba(181,211,222,.58) !important;
  border-radius:24px !important;
  background:linear-gradient(112deg,rgba(243,248,251,.98),rgba(224,242,245,.88) 72%,rgba(231,242,247,.96)) !important;
  box-shadow:0 3px 5px rgba(34,74,96,.08),0 12px 26px -18px rgba(34,74,96,.25),inset 0 1px rgba(255,255,255,.98) !important;
  padding:12px 18px;
}
.history-page .journey-panel { border-color:rgba(181,211,222,.65); border-radius:22px; box-shadow:0 3px 5px rgba(34,74,96,.06),0 12px 26px -18px rgba(34,74,96,.2),inset 0 1px #fff; }
.history-page .panel-head { background:linear-gradient(112deg,rgba(243,248,251,.98),rgba(224,242,245,.88) 72%,rgba(231,242,247,.96)); border-bottom-color:rgba(181,211,222,.48); }
.history-page .state-grid article > strong, .history-page .state-grid article > strong small { font-size:14px; font-weight:600; line-height:22px; }
.history-page .state-grid article > strong { min-height:22px; }
.history-page .round-count { gap:6px; padding:5px 11px; border:1px solid rgba(115,167,180,.36); border-radius:10px; background:linear-gradient(140deg,rgba(255,255,255,.92),rgba(226,242,246,.8)); box-shadow:0 3px 8px -5px rgba(30,76,98,.3),inset 0 1px #fff; color:#386474; }
.history-page .history-event-expand { justify-content:center; min-width:74px; min-height:34px; box-sizing:border-box; gap:8px; padding:7px 11px; border:1px solid rgba(96,158,174,.38); border-radius:11px; background:linear-gradient(145deg,rgba(255,255,255,.95),rgba(221,239,245,.8)); color:#195c70; font-size:12px; font-weight:600; line-height:1.3; box-shadow:0 4px 10px -6px rgba(22,78,101,.3),inset 0 1px rgba(255,255,255,.98); }
.history-page .history-event-expand .el-icon { flex:0 0 14px; width:14px; height:14px; padding:0; border:0; color:#438398; font-size:14px; }
.history-page .history-event-trigger:hover .history-event-expand { border-color:rgba(59,133,157,.65); }
.history-page .history-event-trigger[aria-expanded="true"] .history-event-expand { background:linear-gradient(145deg,rgba(228,246,248,.98),rgba(204,230,239,.9)); border-color:rgba(58,132,153,.45); }
@media (max-width:600px) { .history-page .profile-archive.history-overview { padding:12px; border-radius:18px !important; } .history-page .history-event-expand { min-width:68px; padding:7px 9px; gap:6px; } }
.history-page .profile-archive .state-grid { gap:0; padding-top:10px; }
.history-page .state-grid article { height:auto; min-height:44px; gap:4px; padding:0 16px; backdrop-filter:none; -webkit-backdrop-filter:none; }
.history-page .state-grid article:first-child { padding-left:0; }
.history-page .state-grid article:last-child { padding-right:0; }
.history-page .state-grid .state-label { min-height:18px; font-size:11px; }
@media(max-width:760px) {
  .history-page .profile-archive .state-grid { row-gap:10px; }
  .history-page .state-grid article { min-height:54px; padding:0 12px; }
  .history-page .state-grid article:nth-child(odd) { border-left:0; padding-left:0; }
  .history-page .state-grid article:nth-child(even) { padding-right:0; }
  .history-page .state-grid .state-label-en { margin-left:0; }
}
</style>
