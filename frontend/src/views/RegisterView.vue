<template>
  <div class="auth-page">
    <aside class="auth-brand-panel">
      <div class="auth-brand-lockup">
        <div class="auth-brand-mark">TP</div>
        <div class="auth-brand-name">Training Pilot</div>
      </div>
      <div class="auth-brand-copy">
        <h1>创建你的学习账号</h1>
        <p>账号创建后即可选择学习方向，完成问卷与首次能力诊断。</p>
      </div>
      <span>领域知识个性化学习系统</span>
    </aside>

    <main class="auth-main">
      <section class="auth-form-panel">
        <h2>注册</h2>
        <p class="auth-form-subtitle">用户名和密码是唯一必填信息。</p>

        <p v-if="errorMessage" class="auth-error">{{ errorMessage }}</p>

        <el-form :model="form" label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名" required>
            <el-input v-model="form.username" autocomplete="username" maxlength="64" placeholder="2-64 个字符" />
          </el-form-item>
          <div class="auth-form-grid">
            <el-form-item label="密码" required>
              <el-input
                v-model="form.password"
                type="password"
                show-password
                autocomplete="new-password"
                maxlength="128"
                placeholder="至少 8 位"
              />
            </el-form-item>
            <el-form-item label="确认密码" required>
              <el-input
                v-model="form.confirm_password"
                type="password"
                show-password
                autocomplete="new-password"
                maxlength="128"
                placeholder="再次输入密码"
              />
            </el-form-item>
          </div>

          <div class="auth-optional-title">补充资料（选填）</div>
          <div class="auth-form-grid">
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

          <el-button class="auth-submit" type="primary" native-type="submit" :loading="submitting">
            注册并登录
          </el-button>
        </el-form>

        <p class="auth-switch">已有账号？ <router-link to="/login">返回登录</router-link></p>
      </section>
    </main>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({
  username: '',
  password: '',
  confirm_password: '',
  identity: '',
  education: '',
  major: '',
  job_role: '',
  experience_years: null,
})

async function submit() {
  errorMessage.value = ''
  if (!form.username.trim() || !form.password || !form.confirm_password) {
    errorMessage.value = '请填写用户名、密码和确认密码'
    return
  }
  if (form.password.length < 8) {
    errorMessage.value = '密码至少需要 8 位'
    return
  }
  if (form.password !== form.confirm_password) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }

  submitting.value = true
  try {
    await auth.register({
      username: form.username,
      password: form.password,
      confirm_password: form.confirm_password,
      identity: form.identity || null,
      education: form.education || null,
      major: form.major || null,
      job_role: form.job_role || null,
      experience_years: form.experience_years,
    })
    await router.replace('/')
  } catch (error) {
    errorMessage.value = error?.response?.data?.message || error?.response?.data?.detail || '注册失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>
