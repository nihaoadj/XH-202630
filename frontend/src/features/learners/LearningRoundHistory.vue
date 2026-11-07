<template>
  <article class="learning-round-history" :aria-label="`${primaryName} 学习轮次`">
    <header><div><small>学习轮次 · {{ round.protocol_version === 'legacy-correction/v1' ? '历史纠错记录' : '单主节点学习' }}</small><h3>{{ primaryName }}</h3></div><time :datetime="round.created_at">{{ formatDateTime(round.created_at) }}</time></header>
    <div class="round-history-members"><span v-for="member in round.members" :key="member.member_id">{{ roundRoleLabel(member.role) }}：{{ member.node_name || member.node_id }} · {{ roundStateLabel(member.state) }}</span></div>
    <ol aria-label="本轮学习和纠错阶段">
      <li v-for="stage in round.stages" :key="stage.stage_id"><strong>{{ stage.kind === 'initial' ? '本轮学习' : `本轮纠错 ${stage.ordinal}` }}</strong><span>{{ roundStateLabel(stage.state) }}</span>
        <div v-for="member in stage.members" :key="member.member_id" class="round-history-stage-member"><span>{{ roundRoleLabel(member.role) }} · {{ nodeName(member.node_id) }}</span><small>{{ member.resource_types.join('、') }} · {{ roundStateLabel(member.state) }}</small><el-button text type="primary" @click="open(stage, member)">查看对应链路与资源</el-button></div>
      </li>
    </ol>
  </article>
</template>
<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { formatDateTime } from '../../utils/generationDisplay'
import { roundRoleLabel, roundStateLabel } from '../generation/roundWorkspace.js'
const props = defineProps({ round: { type: Object, required: true }, learnerId: { type: String, required: true } })
const router = useRouter()
const primaryName = computed(() => props.round.members.find(member => member.role === 'primary')?.node_name || '历史节点复习')
const nodeName = id => props.round.members.find(member => member.node_id === id)?.node_name || id
function open(stage, member) {
  router.push({ path: '/generate', query: { learnerId: props.learnerId, roundId: props.round.round_id, memberId: member.member_id, stageId: stage.stage_id, runId: member.job_ids[0] || '' } })
}
</script>
<style scoped>
.learning-round-history { border:1px solid #d9e4eb; border-radius:10px; margin:16px 0; padding:20px; color:#173349; background:white; }.learning-round-history header { display:flex; flex-wrap:wrap; gap:14px; justify-content:space-between; align-items:center; }h3 { margin:8px 0; }small,time { font-size:12px; }.round-history-members { display:flex; flex-wrap:wrap; gap:8px 18px; margin:14px 0; font-size:14px; }ol { padding-left:22px; }li { padding:12px 0; }li>span { margin-left:12px; font-size:13px; }.round-history-stage-member { display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; padding:8px 0; font-size:14px; }
</style>
