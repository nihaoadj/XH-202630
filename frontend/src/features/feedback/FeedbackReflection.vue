<template>
      <aside class="reflection-panel">
        <div class="section-heading compact-heading">
          <div>
            <span class="page-kicker">02 / REFLECTION</span>
            <h2>记录学习感受</h2>
            <p>{{ active ? '这些反馈会跟随本次练习保存，为后续推荐提供依据。' : '记录你的体验，为后续推荐提供依据。' }}</p>
          </div>
          <span v-if="!active" class="progress-pill preparation-status">测评后记录</span>
        </div>

        <PreparationPanel
          v-if="!active"
          class="reflection-preparation"
          compact
          eyebrow="MAKE LEARNING YOURS"
          title="用一次复盘，找到下一轮的重点。"
          description="开始测评后，记录学习体验，让后续建议更贴近你。"
          :steps="[
            { title: '投入与节奏', description: '记录学习耗时与难度感受，找到适合自己的节奏。' },
            { title: '理解与掌握', description: '回顾本轮表现，记录自己的掌握程度。' },
            { title: '困惑与期待', description: '说明仍需解释的问题，以及下一轮想强化的重点。' },
          ]"
        >
          <template #mark><el-icon><ChatDotRound /></el-icon></template>
          <template #footer><el-icon aria-hidden="true"><CircleCheck /></el-icon><span>用体验反馈，完善后续学习建议。</span></template>
        </PreparationPanel>
        <fieldset v-else class="reflection-fields" :disabled="locked" style="border:0;margin:0;padding-inline:0">
          <div class="completion-row">
            <div><strong>本轮学习已完成</strong><span>完成后，系统会更新学习路径</span></div>
            <el-switch :disabled="locked" :model-value="modelValue.completed" @update:model-value="update('completed', $event)" />
          </div>
          <div class="field-grid">
            <label><span>学习耗时 <small>{{ studyTimeLabel }}</small></span><el-input-number :disabled="locked" :model-value="modelValue.time_spent_seconds" @update:model-value="update('time_spent_seconds', $event)" class="study-time-stepper" :min="0" :step="300" controls-position="right" /></label>
            <label><span>难度感受</span><el-select :disabled="locked" :model-value="modelValue.difficulty_feeling" @update:model-value="update('difficulty_feeling', $event)" placeholder="选择感受" popper-class="feedback-difficulty-dropdown"><el-option label="偏简单" value="too_easy" /><el-option label="刚刚好" value="fit" /><el-option label="偏难" value="too_hard" /></el-select></label>
          </div>
          <div class="rating-field">
            <span>掌握自评</span>
            <el-rate :disabled="locked" :model-value="modelValue.self_rating" @update:model-value="update('self_rating', $event)" aria-label="掌握自评" :max="5" show-score />
          </div>
          <label><span>仍然困惑的地方</span><el-input :disabled="locked" :model-value="modelValue.confusing_part" @update:model-value="update('confusing_part', $event)" placeholder="例如：术语、关键步骤或实际迁移" /></label>
          <label><span>补充反馈</span><el-input :disabled="locked" :model-value="modelValue.comment" @update:model-value="update('comment', $event)" type="textarea" :rows="3" placeholder="可以说明你期待下一轮更强化哪些内容，例如增加案例、练习或提高难度。" /></label>
        </fieldset>

        <slot />
      </aside>
</template>
<script setup>
import { computed } from 'vue'
import { ChatDotRound, CircleCheck } from '@element-plus/icons-vue'
import PreparationPanel from '../../components/PreparationPanel.vue'
const props = defineProps({ modelValue: { type: Object, required: true }, active: Boolean, locked: Boolean })
const emit = defineEmits(['update:modelValue'])
const studyTimeLabel = computed(() => `${Math.floor((props.modelValue.time_spent_seconds || 0) / 60)} 分钟`)
function update(key, value) { if (!props.locked) emit('update:modelValue', { ...props.modelValue, [key]: value }) }
</script>
