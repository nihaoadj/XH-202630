<template>
  <div class="landing-page" :data-theme="activeTheme" :class="{ 'has-open-dialog': authVisible, 'is-paged': fullScreens, 'has-screen-navigation': desktopNavigation }" @keydown="handleScreenKey">
    <a class="skip-link" href="#landing-content">跳到主要内容</a>
    <header class="landing-nav">
      <a class="landing-brand" href="/" aria-label="智域匠学首页">
        <img src="/zhiyu-logo.png" alt="" width="44" height="44" />
        <span><strong>智域匠学</strong><small>领域技能个性化培训平台</small></span>
      </a>
      <nav class="landing-nav-actions" aria-label="首页导航">
        <button ref="loginTrigger" class="login-trigger" type="button" @click="openLogin">登录账号 <el-icon aria-hidden="true"><Right /></el-icon></button>
      </nav>
    </header>

    <main id="landing-content" ref="screenScroller" class="landing-main" tabindex="-1" @scroll.passive="updateActiveScreen" @wheel="handleScreenWheel">
      <section id="overview" ref="overviewScreen" class="landing-screen overview-screen" aria-labelledby="hero-title" :inert="fullScreens && activeScreen !== 0">
        <div class="landing-hero screen-content">
          <div class="hero-content">
            <span class="hero-kicker"><span aria-hidden="true" /> 多智能体协同 · 为你的成长而来</span>
            <h1 id="hero-title">把知识，转化为<br /><em>你的下一次进阶。</em></h1>
            <p>从你的目标与能力出发，规划学习路径、生成专属资源，让每一次练习的反馈，都成为下一步成长的依据。</p>
            <div class="hero-actions">
              <button class="primary-action" type="button" @click="openLogin">开始我的学习 <el-icon aria-hidden="true"><Right /></el-icon></button>
              <a class="secondary-action" href="#features" @click="handleFeatureLink">了解平台能力</a>
            </div>
            <div class="hero-assurance"><el-icon aria-hidden="true"><CircleCheck /></el-icon> 画像驱动 <i aria-hidden="true" /> 知识可溯源 <i aria-hidden="true" /> 反馈持续进阶</div>
          </div>
          <section class="learning-visual" aria-labelledby="loop-title">
            <div class="visual-heading"><span class="visual-eyebrow">PERSONALIZED LEARNING</span><span class="visual-tag">学习流程</span></div>
            <h2 id="loop-title">一条围绕你的智能学习路径</h2>
            <div class="intelligence-map">
              <svg class="network-lines" viewBox="0 0 440 340" fill="none" aria-hidden="true">
                <defs><linearGradient id="network-glow" x1="80" y1="30" x2="350" y2="310" gradientUnits="userSpaceOnUse"><stop stop-color="#3d91ad" /><stop offset="1" stop-color="#5677b9" /></linearGradient></defs>
                <circle cx="220" cy="170" r="114" stroke="#729ab8" stroke-opacity=".12" />
                <circle cx="220" cy="170" r="88" stroke="#729ab8" stroke-opacity=".18" stroke-dasharray="2 9" />
                <path d="M85 62H132L184 126M355 62H308L256 126M85 278H132L184 214M355 278H308L256 214" stroke="url(#network-glow)" stroke-opacity=".6" />
                <path d="M154 82L181 114M286 258L259 226" stroke="#176d95" stroke-width="2" />
                <circle cx="220" cy="56" r="3" fill="#3d91ad" /><circle cx="334" cy="170" r="3" fill="#5677b9" /><circle cx="220" cy="284" r="3" fill="#3d91ad" /><circle cx="106" cy="170" r="3" fill="#5677b9" />
              </svg>
              <div class="intelligence-core" aria-hidden="true"><img src="/zhiyu-logo.png" alt="" width="48" height="48" /><strong>个性化学习</strong><span>LEARNING INTELLIGENCE</span></div>
              <ol class="learning-steps">
                <li v-for="(step, index) in learningSteps" :key="step.title">
                  <span class="step-icon"><el-icon aria-hidden="true"><component :is="step.icon" /></el-icon></span>
                  <span class="step-copy"><strong>{{ step.title }}</strong><small>{{ step.description }}</small></span>
                  <span class="step-number" aria-hidden="true">0{{ index + 1 }}</span>
                </li>
              </ol>
            </div>
            <div class="loop-note"><el-icon aria-hidden="true"><Refresh /></el-icon><span>练习反馈，让学习路径持续更新</span></div>
          </section>
        </div>
        <button class="screen-cue" type="button" @click="goToScreen(1)">向下探索平台能力 <el-icon aria-hidden="true"><Bottom /></el-icon></button>
      </section>
      <section id="features" ref="featuresScreen" class="landing-screen feature-section" :class="{ 'is-active': activeScreen === 1 }" aria-labelledby="features-title" :inert="fullScreens && activeScreen !== 1">
        <div class="feature-content screen-content">
          <div class="section-heading">
            <div><span class="section-eyebrow"><i aria-hidden="true" />THE LEARNING SYSTEM</span><h2 id="features-title">从学习目标，<em>到能力提升。</em></h2></div>
            <div class="capability-heading-note"><span>FOUR CAPABILITIES. ONE JOURNEY.</span><p>协作、证据、路径与反馈，<br />围绕你的每一次进阶。</p></div>
          </div>
          <div class="feature-grid">
            <a v-for="(item, index) in features" :key="item.title" :href="item.path" class="feature-card" @click="handleScreenLink($event, index + 2)">
              <div class="feature-card-top"><span class="capability-number">{{ item.index }}</span><span>{{ item.english }}</span></div>
              <CapabilityDiagram :kind="item.kind" />
              <h3>{{ item.title }}</h3><p>{{ item.description }}</p>
              <span class="feature-explore"><span>探索这一特色</span><el-icon aria-hidden="true"><Right /></el-icon></span>
            </a>
          </div>
          <div class="feature-invitation"><div><span class="section-eyebrow">BUILT AROUND YOU</span><h3>让下一步，更有方向。</h3></div><div class="capability-invitation-actions"><button type="button" class="back-to-overview" @click="goToScreen(0)">返回首屏 <el-icon aria-hidden="true"><Top /></el-icon></button><button class="primary-action" type="button" @click="openLogin">开启我的学习 <el-icon aria-hidden="true"><Right /></el-icon></button></div></div>
        </div>
        <button class="screen-cue" type="button" @click="goToScreen(2)">继续探索 · 协作星图 <el-icon aria-hidden="true"><Bottom /></el-icon></button>
      </section>
      <section v-for="(page, index) in showcasePages" :id="page.id" :key="page.key" class="landing-screen showcase-panel" :data-feature="page.key" :class="{ 'is-active': activeScreen === index + 2 }" :aria-labelledby="page.key + '-title'" :inert="fullScreens && activeScreen !== index + 2">
        <component :is="page.component" :active="activeScreen === index + 2 && !authVisible" />
        <button v-if="index < showcasePages.length - 1" class="screen-cue" type="button" @click="goToScreen(index + 3)">继续探索 · {{ showcasePages[index + 1].shortTitle }} <el-icon aria-hidden="true"><Bottom /></el-icon></button>
        <div v-else class="last-screen-actions">
          <button class="feature-button" type="button" @click="openLogin">开始我的学习 <el-icon aria-hidden="true"><Right /></el-icon></button>
          <button class="return-to-top" type="button" @click="goToScreen(0)">回到首页 <el-icon aria-hidden="true"><Top /></el-icon></button>
        </div>
      </section>
    </main>
    <nav class="screen-pagination" aria-label="首页分屏导航">
      <button v-for="(screen, index) in screens" :key="screen.id" type="button" :aria-label="`第 ${index + 1} 屏：${screen.label}`" :aria-current="activeScreen === index ? 'step' : undefined" :aria-controls="screen.id" :title="screen.label" @click="goToScreen(index)"><i aria-hidden="true" /></button>
    </nav>
    <el-dialog v-model="authVisible" class="access-dialog" modal-class="access-overlay" :title="authMode === 'register' ? '注册账号' : '账号登录'" :show-close="false" width="min(1060px, calc(100% - 48px))" align-center append-to-body @close="closeAuth" @closed="restoreFocus">
      <div class="access-layout">
        <aside class="access-story">
          <div class="access-brand"><img src="/zhiyu-logo.png" alt="" width="44" height="44" /><span><strong>智域匠学</strong><small>个性化学习 · 为进阶而生</small></span></div>
          <div class="access-story-copy"><span class="access-eyebrow">PERSONALIZED LEARNING</span><p class="access-story-title">你的下一次进阶，<br /><em>从这里开始。</em></p><p>让知识、资源与反馈，<br />围绕你的目标连接。</p></div>
          <AuthPortalArt class="access-portal-art" :active="authVisible" />
          <ol class="access-benefits"><li><span>01</span><strong>画像驱动</strong></li><li><span>02</span><strong>证据溯源</strong></li><li><span>03</span><strong>反馈进阶</strong></li></ol>
          <p class="access-story-footer"><el-icon aria-hidden="true"><Connection /></el-icon> 多智能体协同 · 让成长相互连接</p>
        </aside>
        <section class="access-form-side">
          <button class="modal-close" type="button" aria-label="关闭账号弹窗" @click="closeAuth"><el-icon aria-hidden="true"><Close /></el-icon></button>
          <div class="access-form-scroll">
          <div class="access-form-panel" v-module-motion="authMode">
            <div class="access-form-topline"><span class="access-form-eyebrow">{{ authMode === 'register' ? 'CREATE ACCOUNT' : 'ACCOUNT ACCESS' }}</span><span class="access-form-index" aria-hidden="true">{{ authMode === 'register' ? '02 / START' : '01 / SIGN IN' }}</span></div>
            <h2>{{ authMode === 'register' ? '创建你的账号' : '欢迎回来' }}</h2>
            <p class="access-form-subtitle">{{ authMode === 'register' ? '先建立账号，学习目标和个人资料可逐步完善。' : '登录智域匠学，继续向你的目标前进。' }}</p>
            <p v-if="errorMessage" ref="errorSummary" class="access-error" role="alert" tabindex="-1">{{ errorMessage }}</p>
            <el-form v-if="authMode === 'login'" class="access-form" label-position="top" :model="form" @submit.prevent="submitLogin">
              <el-form-item label="用户名" for="signin-username" :error="fieldErrors.username">
                <el-input id="signin-username" ref="signinUsername" v-model="form.username" name="username" autocomplete="username" :spellcheck="false" maxlength="64" placeholder="请输入用户名" :aria-invalid="Boolean(fieldErrors.username)"><template #prefix><el-icon aria-hidden="true"><User /></el-icon></template></el-input>
              </el-form-item>
              <el-form-item label="密码" for="signin-password" :error="fieldErrors.password">
                <el-input id="signin-password" ref="signinPassword" v-model="form.password" name="password" :type="passwordVisible.login ? 'text' : 'password'" autocomplete="current-password" maxlength="128" placeholder="请输入密码" :aria-invalid="Boolean(fieldErrors.password)"><template #prefix><el-icon aria-hidden="true"><Lock /></el-icon></template><template #suffix><button class="password-toggle" type="button" :aria-label="passwordVisible.login ? '隐藏密码' : '显示密码'" :aria-pressed="passwordVisible.login" @click="passwordVisible.login = !passwordVisible.login"><el-icon aria-hidden="true"><component :is="passwordVisible.login ? View : Hide" /></el-icon></button></template></el-input>
              </el-form-item>
              <el-button class="access-submit" type="primary" native-type="submit" :loading="submitting">{{ submitting ? '正在登录…' : '登录账号' }}<el-icon v-if="!submitting" aria-hidden="true"><Right /></el-icon></el-button>
            </el-form>
            <el-form v-else class="access-form register-form" label-position="top" :model="registerForm" @submit.prevent="submitRegister">
              <el-form-item label="用户名" for="signup-username" :error="fieldErrors.username"><el-input id="signup-username" ref="signupUsername" v-model="registerForm.username" name="username" autocomplete="username" :spellcheck="false" maxlength="64" placeholder="2–64 个字符" :aria-invalid="Boolean(fieldErrors.username)" /></el-form-item>
              <el-form-item v-for="field in registerPasswordFields" :key="field.key" :label="field.label" :for="`signup-${field.key}`" :error="fieldErrors[field.key]">
                <el-input :id="`signup-${field.key}`" v-model="registerForm[field.key]" :name="field.key" :type="passwordVisible[field.key] ? 'text' : 'password'" autocomplete="new-password" maxlength="128" :placeholder="field.placeholder" :aria-invalid="Boolean(fieldErrors[field.key])"><template #suffix><button class="password-toggle" type="button" :aria-label="`${passwordVisible[field.key] ? '隐藏' : '显示'}${field.label}`" :aria-pressed="passwordVisible[field.key]" @click="passwordVisible[field.key] = !passwordVisible[field.key]"><el-icon aria-hidden="true"><component :is="passwordVisible[field.key] ? View : Hide" /></el-icon></button></template></el-input>
              </el-form-item>
              <details class="optional-details"><summary>补充个人资料 <span>选填，可稍后完善</span></summary><div class="optional-fields"><el-form-item v-for="field in optionalFields" :key="field.key" :label="field.label" :for="`signup-${field.key}`"><el-input :id="`signup-${field.key}`" v-model="registerForm[field.key]" :name="field.key" autocomplete="off" :maxlength="field.maxlength" :placeholder="field.placeholder" /></el-form-item><el-form-item label="经验年限" for="signup-experience"><el-input-number id="signup-experience" v-model="registerForm.experience_years" aria-label="经验年限" :min="0" :max="50" /></el-form-item></div></details>
              <el-button class="access-submit" type="primary" native-type="submit" :loading="submitting">{{ submitting ? '正在创建…' : '创建账号并开始学习' }}</el-button>
            </el-form>
            <p class="access-switch" v-if="authMode === 'login'">还没有账号？<router-link :to="{ name: 'register', query: { ...route.query, auth: '1' } }">创建账号</router-link></p>
            <p class="access-switch" v-else>已有账号？<router-link :to="{ name: 'login', query: { ...route.query, auth: '1' } }">返回登录</router-link></p>
          </div>
          </div>
        </section>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bottom, CircleCheck, Close, Connection, Hide, Lock, Reading, Refresh, Right, Top, TrendCharts, User, View } from '@element-plus/icons-vue'
import { useAuthStore } from '../../stores/auth'
import { showcasePages } from '../home/showcase/showcaseConfig'
import CapabilityDiagram from '../home/showcase/CapabilityDiagram.vue'
import AuthPortalArt from './AuthPortalArt.vue'
import '../home/showcase/showcase.css'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const authVisible = ref(false)
const authMode = ref('login')
const submitting = ref(false)
const errorMessage = ref('')
const fieldErrors = reactive({})
const loginTrigger = ref(null)
const signinUsername = ref(null)
const signinPassword = ref(null)
const signupUsername = ref(null)
const errorSummary = ref(null)
const passwordVisible = reactive({ login: false, password: false, confirm_password: false })
const screenScroller = ref(null)
const overviewScreen = ref(null)
const featuresScreen = ref(null)
const activeScreen = ref(0)
const activeTheme = computed(() => activeScreen.value === 1 ? 'capabilities' : showcasePages[activeScreen.value - 2]?.key || 'home')
const fullScreens = ref(false)
const desktopNavigation = ref(false)
const screens = [{ id: 'overview', label: '学习概览' }, { id: 'features', label: '平台能力' }, ...showcasePages.map(page => ({ id: page.id, label: page.shortTitle }))]
const screenElements = () => [...(screenScroller.value?.children || [])]
let screenResizeObserver
let wheelGestureDirection = 0
let wheelIdleTimer
let screenDestination = 0
let screenAnimationFrame = 0
let screenTransitionDirection = 0
let screenTransitionReading = false
let screenAnimationTarget = null
let pendingScreenAlignment = null
let screenLayoutKey = ''
let motionPreference
function cancelScreenTransition() {
  window.cancelAnimationFrame(screenAnimationFrame)
  screenAnimationFrame = 0
  screenTransitionDirection = 0
  screenTransitionReading = false
  screenAnimationTarget = null
  const scroller = screenScroller.value
  if (scroller) {
    scroller.scrollTo({ top: scroller.scrollTop, behavior: 'instant' })
    scroller.style.scrollSnapType = ''
    scroller.style.scrollBehavior = ''
  }
}
function updateActiveScreen() {
  const scroller = screenScroller.value
  if (!scroller) return
  let index = 0
  for (const [position, screen] of screenElements().entries()) {
    const threshold = fullScreens.value || screenAnimationFrame ? scroller.clientHeight / 2 : 2
    if (scroller.scrollTop >= screen.offsetTop - threshold) index = position
  }
  activeScreen.value = index
  if (!wheelGestureDirection && !screenAnimationFrame) screenDestination = index
}
function updateScreenLayout() {
  const scroller = screenScroller.value
  if (!scroller) return
  const wasPaged = fullScreens.value
  desktopNavigation.value = window.matchMedia('(min-width: 821px) and (min-height: 680px)').matches
  fullScreens.value = desktopNavigation.value &&
    screenElements().every(screen => screen.offsetHeight <= scroller.clientHeight + 1)
  const key = `${window.innerWidth}:${window.innerHeight}:${scroller.clientHeight}`
  const layoutChanged = key !== screenLayoutKey || wasPaged !== fullScreens.value
  screenLayoutKey = key
  if (layoutChanged) {
    const wasTransitioning = Boolean(screenAnimationFrame)
    const target = screenAnimationTarget || { index: activeScreen.value, alignEnd: false }
    cancelScreenTransition()
    window.clearTimeout(wheelIdleTimer)
    wheelGestureDirection = 0
    if (fullScreens.value || wasTransitioning && desktopNavigation.value) scrollToScreen(target.index, 'instant', target.alignEnd)
  }
  updateActiveScreen()
}
function scrollToScreen(index, behavior, alignEnd = false, duration = 760) {
  const scroller = screenScroller.value
  if (!scroller) return
  const screen = screenElements()[index]
  const top = (screen?.offsetTop || 0) + (alignEnd ? Math.max(0, (screen?.offsetHeight || 0) - scroller.clientHeight) : 0)
  const immediate = behavior === 'instant' || window.matchMedia('(prefers-reduced-motion: reduce)').matches
  cancelScreenTransition()
  if (immediate || !desktopNavigation.value) {
    scroller.scrollTo({ top, behavior: immediate ? 'instant' : 'smooth' })
    return
  }
  const start = scroller.scrollTop
  const distance = top - start
  if (Math.abs(distance) < 1) return
  screenTransitionDirection = Math.sign(distance)
  screenTransitionReading = duration === 300
  scroller.style.scrollSnapType = 'none'
  scroller.style.scrollBehavior = 'auto'
  const started = performance.now()
  function advance(now) {
    const progress = Math.max(0, Math.min(1, (now - started) / duration))
    // One clock controls every frame; neither native smooth scroll nor snap competes with it.
    const eased = progress < .5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2
    scroller.scrollTop = start + distance * eased
    if (progress < 1) screenAnimationFrame = window.requestAnimationFrame(advance)
    else {
      scroller.scrollTop = top
      cancelScreenTransition()
      updateActiveScreen()
    }
  }
  screenAnimationFrame = window.requestAnimationFrame(advance)
  screenAnimationTarget = { index, alignEnd }
}
function goToScreen(index, alignEnd = false) {
  if (authVisible.value) return
  const target = Math.max(0, Math.min(screens.length - 1, index))
  screenDestination = target
  const hash = target === 0 ? '' : '#' + screens[target].id
  if (route.hash !== hash) {
    pendingScreenAlignment = { hash, alignEnd }
    router.push({ path: route.path, query: route.query, hash })
  } else scrollToScreen(target, undefined, alignEnd)
}
function handleScreenLink(event, index) {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
  event.preventDefault()
  goToScreen(index)
}
function handleFeatureLink(event) { handleScreenLink(event, 1) }
function handleScreenKey(event) {
  if (authVisible.value || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.defaultPrevented) return
  if (event.target.closest('a, button, input, textarea, select, summary, [contenteditable]')) return
  if (!desktopNavigation.value) return
  const targets = { ArrowDown: activeScreen.value + 1, PageDown: activeScreen.value + 1, End: screens.length - 1, ArrowUp: activeScreen.value - 1, PageUp: activeScreen.value - 1, Home: 0 }
  if (!(event.key in targets)) return
  event.preventDefault()
  goToScreen(targets[event.key])
}
function handleScreenWheel(event) {
  if (!desktopNavigation.value || authVisible.value || event.ctrlKey || event.metaKey || event.defaultPrevented || !event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return
  const direction = Math.sign(event.deltaY)
  const newGesture = wheelGestureDirection !== direction
  wheelGestureDirection = direction
  window.clearTimeout(wheelIdleTimer)
  wheelIdleTimer = window.setTimeout(() => { wheelGestureDirection = 0; updateActiveScreen() }, 180)
  // Reversing a reading-boundary adjustment stays inside the current chapter.
  // A chapter transition can still reverse toward its previous destination.
  if (screenAnimationFrame && screenTransitionReading && direction !== screenTransitionDirection) cancelScreenTransition()
  const scroller = screenScroller.value
  const screen = screenElements()[activeScreen.value]
  const overflow = screen.offsetHeight - scroller.clientHeight
  if (!screenAnimationFrame && overflow > 1) {
    const withinScreen = scroller.scrollTop - screen.offsetTop
    if ((direction > 0 && withinScreen < overflow - 2) || (direction < 0 && withinScreen > 2)) {
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? scroller.clientHeight : 1)
      const boundary = screen.offsetTop + (direction > 0 ? overflow : 0)
      if (direction > 0 ? scroller.scrollTop + delta > boundary : scroller.scrollTop + delta < boundary) {
        event.preventDefault()
        scrollToScreen(activeScreen.value, undefined, direction > 0, 300)
      }
      return
    }
  }
  event.preventDefault()
  if (screenAnimationFrame && direction === screenTransitionDirection) return
  const target = screenDestination + direction
  if (newGesture && target >= 0 && target < screens.length) goToScreen(target, direction < 0)
}
function handleMotionPreference() {
  if (!motionPreference.matches) return
  const target = screenAnimationTarget
  if (target) scrollToScreen(target.index, 'instant', target.alignEnd)
  else cancelScreenTransition()
}
watch(authVisible, visible => {
  if (visible) {
    const target = screenAnimationTarget
    if (target) scrollToScreen(target.index, 'instant', target.alignEnd)
    else cancelScreenTransition()
  }
  window.clearTimeout(wheelIdleTimer)
  wheelGestureDirection = 0
})
watch(() => route.hash, async () => {
  await nextTick()
  const index = screens.findIndex(screen => '#' + screen.id === route.hash)
  screenDestination = Math.max(0, index)
  const alignEnd = pendingScreenAlignment?.hash === route.hash && pendingScreenAlignment.alignEnd
  pendingScreenAlignment = null
  scrollToScreen(screenDestination, undefined, alignEnd)
})
onMounted(() => {
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
  motionPreference.addEventListener('change', handleMotionPreference)
  screenResizeObserver = new ResizeObserver(updateScreenLayout)
  for (const element of [screenScroller.value, ...screenElements()]) screenResizeObserver.observe(element)
  const index = screens.findIndex(screen => '#' + screen.id === route.hash)
  scrollToScreen(Math.max(0, index), 'instant')
  updateActiveScreen()
})
onBeforeUnmount(() => {
  screenResizeObserver?.disconnect()
  window.clearTimeout(wheelIdleTimer)
  cancelScreenTransition()
  motionPreference?.removeEventListener('change', handleMotionPreference)
})
let openingControl = null
const form = reactive({ username: '', password: '' })
const registerForm = reactive({ username: '', password: '', confirm_password: '', identity: '', education: '', major: '', job_role: '', experience_years: null })
const registerPasswordFields = [{ key: 'password', label: '密码', placeholder: '至少 8 位' }, { key: 'confirm_password', label: '确认密码', placeholder: '再次输入密码' }]
const optionalFields = [
  { key: 'identity', label: '身份', maxlength: 64, placeholder: '例如：在校学生' },
  { key: 'education', label: '学历', maxlength: 64, placeholder: '例如：本科' },
  { key: 'major', label: '专业', maxlength: 128, placeholder: '例如：软件工程' },
  { key: 'job_role', label: '岗位 / 背景', maxlength: 128, placeholder: '例如：算法工程师' },
]
const learningSteps = [
  { title: '学习画像', description: '目标与能力诊断', icon: User },
  { title: '领域知识', description: '检索与证据溯源', icon: Connection },
  { title: '专属资源', description: '匹配你的学习目标', icon: Reading },
  { title: '反馈进阶', description: '持续调整下一步', icon: TrendCharts },
]
const features = [
  { index: '01', kind: 'agents', english: 'ORCHESTRATE', title: '多智能体协同', description: '诊断、规划、生成与审核，协作推进同一目标。', path: '#multi-agent' },
  { index: '02', kind: 'evidence', english: 'TRACE', title: '知识有据可依', description: '从事实陈述出发，沿证据追溯知识来源。', path: '#evidence' },
  { index: '03', kind: 'path', english: 'ADAPT', title: '适合你的学习路径', description: '结合画像与诊断，让学习从合适的起点展开。', path: '#learning-path' },
  { index: '04', kind: 'feedback', english: 'EVOLVE', title: '反馈驱动进步', description: '发现薄弱点，调整路线，让下一步更有依据。', path: '#feedback-loop' },
]
function clearErrors() {
  errorMessage.value = ''
  for (const key of Object.keys(fieldErrors)) delete fieldErrors[key]
}
watch(() => [route.name, route.query.login, route.query.auth], () => {
  authMode.value = route.name === 'register' ? 'register' : 'login'
  authVisible.value = route.name === 'register' || route.name === 'login' || route.query.login === '1' || route.query.auth === '1'
  clearErrors()
}, { immediate: true })
function openLogin(event) {
  openingControl = event?.currentTarget || loginTrigger.value
  router.replace({ path: route.path, query: { ...route.query, auth: '1' }, hash: route.hash })
}
function closeAuth() {
  authVisible.value = false
  if (route.name !== 'landing' || route.query.auth || route.query.login) {
    const query = { ...route.query }
    delete query.login
    delete query.auth
    router.replace({ name: 'landing', query, hash: route.hash })
  }
}
function restoreFocus() {
  if (openingControl?.isConnected) openingControl.focus({ preventScroll: true })
  else loginTrigger.value?.focus({ preventScroll: true })
  openingControl = null
}
function targetAfterAuth() {
  const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
  return target.startsWith('/') && !target.startsWith('//') ? target : '/dashboard'
}
async function invalidField(key, message, input) {
  fieldErrors[key] = message
  await nextTick()
  input?.focus()
}
async function submitLogin() {
  if (submitting.value) return
  clearErrors()
  if (!form.username.trim()) return invalidField('username', '请输入用户名', signinUsername.value)
  if (!form.password) return invalidField('password', '请输入密码', signinPassword.value)
  submitting.value = true
  try {
    await auth.login({ username: form.username, password: form.password })
    await router.replace(targetAfterAuth())
  } catch (error) {
    errorMessage.value = error?.response?.data?.message || error?.response?.data?.detail || '登录失败，请稍后重试'
    await nextTick()
    errorSummary.value?.focus()
  } finally {
    submitting.value = false
  }
}
async function submitRegister() {
  if (submitting.value) return
  clearErrors()
  if (!registerForm.username.trim()) return invalidField('username', '请输入用户名', signupUsername.value)
  if (!registerForm.password) return invalidField('password', '请输入密码', { focus: () => document.getElementById('signup-password')?.focus() })
  if (registerForm.password.length < 8) return invalidField('password', '密码至少需要 8 位', { focus: () => document.getElementById('signup-password')?.focus() })
  if (!registerForm.confirm_password || registerForm.password !== registerForm.confirm_password) return invalidField('confirm_password', '请确认两次输入的密码一致', { focus: () => document.getElementById('signup-confirm_password')?.focus() })
  submitting.value = true
  try {
    await auth.register({
      username: registerForm.username, password: registerForm.password, confirm_password: registerForm.confirm_password,
      identity: registerForm.identity || null, education: registerForm.education || null, major: registerForm.major || null,
      job_role: registerForm.job_role || null, experience_years: registerForm.experience_years,
    })
    await router.replace('/dashboard')
  } catch (error) {
    errorMessage.value = error?.response?.data?.message || error?.response?.data?.detail || '注册失败，请稍后重试'
    await nextTick()
    errorSummary.value?.focus()
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.landing-page {
  --entry-ink: #17334a;
  --entry-muted: #536b80;
  --entry-primary: #176d95;
  --entry-line: #6487a433;
  --entry-soft: #e4eff7;
  --entry-ease: cubic-bezier(.22, 1, .36, 1);
  --entry-width: 1320px;
  height: 100vh;
  height: 100dvh;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color-scheme: var(--chapter-scheme, light);
  color: var(--sc-ink, var(--entry-ink));
  background: var(--sc-bg, #eef4f8);
  scroll-behavior: smooth;
}
.landing-page.has-open-dialog .landing-main { overflow: hidden; }
.landing-page a { color: inherit; text-decoration: none; }
.landing-page :is(a, button):focus-visible,
.access-layout :is(a, button, summary):focus-visible { outline: 2px solid #92dcf1; outline-offset: 4px; }
.skip-link { position: fixed; top: 12px; left: 16px; z-index: 100; padding: 12px 18px; background: #fbfdff; color: #17334a; border-radius: 8px; transform: translateY(-150%); }
.skip-link:focus { transform: translateY(0); }
.landing-nav {
  position: relative; z-index: 20; flex-shrink: 0;
  display: flex; align-items: center; justify-content: space-between; gap: 20px;
  min-height: 94px; padding: 18px max(56px, calc((100% - var(--entry-width)) / 2));
  border-bottom: 1px solid var(--sc-line, #9bbcdc18);
  background: var(--sc-bg, #080f1d);
  color: var(--sc-ink, #eef4ff);
  color-scheme: var(--chapter-scheme, dark);
  transition: background-color 450ms var(--entry-ease), color 450ms var(--entry-ease), border-color 450ms var(--entry-ease);
}
.landing-brand, .access-brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
.landing-brand img, .access-brand img { object-fit: contain; flex-shrink: 0; }
.landing-brand strong, .landing-brand small, .access-brand strong, .access-brand small { display: block; }
.landing-brand img { width: 48px; height: 48px; }
.landing-brand strong { font-size: 23px; font-weight: 650; }
.landing-brand small { margin-top: 4px; color: var(--sc-muted, var(--entry-muted)); font-size: 13px; }
.landing-nav-actions { display: flex; align-items: center; gap: 30px; }
.login-trigger, .primary-action, .secondary-action {
  display: inline-flex; align-items: center; justify-content: center; gap: 12px;
  min-height: 46px; padding: 0 22px;
  border: 1px solid transparent; border-radius: 8px; font-weight: 550;
  cursor: pointer; touch-action: manipulation;
  transition: transform 380ms var(--entry-ease), background-color 240ms ease, border-color 240ms ease, box-shadow 380ms ease;
}
.login-trigger { min-height: 48px; border-color: var(--sc-line, #7d9fca40); background: var(--sc-surface, #152137); color: var(--sc-ink, #d9e9fc); font-size: 14px; }
.login-trigger:hover { border-color: var(--sc-accent, #a3c6ef88); background: var(--sc-surface-raised, #1b2d46); transform: translateY(-1px); }
.primary-action { background: #176d95; color: #fff; box-shadow: 0 4px 24px #176d951c; }
.primary-action:hover { background: #125878; box-shadow: 0 8px 32px #176d9532; transform: translateY(-2px); }
.primary-action:active, .login-trigger:active { transform: translateY(0) scale(.98); }
.landing-page .secondary-action { border-color: #7599bf36; background: #fbfdff; color: #17334a; }
.landing-page .secondary-action:hover { border-color: #176d9560; background: #e4eff7; transform: translateY(-2px); }
.landing-main {
  position: relative; flex: 1; min-height: 0;
  overflow-y: auto; overflow-x: hidden;
  scroll-behavior: smooth; scroll-snap-type: y proximity;
  overscroll-behavior-y: contain; scrollbar-width: none;
}
.landing-main::-webkit-scrollbar { display: none; }
.landing-page.is-paged .landing-main { scroll-snap-type: y mandatory; }
.landing-page.has-screen-navigation:not(.is-paged) .landing-main { scroll-snap-type: none; }
.landing-page:not(.has-screen-navigation) .screen-pagination { display: none; }
.landing-screen { position: relative; display: flex; flex-direction: column; justify-content: center; min-height: 100%; padding: 48px 0; scroll-snap-align: start; scroll-snap-stop: always; }
.screen-content { width: min(var(--entry-width), calc(100% - 112px)); margin-inline: auto; }
.overview-screen { padding: 48px 0 76px; background: var(--sc-bg); color: var(--sc-ink); color-scheme: light; }
.landing-hero { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); align-items: center; gap: clamp(30px, 4vw, 58px); }
.screen-cue { position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%); display: flex; align-items: center; justify-content: center; gap: 12px; min-height: 44px; padding: 0 16px; border: 0; background: transparent; color: #536b80; font-size: 12px; cursor: pointer; white-space: nowrap; transition: color 240ms ease; }
.screen-cue .el-icon { font-size: 16px; transition: transform 380ms var(--entry-ease); }
.screen-cue:hover { color: #176d95; }.screen-cue:hover .el-icon { transform: translateY(3px); }
.screen-pagination { position: absolute; z-index: 10; right: 8px; top: calc(50% + 47px); transform: translateY(-50%); display: grid; gap: 2px; padding: 6px 0; border: 0; background: transparent; }
.screen-pagination button { display: flex; align-items: center; justify-content: center; gap: 8px; width: 44px; height: 44px; padding: 0; border: 0; border-radius: 6px; background: transparent; color: #536b80; font-family: Consolas, monospace; font-size: 10px; cursor: pointer; transition: color 280ms ease, background-color 280ms ease; }
.screen-pagination i { width: 3px; height: 22px; border-radius: 3px; background: #738b9d; transform: scaleY(.32); transition: transform 420ms var(--entry-ease), background-color 280ms ease; }
.screen-pagination button[aria-current] { color: #176d95; }.screen-pagination button[aria-current] i { transform: scaleY(1); background: #176d95; }
.screen-pagination button:hover { background: #e4eff7; color: #17334a; }
.hero-content { min-width: 0; animation: entry-reveal 900ms var(--entry-ease) both; }
.hero-kicker { display: inline-flex; align-items: center; gap: 9px; padding: 9px 14px; border: 1px solid #77acd53a; border-radius: 999px; background: #e4eff7; color: #345f79; font-size: 12px; font-weight: 500; }
.hero-kicker > span { width: 5px; height: 5px; border-radius: 50%; background: #176d95; box-shadow: 0 0 9px #92dcf155; }
.hero-content h1 { margin: 28px 0 0; font-size: clamp(42px, 4.8vw, 66px); line-height: 1.35; font-weight: 600; text-wrap: balance; }
.hero-content h1 em { color: #176d95; font-style: normal; }
.hero-content > p { max-width: 550px; margin: 25px 0 0; color: var(--entry-muted); font-size: 17px; line-height: 1.95; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 30px; }
.hero-actions > :is(button, a) { min-height: 54px; padding-inline: 24px; font-size: 16px; }
.hero-assurance { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 24px; color: #536b80; font-size: 12px; }
.hero-assurance > .el-icon { color: #176d95; font-size: 15px; }
.hero-assurance i { width: 2px; height: 2px; background: #748dad; border-radius: 50%; margin-inline: 3px; }
.learning-visual {
  position: relative; min-width: 0; padding: 28px 26px 26px;
  border: 1px solid #7baddf36; border-radius: 18px;
  background: radial-gradient(ellipse at 48% 49%, #c5dfef45, transparent 66%), #fbfdff;
  box-shadow: inset 0 1px 0 #ffffff, 0 24px 80px #315b7810;
  animation: entry-reveal 1000ms 80ms var(--entry-ease) both;
}
.visual-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.visual-eyebrow { color: #536b80; font-family: Consolas, monospace; font-size: 11px; font-weight: 400; }
.visual-tag { flex-shrink: 0; padding: 5px 9px; border: 1px solid #789ecb30; border-radius: 5px; background: #e4eff7; color: #345f79; font-size: 12px; }
.learning-visual h2 { margin: 20px 0 0; font-size: 24px; font-weight: 550; line-height: 1.5; }
.intelligence-map { position: relative; height: 360px; margin-top: 12px; }
.network-lines { position: absolute; inset: 0; width: 100%; height: 100%; }
.intelligence-core {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  width: 156px; height: 156px; border: 1px solid #83b9e15c; border-radius: 50%;
  background: radial-gradient(ellipse at 50% 20%, #f5fcff, #dcecf7 75%);
  box-shadow: inset 0 0 24px #86bded0b, 0 0 50px #58a5ef17;
}
.intelligence-core img { width: 48px; height: 48px; object-fit: contain; }
.intelligence-core strong { margin-top: 8px; color: #17334a; font-size: 16px; font-weight: 550; }
.intelligence-core span { margin-top: 7px; color: #536b80; font-family: Consolas, monospace; font-size: 8px; }
.learning-steps { position: absolute; inset: 0; margin: 0; padding: 0; list-style: none; }
.learning-steps li {
  position: absolute; display: flex; align-items: center; gap: 8px; width: 186px; min-height: 72px;
  padding: 12px; border: 1px solid #769ccb3d; border-radius: 9px;
  background: #fbfdff; box-shadow: 0 6px 24px #315b780b;
}
.learning-steps li:nth-child(1) { top: 18px; left: 0; }
.learning-steps li:nth-child(2) { top: 18px; right: 0; }
.learning-steps li:nth-child(3) { bottom: 18px; left: 0; }
.learning-steps li:nth-child(4) { bottom: 18px; right: 0; }
.step-icon { display: grid; place-items: center; width: 27px; height: 32px; flex-shrink: 0; color: #176d95; font-size: 20px; }
.step-copy { min-width: 0; flex: 1; }.step-copy strong, .step-copy small { display: block; }
.step-copy strong { color: #17334a; font-size: 14px; font-weight: 550; }
.step-copy small { margin-top: 6px; color: #536b80; font-size: 12px; line-height: 1.5; }
.step-number { display: none; }
.loop-note { display: flex; align-items: center; gap: 10px; padding-top: 20px; border-top: 1px solid #6d9fcd24; color: #536b80; font-size: 13px; }
.loop-note .el-icon { color: #176d95; font-size: 16px; }
/* Capability atlas: a light rose / porcelain chapter. */
.feature-section { padding-block: 32px 80px; color: var(--sc-ink); background: var(--sc-bg); color-scheme: var(--chapter-scheme); isolation: isolate; }
.feature-section.is-active .feature-content { animation: entry-reveal 750ms var(--entry-ease) both; }
.feature-section.is-active :deep(.art-signal) { animation: capability-trace 1200ms 150ms var(--entry-ease) both; }
@keyframes capability-trace { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
.feature-section :is(a, button):focus-visible { outline-color: var(--sc-accent); }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 28px; margin-bottom: 30px; }
.section-eyebrow { display: inline-flex; align-items: center; gap: 11px; color: var(--sc-accent); font: 11px Consolas, monospace; letter-spacing: .08em; line-height: 1.6; }
.section-eyebrow > i { width: 26px; height: 1px; background: currentColor; }
.section-heading h2 { margin: 16px 0 0; color: var(--sc-ink); font-size: clamp(36px, 3.4vw, 54px); font-weight: 550; line-height: 1.35; letter-spacing: -.025em; }
.section-heading h2 em { display: block; font-style: normal; color: var(--sc-accent); }
.capability-heading-note { padding-bottom: 4px; text-align: right; }
.capability-heading-note > span { color: var(--sc-muted); font: 10px Consolas, monospace; letter-spacing: .07em; }
.capability-heading-note p { margin: 13px 0 0; color: var(--sc-muted); font-size: 16px; line-height: 1.85; }
.feature-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--sc-line); border-radius: 14px; overflow: hidden; background: var(--sc-surface); box-shadow: 0 24px 60px #653a4b0b, inset 0 1px 0 #ffffffb3; }
.feature-card { position: relative; display: flex; flex-direction: column; min-width: 0; padding: 20px; border: 0; border-radius: 0; background: transparent; transition: background-color 420ms var(--entry-ease); }
.feature-card + .feature-card { border-left: 1px solid var(--sc-line); }
.feature-card::before { content: ''; position: absolute; left: 22px; right: 22px; top: 0; height: 2px; background: var(--sc-accent); opacity: 0; transform: scaleX(.35); transition: transform 500ms var(--entry-ease), opacity 300ms; }
.feature-card:hover, .feature-card:focus-visible { background: var(--sc-surface-raised); }
.feature-card:hover::before, .feature-card:focus-visible::before { opacity: 1; transform: scaleX(1); }
.feature-card:focus-visible { outline-offset: -4px !important; }
.feature-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--sc-muted); font: 10px Consolas, monospace; letter-spacing: .06em; }
.feature-card-top .capability-number { color: var(--sc-accent); font-size: 14px; }
.feature-card .capability-art { margin-block: 13px 7px; transition: transform 650ms var(--entry-ease); }
.feature-card:hover .capability-art, .feature-card:focus-visible .capability-art { transform: translateY(-4px); }
.feature-card h3 { margin: 4px 0 0; color: var(--sc-ink); font-size: 19px; font-weight: 550; line-height: 1.5; }
.feature-card p { flex: 1; margin: 11px 0 18px; color: var(--sc-muted); font-size: 14px; line-height: 1.85; text-wrap: pretty; }
.feature-explore { display: flex; align-items: center; justify-content: space-between; gap: 10px; border-top: 1px solid var(--sc-line); padding-top: 15px; color: var(--sc-muted); font-size: 12px; }
.feature-explore .el-icon { display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid var(--sc-line); border-radius: 50%; color: var(--sc-accent); font-size: 14px; transition: background-color 350ms, transform 350ms var(--entry-ease); }
.feature-card:hover .feature-explore .el-icon { transform: rotate(-35deg); background: #a633550c; }
.feature-invitation { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin-top: 22px; padding: 0 2px; }
.feature-invitation .section-eyebrow { color: var(--sc-muted); font-size: 10px; letter-spacing: .1em; }
.feature-invitation h3 { margin: 7px 0 0; color: var(--sc-ink); font-size: 21px; font-weight: 500; line-height: 1.5; }
.capability-invitation-actions { display: flex; align-items: center; gap: 24px; }
.feature-invitation .primary-action { flex-shrink: 0; min-height: 50px; font-size: 15px; border-radius: 7px; color: var(--sc-on-accent); background: var(--sc-accent); box-shadow: 0 4px 24px #a6335515; }
.feature-invitation .primary-action:hover { background: #8e2948; box-shadow: 0 8px 30px #a6335527; }
.back-to-overview { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 8px; border: 0; border-radius: 6px; color: var(--sc-muted); background: transparent; font-size: 12px; cursor: pointer; }
.back-to-overview:hover { color: var(--sc-ink); }.back-to-overview .el-icon { font-size: 15px; }
.feature-section > .screen-cue { color: var(--sc-muted); }.feature-section > .screen-cue:hover { color: var(--sc-accent); }

:global(.access-overlay) { color-scheme: light; background: #edf2f8ed; backdrop-filter: blur(18px); }
:global(.access-dialog.el-dialog) { padding: 0; height: min(760px, calc(100dvh - 64px)); overflow: hidden; border: 1px solid #ffffff; border-radius: 24px; background: #ffffff; box-shadow: 0 28px 100px #415a8626, 0 4px 16px #415a860d; }
:global(.access-dialog .el-dialog__header) { display: none; }
:global(.access-dialog .el-dialog__body) { height: 100%; max-height: none; overflow: hidden; padding: 0; color: #24334d; overscroll-behavior: contain; scrollbar-color: #c2cce0 #f5f7fb; }
.access-layout { --entry-ease: cubic-bezier(.22, 1, .36, 1); --access-ink: #24334d; --access-muted: #5c6b85; --access-primary: #3e58bd; --access-line: #dbe3ef; display: grid; grid-template-columns: minmax(0, .96fr) minmax(0, 1.04fr); height: 100%; min-height: 0; overflow: hidden; color: var(--access-ink); }
.access-layout :is(a, button, summary):focus-visible { outline: 2px solid #405bbc; outline-offset: 4px; }
.access-story { isolation: isolate; position: relative; display: flex; flex-direction: column; gap: 24px; padding: 36px 36px 25px; border-right: 1px solid #e1e7f2; background: radial-gradient(ellipse at 10% 0%, #e0f3fb, transparent 62%), radial-gradient(ellipse at 90% 55%, #e6e0fd, transparent 68%), #f0f4fb; color: var(--access-ink); overflow: hidden; }
.access-story::before { content: ''; position: absolute; z-index: -1; inset: 0; pointer-events: none; opacity: .32; background-image: linear-gradient(#a8bdd326 1px, transparent 1px), linear-gradient(90deg, #a8bdd326 1px, transparent 1px); background-size: 36px 36px; mask-image: linear-gradient(transparent, #000 65%, transparent); }
.access-story::after { content: ''; position: absolute; pointer-events: none; inset: 12px; z-index: -1; border: 1px solid #ffffffad; border-radius: 15px; }
.access-brand { gap: 11px; }.access-brand strong { font-size: 21px; font-weight: 650; letter-spacing: -.4px; }.access-brand small { color: var(--access-muted); font-size: 11px; margin-top: 5px; }
.access-eyebrow { display: block; color: #536c9b; font: 10px Consolas, monospace; letter-spacing: 1.8px; }
.access-story-copy { margin-top: 13px; }.access-story-title { margin: 17px 0 0; font-size: 32px; font-weight: 600; letter-spacing: -1px; line-height: 1.45; }.access-story-title em { color: #5265b7; font-style: normal; }
.access-story-copy > p:last-child { margin: 15px 0 0; font-size: 14px; color: var(--access-muted); line-height: 1.8; }
.access-portal-art { width: calc(100% + 36px); align-self: center; height: 100%; min-height: 0; flex: 1 1 0; margin: -20px -18px; animation: access-materialize 1300ms var(--entry-ease) both; }
.access-benefits { display: flex; gap: 0; justify-content: space-between; margin: auto 0 0; padding: 0; list-style: none; }
.access-benefits li { display: grid; gap: 8px; }.access-benefits li > span { color: #667b9b; font: 10px Consolas, monospace; }.access-benefits strong { font-size: 13px; font-weight: 500; }
.access-story-footer { display: flex; align-items: center; gap: 8px; margin: 0; padding-top: 18px; border-top: 1px solid #b8c9e54d; color: var(--access-muted); font-size: 11px; }
.access-form-side { position: relative; min-width: 0; display: block; height: 100%; overflow: hidden; padding: 0; background: radial-gradient(ellipse at 95% 0%, #e8edf94f, transparent 50%), #ffffff; }
.access-form-scroll { display: flex; flex-direction: column; height: 100%; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 66px 46px 44px 54px; scrollbar-color: #bcc9e1 #ffffff; scrollbar-width: thin; }
.modal-close { position: absolute; z-index: 2; top: 18px; right: 18px; display: grid; place-items: center; width: 36px; height: 36px; border: 1px solid #e1e6ef; border-radius: 50%; color: #5d6e88; background: #f7f9fc; cursor: pointer; font-size: 18px; transition: background-color 260ms ease, transform 380ms var(--entry-ease); }
.modal-close:hover { background: #eaf0fb; color: #314eaa; transform: rotate(90deg); }
.access-form-panel { flex: 0 0 auto; width: 100%; min-width: 0; margin-block: auto; }.access-form-topline { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 22px; padding-bottom: 13px; border-bottom: 1px solid #e5eaf2; }.access-form-eyebrow { color: #4c6193; font: 10px Consolas, monospace; letter-spacing: 1.5px; }.access-form-index { color: #68768e; font: 9px Consolas, monospace; }
.access-form-panel h2 { margin: 0; color: var(--access-ink); font-size: 38px; font-weight: 600; letter-spacing: -1.2px; line-height: 1.3; }
.access-form-subtitle { margin: 15px 0 30px; color: var(--access-muted); font-size: 14px; line-height: 1.8; }
.access-form :deep(.el-form-item) { display: block; margin-bottom: 24px; }
.access-form :deep(.el-form-item__label) { height: auto; line-height: 1.5; margin-bottom: 9px; padding: 0; color: #40516d; font-size: 13px; font-weight: 500; }
.access-form :deep(.el-input__wrapper) { min-height: 52px; padding: 0 16px; border-radius: 11px; --access-field-fill: #f8faff; background: var(--access-field-fill); box-shadow: 0 0 0 1px #d9e2ef inset, 0 2px 3px #4a609504; transition: box-shadow 280ms ease, background-color 280ms ease; }
.access-form :deep(.el-input__wrapper:hover) { box-shadow: 0 0 0 1px #a4b5da inset; --access-field-fill: #ffffff; background: var(--access-field-fill); }
.access-form :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1.5px #637bc9 inset, 0 0 0 4px #718bdd12; --access-field-fill: #ffffff; background: var(--access-field-fill); }
.access-form :deep(.el-input__inner) { font-size: 16px; color: #263651; background: transparent; border: 0; outline: none; box-shadow: none; caret-color: #4761b9; }.access-form :deep(.el-input__inner::placeholder) { color: #5d6d87; }
.access-form :deep(.el-input__prefix) { margin-right: 9px; color: #6d80a1; }.access-form :deep(.el-form-item__error) { color: #ae3d4d; line-height: 1.4; }
.access-form :deep(.el-input__inner:-webkit-autofill) { -webkit-text-fill-color: #263651; box-shadow: 0 0 0 100px var(--access-field-fill) inset; }
.password-toggle { display: grid; place-items: center; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 6px; background: transparent; color: #607494; cursor: pointer; font-size: 18px; transition: background-color 240ms ease; }.password-toggle:hover { background: #eaf0fa; }
.access-form .access-submit { display: flex; gap: 12px; position: relative; width: 100%; min-height: 52px; margin-top: 7px; border: 1px solid #ffffff33; border-radius: 11px; background: linear-gradient(110deg, #3857ba, #5664c9); background-color: #405bbd; color: #ffffff; font-size: 15px; font-weight: 600; box-shadow: 0 8px 22px #4a60b62b, inset 0 1px 0 #ffffff26; transition: transform 380ms var(--entry-ease), background-color 240ms ease, box-shadow 380ms ease; }
.access-submit :deep(.el-icon:last-child) { margin-left: 12px; }.access-form .access-submit:hover, .access-form .access-submit:focus-visible { background: linear-gradient(110deg, #2e49a5, #4958b9); background-color: #344fae; box-shadow: 0 12px 28px #4a60b63d; transform: translateY(-1px); }.access-form .access-submit:active { transform: translateY(0); box-shadow: 0 3px 10px #4a60b626; }
.access-switch { display: flex; flex-wrap: wrap; justify-content: center; gap: 7px; margin: 26px 0 0; color: var(--access-muted); font-size: 13px; line-height: 1.8; }.access-switch a { color: #405bbd; font-weight: 550; text-decoration: none; }.access-switch a:hover { color: #253e95; text-decoration: underline; }
.access-error { padding: 11px 13px; margin: 0 0 22px; background: #fff2f2; border: 1px solid #eec5ca; border-radius: 10px; color: #9d3544; font-size: 13px; line-height: 1.6; }.register-form :deep(.el-form-item) { margin-bottom: 19px; }
.optional-details { margin: 6px 0 20px; padding: 12px 0; border-block: 1px solid var(--access-line); color: #40516d; }.optional-details summary { cursor: pointer; font-size: 13px; font-weight: 500; line-height: 1.7; }.optional-details summary span { margin-left: 5px; color: var(--access-muted); font-size: 11px; font-weight: 400; }
.optional-fields { padding-top: 20px; }.optional-fields :deep(.el-input-number) { width: 100%; }.optional-fields :deep(.el-input-number .el-input__wrapper) { padding-inline: 40px; }.optional-fields :deep(.el-input-number__decrease), .optional-fields :deep(.el-input-number__increase) { background: #edf2fa; color: #40516d; border-color: #d9e2ef; }
@keyframes access-materialize { from { opacity: 0; transform: translateY(12px) scale(.97); } to { opacity: 1; transform: translateY(0) scale(1); } }
@keyframes entry-reveal { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
@media (min-width: 1600px) {
  .landing-page { --entry-width: 1640px; }
  .landing-brand strong { font-size: 26px; }.landing-brand small { font-size: 14px; }
  .login-trigger { font-size: 16px; }
  .hero-kicker { font-size: 14px; }.hero-content h1 { font-size: clamp(66px, 3.6vw, 78px); }
  .hero-content > p { max-width: 620px; font-size: 19px; }.hero-assurance { font-size: 14px; }
  .hero-actions > :is(button, a) { min-height: 58px; font-size: 18px; padding-inline: 28px; }
  .learning-visual { padding: 32px; }.visual-eyebrow { font-size: 13px; }.visual-tag { font-size: 14px; }
  .learning-visual h2 { font-size: 28px; }.intelligence-map { height: clamp(380px, 38vh, 460px); }
  .learning-steps li { width: 220px; min-height: 84px; padding: 16px; gap: 12px; }.step-icon { font-size: 25px; }
  .step-copy strong { font-size: 16px; }.step-copy small { font-size: 13px; }
  .intelligence-core { width: 184px; height: 184px; }.intelligence-core img { width: 56px; height: 56px; }
  .intelligence-core strong { font-size: 19px; }.intelligence-core span { font-size: 9px; }.loop-note { font-size: 15px; }
  .landing-page[data-theme="capabilities"] .landing-nav { padding-inline: max(72px, calc((100% - 1840px) / 2)); }.feature-section .screen-content { width: min(1840px, calc(100% - 144px)); }.section-heading { margin-bottom: 42px; }.section-heading h2 { font-size: clamp(54px, 3.5vw, 78px); }.capability-heading-note p { font-size: 22px; }.capability-heading-note > span { font-size: 13px; }.section-eyebrow { font-size: 14px; }
  .feature-card { padding: 30px; }.feature-card h3 { font-size: 24px; }.feature-card p { font-size: 18px; margin-bottom: 30px; }.feature-card-top { font-size: 13px; }.feature-card-top .capability-number { font-size: 18px; }.feature-explore { font-size: 15px; padding-top: 20px; }.feature-invitation { margin-top: 34px; }.feature-invitation .section-eyebrow { font-size: 12px; }
  .feature-invitation h3 { font-size: 28px; }.feature-invitation .primary-action { min-height: 56px; font-size: 17px; }
  .screen-cue, .back-to-overview { font-size: 14px; }
}
@media (max-width: 1050px) and (min-width: 821px) { .step-copy strong { font-size: 13px; }.step-copy small { font-size: 11px; } }
@media (max-width: 1050px) { .landing-hero { gap: 28px; }.hero-content h1 { font-size: 42px; }.learning-visual { padding: 22px 18px; }.learning-steps li { width: 150px; padding: 10px; }.step-icon { width: 23px; font-size: 18px; }.step-copy small { font-size: 11px; }.feature-card { padding: 17px; }.feature-card h3 { font-size: 17px; }.feature-card p { font-size: 13px; }.section-heading h2 { font-size: 38px; }.capability-heading-note p { font-size: 14px; }.capability-heading-note > span { font-size: 9px; }.access-form-scroll { padding-inline: 32px; }.access-story { padding-inline: 26px; } }
@media (max-width: 1100px) and (min-width: 821px) { .feature-section { padding-block: 24px 64px; } }
@media (max-height: 760px) and (min-width: 821px) { .overview-screen { padding-block: 28px 68px; }.intelligence-map { height: 286px; }.hero-content h1 { margin-top: 20px; font-size: 42px; }.hero-content > p { margin-top: 18px; }.hero-actions { margin-top: 22px; }.feature-section { padding-block: 24px 70px; }.section-heading { margin-bottom: 22px; }.section-heading h2 { font-size: 34px; }.feature-card { padding-block: 18px; }.feature-invitation { margin-top: 20px; } }
@media (max-width: 820px), (max-height: 679px) { .landing-main { scroll-snap-type: y proximity; scrollbar-width: thin; scrollbar-color: #415776 #080f1d; }.landing-main::-webkit-scrollbar { display: block; width: 5px; }.landing-main::-webkit-scrollbar-thumb { background: #415776; border-radius: 5px; }.landing-screen { padding-block: 40px; }.screen-cue { position: static; transform: none; align-self: center; margin-top: 26px; }.screen-pagination { display: none; } }
@media (max-width: 820px) { .landing-nav { padding-inline: 32px; }.screen-content { width: calc(100% - 64px); }.landing-hero { grid-template-columns: 1fr; gap: 36px; }.hero-content h1 { font-size: clamp(36px, 6vw, 48px); }.learning-visual { max-width: 540px; width: 100%; justify-self: center; }.learning-steps li { width: 170px; padding: 12px; }.step-copy small { font-size: 10px; }.feature-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.feature-card { padding: 22px; }.feature-card:nth-child(3) { border-left: 0; }.feature-card:nth-child(n+3) { border-top: 1px solid var(--sc-line); }.section-heading { align-items: start; flex-direction: column; gap: 20px; }.capability-heading-note { text-align: left; }.capability-heading-note p { font-size: 16px; }.capability-heading-note > span { font-size: 10px; }.feature-card h3 { font-size: 20px; }.feature-card p { font-size: 16px; }.feature-invitation h3 { font-size: 20px; }.capability-invitation-actions { gap: 12px; }.access-layout { grid-template-columns: 1fr; min-height: 0; }.access-story { display: none; }.access-layout { height: 100%; }.access-form-scroll { padding: 64px 40px 36px; } }
@media (max-width: 520px) { .landing-nav { min-height: 72px; padding: 12px 20px; }.landing-brand { gap: 8px; }.landing-brand strong { font-size: 19px; }.landing-brand small { font-size: 10px; }.landing-brand img { width: 36px; height: 36px; }.landing-nav-actions { gap: 0; }.login-trigger { padding-inline: 12px; font-size: 12px; min-height: 42px; gap: 6px; }.screen-content { width: calc(100% - 40px); }.hero-kicker { font-size: 10px; }.hero-content h1 { font-size: 34px; }.hero-content > p { font-size: 14px; }.hero-actions { gap: 10px; }.hero-actions > :is(button, a) { padding-inline: 15px; font-size: 12px; }.learning-visual { padding: 20px 15px; }.visual-eyebrow { font-size: 8px; }.learning-visual h2 { font-size: 17px; }.intelligence-map { height: 310px; }.learning-steps li { width: 136px; min-height: 64px; padding: 9px; gap: 6px; }.step-icon { width: 19px; font-size: 16px; }.step-copy strong { font-size: 11px; }.step-copy small { font-size: 8px; }.intelligence-core { width: 122px; height: 122px; }.intelligence-core strong { font-size: 12px; }.intelligence-core span { font-size: 6px; }.feature-grid { grid-template-columns: 1fr; }.feature-card { padding: 24px; }.feature-card + .feature-card { border-left: 0; border-top: 1px solid var(--sc-line); }.section-heading h2 { font-size: 34px; }:global(.access-dialog.el-dialog) { width: calc(100% - 24px) !important; height: min(660px, calc(100dvh - 24px)); border-radius: 20px; }:global(.access-dialog .el-dialog__body) { height: 100%; max-height: none; }.access-form-scroll { padding: 62px 24px 32px; }.access-form-panel h2 { font-size: 29px; }.access-form :deep(.el-input__inner) { font-size: 16px; } }
@media (max-width: 520px) { .landing-main { width: 100%; }.screen-content { width: calc(100% - 40px); }.feature-invitation { align-items: start; flex-direction: column; gap: 22px; }.capability-invitation-actions { width: 100%; flex-direction: row-reverse; justify-content: space-between; }.feature-invitation .primary-action { flex: 1; }.feature-card h3 { margin-top: 8px; } }
@media (max-height: 600px) { .access-layout { grid-template-columns: 1fr; }.access-story { display: none; } }
@media (prefers-reduced-motion: reduce) { .landing-page, .landing-main { scroll-behavior: auto; }.landing-page *, .access-layout * { transition: none !important; animation: none !important; }:global(.access-overlay), :global(.access-overlay .el-dialog) { transition: none !important; animation: none !important; } }
</style>
