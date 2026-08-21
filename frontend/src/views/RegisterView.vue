<template>
  <div class="auth-page">
    <section class="auth-card">
      <aside class="auth-visual">
        <div class="auth-brand-lockup">
          <img class="auth-logo" src="/rag-logo.png" alt="RAG匠学" />
          <div>
            <div class="auth-brand-name">RAG匠学</div>
            <div class="auth-brand-subtitle">领域知识个性化生成平台</div>
          </div>
        </div>

        <div class="auth-visual-copy">
          <span class="auth-chip">Create Account</span>
          <h1>创建你的 RAG匠学账号</h1>
          <p>注册后即可创建学习画像、完成问卷和诊断，并进入资源生成与反馈闭环。</p>
        </div>

        <div class="auth-insights">
          <article class="auth-insight">
            <strong>统一入口</strong>
            <span>注册一次即可使用学习方向、资源、报告和反馈等全部能力。</span>
          </article>
          <article class="auth-insight">
            <strong>个性化生成</strong>
            <span>新账号会在创建学习方向后自动建立独立学习上下文。</span>
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
        <section class="auth-form-panel auth-register-panel">
          <span class="auth-form-badge">Account Setup</span>
          <h2>注册账号</h2>
          <p class="auth-form-subtitle">用户名、密码和确认密码是必填项，其余信息可后续补充。</p>

          <p v-if="errorMessage" class="auth-error">{{ errorMessage }}</p>

          <el-form class="auth-register-form" :model="form" @submit.prevent="submit">
            <el-form-item label="用户名" required>
              <div class="auth-input-shell">
                <el-icon><User /></el-icon>
                <el-input v-model="form.username" autocomplete="username" maxlength="64" placeholder="2-64 个字符" />
              </div>
            </el-form-item>
            <div class="auth-form-grid">
              <el-form-item label="密码" required>
                <div class="auth-input-shell">
                  <el-icon><Lock /></el-icon>
                  <el-input
                    v-model="form.password"
                    type="password"
                    show-password
                    autocomplete="new-password"
                    maxlength="128"
                    placeholder="至少 8 位"
                  />
                </div>
              </el-form-item>
              <el-form-item label="确认密码" required>
                <div class="auth-input-shell">
                  <el-icon><Lock /></el-icon>
                  <el-input
                    v-model="form.confirm_password"
                    type="password"
                    show-password
                    autocomplete="new-password"
                    maxlength="128"
                    placeholder="再次输入密码"
                  />
                </div>
              </el-form-item>
            </div>

            <div class="auth-optional-title">补充资料（选填）</div>
            <div class="auth-form-grid">
              <el-form-item label="身份">
                <div class="auth-input-shell">
                  <el-input v-model="form.identity" maxlength="64" placeholder="例如：在校学生" />
                </div>
              </el-form-item>
              <el-form-item label="学历">
                <div class="auth-input-shell">
                  <el-input v-model="form.education" maxlength="64" placeholder="例如：本科" />
                </div>
              </el-form-item>
              <el-form-item label="专业">
                <div class="auth-input-shell">
                  <el-input v-model="form.major" maxlength="128" placeholder="例如：软件工程" />
                </div>
              </el-form-item>
              <el-form-item label="岗位 / 背景">
                <div class="auth-input-shell">
                  <el-input v-model="form.job_role" maxlength="128" placeholder="例如：算法工程师" />
                </div>
              </el-form-item>
              <el-form-item label="经验年限">
                <div class="auth-input-shell">
                  <el-input-number v-model="form.experience_years" :min="0" :max="50" />
                </div>
              </el-form-item>
            </div>

            <el-button class="auth-submit" type="primary" native-type="submit" :loading="submitting">
              注册并登录
            </el-button>
          </el-form>

          <p class="auth-switch">已有账号？ <router-link to="/login">返回登录</router-link></p>
        </section>
      </main>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'

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
    await router.replace('/dashboard')
  } catch (error) {
    errorMessage.value = error?.response?.data?.message || error?.response?.data?.detail || '注册失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>
