<template>
  <article v-for="res in resources" :key="res.resource_id" class="reader-card">
    <header class="reader-header">
      <div class="reader-title-wrap">
        <div class="reader-context-title">
          <span v-if="progressLabel" class="learning-status"><i></i>正在学习</span>
          <span class="resource-kicker">{{ resourceKind(res.resource_type) }}</span>
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
      <div class="reader-actions">
        <span v-if="progressLabel" class="learning-progress">{{ progressLabel }}</span>
        <el-tag round effect="plain" :type="difficultyType(res.difficulty)">{{ res.difficulty || '待分级' }}</el-tag>
        <el-button v-if="res.file_path" class="download-button" :icon="Download" @click="download(res.resource_id)">下载材料</el-button>
      </div>
    </header>

    <section class="reader-content">
      <div class="content-label"><span></span>学习内容</div>
      <div class="resource-content markdown-body" v-html="renderedContent(res)"></div>
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
import { Download } from '@element-plus/icons-vue'
import { resourceApi } from '../api'
import SourceRefList from './SourceRefList.vue'

const props = defineProps({
  resources: { type: Array, default: () => [] },
  progressLabel: { type: String, default: '' },
  resourceChoices: { type: Array, default: () => [] },
  selectedResourceId: { type: String, default: '' },
})
const emit = defineEmits(['select-resource'])

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
  }
  return type ? `${type} · ${labels[type] || 'LEARNING MATERIAL'}` : 'LEARNING MATERIAL'
}

function resourceContent(resource) {
  return resource.content_text || resource.content || '暂无内容'
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

function renderedContent(resource) { return renderMarkdown(resourceContent(resource)) }
function download(resourceId) { window.open(resourceApi.downloadUrl(resourceId), '_blank') }
function selectResource(resourceId) { if (resourceId && resourceId !== props.selectedResourceId) emit('select-resource', resourceId) }
</script>

<style scoped>
.reader-card { overflow: hidden; border: 1px solid #dce6ef; border-radius: 10px; background: #fff; box-shadow: 0 14px 32px rgba(35,62,94,.06); }
.reader-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; min-height: 58px; padding: 12px 24px; background: #fbfdff; border-bottom: 1px solid #e4ebf3; }.reader-title-wrap { display: grid; min-width: 0; flex: 1; grid-template-columns: 400px minmax(0,1fr); align-items: center; column-gap: 18px; }.reader-context-title { display: flex; min-width: 0; align-items: center; gap: 12px; }.learning-status { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 7px; color: #2f6e5f; font-size: 13px; font-weight: 800; }.learning-status i { width: 7px; height: 7px; border-radius: 50%; background: #35ae94; box-shadow: 0 0 0 3px rgba(53, 174, 148, .14); }.resource-kicker { overflow: hidden; min-width: 0; padding-left: 12px; border-left: 1px solid #d9e7e5; color: #2f6e5f; font-size: 16px; font-weight: 800; letter-spacing: 0; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }.header-resource-switcher { display: flex; min-width: 0; gap: 6px; padding: 2px 0; overflow-x: auto; scrollbar-width: thin; }.header-resource-choice { display: inline-flex; flex: 0 0 112px; align-items: center; gap: 6px; box-sizing: border-box; width: 112px; height: 30px; padding: 0 9px 0 5px; overflow: hidden; border: 1px solid #dce6ef; border-radius: 7px; background: #fff; color: #62758d; font-size: 12px; font-weight: 700; cursor: pointer; text-overflow: ellipsis; white-space: nowrap; transition: border-color .18s ease,background-color .18s ease,color .18s ease,box-shadow .18s ease; }.header-resource-choice > span { display: grid; width: 20px; height: 20px; place-items: center; border-radius: 5px; background: #eef3f9; color: #71859d; font-size: 9px; font-weight: 800; }.header-resource-choice:hover { border-color: #aac4da; background: #f8fbff; color: #285e8c; }.header-resource-choice.is-active { border-color: #88beb4; background: #edf8f5; color: #226a60; box-shadow: 0 2px 6px rgba(38,116,103,.1); }.header-resource-choice.is-active > span { background: #28796c; color: #fff; }.reader-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; }.learning-progress { color: #52728a; font-size: 12px; font-weight: 650; white-space: nowrap; }.reader-actions :deep(.el-tag) { height: 28px; padding: 0 10px; font-weight: 650; }.download-button { height: 32px; padding: 0 12px; border-color: #9fc5ec; border-radius: 8px; background: #eff7ff; color: #2467b3; font-weight: 700; }.download-button:hover, .download-button:focus-visible { border-color: #2467b3; background: #2467b3; color: #fff; }
.reader-content { padding: 32px 40px 18px; }.content-label { display: flex; align-items: center; gap: 8px; margin-bottom: 19px; color: #2f6e5f; font-size: 13px; font-weight: 800; }.content-label span { width: 4px; height: 16px; border-radius: 99px; background: #2f6e5f; }.resource-content { color: #34475e; font-size: 15px; line-height: 1.9; }.resource-content :deep(h1), .resource-content :deep(h2), .resource-content :deep(h3), .resource-content :deep(h4), .resource-content :deep(h5), .resource-content :deep(h6) { margin: 30px 0 12px; color: #172033; line-height: 1.35; }.resource-content :deep(h1) { font-size: 25px; }.resource-content :deep(h2) { font-size: 21px; }.resource-content :deep(h3) { font-size: 18px; }.resource-content :deep(p), .resource-content :deep(ul), .resource-content :deep(ol), .resource-content :deep(pre), .resource-content :deep(blockquote), .resource-content :deep(table) { margin: 0 0 16px; }.resource-content :deep(ul), .resource-content :deep(ol) { padding-left: 22px; }.resource-content :deep(li + li) { margin-top: 6px; }.resource-content :deep(blockquote) { padding: 10px 16px; border-left: 4px solid #8bc8bd; border-radius: 0 8px 8px 0; background: #f2fbf8; color: #466778; }.resource-content :deep(blockquote p) { margin: 0; }.resource-content :deep(hr) { height: 1px; margin: 24px 0; border: 0; background: #dce6ef; }.resource-content :deep(table) { width: 100%; border-collapse: collapse; overflow: hidden; border: 1px solid #d9e5ed; border-radius: 8px; }.resource-content :deep(th), .resource-content :deep(td) { padding: 9px 12px; border: 1px solid #d9e5ed; text-align: left; vertical-align: top; }.resource-content :deep(th) { background: #f1f7fb; color: #254c66; font-weight: 750; }.resource-content :deep(code) { padding: 2px 6px; border-radius: 5px; background: #ecf3f8; color: #185e7b; font-family: Consolas,'Courier New',monospace; font-size: .9em; }.resource-content :deep(pre) { padding: 16px 18px; border-radius: 10px; background: #10253e; color: #e8f2fb; overflow-x: auto; }.resource-content :deep(pre code) { padding: 0; background: transparent; color: inherit; }
.reader-footer { padding: 20px 40px 25px; background: #fbfcfe; border-top: 1px solid #e8eef4; }.knowledge-tags { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }.knowledge-tags > span { margin-right: 3px; color: #75849a; font-size: 12px; }.knowledge-tags em { padding: 5px 9px; border-radius: 99px; background: #eaf4ff; color: #2f659d; font-size: 11px; font-style: normal; }.source-collapse { margin-top: 13px; border-top: 0; border-bottom: 0; }.source-collapse :deep(.el-collapse-item__header) { height: 32px; border-bottom: 0; background: transparent; color: #60748d; font-size: 12px; }.source-collapse :deep(.el-collapse-item__wrap) { border-bottom: 0; background: transparent; }.source-collapse :deep(.el-collapse-item__content) { padding-bottom: 0; }.source-collapse ul { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }.source-collapse li { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 8px 10px; border-radius: 7px; background: #f1f5f9; color: #53677e; font-size: 12px; }.source-collapse li strong { overflow: hidden; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.source-collapse li span { flex: 0 0 auto; color: #8190a2; font-size: 11px; }
@media (max-width: 1100px) { .reader-title-wrap { grid-template-columns: 310px minmax(0,1fr); column-gap: 12px; } } @media (max-width: 760px) { .reader-header { gap: 10px; min-height: 54px; padding: 11px 16px; }.reader-title-wrap { display: flex; gap: 8px; }.reader-context-title { gap: 8px; }.learning-status { font-size: 12px; }.resource-kicker { max-width: 148px; padding-left: 8px; font-size: 14px; }.header-resource-switcher { gap: 5px; }.header-resource-choice { height: 28px; padding-right: 7px; font-size: 11px; }.learning-progress, .reader-actions :deep(.el-tag) { display: none; }.reader-content, .reader-footer { padding-right: 23px; padding-left: 23px; } }
</style>
