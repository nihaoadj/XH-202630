<template>
  <section class="preparation-panel preparation-workspace" :class="{ 'is-compact-workspace': compact }" :aria-busy="pending" :aria-label="title">
    <div class="workspace-introduction">
      <header class="preparation-heading">
        <span class="workspace-eyebrow">{{ eyebrow }} <i aria-hidden="true"></i></span>
        <span v-if="status" class="workspace-status" role="status"><i aria-hidden="true"></i>{{ status }}</span>
        <h3><span v-for="(phrase, index) in title.split('，')" :key="index" class="heading-phrase">{{ phrase }}{{ index < title.split('，').length - 1 ? '，' : '' }}</span></h3>
        <p>{{ description }}</p>
      </header>
        <figure class="workspace-flow-art" :class="`${variant}-flow-art`">
          <svg v-if="variant === 'library'" class="learning-plane" viewBox="0 0 430 280" fill="none" aria-hidden="true">
            <defs>
              <linearGradient :id="`${variant}-workspace-plane`" x1="100" y1="70" x2="335" y2="218" gradientUnits="userSpaceOnUse"><stop stop-color="#e0f5ef"/><stop offset="1" stop-color="#e6effa"/></linearGradient>
            </defs>
            <g stroke="#cddfe3" stroke-width=".75">
              <path d="m27 175 186-107 186 107-186 107-186-107Zm31-18 186 107m-155-125 186 107m-155-125 186 107m-155-125 186 107m-155-125 186 107M58 193 244 86M89 211 275 104m-155 125 186-107m-155 125 186-107m-155 125 186-107"/>
            </g>
            <path d="M78 132c0-76 272-76 272 0s-272 76-272 0Z" stroke="#9abdc8" stroke-dasharray="3 6"/>
            <path d="m87 171 128-74 128 74-128 74-128-74Z" fill="#eff6f8" stroke="#b4d1d9"/>
            <path d="m87 151 128-74 128 74-128 74-128-74Z" :fill="`url(#${variant}-workspace-plane)`" stroke="#79b8bb"/>
            <path d="m87 131 128-74 128 74-128 74-128-74Z" fill="#f8fdfc" stroke="#468e9a" stroke-width="1.3"/>
            <path d="m108 131 107-62 107 62-107 62-107-62Z" stroke="#c6e1df"/>
            <path d="M87 131v40m256-40v40m-128 34v40" stroke="#79b8bb"/>
            <g stroke="#187c86" stroke-width="1.4" stroke-linejoin="round">
              <path d="m177 88 38-22 38 22v47l-38 22-38-22V88Z" fill="#e4f4f1"/>
              <path d="m177 88 38 22 38-22m-38 22v47"/>
              <path d="m191 97 24-14 24 14m-43 23 11 6m-11 3 11 6"/>
            </g>
            <g fill="#fff" stroke="#91bdc4">
              <rect x="27" y="72" width="91" height="34" rx="4"/>
              <rect x="312" y="72" width="91" height="34" rx="4"/>
              <rect x="172" y="224" width="86" height="34" rx="4"/>
            </g>
            <g stroke="#589da5" stroke-width="1.1"><path d="m118 89 34 19m160-19-34 19m-63 97v19"/><circle cx="152" cy="108" r="3" fill="#b4e9dc"/><circle cx="278" cy="108" r="3" fill="#b4e9dc"/><circle cx="215" cy="205" r="3" fill="#b4e9dc"/></g>
            <g fill="#255869" font-size="12" font-family="'Microsoft YaHei', sans-serif"><text x="49" y="94">{{ flowLabels[0] }}</text><text x="334" y="94">{{ flowLabels[1] }}</text><text x="191" y="246">{{ flowLabels[2] }}</text></g>
          </svg>
          <svg v-else class="production-pipeline" viewBox="0 0 430 250" fill="none" aria-hidden="true">
            <defs>
              <pattern id="production-workspace-grid" width="18" height="18" patternUnits="userSpaceOnUse"><path d="M18 0H0v18" stroke="#e4eeef" stroke-width=".6"/></pattern>
              <linearGradient id="production-agent-surface" x1="148" y1="35" x2="282" y2="211" gradientUnits="userSpaceOnUse"><stop stop-color="#eaf8f3"/><stop offset="1" stop-color="#f0f6fb"/></linearGradient>
            </defs>
            <rect x="2" y="27" width="426" height="202" rx="10" fill="url(#production-workspace-grid)"/>
            <g fill="#426779" font-family="Consolas, monospace" font-size="10" letter-spacing=".7"><text x="13" y="18">01 / PROFILE</text><text x="160" y="18">02 / AGENTS</text><text x="316" y="18">03 / OUTPUT</text></g>
            <rect x="148" y="31" width="134" height="190" rx="10" fill="url(#production-agent-surface)" stroke="#c2dcda"/>
            <g stroke="#7baeb4" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M108 124h18m0 0V64h34m-34 60h34m-34 0v60h34M270 64h23v60m-23 0h35m-35 60h23v-60"/>
              <path d="M155 61l5 3-5 3M155 121l5 3-5 3M155 181l5 3-5 3M300 121l5 3-5 3"/>
            </g>
            <g fill="#a1dfd3" stroke="#4b999e"><circle cx="126" cy="124" r="3"/><circle cx="293" cy="124" r="3"/></g>
            <rect x="12" y="83" width="96" height="82" rx="6" fill="#fff" stroke="#a6c8d0"/>
            <path d="M47 98h17l9 9v19H47V98Z" fill="#edf7f5" stroke="#187d86" stroke-width="1.3" stroke-linejoin="round"/>
            <path d="M64 98v9h9m-20 6h13m-13 6h9" stroke="#187d86" stroke-width="1.2"/>
            <g fill="#fff" stroke="#9fc8c8"><rect x="160" y="44" width="110" height="40" rx="5"/><rect x="160" y="104" width="110" height="40" rx="5"/><rect x="160" y="164" width="110" height="40" rx="5"/></g>
            <g stroke="#187d86" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M176 56h12v5h-12Zm6 5v5m-6 0h12m-12 0v5m12-5v5"/>
              <path d="m178 115-5 9 5 9m9-18 5 9-5 9m-4-17-2 16"/>
              <path d="m182 176 9 4v6c0 5-9 8-9 8s-9-3-9-8v-6l9-4Z" fill="#e7f6f1"/><path d="m178 185 3 3 5-6"/>
            </g>
            <rect x="305" y="83" width="112" height="82" rx="6" fill="#f4faf8" stroke="#83b9b4"/>
            <rect x="347" y="99" width="23" height="27" rx="2" fill="#fff" stroke="#69a6ad"/>
            <rect x="352" y="95" width="23" height="27" rx="2" fill="#fff" stroke="#187d86" stroke-width="1.2"/>
            <path d="M357 102h13m-13 5h13m-13 5h8" stroke="#69a6ad"/>
            <g fill="#255869" font-family="'Microsoft YaHei', sans-serif" font-size="12"><text x="36" y="148">{{ flowLabels[0] }}</text><text x="202" y="68">任务编排</text><text x="202" y="128">内容生成</text><text x="202" y="188">质量校验</text><text x="337" y="148">{{ flowLabels[2] }}</text></g>
            <g fill="#426779" font-family="'Microsoft YaHei', sans-serif" font-size="11" text-anchor="middle"><text x="60" y="244">目标与起点</text><text x="215" y="244">{{ flowLabels[1] }}</text><text x="361" y="244">可用学习资源</text></g>
          </svg>
          <figcaption><span aria-hidden="true">{{ variant === 'library' ? 'KNOWLEDGE → SKILL' : 'PROFILE → OUTPUT' }}</span><span>{{ flowCaption }}</span></figcaption>
        </figure>

    </div>
    <section class="workspace-capabilities" :aria-label="capabilitiesTitle">
      <header><span>{{ capabilitiesTitle }}</span><small aria-hidden="true">{{ capabilitiesEnglish }}</small></header>
      <ol class="preparation-steps">
        <li v-for="capability in capabilities" :key="capability.title" class="workspace-capability-zone" :class="`${variant}-capability-zone`">
          <div class="capability-topline"><el-icon aria-hidden="true"><component :is="capability.icon" /></el-icon><span aria-hidden="true">{{ capability.eyebrow }}</span></div>
          <strong>{{ capability.title }}</strong><p>{{ capability.description }}</p>
          <small>{{ capability.detail }}</small>
        </li>
      </ol>
    </section>
    <footer class="preparation-footer">
      <div class="workspace-footer-copy"><span>{{ footerTitle }}</span><small>{{ footerDescription }}</small></div>
      <div class="workspace-actions" :class="`${variant}-preparation-actions`"><slot name="actions" /></div>
    </footer>
  </section>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
  eyebrow: { type: String, default: 'YOUR LEARNING SPACE' },
  status: { type: String, default: '' },
  variant: { type: String, default: 'library' },
  flowLabels: { type: Array, default: () => ['资源生成', '专注学习', '反馈进阶'] },
  flowCaption: { type: String, default: '学习流程示意' },
  capabilities: { type: Array, default: () => [] },
  capabilitiesTitle: { type: String, default: '材料就绪后，在这里展开学习' },
  capabilitiesEnglish: { type: String, default: 'EXPLORE · PRACTICE · REFLECT' },
  footerTitle: { type: String, default: '' },
  footerDescription: { type: String, default: '' },
  pending: Boolean,
  compact: Boolean,
})
</script>

<style scoped>
.preparation-workspace { --prep-ink: #132c40; --prep-muted: #536b7d; --prep-teal: #086575; --prep-mint: #9cecdf; --prep-line: #d9e4eb; }
.preparation-workspace { position: relative; display: grid; min-width: 0; grid-template-rows: minmax(240px, 1fr) auto auto; gap: 24px; padding: 28px; border: 1px solid #cbdfe4; border-radius: 6px; background: linear-gradient(125deg, #f1f8f6 0%, #fff 55%, #f4f8fc 100%); box-shadow: 0 8px 32px rgb(17 40 60 / 4%); }
.preparation-workspace::before { position: absolute; top: -1px; left: 28px; width: 96px; height: 2px; background: linear-gradient(90deg, #167c7c, #96dacf); content: ''; }
.workspace-introduction { display: grid; min-width: 0; grid-template-columns: minmax(0, 1.2fr) minmax(0, .9fr); align-items: center; gap: 36px; }
.preparation-workspace .preparation-heading { display: block; min-width: 0; }
.workspace-eyebrow { display: flex; align-items: center; gap: 16px; color: var(--prep-teal); font: 11px/1.6 Consolas, monospace; letter-spacing: .06em; }
.workspace-eyebrow i { width: 44px; height: 1px; background: #78b7b5; }
.workspace-status { display: inline-flex; align-items: center; gap: 7px; margin-top: 16px; padding: 5px 9px; border: 1px solid #c5dfdc; border-radius: 4px; background: #edf7f4; color: var(--prep-teal); font-size: 12px; line-height: 1.5; }
.workspace-status i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.preparation-workspace h3 { margin: 16px 0 0; color: var(--prep-ink); font-size: clamp(26px, 2.3vw, 34px); font-weight: 650; line-height: 1.5; text-wrap: balance; }
.heading-phrase { display: inline-block; max-width: 100%; vertical-align: top; }
.preparation-workspace .preparation-heading > p { max-width: 52ch; margin: 16px 0 0; color: var(--prep-muted); font-size: 14px; line-height: 1.85; overflow-wrap: anywhere; }
.workspace-flow-art { display: grid; width: 100%; max-width: 420px; justify-self: center; margin: 0; }
.workspace-flow-art svg { width: 100%; height: 250px; }
.workspace-flow-art figcaption { display: flex; justify-content: center; align-items: center; gap: 16px; color: var(--prep-muted); font-size: 11px; line-height: 1.6; }
.workspace-flow-art figcaption > span:first-child { color: var(--prep-teal); font: 10px/1.6 Consolas, monospace; letter-spacing: .04em; }
.workspace-capabilities { min-width: 0; }
.workspace-capabilities > header { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px 16px; margin-bottom: 14px; color: var(--prep-muted); font-size: 12px; line-height: 1.6; }
.workspace-capabilities > header small { font: 10px/1.6 Consolas, monospace; letter-spacing: .04em; }
.preparation-workspace .preparation-steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0; padding: 0; list-style: none; border: 1px solid var(--prep-line); border-radius: 4px; background: rgb(255 255 255 / 72%); }
.workspace-capability-zone { min-width: 0; padding: 20px 22px; }
.workspace-capability-zone + .workspace-capability-zone { border-left: 1px solid var(--prep-line); }
.capability-topline { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 18px; color: var(--prep-teal); }
.capability-topline .el-icon { font-size: 25px; }
.capability-topline > span { color: var(--prep-muted); font: 10px/1.6 Consolas, monospace; letter-spacing: .04em; }
.workspace-capability-zone > strong { display: block; color: var(--prep-ink); font-size: 18px; font-weight: 650; line-height: 1.5; }
.workspace-capability-zone > p { margin: 9px 0 18px; color: var(--prep-muted); font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.workspace-capability-zone > small { color: var(--prep-teal); font-size: 11px; line-height: 1.7; }
.preparation-workspace .preparation-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 18px; border-top: 1px solid var(--prep-line); }
.workspace-footer-copy { min-width: 0; }
.workspace-footer-copy > span, .workspace-footer-copy > small { display: block; }
.workspace-footer-copy > span { color: var(--prep-ink); font-size: 14px; font-weight: 600; line-height: 1.6; }
.workspace-footer-copy > small { margin-top: 5px; color: var(--prep-muted); font-size: 12px; line-height: 1.7; }
.workspace-actions { display:flex; align-items:center; flex-wrap:wrap; gap:10px; }
.workspace-actions .el-button { margin:0; }
.preparation-workspace :deep(.el-button) { min-height: 44px; padding: 10px 16px; border-radius: 5px; font-size: 13px; font-weight: 600; }
.preparation-workspace .workspace-actions :deep(.el-button--primary) { border-color: #88cfc5 !important; background: var(--prep-mint) !important; color: #123747 !important; }
.preparation-workspace .workspace-actions :deep(.el-button--primary:hover) { border-color: #55a89f !important; background: #b4f2e8 !important; color: #123747 !important; }
.workspace-actions .el-icon { margin-left: 12px; }
.workspace-loading-note { color: var(--prep-muted); font-size: 12px; line-height: 1.7; }

.workspace-actions :deep(.el-button) { margin: 0; min-height: 44px; padding: 10px 16px; border-radius: 5px; font-size: 13px; font-weight: 600; }
.workspace-actions :deep(.el-button:focus-visible) { outline: 3px solid #16758a; outline-offset: 3px; }
@media (min-width: 1100px) {
  .is-compact-workspace { padding: 20px 24px; gap: 18px; grid-template-rows: minmax(160px, 1fr) auto auto; }
  .is-compact-workspace .workspace-introduction { gap: 24px; }
  .is-compact-workspace h3 { font-size: 28px; }
  .is-compact-workspace .preparation-heading > p { margin-top: 12px; font-size: 13px; }
  .is-compact-workspace .workspace-flow-art svg { height: 175px; }
  .is-compact-workspace .production-flow-art svg { height: 220px; }
  .is-compact-workspace .workspace-capabilities > header { margin-bottom: 10px; }
  .is-compact-workspace .workspace-capability-zone { padding: 14px 18px; }
  .is-compact-workspace .capability-topline { margin-bottom: 10px; }
  .is-compact-workspace .capability-topline .el-icon { font-size: 22px; }
  .is-compact-workspace .workspace-capability-zone > strong { font-size: 17px; }
  .is-compact-workspace .workspace-capability-zone > p { margin-block: 8px 12px; font-size: 12px; }
  .is-compact-workspace .preparation-footer { padding-top: 14px; }
}
@media (max-width: 760px) {
  .preparation-workspace { gap: 22px; grid-template-rows: auto auto auto; padding: 24px 18px; }
  .workspace-introduction { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .preparation-workspace h3 { font-size: 26px; }
  .workspace-flow-art { max-width: 320px; }
  .workspace-flow-art svg { height: 200px; }
  .preparation-workspace .preparation-steps { grid-template-columns: minmax(0, 1fr); }
  .workspace-capability-zone { padding: 20px; }
  .workspace-capability-zone + .workspace-capability-zone { border-left: 0; border-top: 1px solid var(--prep-line); }
  .capability-topline { margin-bottom: 12px; }
  .workspace-capability-zone > p { font-size: 14px; }
  .preparation-workspace .preparation-footer { align-items: stretch; flex-direction: column; }
  .workspace-actions { flex-direction: column; align-items: stretch; }
  .preparation-workspace :deep(.el-button) { width: 100%; }

}
@media (prefers-reduced-motion: reduce) {
  .preparation-workspace :deep(*) { transition: none !important; animation: none !important; }
}
</style>
