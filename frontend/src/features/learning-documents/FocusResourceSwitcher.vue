<template>
  <nav v-if="resources.length > 1 || $slots.actions" class="focus-resource-switcher" :aria-label="resources.length > 1 ? '切换本次学习资源' : '本次学习操作'">
    <template v-if="resources.length > 1">
      <button
        v-for="(resource, index) in resources"
        :key="resource.resource_id"
        type="button"
        class="resource-item"
        :class="{ 'is-active': resource.resource_id === selectedResourceId }"
        :aria-pressed="resource.resource_id === selectedResourceId"
        :aria-label="`切换到第 ${index + 1} 份：${resourceShelfTypeLabel(resource)}`"
        @click="$emit('select-resource', resource.resource_id)"
      >
        <span class="resource-order">{{ String(index + 1).padStart(2, '0') }}</span>
        <span class="resource-item-copy" :title="resource.study_context_title">
          <strong>{{ resourceShelfTypeLabel(resource) }}<span class="resource-study-marker">{{ resource.study_marker }}</span></strong>
          <small>{{ resource.resource_kind === 'interactive_courseware' ? '互动课件' : resource.difficulty || '待分级' }}</small>
        </span>
        <span class="resource-arrow" aria-hidden="true">→</span>
      </button>
    </template>
    <slot name="actions" />
  </nav>
</template>

<script setup>
import { resourceShelfTypeLabel } from '../../utils/resourceShelfOrder'

defineProps({ resources: { type: Array, default: () => [] }, selectedResourceId: { type: String, default: '' } })
defineEmits(['select-resource'])
</script>
