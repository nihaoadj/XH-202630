<template>
  <div class="user-bubble">
    <div class="user-message" aria-label="你的消息" role="group">
      <blockquote v-if="parts.quote">
        <span><Link aria-hidden="true" /> 引用材料</span>
        <p>{{ parts.quote }}</p>
      </blockquote>
      <p>{{ parts.question }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Link } from '@element-plus/icons-vue'

const props = defineProps({ text: { type: String, required: true } })

const parts = computed(() => {
  // Previously saved turns contain the same plain-text envelope as new turns.
  const match = /^引用材料：\r?\n“([\s\S]+?)”\r?\n\r?\n我的问题：\r?\n([\s\S]+)$/.exec(props.text)
  return match ? { quote: match[1], question: match[2] } : { quote: '', question: props.text }
})
</script>

<style scoped>
.user-bubble { display: flex; min-width: 0; justify-content: flex-end; padding-inline-start: 24px; }
.user-message {
  min-width: 0;
  max-width: 100%;
  padding: 10px 14px;
  border: 1px solid transparent;
  border-radius: 16px 16px 5px 16px;
  background:
    linear-gradient(145deg, #f5fafc, #e9f1f5) padding-box,
    var(--tutor-glass-edge) border-box;
  box-shadow: var(--tutor-glass-shadow);
  color: var(--tutor-ink);
  font-size: 14px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}
.user-message p { margin: 0; white-space: pre-wrap; }
.user-message blockquote {
  margin: 0 0 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgb(255 255 255 / 70%);
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 90%);
  color: var(--tutor-muted);
  font-size: 12px;
}
.user-message blockquote span { display: flex; align-items: center; gap: 5px; margin-bottom: 2px; color: var(--tutor-detail-ink); font-weight: 600; }
.user-message blockquote svg { width: 14px; height: 14px; fill: currentColor; stroke: none; }
@media (max-width: 560px) {
  .user-message { font-size: 15px; }
}
</style>
