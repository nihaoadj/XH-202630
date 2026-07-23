<template>
  <div>
    <h2>学习反馈</h2>
    <el-form :model="form" label-width="120px">
      <el-form-item label="学习者ID">
        <el-input v-model="form.learner_id" style="width: 320px;" />
        <el-button style="margin-left: 10px;" @click="loadResources">加载资源</el-button>
      </el-form-item>
      <el-form-item label="资源ID">
        <el-select
          v-model="form.resource_id"
          filterable
          allow-create
          default-first-option
          placeholder="选择或输入资源ID"
          style="width: 420px;"
        >
          <el-option
            v-for="item in resources"
            :key="item.resource_id"
            :label="`${item.resource_type} / ${item.difficulty} / ${item.resource_id}`"
            :value="item.resource_id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="答题正确率">
        <el-slider v-model="form.correct_rate" :max="1" :step="0.05" show-input />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSubmit" :loading="submitting">提交反馈</el-button>
        <el-button @click="loadHistory">查看反馈历史</el-button>
        <el-button @click="$router.push('/report')">查看报告</el-button>
      </el-form-item>
    </el-form>

    <el-alert v-if="message" :title="message" type="success" style="margin-bottom: 16px;" />

    <el-card v-if="updatedProfile" style="margin-bottom: 20px;">
      <template #header>更新后的画像</template>
      <p><strong>技能水平：</strong>{{ updatedProfile.skill_level }}</p>
      <p><strong>知识盲区：</strong>{{ (updatedProfile.weak_points || []).join('、') || '-' }}</p>
      <p><strong>学习目标：</strong>{{ updatedProfile.learning_goal }}</p>
    </el-card>

    <el-card>
      <template #header>反馈历史</template>
      <el-empty v-if="!history.length" description="暂无反馈记录" />
      <el-table v-else :data="history" style="width: 100%;">
        <el-table-column prop="resource_id" label="资源ID" min-width="220" />
        <el-table-column prop="correct_rate" label="正确率" width="120">
          <template #default="{ row }">{{ Math.round(row.correct_rate * 100) }}%</template>
        </el-table-column>
        <el-table-column prop="decision" label="决策" width="140" />
        <el-table-column prop="created_at" label="时间" min-width="180" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { feedbackApi, resourceApi } from '../api'

const form = reactive({
  learner_id: localStorage.getItem('last_learner_id') || 'stu_001',
  resource_id: localStorage.getItem('last_resource_id') || '',
  correct_rate: 0.6,
  answers: [],
})

const message = ref('')
const submitting = ref(false)
const resources = ref([])
const history = ref([])
const updatedProfile = ref(null)

async function onSubmit() {
  submitting.value = true
  try {
    const res = await feedbackApi.submit({ ...form })
    message.value = res.data.message
    updatedProfile.value = res.data.updated_profile
    ElMessage.success('反馈已提交')
    await loadHistory()
  } catch (e) {
    console.error(e)
    ElMessage.error(e?.response?.data?.message || '反馈提交失败')
  } finally {
    submitting.value = false
  }
}

async function loadResources() {
  try {
    const res = await resourceApi.listByLearner(form.learner_id)
    resources.value = res.data.resources || []
    if (!form.resource_id && resources.value.length) {
      form.resource_id = resources.value[0].resource_id
    }
  } catch (e) {
    console.error(e)
    ElMessage.warning('未能加载资源历史，请确认学习者已生成资源')
  }
}

async function loadHistory() {
  try {
    const res = await feedbackApi.history(form.learner_id)
    history.value = res.data.items || []
  } catch (e) {
    console.error(e)
    history.value = []
  }
}

onMounted(async () => {
  await loadResources()
  await loadHistory()
})
</script>
