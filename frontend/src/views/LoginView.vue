<template>
  <div class="auth-page">
    <aside class="auth-brand-panel">
      <div class="auth-brand-lockup">
        <div class="auth-brand-mark">TP</div>
        <div class="auth-brand-name">Training Pilot</div>
      </div>
      <div class="auth-brand-copy">
        <h1>继续你的学习路径</h1>
        <p>登录后查看学习方向、诊断结果、生成资源与学习时间线。</p>
      </div>
      <span>领域知识个性化学习系统</span>
    </aside>

    <main class="auth-main">
      <section class="auth-form-panel">
        <h2>登录</h2>
        <p class="auth-form-subtitle">使用已注册的用户名进入系统。</p>

        <p v-if="errorMessage" class="auth-error">{{ errorMessage }}</p>

        <el-form :model="form" label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名" required>
            <el-input
              v-model="form.username"
              autocomplete="username"
              maxlength="64"
              placeholder="请输入用户名"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-form-item label="密码" required>
            <el-input
              v-model="form.password"
              type="password"
              show-password
              autocomplete="current-password"
              maxlength="128"
              placeholder="请输入密码"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button class="auth-submit" type="primary" native-type="submit" :loading="submitting">
            登录
          </el-button>
        </el-form>

        <p class="auth-switch">还没有账号？ <router-link to="/register">立即注册</router-link></p>
      </section>
    </main>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({ username: '', password: '' })

function targetAfterAuth() {
  const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
  return target.startsWith('/') && !target.startsWith('//') ? target : '/'
}

async function submit() {
  errorMessage.value = ''
  if (!form.username.trim() || !form.password) {
    errorMessage.value = '请输入用户名和密码'
    return
  }
  submitting.value = true
  try {
    await auth.login({ username: form.username, password: form.password })
    await router.replace(targetAfterAuth())
  } catch (error) {
    errorMessage.value = error?.response?.data?.message || error?.response?.data?.detail || '登录失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>
