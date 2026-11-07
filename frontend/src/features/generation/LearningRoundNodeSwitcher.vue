<template>
  <section class="round-switcher" aria-label="本轮学习节点">
    <div v-if="detail.members.length > 1" class="round-node-cards" role="group" aria-label="选择学习节点">
      <button v-for="member in detail.members" :key="member.member_id" type="button"
        :aria-pressed="member.member_id === selection.memberId" :class="{ active: member.member_id === selection.memberId }"
        @click="$emit('select', { memberId: member.member_id })">
        <span>{{ roundRoleLabel(member.role) }}</span><strong>{{ member.node_name || member.node_id }}</strong>
        <small>{{ roundStateLabel(member.state) }}<template v-if="member.failed_job_count"> · {{ member.failed_job_count }} 项失败</template></small>
      </button>
    </div>
    <div class="round-stage-controls">
      <label>学习阶段<select :value="selection.stageId" @change="$emit('select', { stageId: $event.target.value })">
        <option v-for="stage in stages" :key="stage.stage_id" :value="stage.stage_id">{{ stage.kind === 'initial' ? '本轮学习' : `本轮纠错 ${stage.ordinal}` }}</option>
      </select></label>
      <label v-if="scope?.job_ids.length > 1">生产任务<select :value="selection.runId" @change="$emit('select', { runId: $event.target.value })">
        <option v-for="(runId, index) in scope.job_ids" :key="runId" :value="runId">任务 {{ index + 1 }} · {{ runId.slice(0, 8) }}</option>
      </select></label>
      <button type="button" class="round-evaluate" @click="$emit('evaluate')">本轮测评</button>
    </div>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { roundRoleLabel, roundStateLabel } from './roundWorkspace.js'
const props = defineProps({ detail: { type: Object, required: true }, selection: { type: Object, required: true } })
defineEmits(['select', 'evaluate'])
const stages = computed(() => props.detail.stages.filter(stage => stage.members.some(member => member.member_id === props.selection.memberId)))
const scope = computed(() => stages.value.find(stage => stage.stage_id === props.selection.stageId)?.members.find(member => member.member_id === props.selection.memberId))
</script>
<style scoped>
.round-switcher { margin:16px 0; padding:16px; border:1px solid #d9e4eb; border-radius:10px; background:#fff; }
.round-node-cards { display:flex; flex-wrap:wrap; gap:12px; }.round-node-cards button { display:grid; gap:7px; flex:1 1 220px; min-height:90px; padding:14px; text-align:left; color:#173349; background:#f5f8fa; border:1px solid #d9e4eb; border-radius:8px; cursor:pointer; }
.round-node-cards button.active { border-color:#08717b; background:#e7f5f2; }.round-node-cards span,.round-node-cards small { font-size:12px; }.round-node-cards strong { font-size:16px; overflow-wrap:anywhere; }
.round-stage-controls { display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-top:12px; }.round-stage-controls label { display:flex; gap:8px; align-items:center; font-size:13px; }.round-stage-controls select,.round-evaluate { min-height:44px; max-width:100%; border:1px solid #b6cbd3; border-radius:5px; color:#173349; background:#fff; padding:8px; }
button:focus-visible,select:focus-visible { outline:2px solid #08717b; outline-offset:3px; }.round-evaluate { margin-left:auto; cursor:pointer; }
</style>
