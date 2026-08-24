<template>
  <div class="auth-page">
    <section class="auth-card">
      <aside class="auth-visual">
        <div class="auth-brand-lockup">
          <img class="auth-logo" src="/zhiyu-logo.png" alt="智域匠学" />
          <div>
            <div class="auth-brand-name">智域匠学</div>
            <div class="auth-brand-subtitle">多智能体领域技能培训平台</div>
          </div>
        </div>

        <div class="auth-visual-copy">
          <span class="auth-chip">Learning Access Portal</span>
          <h1>欢迎回到智域匠学</h1>
          <p>从这里继续进入学习画像、能力诊断、资源生成和反馈迭代，让每一轮学习都围绕你的目标推进。</p>
        </div>

        <div class="auth-insights">
          <article class="auth-insight">
            <strong>画像驱动</strong>
            <span>结合问卷、诊断和学习反馈，持续维护个人学习画像。</span>
          </article>
          <article class="auth-insight">
            <strong>领域知识生成</strong>
            <span>围绕领域知识库、证据引用和多智能体协作生成学习资源。</span>
          </article>
          <article class="auth-insight">
            <strong>闭环学习</strong>
            <span>资源学习、练习反馈和下一轮生成形成完整学习循环。</span>
          </article>
        </div>

        <div class="auth-animation-stage">
          <div class="animation-label">Learning Companions</div>
          <div class="bot-row">
            <div class="learning-bot"><span class="bot-mouth" /></div>
            <div class="learning-bot"><span class="bot-antenna" /><span class="bot-mouth" /></div>
            <div class="learning-bot"><span class="bot-mouth" /></div>
          </div>
        </div>
      </aside>

      <main class="auth-form-side">
        <section class="auth-form-panel">
          <span class="auth-form-badge">Smart Sign In</span>
          <h2>账号登录</h2>
          <p class="auth-form-subtitle">使用已注册的用户名进入智域匠学。</p>

          <p v-if="errorMessage" class="auth-error">{{ errorMessage }}</p>

          <el-form class="auth-login-form" :model="form" @submit.prevent="submit">
            <el-form-item label="用户名" required>
              <div class="auth-input-shell">
                <el-icon><User /></el-icon>
                <el-input
                  v-model="form.username"
                  autocomplete="username"
                  maxlength="64"
                  placeholder="请输入用户名"
                  @keyup.enter="submit"
                />
              </div>
            </el-form-item>
            <el-form-item label="密码" required>
              <div class="auth-input-shell">
                <el-icon><Lock /></el-icon>
                <el-input
                  v-model="form.password"
                  type="password"
                  show-password
                  autocomplete="current-password"
                  maxlength="128"
                  placeholder="请输入密码"
                  @keyup.enter="submit"
                />
              </div>
            </el-form-item>
            <el-button class="auth-submit" type="primary" native-type="submit" :loading="submitting">
              登录
            </el-button>
          </el-form>

          <p class="auth-switch">还没有账号？ <router-link to="/register">立即注册</router-link></p>
        </section>
      </main>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'

import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({ username: '', password: '' })

function targetAfterAuth() {
  const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
  return target.startsWith('/') && !target.startsWith('//') ? target : '/dashboard'
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
