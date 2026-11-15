<template>
  <div class="round-claim-switches" role="group" aria-label="生成前的可选审查">
    <div class="round-claim-switch" :class="{ 'is-on': check }">
      <el-switch v-model="check" aria-label="Claim 强化审查" :disabled="disabled" />
      <span class="round-claim-switch-copy"><strong>Claim 强化审查</strong><small>关键事实逐条核对来源</small></span>
    </div>
    <div class="round-claim-switch" :class="{ 'is-on': retrieval }">
      <el-switch v-model="retrieval" aria-label="证据不足时补检知识库" :disabled="disabled || !check" />
      <span class="round-claim-switch-copy"><strong>缺证补检知识库</strong><small>证据不足时补检并复核</small></span>
    </div>
  </div>
</template>

<script setup>
defineProps({ disabled: Boolean })
const check = defineModel('check', { type: Boolean, default: false })
const retrieval = defineModel('retrieval', { type: Boolean, default: false })
</script>

<style scoped>
.round-claim-switches { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.round-claim-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 5px 12px 5px 10px;
  border: 1px solid transparent;
  border-radius: 999px;
  background:
    linear-gradient(150deg, rgb(255 255 255 / 98%), rgb(238 246 255 / 94%)) padding-box,
    linear-gradient(145deg, #e0eefb, #9cbcdf 52%, #7099c8) border-box;
  box-shadow:
    inset 0 1px 0 #fff,
    inset 0 0 0 1px rgb(255 255 255 / 45%),
    inset 0 -1px 0 rgb(104 145 191 / 18%),
    0 2px 5px rgb(30 63 104 / 13%),
    0 6px 14px -9px rgb(59 112 175 / 26%),
    0 14px 22px -18px rgb(30 63 104 / 50%);
  transition: box-shadow .18s ease;
}
.round-claim-switch.is-on {
  box-shadow:
    inset 0 1px 0 #fff,
    inset 0 0 0 1px rgb(255 255 255 / 50%),
    inset 0 -1px 0 rgb(84 128 178 / 18%),
    0 3px 8px rgb(30 63 104 / 15%),
    0 16px 26px -18px rgb(30 63 104 / 52%);
}
.round-claim-switch-copy { display: grid; min-width: 0; gap: 1px; }
.round-claim-switch-copy strong { color: var(--feedback-ink); font-size: 12px; font-weight: 650; line-height: 1.3; }
.round-claim-switch-copy small { color: var(--feedback-muted); font-size: 11px; line-height: 1.3; }
.round-claim-switch :deep(.el-switch) { flex: none; min-height: 30px; --el-switch-on-color: var(--feedback-navy); }
@media (max-width: 720px) { .round-claim-switch { flex: 1 1 100%; } }
</style>
