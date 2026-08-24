<template>
  <nav v-if="resources.length > 1" class="focus-resource-switcher" aria-label="切换本次学习资源">
    <button
      v-for="(resource, index) in resources"
      :key="resource.resource_id"
      type="button"
      :class="{ 'is-active': resource.resource_id === selectedResourceId }"
      :aria-pressed="resource.resource_id === selectedResourceId"
      :aria-label="`切换到第 ${index + 1} 份：${resource.resource_type || '学习资源'}`"
      @click="$emit('select-resource', resource.resource_id)"
    >
      <span>{{ String(index + 1).padStart(2, '0') }}</span>
      <strong>{{ resource.resource_type || '学习资源' }}</strong>
      <small>{{ resource.resource_kind === 'interactive_courseware' ? '互动课件' : resource.difficulty || '待分级' }}</small>
      <i>→</i>
    </button>
  </nav>
</template>

<script setup>
defineProps({ resources: { type: Array, default: () => [] }, selectedResourceId: { type: String, default: '' } })
defineEmits(['select-resource'])
</script>

<style scoped>
.focus-resource-switcher{display:flex;gap:8px;overflow-x:auto;padding:10px 14px;border:1px solid #dce6ef;border-radius:10px;background:#fbfdff;scrollbar-width:thin}.focus-resource-switcher button{display:grid;grid-template-columns:28px minmax(90px,1fr) 76px 12px;flex:0 0 220px;gap:8px;align-items:center;min-height:44px;padding:7px 9px;border:1px solid #d9e1ec;border-radius:8px;background:#fff;color:#344963;cursor:pointer;text-align:left}.focus-resource-switcher button:hover{background:#f4f8fd}.focus-resource-switcher button.is-active{border-color:#6da3ff;background:linear-gradient(100deg,#eaf4ff,#f5f9ff);box-shadow:0 4px 11px rgba(53,110,157,.1)}.focus-resource-switcher span{display:grid;width:27px;height:27px;place-items:center;border-radius:7px;background:#eff4fa;color:#71839b;font-size:10px;font-weight:800}.focus-resource-switcher .is-active span{background:#1e6ed2;color:#fff}.focus-resource-switcher strong,.focus-resource-switcher small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.focus-resource-switcher strong{font-size:13px}.focus-resource-switcher small{color:#77889d;font-size:10px}.focus-resource-switcher i{color:#91a1b6;font-style:normal}.focus-resource-switcher .is-active i{color:#2058a7}@media(max-width:760px){.focus-resource-switcher{padding:8px}.focus-resource-switcher button{flex-basis:195px;grid-template-columns:26px minmax(76px,1fr) 64px 10px}}
</style>
