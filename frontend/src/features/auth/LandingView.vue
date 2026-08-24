<template>
  <div class="landing-page">
    <header class="landing-nav">
      <div class="landing-brand">
        <img src="/zhiyu-logo.png" alt="智域匠学" />
        <div>
          <strong>智域匠学</strong>
          <span>领域技能个性化培训平台</span>
        </div>
      </div>
      <button class="login-trigger" type="button" @click="openLogin">登录</button>
    </header>

    <main class="landing-main">
      <section class="landing-hero">
        <div class="hero-content">
          <span class="hero-kicker">MULTI-AGENT DOMAIN SKILL LEARNING</span>
          <h1>智域匠学：多智能体协同的领域技能个性化培训平台</h1>
          <p>围绕学习画像、领域知识库、证据约束、资源生成和反馈迭代，构建可追踪、可审核、可持续优化的技能学习闭环。</p>
          <div class="hero-actions">
            <button class="primary-action" type="button" @click="openLogin">进入系统</button>
            <a class="secondary-action" href="#features">查看能力</a>
          </div>
        </div>
        <div class="hero-visual" aria-hidden="true">
          <div class="orbit-card main-card">
            <img src="/zhiyu-logo.png" alt="" />
            <strong>智域匠学</strong>
            <span>Personalized Learning Loop</span>
          </div>
          <div class="orbit-node node-one">检索</div>
          <div class="orbit-node node-two">生成</div>
          <div class="orbit-node node-three">反馈</div>
        </div>
      </section>

      <section id="features" class="feature-section">
        <article v-for="item in features" :key="item.title" class="feature-card">
          <span>{{ item.index }}</span>
          <strong>{{ item.title }}</strong>
          <p>{{ item.description }}</p>
        </article>
      </section>
    </main>

    <Transition name="modal-fade">
      <div v-if="authVisible" class="login-modal" @click.self="closeAuth">
        <section class="auth-card landing-auth-card" :class="{ 'register-auth-card': authMode === 'register' }">
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
              <article class="auth-insight"><strong>画像驱动</strong><span>结合问卷、诊断和学习反馈，持续维护个人学习画像。</span></article>
              <article class="auth-insight"><strong>RAG 生成</strong><span>围绕知识库检索、证据引用和多智能体协作生成学习资源。</span></article>
              <article class="auth-insight"><strong>闭环学习</strong><span>资源学习、练习反馈和下一轮生成形成完整学习循环。</span></article>
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
            <button class="modal-close" type="button" aria-label="关闭登录" @click="closeAuth">×</button>
            <section class="auth-form-panel" :class="{ 'auth-register-panel': authMode === 'register' }">
              <template v-if="authMode === 'login'">
                <span class="auth-form-badge">Smart Sign In</span>
              <h2>账号登录</h2>
                <p class="auth-form-subtitle">使用已注册的用户名进入智域匠学。</p>
                <p v-if="errorMessage" class="auth-error">{{ errorMessage }}</p>

                <el-form class="auth-login-form" :model="form" @submit.prevent="submitLogin">
                  <el-form-item label="用户名" required>
                    <div class="auth-input-shell">
                      <el-icon><User /></el-icon>
                      <el-input v-model="form.username" autocomplete="username" maxlength="64" placeholder="请输入用户名" @keyup.enter="submitLogin" />
                    </div>
                  </el-form-item>
                  <el-form-item label="密码" required>
                    <div class="auth-input-shell">
                      <el-icon><Lock /></el-icon>
                      <el-input v-model="form.password" type="password" show-password autocomplete="current-password" maxlength="128" placeholder="请输入密码" @keyup.enter="submitLogin" />
                    </div>
                  </el-form-item>
                  <el-button class="auth-submit" type="primary" native-type="submit" :loading="submitting">登录</el-button>
                </el-form>

                <p class="auth-switch">还没有账号？ <router-link class="text-link" :to="{ name: 'register', query: { auth: '1' } }">立即注册</router-link></p>
              </template>

              <template v-else>
                <span class="auth-form-badge">Account Setup</span>
                <h2>注册账号</h2>
                <p class="auth-form-subtitle">用户名、密码和确认密码是必填项，其余信息可后续补充。</p>
                <p v-if="errorMessage" class="auth-error">{{ errorMessage }}</p>

                <el-form class="auth-register-form" :model="registerForm" @submit.prevent="submitRegister">
                  <el-form-item label="用户名" required>
                    <div class="auth-input-shell">
                      <el-icon><User /></el-icon>
                      <el-input v-model="registerForm.username" autocomplete="username" maxlength="64" placeholder="2-64 个字符" />
                    </div>
                  </el-form-item>
                  <div class="auth-form-grid auth-register-grid">
                    <el-form-item label="密码" required>
                      <div class="auth-input-shell">
                        <el-icon><Lock /></el-icon>
                        <el-input v-model="registerForm.password" type="password" show-password autocomplete="new-password" maxlength="128" placeholder="至少 8 位" />
                      </div>
                    </el-form-item>
                    <el-form-item label="确认密码" required>
                      <div class="auth-input-shell">
                        <el-icon><Lock /></el-icon>
                        <el-input v-model="registerForm.confirm_password" type="password" show-password autocomplete="new-password" maxlength="128" placeholder="再次输入密码" />
                      </div>
                    </el-form-item>
                  </div>

                  <div class="auth-optional-title">补充资料（选填）</div>
                  <div class="auth-form-grid auth-register-grid">
                    <el-form-item label="身份">
                      <div class="auth-input-shell"><el-input v-model="registerForm.identity" maxlength="64" placeholder="例如：在校学生" /></div>
                    </el-form-item>
                    <el-form-item label="学历">
                      <div class="auth-input-shell"><el-input v-model="registerForm.education" maxlength="64" placeholder="例如：本科" /></div>
                    </el-form-item>
                    <el-form-item label="专业">
                      <div class="auth-input-shell"><el-input v-model="registerForm.major" maxlength="128" placeholder="例如：软件工程" /></div>
                    </el-form-item>
                    <el-form-item label="岗位 / 背景">
                      <div class="auth-input-shell"><el-input v-model="registerForm.job_role" maxlength="128" placeholder="例如：算法工程师" /></div>
                    </el-form-item>
                    <el-form-item label="经验年限">
                      <div class="auth-input-shell"><el-input-number v-model="registerForm.experience_years" :min="0" :max="50" /></div>
                    </el-form-item>
                  </div>

                  <el-button class="auth-submit" type="primary" native-type="submit" :loading="submitting">注册并登录</el-button>
                </el-form>

                <p class="auth-switch">已有账号？ <router-link class="text-link" :to="{ name: 'login', query: { auth: '1' } }">返回登录</router-link></p>
              </template>
            </section>
          </main>
        </section>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '../../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const authVisible = ref(route.query.login === '1' || route.query.auth === '1' || route.name === 'login' || route.name === 'register')
const authMode = ref(route.name === 'register' ? 'register' : 'login')
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({ username: '', password: '' })
const registerForm = reactive({
  username: '',
  password: '',
  confirm_password: '',
  identity: '',
  education: '',
  major: '',
  job_role: '',
  experience_years: null,
})

const features = [
  { index: '01', title: '多智能体协同', description: '任务拆解、检索、生成、校验和反馈在同一条链路中协同推进。' },
  { index: '02', title: '领域知识与证据约束', description: '学习资源围绕领域知识库与证据组织，输出内容可追踪、可复盘。' },
  { index: '03', title: '个性化导学', description: '基于学习画像和诊断结果，持续调整学习路径与资源难度。' },
  { index: '04', title: '闭环反馈迭代', description: '练习反馈会进入下一轮生成，帮助持续巩固薄弱知识点。' },
]

watch(() => route.query.login, (value) => {
  authVisible.value = value === '1' || route.query.auth === '1' || route.name === 'login' || route.name === 'register'
})

watch(() => route.name, (value) => {
  if (value === 'register') authMode.value = 'register'
  if (value === 'login') authMode.value = 'login'
  authVisible.value = value === 'login' || value === 'register' || route.query.login === '1' || route.query.auth === '1'
})

function openLogin() {
  authVisible.value = true
  authMode.value = 'login'
  router.replace({ query: { ...route.query, auth: '1' } })
}

function closeAuth() {
  authVisible.value = false
  const query = { ...route.query }
  delete query.login
  delete query.auth
  router.replace({ query })
}

function switchToLogin() {
  authMode.value = 'login'
  authVisible.value = true
  router.replace({ name: 'login', query: { auth: '1' } })
}

function switchToRegister() {
  authMode.value = 'register'
  authVisible.value = true
  router.replace({ name: 'register', query: { auth: '1' } })
}

function targetAfterAuth() {
  const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
  return target.startsWith('/') && !target.startsWith('//') ? target : '/dashboard'
}

async function submitLogin() {
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

async function submitRegister() {
  errorMessage.value = ''
  if (!registerForm.username.trim() || !registerForm.password || !registerForm.confirm_password) {
    errorMessage.value = '请填写用户名、密码和确认密码'
    return
  }
  if (registerForm.password.length < 8) {
    errorMessage.value = '密码至少需要 8 位'
    return
  }
  if (registerForm.password !== registerForm.confirm_password) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }
  submitting.value = true
  try {
    await auth.register({
      username: registerForm.username,
      password: registerForm.password,
      confirm_password: registerForm.confirm_password,
      identity: registerForm.identity || null,
      education: registerForm.education || null,
      major: registerForm.major || null,
      job_role: registerForm.job_role || null,
      experience_years: registerForm.experience_years,
    })
    await router.replace('/dashboard')
  } catch (error) {
    errorMessage.value = error?.response?.data?.message || error?.response?.data?.detail || '注册失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.landing-page {
  min-height: 100dvh;
  overflow-y: auto;
  background:
    radial-gradient(circle at 18% 12%, rgba(74, 144, 255, 0.18), transparent 28%),
    linear-gradient(180deg, #f8fbff 0%, #eaf3ff 100%);
  color: #10233f;
}

.landing-nav {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px clamp(20px, 5vw, 68px);
  backdrop-filter: blur(16px);
  background: rgba(248, 251, 255, 0.82);
  border-bottom: 1px solid rgba(207, 223, 241, 0.72);
}

.landing-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.landing-brand img {
  width: 48px;
  height: 48px;
  object-fit: contain;
}

.landing-brand strong,
.landing-brand span {
  display: block;
}

.landing-brand strong {
  color: #0f2749;
  font-size: 20px;
  font-weight: 850;
}

.landing-brand span {
  margin-top: 3px;
  color: #5f738f;
  font-size: 12px;
}

.login-trigger,
.primary-action,
.secondary-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 0 18px;
  border-radius: 8px;
  font-weight: 800;
  text-decoration: none;
  cursor: pointer;
}

.login-trigger,
.primary-action {
  border: 1px solid #2058a7;
  background: #2058a7;
  color: #ffffff;
}

.secondary-action {
  border: 1px solid #b8cde3;
  background: #ffffff;
  color: #17447e;
}

.landing-main {
  padding: clamp(26px, 5vw, 72px) clamp(20px, 5vw, 68px) 64px;
}

.landing-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
  gap: 42px;
  align-items: center;
  min-height: calc(100dvh - 180px);
}

.hero-kicker {
  display: block;
  color: #2058a7;
  font-size: 12px;
  font-weight: 850;
  letter-spacing: 0.08em;
}

.hero-content h1 {
  max-width: 920px;
  margin: 18px 0 0;
  color: #0f2749;
  font-size: clamp(42px, 5vw, 72px);
  line-height: 1.08;
}

.hero-content p {
  max-width: 760px;
  margin: 22px 0 0;
  color: #516883;
  font-size: 17px;
  line-height: 1.8;
}

.hero-actions {
  display: flex;
  gap: 12px;
  margin-top: 30px;
  flex-wrap: wrap;
}

.hero-visual {
  position: relative;
  min-height: 480px;
  border: 1px solid #cfe0f4;
  border-radius: 8px;
  background:
    radial-gradient(circle at 50% 42%, rgba(74, 144, 255, 0.24), transparent 36%),
    linear-gradient(180deg, #ffffff 0%, #edf5ff 100%);
  box-shadow: 0 24px 70px rgba(15, 39, 73, 0.14);
  overflow: hidden;
}

.hero-visual::before {
  position: absolute;
  inset: 74px;
  border: 1px solid rgba(32, 88, 167, 0.16);
  border-radius: 50%;
  content: '';
}

.orbit-card,
.orbit-node {
  position: absolute;
  display: grid;
  place-items: center;
  border: 1px solid #cfe0f4;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 16px 40px rgba(15, 39, 73, 0.1);
}

.main-card {
  top: 50%;
  left: 50%;
  width: 220px;
  height: 220px;
  padding: 22px;
  border-radius: 50%;
  transform: translate(-50%, -50%);
}

.main-card img {
  width: 90px;
  height: 90px;
  object-fit: contain;
}

.main-card strong {
  color: #0f2749;
  font-size: 24px;
}

.main-card span {
  color: #5f738f;
  font-size: 12px;
}

.orbit-node {
  width: 92px;
  height: 92px;
  border-radius: 50%;
  color: #17447e;
  font-weight: 850;
}

.node-one { top: 74px; left: 82px; }
.node-two { top: 90px; right: 70px; }
.node-three { right: 118px; bottom: 74px; }

.feature-section {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-top: 24px;
}

.feature-card {
  min-height: 190px;
  padding: 22px;
  border: 1px solid #d9e6f4;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 12px 30px rgba(15, 39, 73, 0.06);
}

.feature-card span,
.feature-card strong,
.feature-card p {
  display: block;
}

.feature-card span {
  color: #2058a7;
  font-size: 12px;
  font-weight: 850;
}

.feature-card strong {
  margin-top: 14px;
  color: #0f2749;
  font-size: 20px;
}

.feature-card p {
  margin: 12px 0 0;
  color: #5f738f;
  font-size: 14px;
  line-height: 1.7;
}

.login-modal {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(15, 39, 73, 0.44);
  backdrop-filter: blur(12px);
}

.landing-auth-card {
  width: min(1120px, calc(100vw - 48px));
  min-height: min(760px, calc(100dvh - 48px));
}

.landing-auth-card.register-auth-card {
  width: min(980px, calc(100vw - 48px));
  min-height: 0;
  max-height: calc(100dvh - 48px);
  grid-template-columns: minmax(330px, 0.9fr) minmax(390px, 1fr);
}

.register-auth-card .auth-visual {
  gap: 20px;
  padding: 30px 30px 26px;
}

.register-auth-card .auth-visual-copy h1 {
  font-size: 36px;
}

.register-auth-card .auth-visual-copy p {
  margin-top: 12px;
  line-height: 1.65;
}

.register-auth-card .auth-insights {
  gap: 8px;
}

.register-auth-card .auth-insight {
  padding: 11px 13px;
}

.register-auth-card .auth-animation-stage {
  min-height: 138px;
  padding: 14px;
}

.register-auth-card .bot-row {
  min-height: 100px;
}

.register-auth-card .learning-bot {
  transform: scale(0.88);
}

.register-auth-card .auth-form-side {
  padding: 32px 42px;
  overflow-y: auto;
}

.modal-close {
  position: absolute;
  top: 18px;
  right: 18px;
  z-index: 2;
  width: 38px;
  height: 38px;
  border: 1px solid #cfdff1;
  border-radius: 50%;
  background: #ffffff;
  color: #17447e;
  font-size: 22px;
  cursor: pointer;
}

.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.18s ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}

@media (max-width: 980px) {
  .landing-hero,
  .feature-section {
    grid-template-columns: 1fr;
  }

  .hero-visual {
    min-height: 380px;
  }
}

@media (max-width: 620px) {
  .landing-nav {
    padding-inline: 16px;
  }

  .landing-main {
    padding-inline: 16px;
  }

  .hero-content h1 {
    font-size: 36px;
  }

  .login-modal {
    padding: 12px;
  }

  .landing-auth-card {
    width: calc(100vw - 24px);
    min-height: calc(100dvh - 24px);
  }

  .landing-auth-card.register-auth-card {
    width: calc(100vw - 24px);
    max-height: calc(100dvh - 24px);
    grid-template-columns: 1fr;
  }
}
</style>
