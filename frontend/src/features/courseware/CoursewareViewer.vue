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
    <div class="courseware-learning-toolbar">
      <span>学习进度：{{ progressLabel }}</span>
      <button type="button" @click="toggleFullscreen">{{ fullscreen ? '退出全屏' : '全屏学习' }}</button>
      <button type="button" @click="restartLearning">重新开始</button>
      <details v-if="resource.source_summary?.length"><summary>查看来源（{{ resource.source_summary.length }}）</summary><ul><li v-for="source in resource.source_summary" :key="source.resource_id">{{ source.resource_type }} · {{ source.topic || source.resource_id }} · v{{ source.version }}<template v-if="source.usage?.adopted === false"> · 未采用：{{ source.usage.unused_reason || '未进入课程主线' }}</template></li></ul></details>
      <span v-if="resource.warnings?.length" class="degraded-note">部分内容使用基础兜底生成</span>
    </div>
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { coursewareApi } from './api'
import { acknowledgeCoursewareEvents, enqueueCoursewareEvent, pendingCoursewareEvents } from './offlineEvents.js'

const props = defineProps({ resource: { type: Object, required: true } })
const frame = ref(null)
const fullscreen = ref(false)
const sceneIndex = ref(1)
const sceneCount = ref(1)
const restoredProgress = ref(null)
let frameLoaded = false
const progressLabel = computed(() => `${sceneIndex.value} / ${sceneCount.value}`)
let nonce = ''
let lifecycleToken = 0
let lifecycleKey = ''
const lifecycle = computed(() => `${props.resource?.resource_id || ''}:${props.resource?.released_release_id || props.resource?.release_id || ''}`)

function newNonce() {
  nonce = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
}

function resetLifecycle() {
  lifecycleToken += 1
  lifecycleKey = lifecycle.value
  frameLoaded = false
  restoredProgress.value = null
  sceneIndex.value = 1
  sceneCount.value = 1
  newNonce()
}

function initializeFrame() {
  frameLoaded = true
  postInit()
}

function postInit() {
  if (!frameLoaded || !frame.value?.contentWindow) return
  frame.value.contentWindow.postMessage({ type: 'courseware-init', nonce, resource_id: props.resource.resource_id, release_id: props.resource.released_release_id || props.resource.release_id, restore: restoredProgress.value }, '*')
}

async function loadLearningProgress() {
  const token = lifecycleToken
  const requestKey = lifecycleKey
  const releaseId = props.resource?.released_release_id || props.resource?.release_id
  if (!releaseId || !props.resource?.resource_id) return
  try {
    const response = await coursewareApi.learningProgress(props.resource.resource_id, releaseId)
    if (token !== lifecycleToken || requestKey !== lifecycleKey) return
    restoredProgress.value = response.data || null
    if (Number.isInteger(restoredProgress.value?.current_scene_index)) {
      sceneIndex.value = restoredProgress.value.current_scene_index + 1
    }
  } catch (_) {
    if (token !== lifecycleToken || requestKey !== lifecycleKey) return
    restoredProgress.value = null
  } finally {
    postInit()
  }
}

async function flushLearningEvents() {
  const pending = pendingCoursewareEvents().filter((item) => item.resource_id === props.resource?.resource_id && item.release_id === (props.resource?.released_release_id || props.resource?.release_id))
  if (!pending.length || !props.resource?.resource_id) return
  try {
    const result = await coursewareApi.ingestLearningEvents(props.resource.resource_id, pending)
    acknowledgeCoursewareEvents(result?.acknowledged_event_ids || [])
  } catch (_) { /* retain queue for offline retry */ }
}

function receiveMessage(event) {
  if (event.source !== frame.value?.contentWindow) return
  if (event.origin !== 'null' && event.origin !== window.location.origin) return
  const data = event.data || {}
  if (data.nonce !== nonce || !['ready', 'progress', 'quiz_result', 'completed', 'learning_event'].includes(data.type)) return
  if (data.resource_id && data.resource_id !== props.resource.resource_id) return
  if (data.release_id && data.release_id !== (props.resource.released_release_id || props.resource.release_id)) return
  if (data.type === 'progress') { sceneIndex.value = Number(data.scene_index || 0) + 1; sceneCount.value = Number(data.scene_count || sceneCount.value) }
  if (data.type === 'learning_event' && data.event) {
    if (data.event.resource_id !== props.resource.resource_id || (props.resource.released_release_id && data.event.release_id !== props.resource.released_release_id)) return
    enqueueCoursewareEvent(data.event)
    flushLearningEvents()
  }
}

function toggleFullscreen() {
  if (!frame.value) return
  if (!document.fullscreenElement) frame.value.requestFullscreen?.()
  else document.exitFullscreen?.()
  fullscreen.value = !fullscreen.value
}

function restartLearning() {
  frame.value?.contentWindow?.postMessage({ type: 'courseware-command', command: 'restart', nonce }, '*')
  sceneIndex.value = 1
}

window.addEventListener('message', receiveMessage)
window.addEventListener('online', flushLearningEvents)
onMounted(async () => {
  resetLifecycle()
  await loadLearningProgress()
  await flushLearningEvents()
  postInit()
})
watch(lifecycle, async () => {
  resetLifecycle()
  await loadLearningProgress()
  postInit()
}, { flush: 'post' })
onBeforeUnmount(() => window.removeEventListener('message', receiveMessage))
onBeforeUnmount(() => window.removeEventListener('online', flushLearningEvents))
</script>

<style scoped>
.courseware-learning-toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 22px;border-bottom:1px solid #e4ebf3;color:#52677f;font-size:12px}.courseware-learning-toolbar button{min-height:36px;padding:6px 10px;border:1px solid #9fc5ec;border-radius:7px;background:#fff;color:#2467b3;cursor:pointer}.courseware-learning-toolbar details{margin-left:auto}.courseware-learning-toolbar ul{margin:8px 0 0;padding-left:18px}.degraded-note{color:#a25a16}
.courseware-card{height:clamp(620px,calc(100dvh - 210px),980px);min-height:0;display:grid;grid-template-rows:auto auto minmax(0,1fr);overflow:hidden;border:1px solid #dce6ef;border-radius:10px;background:#fff;box-shadow:0 14px 32px rgba(35,62,94,.06)}header{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:17px 22px;border-bottom:1px solid #e4ebf3;background:#fbfdff}header span{color:#2058a7;font-size:11px;font-weight:800;letter-spacing:.05em}h2{margin:4px 0 0;color:#172033;font-size:18px}small{display:block;margin-top:5px;color:#a25a16}nav{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px}a{padding:8px 10px;border:1px solid #9fc5ec;border-radius:8px;color:#2467b3;font-size:12px;font-weight:700;text-decoration:none}iframe{display:block;width:100%;height:100%;min-height:0;border:0;background:#f4f8fc}@media(max-width:760px){.courseware-card{height:auto;min-height:760px;grid-template-rows:auto auto minmax(620px,1fr)}header{align-items:flex-start;flex-direction:column}nav{justify-content:flex-start}}
</style>
