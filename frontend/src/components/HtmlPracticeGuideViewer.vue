<template>
  <article class="html-guide-card">
    <header class="html-guide-header">
      <div class="html-guide-title">
        <div class="html-guide-context-title">
          <span v-if="progressLabel" class="learning-status"><i></i>正在学习</span>
          <span class="resource-kicker">实操指南 · INTERACTIVE PRACTICE</span>
        </div>
        <div v-if="resourceChoices.length > 1" class="header-resource-switcher" role="group" aria-label="切换本次学习资源">
          <button
            v-for="(choice, index) in resourceChoices"
            :key="choice.resource_id"
            type="button"
            class="header-resource-choice"
            :class="{ 'is-active': choice.resource_id === selectedResourceId }"
            :aria-pressed="choice.resource_id === selectedResourceId"
            :aria-label="`切换到第 ${index + 1} 份：${choice.resource_type || '学习资源'}`"
            @click="selectResource(choice.resource_id)"
          >
            <span>{{ String(index + 1).padStart(2, '0') }}</span>{{ choice.resource_type || '学习资源' }}
          </button>
        </div>
      </div>
      <div class="html-guide-actions">
        <span v-if="progressLabel" class="learning-progress">{{ progressLabel }}</span>
        <el-tag type="success" effect="plain" round>已审核发布</el-tag>
        <el-button v-if="resource?.file_path" :icon="Download" @click="download">下载 HTML</el-button>
      </div>
    </header>

    <el-alert
      v-if="!previewAllowed"
      title="互动版本尚未通过发布准入，当前不可预览。"
      type="warning"
      :closable="false"
      show-icon
      class="viewer-alert"
    />
    <div v-else-if="loading" class="viewer-loading">
      <el-skeleton :rows="9" animated />
    </div>
    <el-result v-else-if="errorMessage" icon="warning" title="互动实践加载失败" :sub-title="errorMessage">
      <template #extra><el-button type="primary" @click="loadPreview">重试</el-button></template>
    </el-result>
    <iframe
      v-else-if="srcdoc"
      ref="frameRef"
      :key="frameKey"
      class="practice-frame"
      :style="{ height: `${frameHeight}px` }"
      :srcdoc="srcdoc"
      sandbox="allow-scripts"
      referrerpolicy="no-referrer"
      title="互动实操指南"
      @load="frameLoaded = true"
    ></iframe>
  </article>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Download } from '@element-plus/icons-vue'
import { resourceApi } from '../api'
import { isHtmlPreviewable, unwrapHtmlPreview } from '../utils/resourceRepresentations'
import guideStyles from './html-practice-guide.css?raw'
import runtimeSource from '../assets/html_practice_runtime.js?raw'

const props = defineProps({
  resource: { type: Object, required: true },
  progressLabel: { type: String, default: '' },
  resourceChoices: { type: Array, default: () => [] },
  selectedResourceId: { type: String, default: '' },
})

const emit = defineEmits(['progress-change', 'select-resource'])
const frameRef = ref(null)
const frameKey = ref(0)
const frameHeight = ref(680)
const frameLoaded = ref(false)
const loading = ref(false)
const errorMessage = ref('')
const srcdoc = ref('')
let requestGeneration = 0

const previewAllowed = computed(() => isHtmlPreviewable(props.resource))

const ALLOWED_TAGS = new Set([
  'ARTICLE', 'SECTION', 'DIV', 'HEADER', 'FOOTER', 'NAV', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
  'P', 'SPAN', 'STRONG', 'EM', 'B', 'I', 'SMALL', 'MARK', 'UL', 'OL', 'LI', 'DL', 'DT', 'DD',
  'PRE', 'CODE', 'BLOCKQUOTE', 'HR', 'BR', 'DETAILS', 'SUMMARY', 'LABEL', 'INPUT', 'BUTTON',
  'FIELDSET', 'LEGEND', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD',
])

function allowedAttribute(name) {
  return name === 'class'
    || name === 'id'
    || name === 'role'
    || name === 'type'
    || name === 'value'
    || name === 'name'
    || name === 'checked'
    || name === 'disabled'
    || name === 'for'
    || name === 'colspan'
    || name === 'rowspan'
    || name === 'tabindex'
    || name.startsWith('aria-')
    || name.startsWith('data-practice-')
    || name.startsWith('data-source-')
    || name === 'data-correct'
    || name === 'data-answer'
}

function sanitizeFragment(fragment) {
  const parser = new DOMParser()
  const documentFragment = parser.parseFromString(`<main>${fragment}</main>`, 'text/html')
  const container = documentFragment.body.firstElementChild
  if (!container) return ''
  for (const element of [...container.querySelectorAll('*')]) {
    if (!ALLOWED_TAGS.has(element.tagName)) {
      element.replaceWith(...element.childNodes)
      continue
    }
    for (const attribute of [...element.attributes]) {
      if (!allowedAttribute(attribute.name.toLowerCase())) element.removeAttribute(attribute.name)
    }
    if (element.tagName === 'INPUT' && !['checkbox', 'radio'].includes(element.type)) element.type = 'checkbox'
    if (element.tagName === 'BUTTON') element.type = 'button'
  }
  return container.innerHTML.trim()
}

function buildSrcdoc(fragment) {
  const safeFragment = sanitizeFragment(fragment)
  if (!safeFragment) throw new Error('互动内容为空')
  const safeRuntime = runtimeSource.replace(/<\/script/gi, '<\\/script')
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; font-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"><style>${guideStyles}</style></head><body><main class="html-practice-root">${safeFragment}</main><script>${safeRuntime}<\/script></body></html>`
}

async function loadPreview() {
  const resourceId = props.resource?.resource_id
  requestGeneration += 1
  const generation = requestGeneration
  srcdoc.value = ''
  errorMessage.value = ''
  frameLoaded.value = false
  if (!resourceId || !previewAllowed.value) return
  loading.value = true
  try {
    const response = await resourceApi.getPreview(resourceId)
    if (generation !== requestGeneration) return
    const preview = unwrapHtmlPreview(response.data)
    srcdoc.value = buildSrcdoc(preview.html_fragment)
    frameKey.value += 1
  } catch (error) {
    if (generation !== requestGeneration) return
    errorMessage.value = error?.response?.data?.detail || error?.response?.data?.message || error?.message || '请稍后重试'
  } finally {
    if (generation === requestGeneration) loading.value = false
  }
}

function onFrameMessage(event) {
  if (!frameRef.value || event.source !== frameRef.value.contentWindow || event.origin !== 'null') return
  const message = event.data
  if (!message || message.channel !== 'html-practice' || message.version !== 1 || typeof message.payload !== 'object') return
  if (message.type === 'height') {
    const height = Number(message.payload.height)
    if (Number.isFinite(height)) frameHeight.value = Math.min(1600, Math.max(420, height))
  } else if (message.type === 'progress') {
    const completed = Number(message.payload.completed)
    const total = Number(message.payload.total)
    if (Number.isInteger(completed) && Number.isInteger(total) && completed >= 0 && total >= completed) {
      emit('progress-change', { completed, total })
    }
  } else if (message.type !== 'ready' && message.type !== 'checklist-progress' && message.type !== 'quiz-result') {
    return
  }
}

function download() {
  window.open(resourceApi.downloadUrl(props.resource.resource_id), '_blank', 'noopener,noreferrer')
}

function selectResource(resourceId) {
  if (resourceId && resourceId !== props.selectedResourceId) emit('select-resource', resourceId)
}

watch(() => [props.resource?.resource_id, props.resource?.publication_status, props.resource?.review_status], loadPreview)
onMounted(() => {
  window.addEventListener('message', onFrameMessage)
  void loadPreview()
})
onBeforeUnmount(() => {
  requestGeneration += 1
  window.removeEventListener('message', onFrameMessage)
})
</script>

<style scoped>
.html-guide-card { overflow: hidden; border: 1px solid #dce6ef; border-radius: 10px; background: #fff; box-shadow: 0 14px 32px rgba(35, 62, 94, .06); }
.html-guide-header { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 18px; padding: 12px 24px; border-bottom: 1px solid #e4ebf3; background: #fbfdff; }
.html-guide-title, .html-guide-actions { display: flex; align-items: center; gap: 10px; }
.html-guide-title { display: grid; min-width: 0; flex: 1; grid-template-columns: 400px minmax(0,1fr); align-items: center; column-gap: 18px; }
.html-guide-context-title { display: flex; min-width: 0; align-items: center; gap: 10px; }
.html-guide-actions { flex: 0 0 auto; }
.learning-status { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 7px; color: #2f6e5f; font-size: 13px; font-weight: 800; }
.learning-status i { width: 7px; height: 7px; border-radius: 50%; background: #35ae94; box-shadow: 0 0 0 3px rgba(53, 174, 148, .14); }
.resource-kicker { overflow: hidden; min-width: 0; padding-left: 12px; border-left: 1px solid #d9e7e5; color: #2f6e5f; font-size: 15px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.header-resource-switcher { display: flex; min-width: 0; flex: 1; gap: 6px; margin-left: 4px; padding: 2px 0; overflow-x: auto; scrollbar-width: thin; }
.header-resource-choice { display: inline-flex; flex: 0 0 112px; align-items: center; gap: 6px; box-sizing: border-box; width: 112px; height: 30px; padding: 0 9px 0 5px; overflow: hidden; border: 1px solid #dce6ef; border-radius: 7px; background: #fff; color: #62758d; font-size: 12px; font-weight: 700; cursor: pointer; text-overflow: ellipsis; white-space: nowrap; transition: border-color .18s ease,background-color .18s ease,color .18s ease,box-shadow .18s ease; }
.header-resource-choice > span { display: grid; width: 20px; height: 20px; place-items: center; border-radius: 5px; background: #eef3f9; color: #71859d; font-size: 9px; font-weight: 800; }
.header-resource-choice:hover { border-color: #aac4da; background: #f8fbff; color: #285e8c; }
.header-resource-choice.is-active { border-color: #88beb4; background: #edf8f5; color: #226a60; box-shadow: 0 2px 6px rgba(38,116,103,.1); }
.header-resource-choice.is-active > span { background: #28796c; color: #fff; }
.learning-progress { color: #52728a; font-size: 12px; font-weight: 650; white-space: nowrap; }
.viewer-alert { margin: 22px; }
.viewer-loading { padding: 34px 40px; }
.practice-frame { display: block; width: 100%; min-height: 420px; border: 0; background: #fff; transition: height .18s ease; }
@media (max-width: 760px) {
  .html-guide-header { align-items: flex-start; padding: 11px 16px; }
  .html-guide-title { display: flex; gap: 8px; }
  .html-guide-context-title { gap: 8px; }
  .learning-status, .learning-progress, .html-guide-actions :deep(.el-tag) { display: none; }
  .resource-kicker { max-width: 142px; padding-left: 0; border-left: 0; font-size: 13px; }
  .header-resource-switcher { gap: 5px; margin-left: 0; }
  .header-resource-choice { height: 28px; padding-right: 7px; font-size: 11px; }
  .html-guide-actions :deep(.el-button) { padding: 7px 9px; }
}
@media (min-width: 761px) and (max-width: 1100px) { .html-guide-title { grid-template-columns: 310px minmax(0,1fr); column-gap: 12px; } }
</style>
