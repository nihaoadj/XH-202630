<template>
  <div>
    <el-card v-for="res in resources" :key="res.resource_id" class="resource-card">
      <template #header>
        <div class="card-head">
          <div>
            <span>{{ res.resource_type }}</span>
            <el-tag style="margin-left: 10px;" :type="difficultyType(res.difficulty)">
              {{ res.difficulty }}
            </el-tag>
          </div>
          <el-button
            v-if="res.file_path"
            size="small"
            type="primary"
            plain
            @click="download(res.resource_id)"
          >
            下载
          </el-button>
        </div>
      </template>
      <div class="resource-content markdown-body" v-html="renderedContent(res)"></div>
      <el-divider />
      <p><strong>覆盖知识点：</strong>{{ (res.knowledge_points || []).join('、') || '-' }}</p>
      <p v-if="res.review_status"><strong>审核状态：</strong>{{ res.review_status }}</p>
      <p><strong>知识来源：</strong></p>
      <ul>
        <li v-for="ref in res.source_refs || []" :key="`${res.resource_id}-${ref.doc_id}-${ref.chunk_id || ''}`">
          {{ ref.title }}（相似度：{{ Number(ref.score || 0).toFixed(3) }}）
        </li>
      </ul>
    </el-card>
  </div>
</template>

<script setup>
import { resourceApi } from '../api'

defineProps({
  resources: {
    type: Array,
    default: () => [],
  },
})

function difficultyType(difficulty) {
  if (difficulty === '初级') return 'success'
  if (difficulty === '中级') return 'warning'
  return 'danger'
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

    if (!line.trim()) {
      index += 1
      continue
    }

    if (line.startsWith('```')) {
      const codeLines = []
      index += 1
      while (index < lines.length && !lines[index].startsWith('```')) {
        codeLines.push(lines[index])
        index += 1
      }
      if (index < lines.length) {
        index += 1
      }
      blocks.push(`<pre><code>${codeLines.join('\n')}</code></pre>`)
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      const level = heading[1].length
      blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`)
      index += 1
      continue
    }

    const listMatch = line.match(/^[-*]\s+(.*)$/)
    if (listMatch) {
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
      if (
        lines[index].startsWith('```') ||
        /^(#{1,6})\s+/.test(lines[index]) ||
        /^[-*]\s+/.test(lines[index])
      ) {
        break
      }
      paragraphLines.push(lines[index])
      index += 1
    }
    blocks.push(`<p>${renderInlineMarkdown(paragraphLines.join('<br />'))}</p>`)
  }

  return blocks.join('')
}

function renderedContent(resource) {
  return renderMarkdown(resourceContent(resource))
}

function download(resourceId) {
  window.open(resourceApi.downloadUrl(resourceId), '_blank')
}
</script>

<style scoped>
.resource-card {
  margin-bottom: 20px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.resource-content {
  line-height: 1.75;
  color: #1f2937;
}

.resource-content :deep(h1),
.resource-content :deep(h2),
.resource-content :deep(h3),
.resource-content :deep(h4),
.resource-content :deep(h5),
.resource-content :deep(h6) {
  margin: 0 0 12px;
  color: #111827;
}

.resource-content :deep(p),
.resource-content :deep(ul),
.resource-content :deep(pre) {
  margin: 0 0 12px;
}

.resource-content :deep(ul) {
  padding-left: 20px;
}

.resource-content :deep(code) {
  padding: 2px 6px;
  border-radius: 6px;
  background: #f3f4f6;
  font-family: Consolas, 'Courier New', monospace;
}

.resource-content :deep(pre) {
  padding: 14px;
  border-radius: 10px;
  background: #111827;
  color: #f9fafb;
  overflow-x: auto;
}

.resource-content :deep(pre code) {
  padding: 0;
  background: transparent;
  color: inherit;
}
</style>
