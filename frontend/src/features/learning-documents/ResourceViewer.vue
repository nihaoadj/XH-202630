<template>
  <article v-for="res in resources" :key="res.resource_id" class="reader-card">
    <header class="reader-header">
      <div class="reader-title-wrap">
        <div class="reader-context-title">
          <span v-if="progressLabel" class="learning-status"><i></i>正在学习</span>
          <span class="resource-kicker">{{ resourceKind(res.resource_type) }}</span>
        </div>
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
          <span class="header-choice-order">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="header-choice-copy">
            <strong>{{ choice.resource_type || '学习资源' }}</strong>
            <small>{{ choice.difficulty || '待分级' }}</small>
          </span>
          <span class="header-choice-arrow">→</span>
        </button>
      </div>
      <div class="reader-actions">
        <span v-if="progressLabel" class="learning-progress">{{ progressLabel }}</span>
        <slot name="header-actions" :resource="res" />
        <el-tag round effect="plain" :type="difficultyType(res.difficulty)">{{ res.difficulty || '待分级' }}</el-tag>
        <el-button v-if="res.file_path" class="download-button" :icon="Download" @click="download(res.resource_id)">下载材料</el-button>
        <slot name="header-end-actions" :resource="res" />
      </div>
    </header>

    <section class="reader-content">
      <div class="content-label"><span></span>学习内容</div>
      <div
        class="resource-content markdown-body"
        v-html="renderedContent(res)"
        @mouseup="captureSelectedText"
        @keyup="captureSelectedText"
      ></div>
      <button
        v-if="selectedText"
        type="button"
        class="selection-question-popover"
        :style="selectionActionStyle"
        @mousedown.prevent
        @click="askTutorAboutSelection"
      >就这段向 Tutor 提问</button>
    </section>

    <footer class="reader-footer">
      <div v-if="(res.knowledge_points || []).length" class="knowledge-tags">
        <span>关联知识点</span>
        <em v-for="point in res.knowledge_points" :key="point">{{ point }}</em>
      </div>
      <el-collapse v-if="(res.source_refs || []).length" class="source-collapse">
        <el-collapse-item name="sources">
          <template #title><span>参考来源（{{ res.source_refs.length }}）</span></template>
          <SourceRefList :refs="res.source_refs" />
        </el-collapse-item>
      </el-collapse>
    </footer>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Download } from '@element-plus/icons-vue'
import { resourceApi } from '../../api'
import SourceRefList from './SourceRefList.vue'

const props = defineProps({
  resources: { type: Array, default: () => [] },
  progressLabel: { type: String, default: '' },
  resourceChoices: { type: Array, default: () => [] },
  selectedResourceId: { type: String, default: '' },
})
const emit = defineEmits(['select-resource', 'ask-tutor'])
const selectedText = ref('')
const selectionActionPosition = ref({ top: 0, left: 0 })
const maximumSelectionLength = 1500
const selectionActionStyle = computed(() => ({
  top: `${selectionActionPosition.value.top}px`,
  left: `${selectionActionPosition.value.left}px`,
}))

function difficultyType(difficulty) {
  if (difficulty === '初级') return 'success'
  if (difficulty === '中级') return 'warning'
  return 'danger'
}

function resourceKind(type) {
  const labels = {
    '讲义': 'LECTURE',
    '实操指南': 'PRACTICAL GUIDE',
    '分阶测试题': 'PROGRESSIVE ASSESSMENT',
    '复习清单': 'REVIEW CHECKLIST',
    '案例分析': 'CASE STUDY',
    '个性化纠错训练包': 'PERSONALIZED REMEDIATION',
  }
  return type ? `${type} · ${labels[type] || 'LEARNING MATERIAL'}` : 'LEARNING MATERIAL'
}

function resourceContent(resource) {
  return resource.content_text || resource.content || '暂无内容'
}

function learnerFacingReviewChecklist(resource, content) {
  if (resource?.resource_type !== '复习清单') return String(content)
  let readable = String(content)
  // Older records may still carry trace IDs in Markdown. Keep those IDs in
  // the stored structured payload for audits, but never show them to learners.
  readable = readable
    .replace(/^(#{3,4})\s+q-(\d+)\s*$/gmi, (_, hashes, number) => `${hashes} 题目 ${Number(number)}`)
    .replace(/^(小结证据|证据)：.*$/gmi, (_, label) => `${label === '小结证据' ? '小结依据' : '证据依据'}：已完成来源核验。`)

  if (!readable.includes('节点知识小结')) {
    const blocks = resource.review_practice_payload?.node_blocks
    const summaries = Array.isArray(blocks)
      ? blocks.map((block) => String(block?.knowledge_summary || '').trim()).filter(Boolean)
      : []
    if (summaries.length) {
      const summary = summaries.map((item, index) => `### 节点${index + 1}知识小结\n\n${item}\n\n小结依据：已完成来源核验。`).join('\n\n')
      const marker = '## 答案与证据解释'
      readable = readable.includes(marker)
        ? readable.replace(marker, `${summary}\n\n${marker}`)
        : `${readable.trimEnd()}\n\n${summary}`
    }
  }
  return readable
}

function resourceTitle(resource) {
  const type = String(resource?.resource_type || '学习资源').trim()
  const knowledgePoints = [...new Set((resource?.knowledge_points || [])
    .map((point) => String(point || '').trim())
    .filter(Boolean))]
  return knowledgePoints.length ? `${type} · ${knowledgePoints.join('、')}` : type
}

function contentWithResourceTitle(resource) {
  const content = learnerFacingReviewChecklist(resource, resourceContent(resource))
  // The batch topic can describe every generated artifact and is not a useful
  // document title.  Always use the resource identity plus its covered nodes,
  // even for historical content that has no model-provided H1.
  const body = String(content).replace(/^\s*#\s+.*(?:\r?\n|$)/, '').trimStart()
  return `# ${resourceTitle(resource)}\n\n${body}`
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInlineMarkdown(text) {
  return text
    .replace(/\\([\\`*_{}\[\]()#+.!-])/g, '$1')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
}

function normalizeMarkdown(text) {
  return String(text)
    .replace(/\r\n/g, '\n')
    // Some LLM responses escape Markdown block markers.  These escapes make
    // valid block syntax render as literal text, so only remove them at line
    // starts where they cannot represent prose.
    .replace(/^(\s*)\\(?=[>|])/gm, '$1')
    .replace(/^(\s*)\\(?=---+\s*$)/gm, '$1')
    .replace(/^(\s*\d+)\\\.(?=\s)/gm, '$1.')
    .replace(/^(\s*)\\([-*])(?=\s)/gm, '$1$2')
    .replace(/(?<=\|)\\(?=\n|$)/g, '')
    .replace(/^\s*\\?<!--\s*(?:section|step|code|checklist|quiz):[a-z][a-z0-9-]{1,63}\s*-->\s*$/gmi, '')
}

function renderMarkdown(text) {
  const normalized = normalizeMarkdown(text)
  const lines = escapeHtml(normalized).split('\n')
  const blocks = []
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) { index += 1; continue }
    if (line.startsWith('```')) {
      const codeLines = []
      index += 1
      while (index < lines.length && !lines[index].startsWith('```')) { codeLines.push(lines[index]); index += 1 }
      if (index < lines.length) index += 1
      blocks.push(`<pre><code>${codeLines.join('\n')}</code></pre>`)
      continue
    }
    if (/^---+\s*$/.test(line)) { blocks.push('<hr />'); index += 1; continue }
    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) { blocks.push(`<h${heading[1].length}>${renderInlineMarkdown(heading[2])}</h${heading[1].length}>`); index += 1; continue }
    if (line.startsWith('&gt;')) {
      const quote = []
      while (index < lines.length && lines[index].startsWith('&gt;')) {
        quote.push(lines[index].replace(/^&gt;\s?/, ''))
        index += 1
      }
      blocks.push(`<blockquote><p>${renderInlineMarkdown(quote.join('<br />'))}</p></blockquote>`)
      continue
    }
    if (line.startsWith('|') && index + 1 < lines.length && /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(lines[index + 1])) {
      const cells = value => value.trim().replace(/^\||\|$/g, '').split('|').map(cell => renderInlineMarkdown(cell.trim()))
      const headers = cells(line)
      index += 2
      const rows = []
      while (index < lines.length && lines[index].startsWith('|')) { rows.push(cells(lines[index])); index += 1 }
      const headerHtml = headers.map(cell => `<th>${cell}</th>`).join('')
      const rowsHtml = rows.map(row => `<tr>${headers.map((_, cellIndex) => `<td>${row[cellIndex] || ''}</td>`).join('')}</tr>`).join('')
      blocks.push(`<table><thead><tr>${headerHtml}</tr></thead><tbody>${rowsHtml}</tbody></table>`)
      continue
    }
    const listMatch = line.match(/^([-*]|\d+\.)\s+(.*)$/)
    if (listMatch) {
      const ordered = /^\d+\.$/.test(listMatch[1])
      const matcher = ordered ? /^\d+\.\s+(.*)$/ : /^[-*]\s+(.*)$/
      const items = []
      while (index < lines.length) {
        const item = lines[index].match(matcher)
        if (!item) break
        items.push(`<li>${renderInlineMarkdown(item[1])}</li>`)
        index += 1
      }
      blocks.push(`<${ordered ? 'ol' : 'ul'}>${items.join('')}</${ordered ? 'ol' : 'ul'}>`)
      continue
    }
    const paragraph = []
    while (index < lines.length && lines[index].trim()) {
      if (
        lines[index].startsWith('```') ||
        /^(#{1,6})\s+/.test(lines[index]) ||
        /^([-*]|\d+\.)\s+/.test(lines[index]) ||
        lines[index].startsWith('&gt;') ||
        /^---+\s*$/.test(lines[index]) ||
        (lines[index].startsWith('|') && index + 1 < lines.length && /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(lines[index + 1]))
      ) break
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(`<p>${renderInlineMarkdown(paragraph.join('<br />'))}</p>`)
  }
  return blocks.join('')
}

function renderedContent(resource) { return renderMarkdown(contentWithResourceTitle(resource)) }
function download(resourceId) { window.open(resourceApi.downloadUrl(resourceId), '_blank') }
function selectResource(resourceId) { if (resourceId && resourceId !== props.selectedResourceId) emit('select-resource', resourceId) }
function captureSelectedText(event) {
  const selection = window.getSelection?.()
  const content = event.currentTarget
  const isInsideContent = (node) => content?.contains(node?.nodeType === Node.TEXT_NODE ? node.parentNode : node)
  if (!selection?.rangeCount || selection.isCollapsed || !isInsideContent(selection.anchorNode) || !isInsideContent(selection.focusNode)) {
    selectedText.value = ''
    return
  }
  const text = selection.toString().replace(/\s+/g, ' ').trim()
  selectedText.value = text.slice(0, maximumSelectionLength)
  if (selectedText.value) {
    const rect = selection.getRangeAt(0).getBoundingClientRect()
    selectionActionPosition.value = {
      top: Math.min(rect.bottom + 8, window.innerHeight - 44),
      left: Math.max(8, Math.min(rect.left, window.innerWidth - 190)),
    }
  }
}
function askTutorAboutSelection() {
  if (!selectedText.value) return
  emit('ask-tutor', selectedText.value)
  selectedText.value = ''
  window.getSelection?.()?.removeAllRanges()
}
</script>

<style scoped>
.reader-card { overflow: hidden; border: 1px solid #dce6ef; border-radius: 10px; background: #fff; box-shadow: 0 14px 32px rgba(35,62,94,.06); }
.reader-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; min-height: 58px; padding: 12px 24px; background: #fbfdff; border-bottom: 1px solid #e4ebf3; }.reader-title-wrap { display: flex; min-width: 0; align-items: center; gap: 12px; }.learning-status { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 7px; color: #2058a7; font-size: 13px; font-weight: 800; }.learning-status i { width: 7px; height: 7px; border-radius: 50%; background: #4a90ff; box-shadow: 0 0 0 3px rgba(53, 174, 148, .14); }.resource-kicker { overflow: hidden; padding-left: 12px; border-left: 1px solid #d9e7e5; color: #2058a7; font-size: 16px; font-weight: 800; letter-spacing: 0; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }.reader-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; }.learning-progress { color: #52728a; font-size: 12px; font-weight: 650; white-space: nowrap; }.reader-actions :deep(.el-tag) { height: 28px; padding: 0 10px; font-weight: 650; }.download-button { height: 32px; padding: 0 12px; border-color: #9fc5ec; border-radius: 8px; background: #eff7ff; color: #2467b3; font-weight: 700; }.download-button:hover, .download-button:focus-visible { border-color: #2467b3; background: #2467b3; color: #fff; }
.reader-content { padding: 32px 40px 18px; }.content-label { display: flex; align-items: center; gap: 8px; margin-bottom: 19px; color: #2058a7; font-size: 13px; font-weight: 800; }.content-label span { width: 4px; height: 16px; border-radius: 99px; background: #2058a7; }.resource-content { color: #34475e; font-size: 15px; line-height: 1.9; }.resource-content :deep(h1), .resource-content :deep(h2), .resource-content :deep(h3), .resource-content :deep(h4), .resource-content :deep(h5), .resource-content :deep(h6) { margin: 30px 0 12px; color: #172033; line-height: 1.35; }.resource-content :deep(h1) { font-size: 25px; }.resource-content :deep(h2) { font-size: 21px; }.resource-content :deep(h3) { font-size: 18px; }.resource-content :deep(p), .resource-content :deep(ul), .resource-content :deep(pre) { margin: 0 0 16px; }.resource-content :deep(ul) { padding-left: 22px; }.resource-content :deep(li + li) { margin-top: 6px; }.resource-content :deep(code) { padding: 2px 6px; border-radius: 5px; background: #ecf3f8; color: #185e7b; font-family: Consolas,'Courier New',monospace; font-size: .9em; }.resource-content :deep(pre) { padding: 16px 18px; border-radius: 10px; background: #10253e; color: #e8f2fb; overflow-x: auto; }.resource-content :deep(pre code) { padding: 0; background: transparent; color: inherit; }
.selection-question-popover { position:fixed; z-index:45; padding:8px 11px; border:1px solid #197f73; border-radius:8px; background:#218f81; box-shadow:0 8px 19px rgba(25,118,106,.24); color:#fff; font-size:12px; font-weight:750; cursor:pointer; }.selection-question-popover:hover,.selection-question-popover:focus-visible { border-color:#13695f; background:#176f65; }
.reader-footer { padding: 20px 40px 25px; background: #fbfcfe; border-top: 1px solid #e8eef4; }.knowledge-tags { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }.knowledge-tags > span { margin-right: 3px; color: #75849a; font-size: 12px; }.knowledge-tags em { padding: 5px 9px; border-radius: 99px; background: #eaf4ff; color: #2f659d; font-size: 11px; font-style: normal; }.source-collapse { margin-top: 13px; border-top: 0; border-bottom: 0; }.source-collapse :deep(.el-collapse-item__header) { height: 32px; border-bottom: 0; background: transparent; color: #60748d; font-size: 12px; }.source-collapse :deep(.el-collapse-item__wrap) { border-bottom: 0; background: transparent; }.source-collapse :deep(.el-collapse-item__content) { padding-bottom: 0; }.source-collapse ul { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }.source-collapse li { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 8px 10px; border-radius: 7px; background: #f1f5f9; color: #53677e; font-size: 12px; }.source-collapse li strong { overflow: hidden; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.source-collapse li span { flex: 0 0 auto; color: #8190a2; font-size: 11px; }
.reader-header {
  display: grid;
  grid-template-columns: 440px minmax(0, 1fr) max-content;
  justify-content: initial;
}

.reader-title-wrap {
  min-width: 0;
}

.reader-actions {
  grid-column: 3;
  justify-self: end;
}

.header-resource-switcher {
  display: flex;
  min-width: 0;
  gap: 8px;
  overflow-x: auto;
  scrollbar-width: none;
}

.header-resource-switcher::-webkit-scrollbar {
  display: none;
}

.header-resource-choice {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) 14px;
  flex: 0 0 184px;
  min-width: 0;
  min-height: 50px;
  gap: 9px;
  align-items: center;
  padding: 7px 9px;
  border: 1px solid #d9e1ec;
  border-radius: 9px;
  background: #fff;
  color: #344963;
  cursor: pointer;
  text-align: left;
  transition: border-color .18s ease, background-color .18s ease, box-shadow .18s ease;
}

.header-resource-choice:hover {
  background: #f4f8fd;
}

.header-resource-choice.is-active {
  border-color: #6da3ff;
  background: linear-gradient(100deg, #eaf4ff, #f5f9ff);
  box-shadow: 0 5px 12px rgba(53, 110, 157, .11);
}

.header-choice-order {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 8px;
  background: #eff4fa;
  color: #71839b;
  font-size: 10px;
  font-weight: 800;
}

.header-resource-choice.is-active .header-choice-order {
  background: #1e6ed2;
  color: #fff;
}

.header-choice-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.header-choice-copy strong,
.header-choice-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-choice-copy strong {
  color: #203853;
  font-size: 13px;
}

.header-choice-copy small {
  color: #77889d;
  font-size: 10px;
}

.header-choice-arrow {
  color: #91a1b6;
  font-size: 14px;
}

.header-resource-choice.is-active .header-choice-arrow {
  color: #2058a7;
}

@media (max-width: 1100px) {
  .reader-header { grid-template-columns: minmax(0, 1fr) max-content; }
  .reader-actions { grid-column: 2; }
  .header-resource-switcher { grid-column: 1 / -1; grid-row: 2; }
}

@media (max-width: 760px) {
  .reader-header { gap: 10px; min-height: 54px; padding: 11px 16px; }
  .reader-title-wrap { display: flex; gap: 8px; }
  .reader-context-title { gap: 8px; }
  .learning-status { font-size: 12px; }
  .resource-kicker { max-width: 148px; padding-left: 8px; font-size: 14px; }
  .header-resource-switcher { gap: 5px; }
  .header-resource-choice { flex-basis: 158px; min-height: 46px; }
  .learning-progress, .reader-actions :deep(.el-tag) { display: none; }
  .reader-content, .reader-footer { padding-right: 23px; padding-left: 23px; }
}
</style>
