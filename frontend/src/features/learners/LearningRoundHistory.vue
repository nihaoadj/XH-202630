<template>
  <article class="learning-round-history" :aria-label="`${primaryName} 学习轮次`">
    <button type="button" class="round-history-trigger" :aria-expanded="expanded" :aria-controls="`learning-round-details-${round.round_id}`" @click="expanded = !expanded">
      <span class="round-history-heading">
        <span class="round-history-title" role="heading" aria-level="3">{{ primaryName }}</span>
        <time class="round-history-time" :datetime="round.created_at"><el-icon aria-hidden="true"><Clock /></el-icon>{{ formatDateTime(round.created_at) }}</time>
      </span>
      <span class="round-history-meta">
        <span class="round-history-state-pill" :class="`is-${primaryMember?.state || 'unknown'}`"><span class="state-dot" aria-hidden="true"></span>{{ summaryState }}</span>
        <span class="round-history-data-pill"><el-icon aria-hidden="true"><Connection /></el-icon><b>{{ round.members.length }}</b> 个节点</span>
        <span class="round-history-data-pill"><el-icon aria-hidden="true"><Layers /></el-icon><b>{{ round.stages.length }}</b> 个学习阶段</span>
        <span class="round-history-data-pill"><el-icon aria-hidden="true"><Reading /></el-icon><b>{{ resourceCount }}</b> 份资源</span>
        <span v-for="node in assessmentNodes" :key="node.member_id" class="round-history-data-pill is-score"><el-icon aria-hidden="true"><DataAnalysis /></el-icon>{{ round.members.length > 1 ? roundRoleLabel(node.role) : '测评' }}<b>{{ Math.round(node.score * 100) }}%</b></span>
        <span v-if="nextStep" class="round-history-data-pill is-next" :class="`route-${nextAction}`"><el-icon aria-hidden="true"><Position /></el-icon>{{ nextStep }}</span>
        <span v-if="chosenStep" class="round-history-data-pill is-selected"><el-icon aria-hidden="true"><CircleCheck /></el-icon>{{ chosenStep }}</span>
        <span v-if="previewError" class="round-history-preview-note">{{ previewError }}</span>
      </span>
      <span class="round-history-expand" aria-hidden="true"><span>{{ expanded ? '收起' : '展开' }}</span><el-icon><ArrowDown /></el-icon></span>
    </button>
    <div v-show="expanded" :id="`learning-round-details-${round.round_id}`" class="round-history-details">
      <ol aria-label="本轮学习和纠错阶段">
        <li v-for="stage in round.stages" :key="stage.stage_id">
          <div class="round-history-stage-heading"><strong>{{ stage.kind === 'initial' ? '本轮学习' : `本轮纠错 ${stage.ordinal}` }}</strong><span>{{ roundStateLabel(stage.state) }}</span><el-button v-if="stage.members.length === 1" class="stage-link" text @click="open(stage, stage.members[0])">查看学习链路 ↗</el-button></div>
          <div v-for="member in stage.members" :key="member.member_id" class="round-history-stage-member">
            <div v-if="stage.members.length > 1" class="round-history-member-head"><strong>{{ roundRoleLabel(member.role) }} · {{ nodeName(member.node_id) }}</strong><el-button class="stage-link" text @click="open(stage, member)">查看学习链路 ↗</el-button></div>
            <HistoryRoundResources :member="member" :learner-id="learnerId" :active="expanded" />
          </div>
        </li>
      </ol>
    </div>
  </article>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowDown, Connection, CopyDocument as Layers, DataAnalysis, Position, Clock, CircleCheck, Reading } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { formatDateTime } from '../../utils/generationDisplay'
import { roundRoleLabel, roundStateLabel } from '../generation/roundWorkspace.js'
import { roundFeedbackApi } from '../feedback/roundApi.js'
import HistoryRoundResources from './HistoryRoundResources.vue'
const props = defineProps({ round: { type: Object, required: true }, learnerId: { type: String, required: true } })
const router = useRouter()
const expanded = ref(false)
const primaryName = computed(() => props.round.members.find(member => member.role === 'primary')?.node_name || '历史节点复习')
const primaryMember = computed(() => props.round.members.find(member => member.role === 'primary') || props.round.members[0])
const summaryState = computed(() => primaryMember.value ? roundStateLabel(primaryMember.value.state) : '历史记录')
const resourceCount = computed(() => new Set([
  ...props.round.members.flatMap(member => member.resource_ids || []),
  ...props.round.stages.flatMap(stage => stage.members.flatMap(member => member.resource_ids || [])),
].filter(Boolean)).size)
const assessmentNodes = ref([])
const nextStep = ref('')
const nextAction = ref('')
const chosenStep = ref('')
const previewError = ref('')
watch(() => [props.learnerId, props.round.round_id, props.round.stages.map(stage => `${stage.stage_id}:${stage.state}`).join(',')], async (_, __, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  assessmentNodes.value = []
  nextStep.value = ''
  nextAction.value = ''
  chosenStep.value = ''
  previewError.value = ''
  const roundId = props.round.round_id
  const stage = [...props.round.stages].sort((a, b) => b.ordinal - a.ordinal).find(item => item.state === 'completed')
  if (!stage) return
  try {
    const { data } = await roundFeedbackApi.result(roundId, stage.stage_id)
    if (!current || data.round_id !== roundId || data.stage_id !== stage.stage_id || !data.nodes) return
    assessmentNodes.value = data.nodes.filter(node => props.round.members.some(member => member.member_id === node.member_id) && Number.isFinite(node.score) && node.score >= 0 && node.score <= 1)
    const action = ({ hold: '保持主路径', advance: '下一节点', practice: '强化巩固', remediate: '补救学习' })[data.primary_path_action]
    nextStep.value = action ? `下一步建议：${action}` : ''
    nextAction.value = data.primary_path_action || ''
    if (!data.attempt_id) return
    try {
      const response = await roundFeedbackApi.candidates(roundId, data.attempt_id)
      if (!current) return
      const selection = response.data.confirmed_selection
      if (selection?.confirmed && selection.label) {
        const names = (selection.nodes || []).map(node => node.name).filter(Boolean).join('、')
        const intent = selection.payload?.primary_learning_intent
        const label = selection.route === 'correction' ? '强化巩固' : ({ upgrade_learning: '下一节点', learn_new_knowledge: '下一节点', reinforce_weakness: '强化巩固', downgrade_learning: '补救学习' })[intent] || (selection.label === '下一轮学习' ? '学习节点' : selection.label)
        chosenStep.value = `已选${label}${names ? ` · ${names}` : ''}`
      }
    } catch {
      if (current) previewError.value = '下一步选择暂不可用'
    }
  } catch {
    if (current) previewError.value = '测评摘要暂不可用'
  }
}, { immediate: true })
const nodeName = id => props.round.members.find(member => member.node_id === id)?.node_name || id
function open(stage, member) {
  router.push({ path: '/generate', query: { learnerId: props.learnerId, roundId: props.round.round_id, memberId: member.member_id, stageId: stage.stage_id, runId: member.job_ids[0] || '' } })
}
</script>
<style scoped>
.learning-round-history { min-width:0; color:var(--history-ink, #173349); }
.round-history-trigger {
  display:grid;
  grid-template-columns:minmax(0, 1fr) auto auto;
  grid-template-rows:auto auto;
  align-items:center;
  width:100%;
  min-width:0;
  gap:5px 18px;
  padding:16px 18px;
  border:0;
  border-radius:inherit;
  background:linear-gradient(112deg, rgba(255,255,255,.91), rgba(220,240,242,.78) 58%, rgba(232,241,249,.82));
  color:inherit;
  font:inherit;
  text-align:left;
  cursor:pointer;
  backdrop-filter:blur(15px);
  -webkit-backdrop-filter:blur(15px);
  transition:background 180ms ease, box-shadow 180ms ease;
}
.round-history-trigger:hover { background:linear-gradient(112deg, rgba(255,255,255,.98), rgba(217,240,240,.9) 58%, rgba(226,239,250,.92)); }
.round-history-trigger:focus-visible { outline:2px solid #167587; outline-offset:-3px; }
.round-history-heading { display:contents; }
.round-history-heading small { color:var(--history-muted, #536b7d); font-size:11px; line-height:1.6; }
.round-history-title { grid-column:1; grid-row:1; min-width:0; color:var(--history-ink, #173349); font-size:16px; font-weight:680; line-height:1.45; overflow-wrap:anywhere; }
.round-history-meta { display:flex; grid-column:1; grid-row:2; flex-wrap:wrap; align-items:center; gap:5px 10px; min-width:0; color:var(--history-muted, #536b7d); font-size:11px; line-height:1.65; }
.round-history-meta time { color:var(--history-muted, #536b7d); font-size:11px; font-variant-numeric:tabular-nums; white-space:nowrap; }
.round-history-state-pill { display:inline-flex; align-items:center; padding:2px 9px; border:1px solid rgba(76,153,155,.2); border-radius:999px; background:rgba(221,242,238,.82); color:#0d6570; font-size:10px; line-height:1.6; white-space:nowrap; }
.round-history-data-pill { display:inline-flex; align-items:center; gap:5px; max-width:100%; padding:3px 9px; border:1px solid rgba(104,154,179,.28); border-radius:999px; background:linear-gradient(135deg, rgba(255,255,255,.88), rgba(226,239,249,.75)); color:#365d75; box-shadow:0 4px 10px -7px rgba(23,67,88,.45), inset 0 1px rgba(255,255,255,.96); overflow-wrap:anywhere; }
.round-history-data-pill b { color:#164d68; font-size:12px; font-weight:650; font-variant-numeric:tabular-nums; }
.round-history-data-pill .el-icon { flex-shrink:0; color:#43869b; }
.round-history-data-pill.is-score { border-color:rgba(52,143,139,.3); background:linear-gradient(135deg, rgba(245,255,252,.94), rgba(208,239,230,.8)); color:#25655f; }
.round-history-data-pill.is-score b { color:#0e7069; }
.round-history-data-pill.is-next { border-color:rgba(108,132,179,.3); background:linear-gradient(135deg, rgba(249,251,255,.92), rgba(226,232,249,.8)); color:#455d88; }
.round-history-preview-note { color:var(--history-muted, #536b7d); }
.round-history-expand { display:flex; grid-column:3; grid-row:1 / span 2; align-items:center; justify-content:center; gap:8px; min-width:74px; min-height:34px; box-sizing:border-box; padding:7px 11px; border:1px solid rgba(96,158,174,.38); border-radius:11px; background:linear-gradient(145deg,rgba(255,255,255,.95),rgba(221,239,245,.8)); color:#195c70; font-size:12px; font-weight:600; line-height:1.3; white-space:nowrap; box-shadow:0 4px 10px -6px rgba(22,78,101,.3),inset 0 1px rgba(255,255,255,.98); transition:background 180ms ease,box-shadow 180ms ease,border-color 180ms ease; }
.round-history-expand .el-icon { display:inline-flex; flex:0 0 14px; width:14px; height:14px; padding:0; border:0; background:none; color:#438398; font-size:14px; transition:transform 180ms ease; }
.round-history-trigger:hover .round-history-expand, .round-history-trigger:focus-visible .round-history-expand { border-color:rgba(59,133,157,.65); box-shadow:0 5px 12px -6px rgba(22,78,101,.4),inset 0 1px #fff; }
.round-history-trigger[aria-expanded="true"] .round-history-expand { background:linear-gradient(145deg,rgba(228,246,248,.98),rgba(204,230,239,.9)); border-color:rgba(58,132,153,.45); }
.round-history-trigger[aria-expanded="true"] .round-history-expand .el-icon { transform:rotate(180deg); }
.round-history-details { padding:0 18px 18px; border-top:1px solid rgba(134,177,190,.22); background:linear-gradient(155deg, rgba(249,253,254,.64), rgba(228,241,246,.58)); }
.round-history-members { display:flex; flex-wrap:wrap; gap:8px; padding:14px 0 0; }
.round-history-members > span { padding:5px 10px; border:1px solid rgba(87,158,157,.25); border-radius:999px; background:linear-gradient(135deg, rgba(240,250,248,.94), rgba(218,241,237,.78)); color:#2f6660; font-size:11px; line-height:1.6; overflow-wrap:anywhere; box-shadow:0 5px 14px -11px rgba(15,91,101,.48), inset 0 1px rgba(255,255,255,.94); }
ol { display:grid; gap:10px; margin:0; padding:14px 0 0; list-style:none; }
li { min-width:0; padding:13px 14px; border:1px solid rgba(151,184,198,.38); border-left:2px solid rgba(45,140,148,.62); border-radius:13px; background:linear-gradient(145deg, rgba(255,255,255,.8), rgba(228,240,245,.7)); box-shadow:0 12px 25px -20px rgba(19,60,78,.48), inset 0 1px rgba(255,255,255,.94); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
.round-history-stage-heading { display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; margin-bottom:6px; font-size:13px; }
.round-history-stage-heading > span { padding:2px 9px; border-radius:999px; background:rgba(222,241,239,.86); color:#0d5f6b; font-size:11px; line-height:1.6; white-space:nowrap; }
.round-history-stage-member { display:flex; flex-wrap:wrap; gap:10px 14px; align-items:center; padding:10px 0; }
.round-history-stage-member + .round-history-stage-member { border-top:1px dashed rgba(144,178,190,.4); }
.round-history-member-copy { display:grid; flex:1 1 220px; min-width:0; gap:3px; overflow-wrap:anywhere; }
.round-history-member-copy strong { color:var(--history-ink, #173349); font-size:13px; line-height:1.6; }
.round-history-member-copy small { color:var(--history-muted, #536b7d); font-size:11px; line-height:1.6; }
.round-history-stage-member .el-button { min-height:40px; height:40px; margin:0; padding:8px 12px; border-radius:9px; font-size:12px; box-shadow:0 8px 18px -13px rgba(16,64,86,.5); }
@media (max-width:600px) {
  .round-history-trigger { gap:6px 9px; padding:14px; }
  .round-history-title { font-size:15px; }
  .round-history-trigger { grid-template-columns:minmax(0,1fr) auto; }
  .round-history-expand { grid-column:2; grid-row:1 / span 3; min-width:68px; padding:7px 9px; gap:6px; }
  .round-history-trigger .round-history-time { grid-column:1; grid-row:3; justify-self:start; }
  .round-history-details { padding:0 14px 14px; }
  .round-history-stage-member { align-items:flex-start; }
  .round-history-stage-member .el-button { width:100%; }
}
@media (prefers-reduced-motion:reduce) { .round-history-trigger, .round-history-expand, .round-history-expand .el-icon { transition:none; } }
.round-history-time { display:inline-flex; grid-column:2; grid-row:1 / span 2; align-self:center; align-items:center; justify-content:center; gap:7px; padding:6px 10px; border:1px solid rgba(111,160,180,.46); border-radius:9px; background:linear-gradient(135deg,rgba(255,255,255,.88),rgba(233,243,248,.76)); box-shadow:inset 0 1px rgba(255,255,255,.96),0 3px 8px -6px rgba(30,76,98,.32); color:var(--history-muted, #536b7d); font-size:11px; font-variant-numeric:tabular-nums; white-space:nowrap; }
.round-history-state-pill { gap:6px; padding:3px 10px; border-color:rgba(64,144,143,.28); background:linear-gradient(135deg,rgba(248,255,253,.95),rgba(212,240,233,.85)); font-size:11px; box-shadow:0 4px 10px -7px rgba(23,67,88,.4),inset 0 1px rgba(255,255,255,.95); }
.state-dot { width:6px; height:6px; border-radius:50%; background:currentColor; box-shadow:0 0 0 3px rgba(30,133,125,.1); }
.round-history-state-pill.is-producing { color:#365f90; background:linear-gradient(135deg,#f4f9ff,#dfeaf8); }
.round-history-state-pill.is-awaiting_assessment { color:#87601c; border-color:rgba(173,133,62,.28); background:linear-gradient(135deg,#fffcf3,#f5ecd4); }
.round-history-state-pill.is-failed { color:#994957; border-color:rgba(176,92,111,.28); background:linear-gradient(135deg,#fff6f7,#f6e2e8); }
.round-history-data-pill.route-advance { color:#286785; background:linear-gradient(135deg,#f5fbff,#deedf9); }
.round-history-data-pill.route-remediate { color:#8a602b; border-color:rgba(169,128,67,.28); background:linear-gradient(135deg,#fffcf5,#f5e8cf); }
.round-history-data-pill.route-practice { color:#67548e; border-color:rgba(137,114,176,.28); background:linear-gradient(135deg,#fbf8ff,#ece3f7); }
.round-history-data-pill.is-selected { color:#24665d; border-color:rgba(63,141,126,.28); background:linear-gradient(135deg,#f8fffc,#dcefe7); }
.round-history-stage-heading { margin-bottom:8px; }
.round-history-stage-heading .stage-link, .round-history-member-head .stage-link { margin-left:auto; min-height:30px; height:30px; padding:4px 7px; font-size:11px; color:#2a6a80; box-shadow:none; }
.round-history-stage-member { padding:0; }
.round-history-member-head { display:flex; width:100%; align-items:center; gap:10px; font-size:12px; }
@media(max-width:600px) { .round-history-stage-heading .stage-link, .round-history-member-head .stage-link { width:auto; } }
</style>
