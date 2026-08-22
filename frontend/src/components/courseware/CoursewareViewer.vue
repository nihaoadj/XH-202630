<template>
  <section class="courseware-card">
    <header>
      <div>
        <span>INTERACTIVE COURSEWARE</span>
        <h2>{{ resource.title || resource.resource_type || '互动HTML课件' }}</h2>
        <small v-if="resource.status === 'stale'">源资源已有新版本，当前课件仍可使用，建议重新生成。</small>
      </div>
      <nav aria-label="课件导出">
        <a :href="coursewareApi.downloadUrl(resource.resource_id)" target="_blank" rel="noopener">HTML</a>
        <a v-for="format in ['zip', 'scorm', 'xapi']" :key="format" :href="coursewareApi.packageUrl(resource.resource_id, format)" target="_blank" rel="noopener">{{ format.toUpperCase() }}</a>
      </nav>
    </header>
    <iframe
      ref="frame"
      :src="coursewareApi.previewUrl(resource.resource_id)"
      sandbox="allow-scripts"
      title="互动HTML课件预览"
      @load="initializeFrame"
    />
  </section>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { coursewareApi } from '../../api/courseware'

const props = defineProps({ resource: { type: Object, required: true } })
const frame = ref(null)
const nonce = (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`)

function initializeFrame() {
  frame.value?.contentWindow?.postMessage({ type: 'courseware-init', nonce }, '*')
}

function receiveMessage(event) {
  if (event.source !== frame.value?.contentWindow) return
  const data = event.data || {}
  if (data.nonce !== nonce || !['ready', 'height', 'progress', 'quiz_result', 'completed'].includes(data.type)) return
  if (data.type === 'height' && Number.isFinite(data.height)) frame.value.style.height = `${Math.max(480, Math.min(1600, data.height))}px`
}

window.addEventListener('message', receiveMessage)
onBeforeUnmount(() => window.removeEventListener('message', receiveMessage))
</script>

<style scoped>
.courseware-card{overflow:hidden;border:1px solid #dce6ef;border-radius:10px;background:#fff;box-shadow:0 14px 32px rgba(35,62,94,.06)}header{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:17px 22px;border-bottom:1px solid #e4ebf3;background:#fbfdff}header span{color:#2058a7;font-size:11px;font-weight:800;letter-spacing:.05em}h2{margin:4px 0 0;color:#172033;font-size:18px}small{display:block;margin-top:5px;color:#a25a16}nav{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px}a{padding:8px 10px;border:1px solid #9fc5ec;border-radius:8px;color:#2467b3;font-size:12px;font-weight:700;text-decoration:none}iframe{display:block;width:100%;height:720px;border:0;background:#f4f8fc}@media(max-width:760px){header{align-items:flex-start;flex-direction:column}nav{justify-content:flex-start}iframe{height:680px}}
</style>
