<template>
  <section class="preparation-panel" :class="{ 'is-horizontal': horizontal, 'is-compact': compact }" :aria-label="title" :aria-busy="pending">
    <header class="preparation-heading">
      <span class="preparation-mark" aria-hidden="true">
        <slot name="mark">
        <svg viewBox="0 0 32 32" fill="none">
          <path d="M9 5h10l5 5v17H9V5Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />
          <path d="M19 5v6h5M13 15h7m-7 4h7m-7 4h4M5 10v17" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
        </slot>
      </span>
      <div>
        <span class="preparation-eyebrow" aria-hidden="true">{{ eyebrow }}</span>
        <h3>{{ title }}</h3>
        <p>{{ description }}</p>
      </div>
    </header>
    <div v-if="$slots.context" class="preparation-context"><slot name="context" /></div>
    <ol v-if="steps.length" class="preparation-steps" aria-label="接下来的步骤">
      <li v-for="(step, index) in steps" :key="step.title">
        <span class="preparation-number" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span>
        <div><strong>{{ step.title }}</strong><p>{{ step.description }}</p></div>
      </li>
    </ol>
    <footer v-if="$slots.footer" class="preparation-footer"><slot name="footer" /></footer>
  </section>
</template>

<script setup>
defineProps({
  eyebrow: { type: String, default: 'YOUR NEXT STEP' },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  steps: { type: Array, default: () => [] },
  pending: Boolean,
  horizontal: Boolean,
  compact: Boolean,
})
</script>

<style scoped>
.preparation-panel { display: flex; min-width: 0; flex-direction: column; gap: 24px; padding: 28px; color: #132c40; background: linear-gradient(135deg, #f2f8f7 0%, #fff 60%); }
.preparation-heading { display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: 16px; align-items: start; }
.preparation-heading > div { min-width: 0; }
.preparation-mark { display: grid; width: 44px; height: 44px; place-items: center; border: 1px solid #bad9d6; border-radius: 6px; background: #e6f3f0; color: #086575; }
.preparation-mark svg { width: 30px; height: 30px; }
.preparation-eyebrow { display: block; color: #536b7d; font: 10px/1.6 Consolas, 'SFMono-Regular', monospace; letter-spacing: .06em; }
.preparation-heading h3 { margin: 7px 0 0; font-size: 24px; font-weight: 650; line-height: 1.5; text-wrap: balance; }
.preparation-heading p { max-width: 58ch; margin: 10px 0 0; color: #536b7d; font-size: 13px; line-height: 1.85; overflow-wrap: anywhere; }
.preparation-context { min-width: 0; padding: 16px 0; border-block: 1px solid #dce7e9; }
.preparation-steps { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }
.preparation-steps li { position: relative; display: grid; min-width: 0; grid-template-columns: 32px minmax(0, 1fr); gap: 14px; padding: 14px 0; }
.preparation-steps li:not(:last-child)::after { position: absolute; top: 50px; bottom: -10px; left: 15px; width: 1px; background: #c8dcdf; content: ''; }
.preparation-number { display: grid; width: 32px; height: 32px; place-items: center; border: 1px solid #b9d4d8; border-radius: 4px; background: #edf7f5; color: #086575; font: 11px/1 Consolas, monospace; }
.preparation-steps strong { display: block; padding-top: 4px; font-size: 14px; font-weight: 600; line-height: 1.5; }
.preparation-steps p { margin: 5px 0 0; color: #536b7d; font-size: 12px; line-height: 1.85; overflow-wrap: anywhere; }
.preparation-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-top: auto; padding-top: 20px; border-top: 1px solid #dce7e9; color: #536b7d; font-size: 12px; line-height: 1.8; }
.is-horizontal { gap: 28px; }
.is-horizontal .preparation-heading h3 { font-size: clamp(22px, 2.4vw, 30px); }
.is-horizontal .preparation-steps { grid-template-columns: repeat(3, minmax(0, 1fr)); padding-block: 12px; border-block: 1px solid #dce7e9; }
.is-horizontal .preparation-steps li { padding: 12px 22px; }
.is-horizontal .preparation-steps li:first-child { padding-left: 0; }
.is-horizontal .preparation-steps li:last-child { padding-right: 0; }
.is-horizontal .preparation-steps li:not(:last-child) { border-right: 1px solid #dce7e9; }
.is-horizontal .preparation-steps li::after { display: none; }
.is-horizontal .preparation-footer { padding-top: 0; border: 0; }
.is-compact { gap: 18px; padding: 24px; }
.is-compact .preparation-heading { grid-template-columns: 36px minmax(0, 1fr); gap: 12px; }
.is-compact .preparation-mark { width: 36px; height: 36px; }
.is-compact .preparation-mark svg { width: 25px; height: 25px; }
.is-compact .preparation-heading h3 { font-size: 20px; }
.is-compact .preparation-steps li { padding-block: 10px; }
@media (max-width: 760px) {
  .preparation-panel { gap: 20px; padding: 22px 18px; }
  .preparation-heading { grid-template-columns: 36px minmax(0, 1fr); gap: 12px; }
  .preparation-mark { width: 36px; height: 36px; }
  .preparation-heading h3, .is-horizontal .preparation-heading h3 { font-size: 22px; }
  .is-horizontal .preparation-steps { grid-template-columns: minmax(0, 1fr); padding-block: 6px; }
  .is-horizontal .preparation-steps li { padding: 14px 0; }
  .is-horizontal .preparation-steps li:not(:last-child) { border-right: 0; border-bottom: 1px solid #dce7e9; }
  .preparation-footer { align-items: stretch; flex-direction: column; }
  .preparation-footer :slotted(.el-button) { width: 100%; min-height: 44px; margin: 0; }
}
</style>
