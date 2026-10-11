<template>
  <div class="history-page">
    <section class="history-layout" aria-label="学习历史">
      <aside class="profile-archive" aria-labelledby="profile-archive-title">
        <header class="archive-list-head">
          <div>
            <span class="archive-kicker">01 / PROFILES</span>
            <h2 id="profile-archive-title">学习画像</h2>
          </div>
          <el-button class="archive-refresh" :icon="Refresh" aria-label="刷新学习画像" @click="refreshProfiles">刷新</el-button>
        </header>
        <div class="profile-filter">
          <label id="skill-filter-label">能力层级 <span>LEVEL</span></label>
          <el-select v-model="skillFilter" clearable placeholder="全部层级" aria-label="能力层级" popper-class="history-filter-dropdown">
            <el-option label="初级" value="初级" />
            <el-option label="中级" value="中级" />
            <el-option label="进阶" value="进阶" />
          </el-select>
          <div class="profile-count"><span>选择画像，回看学习记录</span><b>{{ filteredProfiles.length }} 个画像</b></div>
        </div>
        <div v-if="!filteredProfiles.length" class="history-empty profile-empty" role="status">
          <el-icon aria-hidden="true"><User /></el-icon>
          <h3>没有匹配的学习画像</h3>
          <p>可调整能力层级，或刷新画像列表。</p>
        </div>
        <div v-else class="profile-scroll" role="region" aria-label="学习画像列表" tabindex="0">
          <div v-for="(profile, index) in filteredProfiles" :key="profile.learner_id" class="profile-entry" :class="{ 'is-active': activeLearnerId === profile.learner_id }">
            <button type="button" class="profile-item" :class="{ active: activeLearnerId === profile.learner_id }" :aria-pressed="activeLearnerId === profile.learner_id" @click="selectProfile(profile)">
              <span class="profile-card-head">
                <span class="profile-number">{{ String(index + 1).padStart(2, '0') }}</span>
                <span class="profile-state">{{ activeLearnerId === profile.learner_id ? '当前查看' : profile.skill_level || '待诊断' }}</span>
              </span>
              <strong class="profile-direction">{{ resolveTrackName(profile.knowledge_base_id) }}</strong>
              <span class="profile-goal">{{ profile.learning_goal || '尚未设置学习目标' }}</span>
              <span class="profile-person"><el-icon aria-hidden="true"><User /></el-icon>{{ profileDisplayName(profile) }}<span v-if="activeLearnerId === profile.learner_id && profile.skill_level" class="profile-level">{{ profile.skill_level }}</span></span>
            </button>
            <el-tooltip v-if="activeLearnerId === profile.learner_id" content="永久删除当前学习画像">
              <el-button class="profile-delete-action" :icon="Delete" :loading="deletingProfile" aria-label="删除学习画像" @click="deleteSelectedProfile" />
            </el-tooltip>
          </div>
        </div>
        <footer class="profile-foot"><el-icon aria-hidden="true"><Clock /></el-icon><span>学习记录，随画像持续积累。</span></footer>
      </aside>

      <main class="journey-workspace" :aria-busy="loadingJourney" v-module-motion="{ key: activeLearnerId + ':' + statusFilter + ':' + timeFilter, ready: !loadingJourney && !!journey }">
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
          <section class="state-grid" aria-label="当前学习状态">
            <article>
              <span class="state-label"><el-icon aria-hidden="true"><Position /></el-icon>当前学习节点</span>
              <strong>{{ nodeLabels(journey.current_state.current_nodes) || '等待学习路径生成' }}</strong>
              <span class="state-caption">CURRENT NODE</span>
            </article>
            <article>
              <span class="state-label"><el-icon aria-hidden="true"><DataAnalysis /></el-icon>最近测评</span>
              <strong>{{ scoreLabel(journey.current_state.latest_assessment) }}</strong>
              <span class="state-caption">ASSESSMENT</span>
            </article>
            <article class="state-completed">
              <span class="state-label"><el-icon aria-hidden="true"><CircleCheck /></el-icon>已完成节点</span>
              <strong>{{ journey.current_state.completed_nodes.length }} <small>个</small></strong>
              <span class="state-caption">COMPLETED</span>
            </article>
            <article class="state-next">
              <span class="state-label"><el-icon aria-hidden="true"><Right /></el-icon>下一步建议</span>
              <strong>{{ journey.current_state.next_action || '完成当前资源学习后进行测评' }}</strong>
              <span class="state-caption">NEXT STEP</span>
            </article>
          </section>

          <section class="journey-panel" aria-labelledby="journey-title">
            <header class="panel-head">
              <div class="journey-heading">
                <span class="archive-kicker">02 / LEARNING JOURNEY</span>
                <div class="journey-title-row"><h2 id="journey-title">学习进程链路</h2><span class="round-count">当前显示 <b>{{ orderedRounds.length }}</b> 轮</span></div>
                <p class="panel-caption">资源、测评、反馈与路径变化，按生成批次串联。未发生的环节会明确标记。</p>
              </div>
              <div class="round-filters">
                <div class="round-filter">
                  <label>轮次状态 <span>STATUS</span></label>
                  <el-select v-model="statusFilter" clearable placeholder="全部状态" aria-label="轮次状态" popper-class="history-filter-dropdown">
                    <el-option label="已完成" value="completed" />
                    <el-option label="进行中" value="running" />
                    <el-option label="失败" value="failed" />
                  </el-select>
                </div>
                <div class="round-filter">
                  <label>记录时间 <span>PERIOD</span></label>
                  <el-select v-model="timeFilter" aria-label="记录时间范围" popper-class="history-filter-dropdown">
                    <el-option label="全部时间" value="all" />
                    <el-option label="近 7 天" value="7" />
                    <el-option label="近 30 天" value="30" />
                  </el-select>
                </div>
              </div>
            </header>

            <div class="journey-scroll" role="region" aria-label="学习进程记录" tabindex="0">
              <p v-if="journeyError" class="journey-error" role="alert">{{ journeyError }}</p>
              <div v-if="!filteredRounds.length && !orderedEvents.length" class="history-empty journey-empty" role="status">
                <el-icon aria-hidden="true"><Clock /></el-icon>
                <span class="archive-kicker">YOUR JOURNEY STARTS HERE</span>
                <h3>尚未记录学习链路</h3>
                <p>可调整筛选条件，或在完成学习后回看记录。</p>
              </div>
              <div v-else class="journey-chain">
                <article v-for="(event, index) in orderedEvents" :key="event.event_id" class="journey-chain-item history-event">
                  <div class="journey-chain-rail"><span>{{ String(index + 1).padStart(2, '0') }}</span></div>
                  <div class="journey-chain-content">
                    <div class="history-event-content">
                      <div class="event-heading"><span class="round-kicker">历史起点 · 未关联运行</span><time :datetime="event.occurred_at">{{ formatTime(event.occurred_at) }}</time></div>
                      <h3>{{ event.title }}</h3>
                      <p>{{ event.description }}</p>
                    </div>
                  </div>
                </article>

                <article v-for="(round, index) in orderedRounds" :key="round.round_id || round.batch_id || round.run_id" class="journey-chain-item" :class="[{ failed: round.status === 'failed', running: ['running', 'queued'].includes(round.status) }, { followup: round.is_followup }]" :aria-label="`${round.topic} 学习链路`">
                  <div class="journey-chain-rail"><span>{{ String(orderedEvents.length + index + 1).padStart(2, '0') }}</span></div>
                  <div class="journey-chain-content">
                    <div class="round-summary">
                      <div class="round-heading">
                        <span class="round-kicker">{{ round.is_followup ? '反馈后的后续学习' : '学习链路节点' }}</span>
                        <h3>{{ round.topic }}</h3>
                        <p class="round-meta">
                          <span class="round-status"><el-icon aria-hidden="true"><Warning v-if="round.status === 'failed'" /><Clock v-else-if="['running', 'queued'].includes(round.status)" /><CircleCheck v-else /></el-icon>{{ roundStatus(round) }}</span>
                          <time :datetime="round.occurred_at">{{ formatTime(round.occurred_at) }}</time>
                          <span v-if="round.parent_run_id" class="round-parent">由上一轮反馈触发</span>
                        </p>
                      </div>
                      <el-button class="round-toggle" :aria-expanded="expandedRounds.includes(round.round_id || round.batch_id || round.run_id)" :aria-controls="`history-round-${round.round_id || round.batch_id || round.run_id}`" @click="toggleRound(round.round_id || round.batch_id || round.run_id)">
                        {{ expandedRounds.includes(round.round_id || round.batch_id || round.run_id) ? '收起详情' : '展开详情' }}<el-icon aria-hidden="true"><ArrowDown /></el-icon>
                      </el-button>
                    </div>

                    <div class="journey-stages" aria-label="本轮六个学习环节">
                      <div class="journey-stage" :class="stageTone(round.status)"><span class="stage-index">01</span><div><b>资源生成</b><small>{{ roundStatus(round) }}</small></div></div>
                      <div class="journey-stage" :class="round.resources.length ? 'done' : 'pending'"><span class="stage-index">02</span><div><b>资源发布</b><small>{{ round.resources.length ? `${round.resources.length} 项资源` : '尚无资源产物' }}</small></div></div>
                      <div class="journey-stage" :class="round.assessment ? 'done' : 'pending'"><span class="stage-index">03</span><div><b>反馈测评</b><small>{{ scoreLabel(round.assessment) }}</small></div></div>
                      <div class="journey-stage" :class="round.feedback ? 'done' : 'pending'"><span class="stage-index">04</span><div><b>反馈决策</b><small>{{ round.feedback ? round.feedback.action : '待形成反馈' }}</small></div></div>
                      <div class="journey-stage" :class="round.path_change ? 'done' : 'pending'"><span class="stage-index">05</span><div><b>路径变化</b><small>{{ pathStageLabel(round.path_change) }}</small></div></div>
                      <div class="journey-stage" :class="round.feedback?.followup_run_ids?.length ? 'done' : 'pending'"><span class="stage-index">06</span><div><b>后续任务</b><small>{{ round.feedback?.followup_run_ids?.length ? `${round.feedback.followup_run_ids.length} 个后续批次` : '暂无后续任务' }}</small></div></div>
                    </div>

                    <div v-if="expandedRounds.includes(round.round_id || round.batch_id || round.run_id)" :id="`history-round-${round.round_id || round.batch_id || round.run_id}`" class="round-detail">
                      <ol class="chain">
                        <li><b>生成</b><span>{{ runDetail(round) }}</span></li>
                        <li><b>资源</b><span v-if="round.resources.length">{{ round.resources.map(resourceLabel).join('、') }}</span><span v-else>尚无可展示的资源产物</span></li>
                        <li><b>测评</b><span>{{ assessmentDetail(round.assessment) }}</span></li>
                        <li><b>反馈</b><span>{{ feedbackDetail(round.feedback) }}</span></li>
                        <li><b>学习路径</b><span>{{ pathDetail(round.path_change) }}</span></li>
                      </ol>
                      <div v-if="round.path_change?.mastery_changes?.length" class="mastery-list"><span v-for="item in round.path_change.mastery_changes" :key="item.knowledge_point_id">{{ item.knowledge_point_id }}：{{ masteryLabel(item) }}</span></div>
                      <div class="round-links">
                        <el-button class="history-primary" :icon="Reading" @click="toResources(round.batch_id || round.run_id)">查看本轮资源<el-icon aria-hidden="true"><Right /></el-icon></el-button>
                        <el-button :icon="Connection" @click="toGenerate(round.run_id)">查看运行进度</el-button>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
              <el-button v-if="journey.next_offset !== null" class="load-more" :loading="loadingMore" @click="loadMore">加载更多轮次<el-icon v-if="!loadingMore" aria-hidden="true"><ArrowDown /></el-icon></el-button>
              <div v-else-if="orderedRounds.length || orderedEvents.length" class="journey-end"><span />当前记录已展示完毕<span /></div>
            </div>
          </section>
        </template>
        <div v-else class="history-empty timeline-empty" role="status">
          <el-icon aria-hidden="true"><Connection /></el-icon>
          <span class="archive-kicker">LEARNING ARCHIVE</span>
          <h3>请选择一个学习画像查看学习旅程</h3>
          <p>从左侧画像开始，回看每一轮学习的来路与进展。</p>
        </div>
      </main>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, CircleCheck, Clock, Connection, DataAnalysis, Delete, Position, Reading, Refresh, Right, User, Warning } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { knowledgeApi, learningHistoryApi, profileApi } from '../../api'
import { useAppStore } from '../../stores/app'
import { formatDateTime } from '../../utils/generationDisplay'

const router = useRouter(); const store = useAppStore()
const profiles = ref([]); const tracks = ref([]); const skillFilter = ref(''); const statusFilter = ref(''); const timeFilter = ref('all')
const journey = ref(null); const activeLearnerId = ref(''); const deletingProfile = ref(false); const loadingMore = ref(false); const expandedRounds = ref([])
const loadingJourney = ref(false)
const journeyError = ref('')
let journeyRequestVersion = 0
let historyMounted = true
const filteredProfiles = computed(() => profiles.value.filter((profile) => !skillFilter.value || profile.skill_level === skillFilter.value))
const filteredRounds = computed(() => (journey.value?.rounds || []).filter((round) => (!statusFilter.value || round.status === statusFilter.value) && withinPeriod(round.occurred_at)))
const orderedRounds = computed(() => [...filteredRounds.value].sort((left, right) => new Date(left.occurred_at || 0).getTime() - new Date(right.occurred_at || 0).getTime()))
const orderedEvents = computed(() => (journey.value?.unlinked_events || []).filter((event) => withinPeriod(event.occurred_at)).slice().sort((left, right) => new Date(left.occurred_at || 0).getTime() - new Date(right.occurred_at || 0).getTime()))
function resolveTrackName(id) { return tracks.value.find((item) => item.track_id === id || item.knowledge_base_id === id)?.name || id || '未命名方向' }
function profileDisplayName(profile) { const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot; return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未命名画像' }
function formatTime(value) { return value ? formatDateTime(value) : '时间未知' }
function withinPeriod(value) { if (timeFilter.value === 'all' || !value) return true; return Date.now() - new Date(value).getTime() <= Number(timeFilter.value) * 86400000 }
function nodeLabels(nodes) { return (nodes || []).map((item) => item.knowledge_point_id).join('、') }
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
  if (activeLearnerId.value) return loadJourney(activeLearnerId.value)
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
    journey.value = offset ? { ...journey.value, rounds: [...journey.value.rounds, ...res.data.rounds], next_offset: res.data.next_offset } : res.data
  } catch (error) {
    if (!isCurrent()) return
    journeyError.value = error?.response?.data?.message || error?.message || '学习旅程加载失败'
    ElMessage.error(journeyError.value)
  } finally {
    if (isCurrent()) { loadingJourney.value = false; loadingMore.value = false }
  }
}
async function selectProfile(profile, allowDuringDelete = false) {
  if (!historyMounted || (deletingProfile.value && !allowDuringDelete)) return
  activeLearnerId.value = profile.learner_id
  expandedRounds.value = []
  journey.value = null
  applyProfile(profile)
  await loadJourney(profile.learner_id)
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
    activeLearnerId.value = ''; journey.value = null; journeyError.value = ''
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
onBeforeUnmount(() => { historyMounted = false; ++journeyRequestVersion })
</script>

<style scoped>
.journey-error { margin: 0 0 16px; padding: 12px 16px; border-left: 2px solid #a33b40; background: #fdf8f7; color: #a33b40; font-size: 13px; line-height: 1.7; }
.history-page {
  --history-ink: #132c40;
  --history-muted: #536b7d;
  --history-teal: #086575;
  --history-line: #d9e4eb;
  --history-paper: #f5f7fa;
  --rag-ink: #132c40;
  --rag-line: #d9e4eb;
  --rag-blue-700: #086575;
  --rag-blue-800: #1d4055;
  --rag-blue-500: #187487;
  --rag-blue-50: #edf8f6;
  --rag-radius: 5px;
  --rag-shadow-soft: none;
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
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 24px;
  border: 0 !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  overflow: hidden;
}
.history-page .profile-archive {
  display: flex;
  min-height: 0;
  flex-direction: column;
  padding: 16px;
  border: 1px solid var(--history-line) !important;
  border-top: 2px solid #132c40 !important;
  border-radius: 0 !important;
  background: #eef3f6 !important;
  box-shadow: none !important;
}
.archive-list-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 0 18px; }
.archive-kicker, .state-caption, .profile-number, .round-kicker, .stage-index, .round-filter label > span, .profile-filter label > span {
  font-family: Consolas, "SFMono-Regular", monospace;
  font-size: 10px;
  font-weight: 400;
  letter-spacing: .025em;
}
.history-page .archive-kicker { display: block; color: var(--history-muted) !important; line-height: 1.5; }
.archive-list-head h2, .panel-head h2 { margin: 6px 0 0; color: var(--history-ink); font-size: 21px; font-weight: 650; line-height: 1.35; letter-spacing: -.025em; }
.history-page :deep(.el-button) { min-width: 44px; min-height: 44px; height: auto; margin-left: 0; padding: 10px 14px; border-radius: 5px; color: var(--history-ink); font-size: 12px; font-weight: 600; box-shadow: none; }
.history-page :deep(.el-button > span) { gap: 6px; }
.history-page :deep(.el-button:hover) { border-color: #649eaa; background: #edf8f6; color: #086575; }
.history-page :deep(.el-button:focus-visible), .profile-item:focus-visible { outline: 2px solid #167587; outline-offset: 3px; }
.history-page :deep(.el-select) { width: 100%; min-width: 0; }
.history-page :deep(.el-select__wrapper) { min-height: 44px; padding: 8px 12px; border-radius: 5px; background: #fff; color: var(--history-ink); box-shadow: 0 0 0 1px #cbdbe4 inset; font-size: 12px; }
.history-page :deep(.el-select__placeholder), .history-page :deep(.el-select__placeholder.is-transparent) { color: var(--history-ink); }
.history-page :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 2px #167587 inset; }
.history-page :deep(.el-select__caret) { color: #536b7d; }
.history-page :deep(.el-select__clear) { width: 24px; height: 24px; }
.history-page .archive-refresh { padding: 10px 9px; border-color: transparent; background: transparent; color: var(--history-muted); }
.profile-filter { padding-bottom: 15px; }
.profile-filter label, .round-filter label { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 7px; color: var(--history-muted); font-size: 12px; line-height: 1.5; }
.profile-count { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px 8px; margin-top: 12px; color: var(--history-muted); font-size: 11px; }
.profile-count b { color: var(--history-teal); font-weight: 600; }
.profile-scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 3px 7px 3px 3px; margin-left: -3px; border-top: 1px solid var(--history-line); }
.profile-entry { display: grid; grid-template-columns: minmax(0, 1fr) 44px; align-items: start; min-width: 0; border-bottom: 1px solid var(--history-line); }
.profile-entry:not(.is-active) .profile-item { grid-column: 1 / -1; }
.profile-entry.is-active { background: #edf8f6; }
.history-page .profile-item {
  display: flex;
  width: 100%;
  min-width: 0;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  padding: 17px 12px 17px 14px;
  border: 1px solid transparent !important;
  border-left: 3px solid transparent !important;
  border-radius: 3px;
  background: transparent !important;
  color: var(--history-ink);
  box-shadow: none !important;
  text-align: left;
  cursor: pointer;
  font: inherit;
  transition: background-color 160ms ease, border-color 160ms ease;
}
.history-page .profile-item:hover { background: #eef3f6 !important; border-color: transparent !important; box-shadow: none !important; }
.history-page .profile-item.active { border-color: transparent !important; border-left-color: #167c7c !important; background: #edf8f6 !important; box-shadow: none !important; }
.profile-card-head { display: flex; align-items: center; gap: 10px; min-height: 24px; }
.profile-number { color: var(--history-muted); }
.profile-state { padding: 3px 6px; border: 1px solid #d9e4eb; border-radius: 3px; color: #536b7d; font-size: 10px; line-height: 1.5; }
.active .profile-state { border-color: #a9d4d0; background: #e0f3f0; color: #086575; }
.profile-direction { color: var(--history-ink); font-size: 15px; font-weight: 650; line-height: 1.55; overflow-wrap: anywhere; }
.profile-goal { color: var(--history-muted); font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
.profile-person { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; color: var(--history-muted); font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
.profile-level { margin-left: auto; color: var(--history-teal); }
.history-page .profile-delete-action { grid-column: 2; grid-row: 1; margin-top: 6px; width: 44px; height: 44px; padding: 0; border: 0; background: transparent; color: var(--history-muted); }
.history-page .profile-delete-action:hover { color: #a33b40; background: #fff0f0; }
.profile-foot { display: flex; gap: 7px; align-items: center; padding: 14px 3px 0; border-top: 1px solid #cadbe4; color: var(--history-muted); font-size: 11px; line-height: 1.6; }
.journey-workspace { display: flex; min-height: 0; min-width: 0; flex-direction: column; overflow: hidden; }
.state-grid { display: grid; grid-template-columns: 1.1fr .85fr .65fr 1.4fr; padding: 19px 0 18px; border: 1px solid var(--history-line); border-top: 2px solid #132c40; background: #fff; }
.state-grid article { display: flex; min-width: 0; flex-direction: column; gap: 9px; padding: 0 18px; border-right: 1px solid var(--history-line); }
.state-grid article:last-child { border: 0; }
.state-label { display: flex; align-items: center; gap: 7px; color: var(--history-muted); font-size: 12px; line-height: 1.5; }
.state-label .el-icon { color: var(--history-teal); font-size: 15px; }
.state-grid strong { color: var(--history-ink); font-size: 15px; font-weight: 600; line-height: 1.65; overflow-wrap: anywhere; }
.state-grid .state-completed strong { color: var(--history-teal); font-size: 25px; line-height: 1; font-variant-numeric: tabular-nums; }
.state-completed small { font-size: 12px; font-weight: 400; }
.state-next strong { font-size: 13px; font-weight: 500; }
.state-caption { margin-top: auto; color: var(--history-muted); line-height: 1.5; }
.journey-panel { display: flex; min-width: 0; min-height: 0; flex: 1; flex-direction: column; margin-top: 20px; border: 1px solid var(--history-line); border-top: 2px solid #132c40; background: #eef3f6; }
.panel-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 14px 22px; align-items: flex-start; padding: 20px; border-bottom: 1px solid var(--history-line); background: #fff; }
.journey-heading { flex: 1 1 300px; min-width: 0; }
.journey-title-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 13px; }
.round-count { margin-top: 7px; color: var(--history-muted); font-size: 11px; white-space: nowrap; }
.round-count b { color: var(--history-teal); font-family: Consolas, monospace; font-size: 14px; font-weight: 400; }
.panel-caption { max-width: 570px; margin: 9px 0 0; color: var(--history-muted); font-size: 12px; line-height: 1.75; }
.round-filters { display: grid; flex: 0 0 270px; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; min-width: 0; padding-top: 2px; }
.round-filter { min-width: 0; }
.round-filter label > span { font-size: 9px; }
.journey-scroll { min-width: 0; min-height: 0; flex: 1; padding: 18px 12px 8px 12px; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
.profile-scroll:focus-visible, .journey-scroll:focus-visible { outline: 2px solid #167587; outline-offset: -2px; border-radius: 3px; }
.profile-scroll, .journey-scroll { scrollbar-width: thin; scrollbar-color: #9ebcc6 transparent; }
.profile-scroll::-webkit-scrollbar, .journey-scroll::-webkit-scrollbar { width: 5px; height: 5px; }
.profile-scroll::-webkit-scrollbar-thumb, .journey-scroll::-webkit-scrollbar-thumb { border-radius: 4px; background: #9ebcc6; }
.journey-chain-item { --node-color: #167c7c; --node-header: #f7fbfb; display: grid; grid-template-columns: 40px minmax(0, 1fr); min-width: 0; }
.journey-chain-item.failed { --node-color: #b76165; --node-header: #fdf8f7; }
.journey-chain-item.running { --node-color: #537996; --node-header: #f5f8fc; }
.journey-chain-rail { position: relative; display: flex; justify-content: center; }
.journey-chain-rail::after { position: absolute; top: 39px; bottom: -23px; width: 1px; background: #aac6d1; content: ""; }
.journey-chain-item:last-child .journey-chain-rail::after { bottom: 20px; }
.journey-chain-rail > span { display: flex; position: relative; z-index: 1; align-items: center; justify-content: center; flex: 0 0 auto; width: 28px; height: 28px; margin-top: 21px; border: 1px solid #a9cecf; border-radius: 5px; background: #eaf6f3; color: #086575; font-family: Consolas, monospace; font-size: 11px; line-height: 1; }
.history-event .journey-chain-rail > span { border-color: #cad8e2; background: #f5f7fa; color: #536b7d; }
.failed .journey-chain-rail > span { border-color: #e4b7b8; background: #fff2f1; color: #a33b40; }
.running .journey-chain-rail > span { border-color: #bacddb; background: #eaf1f8; color: #315b80; }
.journey-chain-content { min-width: 0; margin: 0 0 16px 9px; border: 1px solid #d1e0e7; border-left: 3px solid var(--node-color); background: #fff; }
.history-event .journey-chain-content { border-left: 2px solid #b6cbd5; background: #f8fafc; }
.history-event-content { padding: 15px 18px; }
.event-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 7px 12px; }
.round-kicker { display: block; color: var(--history-muted); font-family: inherit; font-size: 11px; line-height: 1.65; }
.history-event-content h3 { margin: 7px 0; color: var(--history-ink); font-size: 15px; font-weight: 600; line-height: 1.55; overflow-wrap: anywhere; }
.history-event-content p { margin: 0; color: var(--history-muted); font-size: 12px; line-height: 1.75; overflow-wrap: anywhere; }
.event-heading time, .round-meta time { color: var(--history-muted); font-size: 11px; font-variant-numeric: tabular-nums; line-height: 1.65; }
.round-summary { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px; border-bottom: 1px solid var(--history-line); background: var(--node-header); }
.round-heading { min-width: 0; }
.round-heading h3 { margin: 6px 0 8px; color: var(--history-ink); font-size: 18px; font-weight: 650; line-height: 1.5; overflow-wrap: anywhere; }
.followup .round-kicker { color: var(--history-teal); }
.round-meta { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; margin: 0; color: var(--history-muted); font-size: 12px; line-height: 1.65; }
.round-status { display: inline-flex; align-items: center; gap: 5px; color: var(--history-teal); }
.round-status .el-icon { font-size: 14px; }
.failed .round-status { color: #a33b40; }
.running .round-status { color: #315b80; }
.round-parent { padding-left: 10px; border-left: 1px solid var(--history-line); }
.history-page .round-toggle { flex: 0 0 auto; padding: 10px 11px; background: transparent; font-weight: 500; }
.round-toggle .el-icon { transition: transform 180ms ease; }
.round-toggle[aria-expanded="true"] .el-icon { transform: rotate(180deg); }
.journey-stages { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); padding: 18px; gap: 12px 0; }
.journey-stage { display: flex; min-width: 0; gap: 7px; padding: 0 10px; border-left: 1px solid var(--history-line); align-items: flex-start; }
.journey-stage:first-child { padding-left: 0; border-left: 0; }
.stage-index { display: flex; flex: 0 0 auto; justify-content: center; align-items: center; width: 21px; height: 21px; margin-top: 1px; border: 1px solid #ccd8e1; border-radius: 3px; background: #f4f7f9; color: #536b7d; font-size: 9px; line-height: 1; }
.journey-stage > div { min-width: 0; }
.journey-stage b { display: block; color: var(--history-ink); font-size: 12px; font-weight: 600; line-height: 1.8; }
.journey-stage small { display: block; margin-top: 5px; color: var(--history-muted); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.journey-stage.done .stage-index { border-color: #aad1cb; background: #eaf6f3; color: #086575; }
.journey-stage.active .stage-index { border-color: #bacddb; background: #eaf1f8; color: #315b80; }
.journey-stage.failed .stage-index { border-color: #e4b7b8; background: #fff2f1; color: #a33b40; }
.round-detail { padding: 18px; border-top: 1px dashed #ccdbe3; }
.chain { display: grid; gap: 13px; margin: 0; padding: 0; list-style: none; }
.chain li { display: grid; grid-template-columns: 60px minmax(0, 1fr); gap: 14px; color: var(--history-muted); font-size: 12px; line-height: 1.85; }
.chain b { color: var(--history-ink); font-weight: 600; }
.chain li > span { overflow-wrap: anywhere; }
.mastery-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.mastery-list span { padding: 5px 9px; border-left: 2px solid #73b5ad; background: #edf8f6; color: var(--history-teal); font-size: 11px; line-height: 1.8; overflow-wrap: anywhere; }
.round-links { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
.history-page .history-primary { border-color: #11283c; background: #11283c; color: #fff; }
.history-page .history-primary:hover { border-color: #1d4055; background: #1d4055; color: #fff; }
.history-page .load-more { display: flex; margin: 24px auto 8px; border-color: #cbdbe4; background: #fff; }
.journey-end { display: flex; justify-content: center; align-items: center; gap: 12px; padding: 24px 0 8px; color: var(--history-muted); font-size: 11px; }
.journey-end > span { width: 32px; height: 1px; background: var(--history-line); }
.history-empty { display: flex; flex: 1; min-width: 0; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 28px 18px; text-align: center; }
.history-empty > .el-icon { margin-bottom: 7px; color: #167587; font-size: 35px; }
.history-empty h3 { margin: 0; font-size: 16px; font-weight: 600; line-height: 1.6; overflow-wrap: anywhere; }
.history-empty p { max-width: 340px; margin: 0; color: var(--history-muted); font-size: 12px; line-height: 1.8; }
.profile-empty h3 { font-size: 14px; }
.journey-empty { min-height: 260px; height: 100%; }
.timeline-empty { border-top: 2px solid #132c40; }

/* The compact header is scoped by the mounted history page; shared page styles stay untouched. */
:global(.app-shell:has(.history-page)) { background: #f5f7fa; }
:global(.app-shell:has(.history-page) .topbar) { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 16px; min-height: 60px; padding: 8px 28px; background: #fff; border-bottom: 1px solid #d9e4eb; box-shadow: none; }
:global(.app-shell:has(.history-page) .topbar-copy) { display: flex; flex-direction: row-reverse; justify-content: flex-end; align-items: center; gap: 14px; min-width: 0; }
:global(.app-shell:has(.history-page) .topbar-copy h1) { margin: 0; font-size: 18px; font-weight: 650; line-height: 1.5; color: #132c40; white-space: nowrap; }
:global(.app-shell:has(.history-page) .topbar-kicker) { margin: 0; padding-left: 14px; border-left: 1px solid #d9e4eb; color: #536b7d; font: 10px/1.5 Consolas, monospace; letter-spacing: 0; }
:global(.app-shell:has(.history-page) .topbar-copy p) { display: none; }
:global(.app-shell:has(.history-page) .topbar-actions) { position: static; display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px; margin: 0; transform: none; }
:global(.app-shell:has(.history-page) .topbar-action) { min-height: 44px; margin: 0 !important; padding: 10px 9px; border: 0 !important; border-radius: 5px !important; background: transparent !important; color: #536b7d !important; font-size: 12px; font-weight: 400; box-shadow: none !important; }
:global(.app-shell:has(.history-page) .topbar-action:hover) { background: #edf8f6 !important; color: #086575 !important; }
:global(.app-shell:has(.history-page) .topbar-action:focus-visible) { outline: 2px solid #167587; outline-offset: 2px; }
:global(.app-shell:has(.history-page) .topbar-meta) { display: flex; align-items: center; min-width: 0; width: auto; gap: 0; padding-left: 14px; border-left: 1px solid #d9e4eb; }
:global(.app-shell:has(.history-page) .topbar-meta > div) { min-width: 58px; padding: 0 6px; border: 0 !important; border-radius: 0 !important; background: transparent !important; box-shadow: none !important; }
:global(.app-shell:has(.history-page) .topbar-meta > div:last-child) { display: none; }
:global(.app-shell:has(.history-page) .topbar-meta span) { font-size: 10px; line-height: 1.5; color: #536b7d; }
:global(.app-shell:has(.history-page) .topbar-meta strong) { max-width: 160px; margin-top: 3px; color: #132c40; white-space: normal; overflow-wrap: anywhere; font-size: 12px; line-height: 1.5; }
:global(.app-shell:has(.history-page) .content-area) { padding: 22px 28px 24px; background: #f5f7fa; overflow: hidden; }
:global(.history-filter-dropdown .el-select-dropdown__item) { min-height: 36px; line-height: 36px; font-size: 12px; color: #132c40; }
:global(.history-filter-dropdown .el-select-dropdown__item.is-selected) { background: #edf8f6; color: #086575; font-weight: 600; }

@media (max-width: 1500px) {
  .journey-stages { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 17px 0; }
  .journey-stage:nth-child(4) { padding-left: 0; border-left: 0; }
  .panel-head { gap: 12px 18px; }
  .journey-heading { flex-basis: 270px; }
  .round-filters { flex-basis: 248px; }
}
@media (max-width: 1300px) {
  :global(.app-shell:has(.history-page) .topbar-kicker) { display: none; }
  .history-page > .history-layout { grid-template-columns: 264px minmax(0, 1fr); gap: 20px; }
  .state-grid { grid-template-columns: 1fr .9fr .7fr 1.2fr; }
  .state-grid article { padding: 0 12px; }
}
@media (max-width: 1100px) {
  .state-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 0; }
  .state-grid article:nth-child(2) { border-right: 0; }
  .panel-head { display: block; }
  .round-filters { margin-top: 16px; width: 100%; }
}
@media (max-width: 960px), (max-height: 640px) {
  :global(.app-shell:has(.history-page) .content-area) { overflow: auto; }
  .history-page, .history-page > .history-layout { height: auto; overflow: visible; }
  .journey-workspace { overflow: visible; }
  .journey-scroll { overflow: visible; flex: none; min-height: 260px; }
  .profile-scroll { max-height: 460px; flex: 1 0 auto; }
  .journey-panel { min-height: 300px; flex: none; }
  .timeline-empty { min-height: 340px; }
}
@media (max-width: 960px) {
  .history-page > .history-layout { grid-template-columns: minmax(0, 1fr); gap: 28px; }
  .history-page .profile-archive { max-height: 440px; padding: 16px; }
  .profile-scroll { max-height: 240px; flex: 1; }
  .archive-list-head { padding-top: 0; padding-bottom: 12px; }
  .profile-filter { padding-bottom: 12px; }
  .profile-foot { padding-top: 10px; }
  .profile-filter .el-select { max-width: none; }
  .panel-head { display: flex; }
  .round-filters { flex-basis: 260px; margin-top: 0; }
  .state-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .state-grid article:nth-child(2) { border-right: 1px solid var(--history-line); }
  :global(.app-shell:has(.history-page) .topbar) { gap: 8px; }
}
@media (max-width: 760px) {
  :global(.app-shell:has(.history-page) .topbar) { padding: 8px 18px; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 12px; }
  :global(.app-shell:has(.history-page) .topbar-actions) { grid-row: 2; grid-column: 1 / -1; justify-content: flex-start; flex-wrap: nowrap; }
  :global(.app-shell:has(.history-page) .topbar-action) { padding: 10px 8px; }
  :global(.app-shell:has(.history-page) .topbar-meta) { grid-row: 1; grid-column: 2; }
  :global(.app-shell:has(.history-page) .content-area) { padding: 18px 18px 24px; }
  .panel-head { display: block; }
  .round-filters { width: 100%; margin-top: 16px; }
  .state-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .state-grid article:nth-child(2) { border: 0; }
  .round-summary { align-items: flex-start; gap: 10px; padding: 14px; }
  .round-heading h3 { font-size: 16px; }
  .history-page .round-toggle { padding: 10px 8px; font-size: 11px; }
  .journey-stages { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 0; }
  .panel-head { padding: 18px 14px; }
  .journey-stage:nth-child(4) { border-left: 1px solid var(--history-line); padding-left: 10px; }
  .journey-stage:nth-child(odd) { border-left: 0; padding-left: 0; }
}
@media (max-width: 600px) {
  :global(.app-shell:has(.history-page) .sidebar) { padding: 0; }
  :global(.app-shell:has(.history-page) .sidebar .sidebar-inner) { gap: 4px; padding: 8px 10px; }
  :global(.app-shell:has(.history-page) .sidebar .brand-block) { display: none; }
  :global(.app-shell:has(.history-page) .sidebar .nav-list) { gap: 6px; align-items: stretch; }
  :global(.app-shell:has(.history-page) .sidebar .nav-item) { display: flex; min-width: 44px; min-height: 44px; align-items: center; justify-content: center; padding: 8px; }
  :global(.app-shell:has(.history-page) .sidebar .nav-item .nav-icon) { display: inline-flex; }
  :global(.app-shell:has(.history-page) .sidebar .nav-item .nav-text) { display: none; }
  .round-summary { flex-wrap: wrap; }
  .round-heading { flex: 1 1 100%; }
  .history-page .round-toggle { padding: 10px 12px; }
  .journey-chain-item { grid-template-columns: 30px minmax(0, 1fr); }
  .journey-chain-rail > span { width: 25px; height: 25px; font-size: 10px; }
  .journey-chain-content { margin-left: 8px; }
  .journey-scroll { padding: 14px 7px 8px; }
  .journey-stages, .round-detail { padding: 14px; }
  .history-event-content { padding: 14px; }
  .chain li { grid-template-columns: minmax(0, 1fr); gap: 2px; }
  .round-links { flex-direction: column; align-items: stretch; }
  .history-page .round-links .el-button { width: 100%; }
  .round-parent { padding-left: 0; border: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .history-page .profile-item, .history-page .round-toggle .el-icon, .history-page :deep(.el-button) { transition: none; }
}
</style>
