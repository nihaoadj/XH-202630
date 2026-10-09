<template>
  <svg class="portal-art" :class="{ 'is-active': active }" viewBox="0 0 480 330" fill="none" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="access-orbit" x1="105" y1="235" x2="375" y2="85" gradientUnits="userSpaceOnUse"><stop stop-color="#77c8dd" /><stop offset=".4" stop-color="#fbffff" /><stop offset=".7" stop-color="#809ae8" /><stop offset="1" stop-color="#b8a5e6" /></linearGradient>
      <linearGradient id="access-edge" x1="174" y1="96" x2="304" y2="234" gradientUnits="userSpaceOnUse"><stop stop-color="#ffffff" /><stop offset=".45" stop-color="#a4cfe2" stop-opacity=".7" /><stop offset="1" stop-color="#9c9ddc" stop-opacity=".55" /></linearGradient>
      <radialGradient id="access-core-glow"><stop stop-color="#f7ffff" stop-opacity=".85" /><stop offset=".55" stop-color="#e3f8fc" stop-opacity=".45" /><stop offset="1" stop-color="#e6e9ff" stop-opacity="0" /></radialGradient>
      <radialGradient id="access-aura"><stop stop-color="#b8bbf6" stop-opacity=".55" /><stop offset="1" stop-color="#dceafa" stop-opacity="0" /></radialGradient>
      <filter id="access-soft-shadow"><feGaussianBlur stdDeviation="9" /></filter>
      <filter id="access-logo-shadow" x="-50%" y="-50%" width="200%" height="210%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#579bc2" flood-opacity=".2" /></filter>
    </defs>
    <ellipse cx="240" cy="163" rx="200" ry="150" fill="url(#access-aura)" />
    <g stroke="#8399c8" stroke-opacity=".12"><path d="M48 275H432M75 295H405M108 313H372M240 248V319M180 248L132 319M300 248L348 319" /></g>
    <ellipse cx="240" cy="286" rx="96" ry="12" fill="#7890c7" opacity=".2" filter="url(#access-soft-shadow)" />
    <ellipse cx="240" cy="167" rx="157" ry="112" transform="rotate(-28 240 167)" stroke="url(#access-orbit)" stroke-opacity=".75" stroke-width="2.5" />
    <ellipse cx="240" cy="167" rx="142" ry="103" transform="rotate(30 240 167)" stroke="white" stroke-opacity=".9" stroke-width="1.5" />
    <g class="portal-core">
      <circle cx="240" cy="167" r="98" fill="url(#access-core-glow)" />
      <circle cx="240" cy="167" r="76" stroke="url(#access-edge)" stroke-width="1.2" />
      <circle cx="240" cy="167" r="84" stroke="#9cb9d9" stroke-opacity=".35" stroke-dasharray="1 13" stroke-linecap="round" />
      <image href="/zhiyu-logo.png" x="198" y="122" width="84" height="84" filter="url(#access-logo-shadow)" />
    </g>
    <g transform="rotate(30 240 167)"><g class="portal-tracer"><circle r="11" fill="#859cdd" fill-opacity=".16" /><circle r="4" fill="#738bcb" stroke="white" stroke-width="2" /></g></g>
    <g fill="#849abd"><circle cx="126" cy="88" r="2" /><circle cx="361" cy="237" r="2" /><circle cx="332" cy="48" r="1.5" /></g>
    <g stroke="#9bafd1" stroke-opacity=".6"><path d="M114 143H122M118 139V147M334 268H342M338 264V272" /></g>
  </svg>
</template>

<script setup>
defineProps({ active: { type: Boolean, default: false } })
</script>

<style scoped>
.portal-art { display: block; width: 100%; height: auto; overflow: visible; }
.portal-core { animation: portal-suspend 8s ease-in-out infinite; animation-play-state: paused; }
.portal-tracer { offset-path: path('M98 167A142 103 0 1 1 382 167A142 103 0 1 1 98 167'); offset-anchor: 0px 0px; offset-rotate: 0deg; animation: portal-flow 18s linear infinite; animation-play-state: paused; }
.portal-art.is-active :is(.portal-core, .portal-tracer) { animation-play-state: running; }
@keyframes portal-suspend { 0%, 100% { transform: translateY(3px); } 50% { transform: translateY(-5px); } }
@keyframes portal-flow { from { offset-distance: 0%; } to { offset-distance: 100%; } }
@media (prefers-reduced-motion: reduce) { .portal-core, .portal-tracer { animation: none !important; } }
</style>
