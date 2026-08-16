<template>
  <div class="user-profile-page">
    <section class="header-band">
      <div>
        <h2>用户资料</h2>
        <p>这些信息会在新建学习方向时复用，可按需补充。</p>
      </div>
      <el-button @click="$router.push('/learning/new')">去新建学习方向</el-button>
    </section>

    <el-card class="profile-card">
      <template #header>
        <div class="card-head">
          <span>基础信息</span>
          <el-tag effect="plain">当前账号</el-tag>
        </div>
      </template>

      <el-form :model="form" label-position="top">
        <el-form-item label="用户名">
          <el-input :model-value="auth.currentUser?.username" disabled />
        </el-form-item>

        <div class="form-grid">
          <el-form-item label="身份">
            <el-input v-model="form.identity" maxlength="64" placeholder="例如 在校学生" />
          </el-form-item>
          <el-form-item label="学历">
            <el-input v-model="form.education" maxlength="64" placeholder="例如 本科" />
          </el-form-item>
          <el-form-item label="专业">
            <el-input v-model="form.major" maxlength="128" placeholder="例如 软件工程" />
          </el-form-item>
          <el-form-item label="岗位 / 背景">
            <el-input v-model="form.job_role" maxlength="128" placeholder="例如 算法工程师" />
          </el-form-item>
          <el-form-item label="经验年限">
            <el-input-number v-model="form.experience_years" :min="0" :max="50" />
          </el-form-item>
        </div>

        <div class="action-row">
          <el-button type="primary" :loading="saving" @click="saveProfile">保存资料</el-button>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { userApi } from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const saving = ref(false)
const form = reactive({
  identity: '',
  education: '',
  major: '',
  job_role: '',
  experience_years: null,
})

function fillForm(user) {
  form.identity = user?.identity === '其他' ? '' : (user?.identity || '')
  form.education = user?.education === '未填写' ? '' : (user?.education || '')
  form.major = user?.major === '未填写' ? '' : (user?.major || '')
  form.job_role = user?.job_role || ''
  form.experience_years = user?.experience_years ?? null
}

async function saveProfile() {
  if (!auth.currentUser?.user_id) return
  saving.value = true
  try {
    const response = await userApi.update(auth.currentUser.user_id, {
      identity: form.identity || '其他',
      education: form.education || '未填写',
      major: form.major || '未填写',
      job_role: form.job_role || null,
      experience_years: form.experience_years,
    })
    auth.setCurrentUser(response.data)
    fillForm(response.data)
    ElMessage.success('用户资料已保存')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '用户资料保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => fillForm(auth.currentUser))
</script>

<style scoped>
.user-profile-page {
  max-width: 960px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.header-band {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: #ffffff;
}

.header-band h2 {
  margin: 0;
}

.header-band p {
  margin: 8px 0 0;
  color: #667085;
}

.profile-card {
  border-radius: 8px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 18px;
}

.action-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

@media (max-width: 720px) {
  .header-band {
    flex-direction: column;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
