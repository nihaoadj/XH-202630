<template>
  <div>
    <el-card v-for="res in resources" :key="res.resource_id" style="margin-bottom: 20px;">
      <template #header>
        <span>{{ res.resource_type }}</span>
        <el-tag style="margin-left: 10px;" :type="difficultyType(res.difficulty)">{{ res.difficulty }}</el-tag>
      </template>
      <pre style="white-space: pre-wrap;">{{ resourceContent(res) }}</pre>
      <el-divider />
      <p><strong>覆盖知识点：</strong>{{ res.knowledge_points.join('、') }}</p>
      <p><strong>知识溯源：</strong></p>
      <ul>
        <li v-for="ref in res.source_refs" :key="ref.doc_id">
          {{ ref.title }}（相似度：{{ ref.score.toFixed(3) }}）
        </li>
      </ul>
    </el-card>
  </div>
</template>

<script setup>
defineProps({
  resources: {
    type: Array,
    default: () => [],
  },
})

function difficultyType(d) {
  if (d === '初级') return 'success'
  if (d === '中级') return 'warning'
  return 'danger'
}

function resourceContent(res) {
  return res.content_text || res.content || '暂无内容'
}
</script>
