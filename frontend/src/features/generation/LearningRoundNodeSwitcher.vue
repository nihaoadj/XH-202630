<template>
  <button v-if="current && next" type="button" class="round-node-switch"
    :aria-label="`切换学习节点，当前${roundRoleLabel(current.role)} ${current.node_name || current.node_id}，切换至${roundRoleLabel(next.role)} ${next.node_name || next.node_id}`"
    @click="$emit('select', { memberId: next.member_id })">
    <span>{{ roundRoleLabel(current.role) }}</span>
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2 5h11m-3-3 3 3-3 3M14 11H3m3-3-3 3 3 3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" /></svg>
  </button>
</template>
<script setup>
import { computed } from 'vue'
import { roundRoleLabel } from './roundWorkspace.js'
const props = defineProps({ detail: { type: Object, required: true }, selection: { type: Object, required: true } })
defineEmits(['select'])
const current = computed(() => props.detail.members.find(member => member.member_id === props.selection.memberId))
const next = computed(() => {
  const members = props.detail.members
  if (members.length < 2 || !current.value) return null
  return members[(members.findIndex(member => member.member_id === current.value.member_id) + 1) % members.length]
})
</script>
<style scoped>
.round-node-switch { display:inline-flex; align-items:center; gap:6px; flex:0 1 auto; min-width:0; max-width:110px; min-height:32px; padding:5px 8px; border:1px solid #c8d5e2; border-radius:6px; color:#294861; background:#eaf0f6; font-size:12px; line-height:1.5; font-weight:500; font-family:inherit; cursor:pointer; }
.round-node-switch span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.round-node-switch svg { flex:none; }
.round-node-switch:hover { border-color:#95acc1; background:#dfe9f2; }
.round-node-switch:focus-visible { outline:2px solid #176b70; outline-offset:2px; }
@media(pointer:coarse),(max-width:720px) { .round-node-switch { min-height:44px; } }
</style>
