<template>
  <section v-if="round || needs.length" class="round-report-summary" aria-label="当前主节点与待补救项">
    <header><h3>当前学习目标与待补救项</h3><p>主学习目标按轮次角色确定；复习与纠错结果分别保留。</p></header>
    <div v-if="round" class="round-report-members"><article v-for="member in round.members" :key="member.member_id"><span>{{ roundRoleLabel(member.role) }}</span><strong>{{ member.node_name || member.node_id }}</strong><small>{{ roundStateLabel(member.state) }}</small></article></div>
    <ul v-if="pendingNeeds.length"><li v-for="need in pendingNeeds" :key="need.node_id || need.skill_node_id"><strong>{{ need.node_name || need.name || need.node_id || need.skill_node_id }}</strong><span>{{ need.status === 'remediate' ? '待补救' : '待巩固' }} · 等待 {{ need.wait_rounds || 0 }} 轮</span></li></ul>
    <p v-else>当前没有尚未解决的补救记录。</p>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { roundRoleLabel, roundStateLabel } from '../generation/roundWorkspace.js'
const props = defineProps({ round: { type: Object, default: null }, needs: { type: Array, default: () => [] } })
const pendingNeeds = computed(() => props.needs.filter(need => need.status !== 'resolved'))
</script>
<style scoped>
.round-report-summary { margin:18px 0; padding:20px; border:1px solid #d9e4eb; background:white; border-radius:10px; color:#173349; }h3 { margin:0 0 8px; }p { line-height:1.7; color:#526b7a; }.round-report-members { display:flex; flex-wrap:wrap; gap:14px; }.round-report-members article { display:grid; gap:8px; flex:1 1 220px; padding:14px; border:1px solid #d9e4eb; border-radius:7px; }.round-report-members span,.round-report-members small { font-size:13px; }li { padding:8px 0; line-height:1.6; }li span { margin-left:16px; }
</style>
