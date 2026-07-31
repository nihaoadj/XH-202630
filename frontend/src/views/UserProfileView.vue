<template>
  <div class="user-profile-page">
    <section class="header-card">
      <div>
        <h2>用户基础资料</h2>
        <p>身份、学历、专业、岗位等固定信息在这里维护，后续新建学习方向时直接复用。</p>
      </div>
      <el-button v-if="store.currentUserId" @click="$router.push('/learning/new')">去新建学习方向</el-button>
    </section>

    <section class="layout">
      <el-card class="list-card">
        <template #header>
          <div class="card-head">
            <span>已有用户</span>
            <el-button text @click="loadUsers">刷新</el-button>
          </div>
        </template>

        <el-empty v-if="!users.length" description="还没有用户资料" />
        <button
          v-for="user in users"
          :key="user.user_id"
          type="button"
          class="user-item"
          :class="{ active: activeUserId === user.user_id }"
          @click="selectUser(user)"
        >
          <strong>{{ user.display_name }}</strong>
          <span>{{ user.identity }}</span>
          <span>{{ user.education }} / {{ user.major }}<span v-if="user.job_role"> / {{ user.job_role }}</span></span>
        </button>
      </el-card>

      <el-card class="form-card">
        <template #header>
          <div class="card-head">
            <span>{{ isEditing ? '编辑用户资料' : '新建用户资料' }}</span>
            <el-button text @click="resetForm">新建空白</el-button>
          </div>
        </template>

        <el-form :model="form" label-position="top">
          <el-form-item label="显示名称" required>
            <el-input v-model="form.display_name" placeholder="例如 张三" />
          </el-form-item>
          <el-form-item label="身份" required>
            <el-input v-model="form.identity" placeholder="例如 在校学生 / 职场工程师 / 转行学习者" />
          </el-form-item>
          <el-form-item label="学历" required>
            <el-input v-model="form.education" placeholder="例如 本科" />
          </el-form-item>
          <el-form-item label="专业" required>
            <el-input v-model="form.major" placeholder="例如 软件工程" />
          </el-form-item>
          <el-form-item label="岗位 / 背景">
            <el-input v-model="form.job_role" placeholder="例如 算法工程师" />
          </el-form-item>
          <el-form-item label="经验年限">
            <el-input-number v-model="form.experience_years" :min="0" :max="50" />
          </el-form-item>

          <div class="action-row">
            <el-button @click="useAsCurrent" :disabled="!activeUserId">设为当前用户</el-button>
            <el-button type="primary" :loading="saving" @click="saveUser">
              {{ isEditing ? '保存修改' : '创建用户' }}
            </el-button>
          </div>
        </el-form>
      </el-card>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { userApi } from '../api'
import { useAppStore } from '../stores/app'

const store = useAppStore()
const users = ref([])
const saving = ref(false)
const isEditing = ref(false)
const activeUserId = ref('')

const form = reactive({
  display_name: '',
  identity: '',
  education: '',
  major: '',
  job_role: '',
  experience_years: null,
})

function resetForm() {
  form.display_name = ''
  form.identity = ''
  form.education = ''
  form.major = ''
  form.job_role = ''
  form.experience_years = null
  activeUserId.value = ''
  isEditing.value = false
}

function selectUser(user) {
  activeUserId.value = user.user_id
  form.display_name = user.display_name
  form.identity = user.identity || ''
  form.education = user.education
  form.major = user.major
  form.job_role = user.job_role || ''
  form.experience_years = user.experience_years ?? null
  isEditing.value = true
}

function useAsCurrent() {
  const selected = users.value.find((item) => item.user_id === activeUserId.value)
  if (!selected) return
  store.setCurrentUserProfile(selected)
  ElMessage.success('已设为当前用户')
}

async function loadUsers() {
  try {
    const res = await userApi.list()
    users.value = res.data.items || []
  } catch (error) {
    console.error(error)
    ElMessage.error('用户资料加载失败')
  }
}

async function saveUser() {
  if (!form.display_name || !form.identity || !form.education || !form.major) {
    ElMessage.warning('请先填写完整的用户信息')
    return
  }

  saving.value = true
  try {
    const payload = {
      display_name: form.display_name,
      identity: form.identity,
      education: form.education,
      major: form.major,
      job_role: form.job_role || null,
      experience_years: form.experience_years,
      metadata: {},
    }

    let res
    if (isEditing.value) {
      res = await userApi.update(activeUserId.value, payload)
    } else {
      res = await userApi.create(payload)
      activeUserId.value = res.data.user_id
      isEditing.value = true
    }
    store.setCurrentUserProfile(res.data)
    await loadUsers()
    ElMessage.success(isEditing.value ? '用户资料已保存' : '用户资料已创建')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '用户资料保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadUsers()
  if (store.currentUserProfile) {
    selectUser(store.currentUserProfile)
  }
})
</script>

<style scoped>
.user-profile-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.header-card,
.list-card,
.form-card {
  border-radius: 14px;
}

.header-card {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 22px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.header-card h2 {
  margin: 0;
}

.header-card p {
  margin: 8px 0 0;
  color: #667085;
}

.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.user-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  margin-bottom: 10px;
  border: 1px solid #d8dee8;
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.user-item.active {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
}

.user-item span {
  color: #667085;
  font-size: 13px;
}

.action-row {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

@media (max-width: 920px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .header-card {
    flex-direction: column;
  }
}
</style>
