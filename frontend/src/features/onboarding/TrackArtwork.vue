<script setup>
defineProps({ kind:String, detail:Boolean })
</script>

<template>
  <svg :viewBox="detail ? '0 0 160 100' : '0 0 40 40'" fill="none" xmlns="http://www.w3.org/2000/svg">
    <g v-if="detail" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round">
      <g v-if="kind === 'rag'">
        <path d="m25 49 52-26 57 27-52 28Z" fill="currentColor" fill-opacity=".07" />
        <path d="m25 61 57 29 52-28M25 55l57 29 52-28M25 49v12m109-11v12M77 23v12" opacity=".5" />
        <path d="m53 50 26-13 27 13-26 14Z" /><path d="m64 50 15-7 15 7-14 7Z" fill="currentColor" fill-opacity=".15" />
        <path d="M9 21h22l15 15M115 27l12-11h23M82 78v17" opacity=".55" />
        <circle cx="9" cy="21" r="2" /><circle cx="150" cy="16" r="2" />
      </g>
      <g v-else-if="kind === 'agent'">
        <ellipse cx="81" cy="51" rx="56" ry="30" transform="rotate(-25 81 51)" opacity=".35" />
        <path d="m33 26 48 25 47-21M81 51l-6 37" opacity=".6" />
        <path d="m81 35 16 16-16 16-16-16Z" fill="currentColor" fill-opacity=".1" />
        <path d="m81 43 8 8-8 8-8-8Z" />
        <circle cx="33" cy="26" r="8" /><circle cx="128" cy="30" r="8" /><circle cx="75" cy="88" r="6" />
        <circle cx="33" cy="26" r="2" fill="currentColor" /><circle cx="128" cy="30" r="2" fill="currentColor" />
      </g>
      <g v-else-if="kind === 'api'">
        <path d="m41 26-18 24 18 24m78-48 18 24-18 24" stroke-width="2" opacity=".6" />
        <path d="M47 50h24l14-22h25M71 50l14 22h25M80 50h31" />
        <rect x="69" y="40" width="20" height="20" rx="5" fill="currentColor" fill-opacity=".08" />
        <circle cx="113" cy="28" r="3" /><circle cx="114" cy="50" r="3" /><circle cx="113" cy="72" r="3" />
        <path d="M51 19h12m-12 62h12M7 50h7m132 0h7" opacity=".45" />
      </g>
    </g>
    <g v-else stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <g v-if="kind === 'rag'">
        <path d="m5 17 15-8 15 8-15 8Z" /><path d="m5 23 15 8 15-8M5 29l15 8 15-8" opacity=".65" /><path d="m14 17 6-3 6 3-6 3Z" fill="currentColor" fill-opacity=".2" />
      </g>
      <g v-else-if="kind === 'agent'">
        <path d="m20 12 8 8-8 8-8-8Z" /><path d="m9 9 6 6m10 0 6-6M20 28v6" /><circle cx="7" cy="7" r="3" /><circle cx="33" cy="7" r="3" /><circle cx="20" cy="36" r="2" /><path d="m20 17 3 3-3 3-3-3Z" fill="currentColor" />
      </g>
      <g v-else-if="kind === 'api'">
        <path d="m11 9-7 11 7 11m18-22 7 11-7 11M12 20h6l5-8h5m-10 8 5 8h5" /><rect x="17" y="17" width="6" height="6" rx="1.5" fill="currentColor" fill-opacity=".2" />
      </g>
    </g>
  </svg>
</template>
