<template>
  <div>
    <h2>学习反馈</h2>
    <el-form :model="form" label-width="120px">
      <el-form-item label="学习者ID">
        <el-input v-model="form.learner_id" />
      </el-form-item>
      <el-form-item label="资源ID">
        <el-input v-model="form.resource_id" />
      </el-form-item>
      <el-form-item label="答题正确率">
        <el-slider v-model="form.correct_rate" :max="1" :step="0.05" show-input />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSubmit">提交反馈</el-button>
      </el-form-item>
    </el-form>

    <el-alert v-if="message" :title="message" type="success" />
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { feedbackApi } from '../api'

const form = reactive({
  learner_id: 'stu_001',
  resource_id: 'res_001',
  correct_rate: 0.6,
  answers: [],
})

const message = ref('')

async function onSubmit() {
  const res = await feedbackApi.submit(form)
  message.value = res.data.message
}
</script>
