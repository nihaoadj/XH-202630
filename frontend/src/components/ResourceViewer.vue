<template>
  <article v-for="res in resources" :key="res.resource_id" class="reader-card">
    <header class="reader-header">
      <div class="reader-title-wrap">
        <span class="resource-kicker">{{ resourceKind(res.resource_type) }}</span>
        <h1>{{ res.title || res.resource_type || '学习资源' }}</h1>
        <p>{{ resourceIntroduction(res) }}</p>
      </div>
      <div class="reader-actions">
        <el-tag round effect="plain" :type="difficultyType(res.difficulty)">{{ res.difficulty || '待分级' }}</el-tag>
        <el-button v-if="res.file_path" class="download-button" type="primary" plain @click="download(res.resource_id)">下载材料</el-button>
      </div>
    </header>

    <section class="learning-brief">
      <div><span>学习重点</span><strong>{{ knowledgePointTitle(res) }}</strong></div>
      <div><span>知识点覆盖</span><strong>{{ (res.knowledge_points || []).length || 1 }} 个主题</strong></div>
      <div><span>材料类型</span><strong>{{ res.resource_type || '学习材料' }}</strong></div>
    </section>

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
          <ul>
            <li v-for="ref in res.source_refs" :key="`${res.resource_id}-${ref.doc_id}-${ref.chunk_id || ''}`">
              <strong>{{ ref.title || '知识库资料' }}</strong><span>相关度 {{ Number(ref.score || 0).toFixed(2) }}</span>
            </li>
          </ul>
        </el-collapse-item>
      </el-collapse>
    </footer>
  </article>
</template>

<script setup>
import { resourceApi } from '../api'

defineProps({ resources: { type: Array, default: () => [] } })

function difficultyType(difficulty) {
  if (difficulty === '初级') return 'success'
  if (difficulty === '中级') return 'warning'
  return 'danger'
}

function resourceKind(type) {
  return type ? `${type.toUpperCase()} · LEARNING MATERIAL` : 'LEARNING MATERIAL'
}

function resourceIntroduction(resource) {
  const points = resource.knowledge_points || []
  return points.length
    ? `围绕 ${points.slice(0, 2).join('、')} 等核心内容设计，帮助你将知识转化为可实践的能力。`
    : '为当前学习路径准备的专属学习材料，建议完成阅读后再继续下一份资源。'
}

function knowledgePointTitle(resource) {
  const points = resource.knowledge_points || []
  return points.length ? points.slice(0, 2).join('、') : '当前学习方向核心内容'
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
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
}

function renderMarkdown(text) {
  const escaped = escapeHtml(text).replace(/\r\n/g, '\n')
  const blocks = []
  const lines = escaped.split('\n')
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
    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) { const level = heading[1].length; blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`); index += 1; continue }
    if (line.match(/^[-*]\s+(.*)$/)) {
      const items = []
      while (index < lines.length) {
        const match = lines[index].match(/^[-*]\s+(.*)$/)
        if (!match) break
        items.push(`<li>${renderInlineMarkdown(match[1])}</li>`)
        index += 1
      }
      blocks.push(`<ul>${items.join('')}</ul>`)
      continue
    }
    const paragraphLines = []
    while (index < lines.length && lines[index].trim()) {
      if (lines[index].startsWith('```') || /^(#{1,6})\s+/.test(lines[index]) || /^[-*]\s+/.test(lines[index])) break
      paragraphLines.push(lines[index])
      index += 1
    }
    blocks.push(`<p>${renderInlineMarkdown(paragraphLines.join('<br />'))}</p>`)
  }
  return blocks.join('')
}

function renderedContent(resource) { return renderMarkdown(resourceContent(resource)) }
function download(resourceId) { window.open(resourceApi.downloadUrl(resourceId), '_blank') }
</script>

<style scoped>
.reader-card { overflow: hidden; border: 1px solid #dce6ef; border-radius: 20px; background: #fff; box-shadow: 0 14px 32px rgba(35,62,94,.06); }
.reader-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 26px; padding: 34px 40px 30px; background: radial-gradient(circle at 94% 12%, rgba(81,186,170,.14), transparent 26%), linear-gradient(180deg,#fbfdff,#f7fbff); border-bottom: 1px solid #e4ebf3; }.resource-kicker { color: #278174; font-size: 10px; font-weight: 800; letter-spacing: .1em; }.reader-title-wrap h1 { margin: 10px 0 0; color: #172d49; font-size: 28px; letter-spacing: -.025em; }.reader-title-wrap p { max-width: 720px; margin: 11px 0 0; color: #6e7e94; font-size: 14px; line-height: 1.75; }.reader-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 10px; }.reader-actions :deep(.el-tag) { height: 29px; padding: 0 11px; font-weight: 650; }.download-button { height: 34px; border-radius: 9px; }
.learning-brief { display: grid; grid-template-columns: 1.5fr repeat(2,1fr); margin: 0 40px; padding: 18px 0; border-bottom: 1px solid #e6edf4; }.learning-brief > div { display: flex; min-width: 0; flex-direction: column; gap: 6px; }.learning-brief > div + div { padding-left: 23px; border-left: 1px solid #e6edf4; }.learning-brief span { color: #7c8ca1; font-size: 11px; }.learning-brief strong { overflow: hidden; color: #29435f; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.reader-content { padding: 32px 40px 18px; }.content-label { display: flex; align-items: center; gap: 8px; margin-bottom: 19px; color: #245e99; font-size: 13px; font-weight: 750; }.content-label span { width: 4px; height: 16px; border-radius: 99px; background: linear-gradient(#2388cb,#2db79e); }.resource-content { color: #34475e; font-size: 15px; line-height: 1.9; }.resource-content :deep(h1), .resource-content :deep(h2), .resource-content :deep(h3), .resource-content :deep(h4), .resource-content :deep(h5), .resource-content :deep(h6) { margin: 30px 0 12px; color: #183756; line-height: 1.35; }.resource-content :deep(h1) { font-size: 25px; }.resource-content :deep(h2) { font-size: 21px; }.resource-content :deep(h3) { font-size: 18px; }.resource-content :deep(p), .resource-content :deep(ul), .resource-content :deep(pre) { margin: 0 0 16px; }.resource-content :deep(ul) { padding-left: 22px; }.resource-content :deep(li + li) { margin-top: 6px; }.resource-content :deep(code) { padding: 2px 6px; border-radius: 5px; background: #ecf3f8; color: #185e7b; font-family: Consolas,'Courier New',monospace; font-size: .9em; }.resource-content :deep(pre) { padding: 16px 18px; border-radius: 10px; background: #10253e; color: #e8f2fb; overflow-x: auto; }.resource-content :deep(pre code) { padding: 0; background: transparent; color: inherit; }
.reader-footer { padding: 20px 40px 25px; background: #fbfcfe; border-top: 1px solid #e8eef4; }.knowledge-tags { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }.knowledge-tags > span { margin-right: 3px; color: #75849a; font-size: 12px; }.knowledge-tags em { padding: 5px 9px; border-radius: 99px; background: #eaf4ff; color: #2f659d; font-size: 11px; font-style: normal; }.source-collapse { margin-top: 13px; border-top: 0; border-bottom: 0; }.source-collapse :deep(.el-collapse-item__header) { height: 32px; border-bottom: 0; background: transparent; color: #60748d; font-size: 12px; }.source-collapse :deep(.el-collapse-item__wrap) { border-bottom: 0; background: transparent; }.source-collapse :deep(.el-collapse-item__content) { padding-bottom: 0; }.source-collapse ul { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }.source-collapse li { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 8px 10px; border-radius: 7px; background: #f1f5f9; color: #53677e; font-size: 12px; }.source-collapse li strong { overflow: hidden; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.source-collapse li span { flex: 0 0 auto; color: #8190a2; font-size: 11px; }
@media (max-width: 760px) { .reader-header { flex-direction: column; padding: 26px 23px 23px; }.reader-title-wrap h1 { font-size: 23px; }.learning-brief { grid-template-columns: 1fr; gap: 14px; margin: 0 23px; }.learning-brief > div + div { padding-top: 14px; padding-left: 0; border-top: 1px solid #e6edf4; border-left: 0; }.reader-content, .reader-footer { padding-right: 23px; padding-left: 23px; } }
</style>
