<template>
  <div class="capability-art" :class="'art-' + kind" aria-hidden="true">
    <svg viewBox="0 0 260 166" fill="none" focusable="false">
      <g class="art-registration"><path d="M12 28V16H24M236 16H248V28M12 138V150H24M236 150H248V138" /><path d="M126 13H134M130 9V17M126 153H134M130 149V157" /></g>
      <g v-if="kind === 'agents'">
        <ellipse class="art-orbit" cx="130" cy="83" rx="98" ry="52" />
        <ellipse class="art-orbit" cx="130" cy="83" rx="56" ry="64" transform="rotate(38 130 83)" />
        <path class="art-wire" d="M52 48L130 83L208 48M52 120L130 83L208 120" />
        <path class="art-signal" pathLength="1" d="M52 48L130 83L208 120" />
        <circle class="art-core-ring" cx="130" cy="83" r="35" />
        <circle class="art-core" cx="130" cy="83" r="27" />
        <path class="art-core-mark" d="M118 80V75H128V85H124M132 81V91H142V86M124 83L136 83" />
        <g v-for="(node, index) in agentNodes" :key="index" :transform="`translate(${node[0]} ${node[1]})`">
          <rect class="art-node" x="-18" y="-16" width="36" height="32" rx="9" />
          <path class="art-robot" d="M-7-7H7Q10-7 10-4V6Q10 9 7 9H-7Q-10 9-10 6V-4Q-10-7-7-7ZM0-7V-12M-3-12H3M-4 5H4" />
          <circle class="art-dot" cx="-4" cy="-1" r="1.4" /><circle class="art-dot" cx="4" cy="-1" r="1.4" />
        </g>
        <circle class="art-spark" cx="93" cy="67" r="3" />
      </g>
      <g v-else-if="kind === 'evidence'">
        <rect class="art-sheet-back" x="83" y="25" width="96" height="112" rx="6" />
        <rect class="art-sheet" x="69" y="35" width="96" height="112" rx="6" />
        <rect class="art-document" x="55" y="45" width="96" height="104" rx="6" />
        <path class="art-text" d="M70 62H113M70 73H134M70 107H131M70 116H118M70 133H97" />
        <rect class="art-highlight" x="63" y="82" width="80" height="15" rx="2" />
        <path class="art-accent-line" d="M70 89H123M143 89H185Q197 89 197 77V59" />
        <circle class="art-core" cx="197" cy="43" r="18" />
        <path class="art-core-mark" d="M190 43L195 48L204 38" />
        <path class="art-wire" d="M152 120H197V102" /><circle class="art-dot" cx="197" cy="102" r="3" />
      </g>
      <g v-else-if="kind === 'path'">
        <path class="art-track" d="M40 35H100Q130 35 130 64V100Q130 130 160 130H222M40 82H220M40 130H92Q110 130 110 109V59Q110 35 140 35H220" />
        <path class="art-signal" pathLength="1" d="M40 130H92Q110 130 110 109V59Q110 35 140 35H220" />
        <g v-for="(node, index) in pathNodes" :key="index" :transform="`translate(${node[0]} ${node[1]})`">
          <circle :class="index < 3 ? 'art-path-active' : 'art-node'" r="8" />
          <circle v-if="index < 3" class="art-spark" r="2" />
        </g>
        <rect class="art-node" x="20" y="117" width="28" height="26" rx="7" /><path class="art-core-mark" d="M29 130H39M35 126L39 130L35 134" />
        <circle class="art-core-ring" cx="218" cy="35" r="16" />
        <path class="art-subtle" d="M25 59H235M25 105H235" />
      </g>
      <g v-else>
        <path class="art-track" d="M51 40H205M51 40V123H205" />
        <path class="art-signal" pathLength="1" d="M51 40H115Q139 40 139 64V99Q139 123 162 123H205" />
        <path class="art-wire" d="M205 123V75Q205 60 190 60H179" />
        <rect class="art-node" x="32" y="22" width="38" height="36" rx="9" />
        <path class="art-robot" d="M43 40H59M51 32V48" />
        <circle class="art-core" cx="139" cy="83" r="22" />
        <path class="art-core-mark" d="M132 77A9 9 0 1 1 130 87M129 75L132 79L137 76" />
        <rect class="art-node" x="186" y="105" width="38" height="36" rx="9" />
        <path class="art-core-mark" d="M197 123L203 128L213 117" />
        <circle class="art-spark" cx="99" cy="40" r="3" /><circle class="art-dot" cx="51" cy="123" r="4" />
        <path class="art-subtle" d="M92 16V150M168 16V150" />
      </g>
    </svg>
  </div>
</template>

<script setup>
defineProps({ kind: { type: String, required: true } })
const agentNodes = [[52, 48], [208, 48], [52, 120], [208, 120]]
const pathNodes = [[76, 130], [110, 82], [218, 35], [42, 35], [218, 82], [190, 130]]
</script>

<style scoped>
.capability-art { position: relative; isolation: isolate; width: 100%; height: 130px; }
.capability-art::before { content: ''; position: absolute; inset: 6% 7%; z-index: -1; background: radial-gradient(ellipse, #d7819919, transparent 68%); }
svg { display: block; width: 100%; height: 100%; overflow: visible; }
.art-registration { stroke: #986c822e; stroke-width: 1; }
.art-orbit { stroke: #986c8238; stroke-width: .9; }
.art-wire { stroke: #96667b70; stroke-width: 1.2; }
.art-signal { stroke: #a63355; stroke-width: 1.5; stroke-dasharray: 1; }
.art-core-ring { stroke: #a6335555; stroke-width: 1; fill: #a6335509; }
.art-core { fill: #f3dfe7; stroke: #b85b78; stroke-width: 1; }
.art-core-mark { stroke: #a63355; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.art-node { fill: #fffafc; stroke: #986c8273; stroke-width: 1; }
.art-robot { stroke: #795165; stroke-width: 1.2; stroke-linecap: round; stroke-linejoin: round; }
.art-dot { fill: #9f7284; }
.art-spark { fill: #a63355; filter: drop-shadow(0 0 4px #bc607e); }
.art-sheet-back { fill: #f3eaef; stroke: #986c8245; }
.art-sheet { fill: #f7eff3; stroke: #986c8260; }
.art-document { fill: #fffbfd; stroke: #a07a8e99; }
.art-text { stroke: #8a627e80; stroke-width: 2; stroke-linecap: round; }
.art-highlight { fill: #a6335522; }
.art-accent-line { stroke: #a63355; stroke-width: 1.5; }
.art-track { stroke: #9469804d; stroke-width: 1.1; stroke-dasharray: 3 5; }
.art-path-active { fill: #f3dfe7; stroke: #a63355; }
.art-subtle { stroke: #986c8238; stroke-dasharray: 2 5; }
@media (prefers-reduced-motion: reduce) { svg * { animation: none !important; } }
@media (min-width: 1800px) { .capability-art { height: 210px; } }
@media (min-width: 821px) and (max-width: 1100px) { .capability-art { height: 88px; } }
@media (max-width: 520px) { .capability-art { height: 175px; max-width: 285px; margin-inline: auto; } }
</style>
