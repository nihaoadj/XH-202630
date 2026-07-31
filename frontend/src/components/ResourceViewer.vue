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
      <pre class="resource-content">{{ resourceContent(res) }}</pre>
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
  white-space: pre-wrap;
}
</style>
