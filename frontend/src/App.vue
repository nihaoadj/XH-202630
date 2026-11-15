<template>
  <router-view v-if="isAuthRoute || isPublicRoute || isResourceFocusMode" />

  <div v-else class="app-shell" :class="{ 'is-sidebar-collapsed': sidebarCollapsed, 'is-sidebar-animating': sidebarAnimating, 'is-dashboard': route.name === 'dashboard', 'is-onboarding': route.name === 'onboarding', 'is-generation': route.name === 'generate', 'is-resources': route.name === 'resources', 'is-feedback': route.name === 'feedback' }">
    <aside ref="sidebarElement" class="sidebar" @pointermove="moveSidebarLight" @pointerleave="resetSidebarLight" @pointercancel="resetSidebarLight">
      <svg class="sidebar-cells" aria-hidden="true">
        <defs>
          <pattern id="sidebar-cell-pattern" x="-8.5" y="-8.5" width="48" height="48" patternUnits="userSpaceOnUse">
            <g fill="#5e95aa" fill-opacity=".20" stroke="#3c758e" stroke-opacity=".40" stroke-width=".7">
              <rect class="sidebar-cell" x="0" y="0" width="16" height="16"/>
              <rect class="sidebar-cell" x="16" y="0" width="16" height="16" style="animation-delay:-.2s"/>
              <rect class="sidebar-cell" x="32" y="0" width="16" height="16" style="animation-delay:-.4s"/>
              <rect class="sidebar-cell" x="0" y="16" width="16" height="16" style="animation-delay:-.4s"/>
              <rect class="sidebar-cell" x="16" y="16" width="16" height="16" style="animation-delay:-.6s"/>
              <rect class="sidebar-cell" x="32" y="16" width="16" height="16" style="animation-delay:-.8s"/>
              <rect class="sidebar-cell" x="0" y="32" width="16" height="16" style="animation-delay:-.8s"/>
              <rect class="sidebar-cell" x="16" y="32" width="16" height="16" style="animation-delay:-1s"/>
              <rect class="sidebar-cell" x="32" y="32" width="16" height="16" style="animation-delay:-1.2s"/>
            </g>
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#sidebar-cell-pattern)"/>
      </svg>
      <svg class="sidebar-orbits" viewBox="38 0 224 340" fill="none" aria-hidden="true">
        <defs>
          <linearGradient id="sidebar-orbit-color" x1="0" y1="340" x2="224" y2="0" gradientUnits="userSpaceOnUse">
            <stop stop-color="#347d97" stop-opacity=".32"/>
            <stop offset="1" stop-color="#55a79c" stop-opacity=".16"/>
          </linearGradient>
        </defs>
        <g class="sidebar-facets" stroke="url(#sidebar-orbit-color)" stroke-linejoin="round">
          <path d="M30 150 192 88 290 148 128 210Z" fill="#ffffff4d"/>
          <path d="M30 196 192 134 290 194 128 256Z" fill="#76aeb51a"/>
          <path d="M30 242 192 180 290 240 128 302Z" fill="#ffffff66"/>
          <path d="M128 210v92M192 88v92" stroke-dasharray="2 6"/>
          <path class="sidebar-orbit-pulse" pathLength="300" d="M30 150 192 88 290 148 128 210 30 150" stroke="#438b9f" stroke-width="1.5"/>
          <path class="sidebar-orbit-pulse sidebar-orbit-pulse-delayed" pathLength="300" d="M30 242 192 180 290 240 128 302 30 242" stroke="#528e90" stroke-width="1.5"/>
        </g>
      </svg>
      <div class="sidebar-inner">
        <div class="brand-block">
          <span class="brand-logo"><img src="/zhiyu-logo.png" alt="智域匠学" /></span>
          <div class="brand-copy">
            <div class="brand-name">智域匠学</div>
            <div class="brand-tag">多智能体领域技能培训平台</div>
          </div>
        </div>

        <nav class="nav-list" aria-label="学习导航">
          <router-link v-for="item in navigation" :key="item.to" :to="item.to" class="nav-item" active-class="is-active" :aria-label="item.label" :title="sidebarCollapsed ? item.label : undefined">
            <el-icon class="nav-icon" aria-hidden="true"><component :is="item.icon" /></el-icon>
            <span class="nav-text">{{ item.label }}</span>
            <small class="nav-hint">{{ item.hint }}</small>
          </router-link>
        </nav>

        <button class="sidebar-toggle" type="button" :aria-label="sidebarCollapsed ? '展开侧栏' : '收起侧栏'" :aria-expanded="!sidebarCollapsed" @click="toggleSidebar">
          <el-icon class="sidebar-toggle-icon" aria-hidden="true"><component :is="sidebarCollapsed ? Expand : Fold" /></el-icon>
          <span class="sidebar-toggle-label">{{ sidebarCollapsed ? '展开侧栏' : '收起侧栏' }}</span>
        </button>

        <button class="logout-button" type="button" aria-label="退出登录" @click="handleLogout">
          <el-icon class="logout-icon" aria-hidden="true"><SwitchButton /></el-icon>
          <span class="logout-label">退出登录</span>
        </button>
      </div>
    </aside>

    <main ref="mainElement" class="main-area" :class="{ 'has-white-workspace': hasWhiteWorkspace }">
      <header class="topbar">
        <svg class="topbar-circuit" viewBox="0 0 900 80" preserveAspectRatio="none" fill="none" aria-hidden="true">
          <g class="topbar-circuit-lines">
            <path class="topbar-circuit-spine" d="M32 40H432 M468 40H868" />
            <g class="topbar-circuit-wing">
              <path d="M112 40V28H284l12 12" />
            </g>
            <g class="topbar-circuit-wing" transform="translate(900 0) scale(-1 1)">
              <path d="M112 40V28H284l12 12" />
            </g>
          </g>
          <path class="topbar-circuit-signal" pathLength="418" d="M450 40H32" />
          <path class="topbar-circuit-signal" pathLength="418" d="M450 40H868" />
          <g class="topbar-circuit-nodes">
            <g class="topbar-circuit-node-wing">
              <circle cx="32" cy="40" r="2" />
              <circle cx="112" cy="40" r="2.2" />
              <circle cx="284" cy="28" r="2" />
              <circle cx="296" cy="40" r="2" />
            </g>
            <g class="topbar-circuit-node-wing" transform="translate(900 0) scale(-1 1)">
              <circle cx="32" cy="40" r="2" />
              <circle cx="112" cy="40" r="2.2" />
              <circle cx="284" cy="28" r="2" />
              <circle cx="296" cy="40" r="2" />
            </g>
          </g>
          <g class="topbar-circuit-core">
            <path d="m450 26 14 14-14 14-14-14z" />
            <circle cx="450" cy="40" r="3.2" />
            <path d="M450 18v4m0 36v4m-26-22h7m38 0h7" />
          </g>
        </svg>
        <div class="topbar-copy">
          <span class="topbar-kicker">{{ currentKicker }}</span>
          <h1>{{ currentTitle }}</h1>
          <p>{{ currentSubtitle }}</p>
        </div>
        <div class="topbar-actions">
          <el-button class="topbar-action" :class="{ 'app-secondary-button': !hasWhiteWorkspace && route.name !== 'onboarding' }" :icon="Clock" aria-label="学习历史" title="学习历史" @click="$router.push('/learning/history')" />
          <el-button class="topbar-action" :class="{ 'app-secondary-button': !hasWhiteWorkspace && route.name !== 'onboarding' }" :icon="DataAnalysis" aria-label="学习报告" title="学习报告" @click="$router.push('/report')" />
          <el-button class="topbar-action" :class="{ 'app-secondary-button': !hasWhiteWorkspace && route.name !== 'onboarding' }" :icon="User" aria-label="用户资料" title="用户资料" @click="$router.push('/user/profile')" />
        </div>
        <div class="topbar-meta">
          <div>
            <span>当前用户</span>
            <strong>{{ auth.currentUser?.username || '未登录' }}</strong>
          </div>
          <div>
            <span>当前方向</span>
            <strong>{{ store.currentLearningDirectionName || '未选择' }}</strong>
          </div>
        </div>
      </header>

      <section class="content-area" :class="{ 'is-contained-scroll': containedScroll }">
        <router-view />
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound, Clock, DataAnalysis, Document, Expand, Fold, HomeFilled, Plus, Reading, SwitchButton, User } from '@element-plus/icons-vue'
import { useAuthStore } from './stores/auth'
import { useAppStore } from './stores/app'
import { installPageMotion } from './ui/motion'

const route = useRoute()
const hasWhiteWorkspace = computed(() =>
  ['dashboard', 'generate', 'resources', 'feedback', 'history', 'report', 'user-profile'].includes(route.name),
)
const router = useRouter()
const disposePageMotion = installPageMotion(router)
const auth = useAuthStore()
const store = useAppStore()
const sidebarCollapsed = ref(localStorage.getItem('app_sidebar_collapsed') === 'true')
const sidebarElement = ref(null)
const mainElement = ref(null)
const sidebarAnimating = ref(false)
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
let sidebarAnimations = []
let sidebarMotionVersion = 0
let shellMounted = false

const navigation = [
  { to: '/dashboard', label: '工作台', hint: '总览学习进度', icon: HomeFilled },
  { to: '/learning/new', label: '新建方向', hint: '5 步完成诊断', icon: Plus },
  { to: '/generate', label: '资源生成', hint: '查看生成任务', icon: Document },
  { to: '/resources', label: '学习资源', hint: '阅读和专注学习', icon: Reading },
  { to: '/feedback', label: '学习反馈', hint: '记录练习结果', icon: ChatDotRound },
]

const containedScroll = computed(() => false)
const isAuthRoute = computed(() => Boolean(route.meta.authLayout))
const isPublicRoute = computed(() => Boolean(route.meta.publicLayout))
const isResourceFocusMode = computed(() => route.name === 'resources' && route.query.focus === '1')

const currentTitle = computed(() => ({
  dashboard: '工作台',
  onboarding: '创建学习方向',
  generate: '资源生成',
  resources: '学习资源',
  feedback: '学习反馈',
  report: '学习报告',
  history: '学习历史',
  'user-profile': '用户资料',
}[route.name] || '智域匠学'))

const currentKicker = computed(() => ({
  dashboard: 'LEARNING WORKSPACE',
  onboarding: 'LEARNING PATH SETUP',
  generate: 'RESOURCE GENERATION',
  resources: 'LEARNING MATERIALS',
  feedback: 'LEARNING FEEDBACK',
  report: 'LEARNING REPORT',
  history: 'LEARNING HISTORY',
  'user-profile': 'LEARNER PROFILE',
}[route.name] || 'LEARNING WORKBENCH'))

const currentSubtitle = computed(() => ({
  dashboard: '围绕当前学习画像和任务进度，快速进入下一步。',
  onboarding: '先完成方向、问卷和诊断，再进入资源生成。',
  generate: '管理生成任务，查看资源批次和运行状态。',
  resources: '查看已生成内容，并进入专注学习模式。',
  feedback: '记录练习表现，驱动下一轮资源生成。',
  report: '汇总诊断、反馈与资源，观察能力变化。',
  history: '回看学习路径、事件记录和关键节点。',
  'user-profile': '维护账号资料，让后续的学习方向复用更顺滑。',
}[route.name] || '智域匠学的统一入口。'))

function stopSidebarMotion() {
  ++sidebarMotionVersion
  for (const animation of sidebarAnimations) animation.cancel()
  sidebarAnimations = []
  sidebarAnimating.value = false
}

function moveSidebarLight(event) {
  if (event.pointerType === 'touch' || reducedMotion.matches || window.innerWidth <= 1080) return
  const sidebar = sidebarElement.value
  const bounds = sidebar.getBoundingClientRect()
  const visibleWidth = Number.parseFloat(getComputedStyle(sidebar.closest('.app-shell')).getPropertyValue('--sidebar-width'))
  const x = event.clientX - bounds.left
  const y = event.clientY - bounds.top
  sidebar.style.setProperty('--sidebar-pointer-x', x + 'px')
  sidebar.style.setProperty('--sidebar-pointer-y', y + 'px')
  sidebar.style.setProperty('--sidebar-shift-x', ((x / visibleWidth - .5) * 6) + 'px')
  sidebar.style.setProperty('--sidebar-shift-y', ((y / bounds.height - .5) * 8) + 'px')
  sidebar.setAttribute('data-pointer', '')
}

function resetSidebarLight() {
  const sidebar = sidebarElement.value
  sidebar?.removeAttribute('data-pointer')
  sidebar?.style.removeProperty('--sidebar-shift-x')
  sidebar?.style.removeProperty('--sidebar-shift-y')
}

async function toggleSidebar() {
  const sidebar = sidebarElement.value
  const main = mainElement.value
  const animate = shellMounted && sidebar && main && window.innerWidth > 1080 && !reducedMotion.matches
  // Read the displayed positions before canceling so rapid reversals stay continuous.
  const previousLeft = animate ? main.getBoundingClientRect().left : 0
  const previousClip = animate ? getComputedStyle(sidebar).clipPath : ''
  const artwork = animate ? sidebar.querySelector('.sidebar-orbits') : null
  const previousArtworkTransform = artwork ? getComputedStyle(artwork).transform : ''
  stopSidebarMotion()
  const version = sidebarMotionVersion
  sidebarCollapsed.value = !sidebarCollapsed.value
  resetSidebarLight()
  localStorage.setItem('app_sidebar_collapsed', String(sidebarCollapsed.value))
  if (!animate) return
  sidebarAnimating.value = true
  await nextTick()
  if (!shellMounted || version !== sidebarMotionVersion) return

  // Commit the new layout once; animate position and clipping without scaling text.
  const offset = previousLeft - main.getBoundingClientRect().left
  const finalClip = getComputedStyle(sidebar).clipPath
  const timing = { duration: sidebarCollapsed.value ? 260 : 300, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' }
  try {
    sidebarAnimations.push(main.animate([{ transform: `translateX(${offset}px)` }, { transform: 'translateX(0)' }], timing))
    sidebarAnimations.push(sidebar.animate([{ clipPath: previousClip }, { clipPath: finalClip }], timing))
    if (artwork) {
      sidebarAnimations.push(artwork.animate([
        { transform: previousArtworkTransform },
        { transform: getComputedStyle(artwork).transform },
      ], timing))
    }
    await Promise.allSettled(sidebarAnimations.map((animation) => animation.finished))
  } catch {
    // The selected state remains usable even if the browser cannot create motion.
    if (version === sidebarMotionVersion) stopSidebarMotion()
  } finally {
    if (version === sidebarMotionVersion) {
      sidebarAnimations = []
      sidebarAnimating.value = false
    }
  }
}

async function handleLogout() {
  await auth.logout()
  await router.replace('/login')
}

watch(() => route.fullPath, stopSidebarMotion)
onMounted(() => {
  shellMounted = true
  window.addEventListener('resize', stopSidebarMotion, { passive: true })
  reducedMotion.addEventListener('change', stopSidebarMotion)
  reducedMotion.addEventListener('change', resetSidebarLight)
})
onBeforeUnmount(() => {
  disposePageMotion()
  shellMounted = false
  stopSidebarMotion()
  window.removeEventListener('resize', stopSidebarMotion)
  reducedMotion.removeEventListener('change', stopSidebarMotion)
  reducedMotion.removeEventListener('change', resetSidebarLight)
})
</script>

<style scoped>
:global(html),
:global(body),
:global(#app) {
  width: 100%;
  height: 100%;
  min-height: 100%;
  margin: 0;
  overflow: hidden;
  background: #eef5ff;
  color: #0f2340;
}

:global(*) {
  box-sizing: border-box;
}

.app-shell {
  --sidebar-open-width:224px;
  --sidebar-width:var(--sidebar-open-width);
  --navigation-ice: #e1eff5;
  --navigation-ice-light: #f2f9fc;
  --navigation-surface:
    radial-gradient(ellipse at 0 0, #cce8f4, transparent 42%),
    linear-gradient(165deg, var(--navigation-ice-light), #eaf5f8 55%, #dcebf3);
  --navigation-line: #c4dce8;
  height: 100vh;
  height: 100dvh;
  min-height: 0;
  display: grid;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.12), transparent 26%),
    linear-gradient(180deg, #f8fbff 0%, #edf4ff 100%);
  color: #10233f;
  overflow: hidden;
}

.app-shell.is-sidebar-collapsed {
  --sidebar-width:72px;
}

.sidebar {
  --sidebar-ink: #152d46;
  --sidebar-text: #264759;
  --sidebar-muted: #466174;
  --sidebar-hover: #f4fafc;
  --sidebar-active: #d6eee9;
  --sidebar-active-ink: #13564f;
  --sidebar-active-line: #7fbdb9;
  --sidebar-focus: #176c88;
  position:relative;
  isolation:isolate;
  z-index:20;
  width:var(--sidebar-open-width);
  height:100%;
  min-width:0;
  background:var(--navigation-surface);
  color:var(--sidebar-ink);
  box-shadow:inset -1px 0 var(--navigation-line);
  clip-path:inset(0 calc(var(--sidebar-open-width) - var(--sidebar-width)) 0 0);
}
.sidebar::before,.sidebar::after {
  position:absolute;
  z-index:-1;
  pointer-events:none;
  content:'';
}
.sidebar::before {
  inset:-8px;
  background:
    repeating-linear-gradient(90deg,transparent 0 15px,#749fb620 15px 16px),
    repeating-linear-gradient(0deg,transparent 0 15px,#749fb61c 15px 16px),
    linear-gradient(90deg,#ffffff50,transparent 32%,#b4d3df24 74%,transparent);
  mask-image:linear-gradient(#0004,transparent 28%,transparent 62%,#000b);
  transform:translate(calc(var(--sidebar-shift-x,0px) * -.5),calc(var(--sidebar-shift-y,0px) * -.5));
  transition:transform 450ms cubic-bezier(.22,1,.36,1);
}
.sidebar::after {
  inset:0;
  background:
    linear-gradient(160deg,#ffffff66,transparent 32%),
    radial-gradient(ellipse at 20% 100%,#80b8c84d,transparent 68%) left bottom / 224px 340px no-repeat;
}
.sidebar-facets {
  transform:translate(var(--sidebar-shift-x,0px),var(--sidebar-shift-y,0px));
  transition:transform 500ms cubic-bezier(.22,1,.36,1);
}
.sidebar-cells {
  position:absolute;
  z-index:-1;
  inset:0;
  width:100%;
  height:100%;
  pointer-events:none;
  mask-image:radial-gradient(ellipse 44px 54px at var(--sidebar-pointer-x,0px) var(--sidebar-pointer-y,0px),#000 20%,transparent 90%);
  opacity:0;
  transform:translate(calc(var(--sidebar-shift-x,0px) * -.5),calc(var(--sidebar-shift-y,0px) * -.5));
  transition:opacity 350ms ease,transform 450ms cubic-bezier(.22,1,.36,1);
}
.sidebar[data-pointer] .sidebar-cells { opacity:1; }
.sidebar-cell { opacity:0; }
.sidebar[data-pointer] .sidebar-cell { animation:sidebar-cell-reveal 2.4s ease-in-out infinite; }
@keyframes sidebar-cell-reveal {
  0%,100% { opacity:0; }
  35%,50% { opacity:.85; }
}
.sidebar-orbits {
  position:absolute;
  z-index:-1;
  left:0;
  bottom:0;
  width:var(--sidebar-open-width);
  height:340px;
  pointer-events:none;
  transform:translateX(calc((var(--sidebar-width) - var(--sidebar-open-width)) / 2));
}
.sidebar-orbit-pulse { stroke-dasharray:12 288; stroke-linecap:round; animation:sidebar-orbit-travel 9s linear infinite; }
.sidebar-orbit-pulse-delayed { animation-duration:12s; animation-delay:-5s; }
@keyframes sidebar-orbit-travel { to { stroke-dashoffset:-300; } }
.sidebar-inner { display:grid; width:var(--sidebar-open-width); height:100%; min-height:0; grid-template-rows:64px minmax(260px,1fr) 44px 44px; gap:18px; padding:22px 10px 18px; overflow-y:auto; scrollbar-width:thin; scrollbar-color:var(--sidebar-muted) var(--navigation-ice); }
.brand-block { display:grid; grid-template-columns:52px minmax(0,1fr); align-items:center; min-width:0; min-height:44px; gap:6px; }
.brand-logo { display:grid; place-items:center; justify-self:center; flex:none; width:44px; height:44px; padding:3px; border:1px solid #aecfdf; border-radius:12px; background:linear-gradient(145deg,#fbfeff,#d8edf7); box-shadow:inset 0 1px #fff,0 3px 8px rgb(42 94 124 / 16%); }
.brand-logo img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  transform: scale(1.28);
  filter: brightness(.88) saturate(1.18) drop-shadow(0 1px 1.5px rgb(40 116 156 / 30%));
}
.brand-copy { width:146px; max-width:100%; min-width:0; white-space:nowrap; opacity:1; transform:translateX(0); transition:opacity 150ms ease 70ms,transform 220ms ease; }
.brand-name { font-size:18px; font-weight:650; line-height:1.4; }
.brand-tag { margin-top:4px; color:var(--sidebar-muted); font-size:10px; line-height:1.7; }
.nav-list { display:grid; grid-template-rows:repeat(5,minmax(0,1fr)); min-width:0; min-height:0; gap:0; }
.nav-item { position:relative; display:grid; grid-template-columns:44px minmax(0,1fr); grid-template-areas:'icon text' 'icon hint'; align-content:center; align-self:center; min-width:0; min-height:58px; padding:9px 4px; border-radius:9px; color:var(--sidebar-text); text-decoration:none; transition:background-color 150ms ease,color 150ms ease; }
.nav-item:hover { background:var(--sidebar-hover); color:var(--sidebar-ink); }
.nav-item.is-active { background:var(--sidebar-active); color:var(--sidebar-active-ink); box-shadow:inset 0 0 0 1px var(--sidebar-active-line),0 4px 12px #35817c23; }
.nav-icon { grid-area:icon; display:grid; place-items:center; justify-self:center; align-self:center; width:28px; min-width:28px; height:28px; border:1px solid #c2dce8; border-radius:8px; background:#f3fafc; font-size:16px; line-height:1; }
.nav-item.is-active .nav-icon { border-color:var(--sidebar-active-line); background:#ebfaf6; }
.nav-text { grid-area:text; font-size:13px; font-weight:550; white-space:nowrap; opacity:1; transform:translateX(0); transition:opacity 150ms ease 70ms,transform 220ms ease; }
.nav-hint { grid-area:hint; padding-top:3px; color:var(--sidebar-muted); font-size:10px; line-height:1.5; font-style:normal; white-space:nowrap; opacity:1; transform:translateX(0); transition:opacity 150ms ease 70ms,transform 220ms ease; }
.nav-item.is-active .nav-hint { color:#345e60; }
.sidebar-toggle,.logout-button { display:flex; align-items:center; justify-content:flex-start; gap:4px; height:44px; margin:0; padding:0 4px; border:0; border-radius:9px; background:transparent; color:var(--sidebar-text); font-family:inherit; font-size:12px; font-weight:500; line-height:1.5; cursor:pointer; transition:background-color 150ms ease,color 150ms ease; }
.sidebar-toggle:hover,.logout-button:hover { border-color:transparent; background:var(--sidebar-hover); color:var(--sidebar-ink); }
.sidebar-toggle-icon,.logout-icon { display:inline-flex; justify-content:center; width:44px; min-width:44px; font-size:18px; }
.sidebar-toggle-label,.logout-label { white-space:nowrap; opacity:1; transform:translateX(0); transition:opacity 150ms ease 70ms,transform 220ms ease; }
.sidebar :is(a,button):focus-visible { outline:3px solid var(--sidebar-focus); outline-offset:2px; }
.is-sidebar-collapsed .brand-copy,.is-sidebar-collapsed .nav-text,.is-sidebar-collapsed .nav-hint,.is-sidebar-collapsed .sidebar-toggle-label,.is-sidebar-collapsed .logout-label { opacity:0; visibility:hidden; transform:translateX(-6px); pointer-events:none; transition:opacity 90ms ease,transform 180ms ease,visibility 0s linear 90ms; }
.is-sidebar-collapsed .nav-item,.is-sidebar-collapsed .sidebar-toggle,.is-sidebar-collapsed .logout-button { width:52px; }
.is-sidebar-animating .sidebar { will-change:clip-path; }
.is-sidebar-animating .main-area { will-change:transform; }

.main-area {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.topbar {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, max-content);
  align-items: flex-start;
  gap: 18px;
  padding: 22px 28px 18px;
}

.topbar-copy {
  min-width: 0;
}

.topbar-actions {
  display: flex;
  position: absolute;
  top: 22px;
  left: 50%;
  align-items: center;
  gap: 10px;
  flex-wrap: nowrap;
  transform: translateX(-50%);
}

.topbar-action {
  min-height: 36px;
  padding-inline: 14px;
}

.topbar-kicker {
  display: block;
  color: #2b66cf;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.topbar h1 {
  margin: 8px 0 0;
  color: #10233f;
  font-size: 26px;
  font-weight: 800;
  line-height: 1.1;
}

.topbar p {
  margin: 8px 0 0;
  color: #5e728d;
  font-size: 14px;
  line-height: 1.6;
}

.topbar-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  min-width: 320px;
}

.topbar-meta > div {
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid #dbe7f4;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.9);
}

.topbar-meta span {
  display: block;
  color: #6d8196;
  font-size: 12px;
}

.topbar-meta strong {
  display: block;
  margin-top: 5px;
  color: #163353;
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.content-area {
  min-width: 0;
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  overflow-x: hidden;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 0 28px 28px;
}

.content-area.is-contained-scroll {
  overflow: hidden;
}

@media (max-width:1080px) {
  .sidebar-orbits { display:none; }
  .app-shell,.app-shell.is-sidebar-collapsed { grid-template-columns:1fr; grid-template-rows:auto minmax(0,1fr); }
  .sidebar { width:100%; height:auto; clip-path:none; box-shadow:inset 0 -1px var(--navigation-line); }
  .sidebar-inner,.is-sidebar-collapsed .sidebar-inner { width:100%; grid-template-columns:44px minmax(0,1fr) 44px 44px; grid-template-rows:auto; align-items:center; gap:12px; height:auto; max-height:none; padding:9px 20px; overflow:visible; }
  .brand-block,.is-sidebar-collapsed .brand-block { display:flex; width:auto; }
  .brand-copy { display:none; }
  .nav-list { grid-template-columns:repeat(5,minmax(0,1fr)); grid-template-rows:auto; gap:4px; }
  .nav-item,.is-sidebar-collapsed .nav-item { display:flex; align-items:center; justify-content:center; gap:7px; width:auto; min-height:44px; padding:8px; }
  .nav-text,.is-sidebar-collapsed .nav-text { display:block; opacity:1; visibility:visible; transform:none; font-size:11px; transition:none; }
  .nav-hint { display:none; }
  .nav-icon { width:24px; min-width:24px; height:24px; font-size:15px; }
  .nav-item.is-active::before { position:absolute; inset:auto 20% 0; height:2px; background:var(--sidebar-focus); content:''; }
  .sidebar-toggle,.logout-button,.is-sidebar-collapsed .sidebar-toggle,.is-sidebar-collapsed .logout-button { justify-content:center; width:44px; padding:0; }
  .sidebar-toggle-icon,.logout-icon { width:20px; min-width:20px; }
  .sidebar-toggle-label,.logout-label { display:none; }

  .topbar {
    position: static;
    display: flex;
    flex-direction: column;
  }

  .topbar-actions {
    position: static;
    transform: none;
    width: 100%;
    flex-wrap: wrap;
  }

  .topbar-meta {
    min-width: 0;
    width: 100%;
  }

  .content-area {
    padding-inline: 20px;
  }
}

@media (max-width: 720px) {
  .topbar {
    padding: 18px 18px 14px;
  }

  .topbar h1 {
    font-size: 24px;
  }

  .topbar-meta {
    grid-template-columns: 1fr;
  }

  .content-area {
    padding: 0 16px 16px;
  }
}
/* Workbench and learning setup share a route-scoped workspace theme. */
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) {
  --dashboard-ink: #172c45;
  --dashboard-muted: #59697b;
  --dashboard-line: #dce2e8;
  --dashboard-focus: #2269ba;
  background: #f5f7f9;
  color: var(--dashboard-ink);
}
:is(.is-onboarding, .has-white-workspace) .topbar { display:grid; grid-template-columns:minmax(120px,1fr) auto auto; align-items:center; gap:27px; min-height:78px; padding:14px 36px; border-bottom:1px solid var(--dashboard-line); background:#fff; }
:is(.is-onboarding, .has-white-workspace) .topbar-copy { display:flex; flex-direction:row-reverse; justify-content:flex-end; align-items:center; gap:15px; }
:is(.is-onboarding, .has-white-workspace) .topbar h1 { margin:0; font-size:18px; font-weight:650; line-height:1.5; color:var(--dashboard-ink); }
:is(.is-onboarding, .has-white-workspace) .topbar-kicker { padding-left:15px; border-left:1px solid var(--dashboard-line); color:var(--dashboard-muted); font:10px/1.5 Consolas,'SFMono-Regular',monospace; }
:is(.is-onboarding, .has-white-workspace) .topbar-copy p { display:none; }
:is(.is-onboarding, .has-white-workspace) .topbar-actions { position:static; transform:none; width:auto; gap:2px; flex-wrap:nowrap; }
:is(.is-onboarding, .has-white-workspace) .topbar-action { min-height:44px; margin:0; padding-inline:12px; border:1px solid transparent; border-radius:4px; background:transparent; color:var(--dashboard-ink); font-size:12px; font-weight:600; }
:is(.is-onboarding, .has-white-workspace) .topbar-action:hover { border-color:transparent; background:#f0f4f7; color:var(--dashboard-ink); }
:is(.is-onboarding, .has-white-workspace) .topbar-meta { display:flex; min-width:0; width:auto; padding-left:24px; border-left:1px solid var(--dashboard-line); }
:is(.is-onboarding, .has-white-workspace) .topbar-meta > div { padding:0; border:0; border-radius:0; background:transparent; }
:is(.is-onboarding, .has-white-workspace) .topbar-meta > div:last-child { display:none; }
:is(.is-onboarding, .has-white-workspace) .topbar-meta span { color:var(--dashboard-muted); font-size:10px; }
:is(.is-onboarding, .has-white-workspace) .topbar-meta strong { max-width:160px; margin-top:3px; white-space:normal; overflow-wrap:anywhere; color:var(--dashboard-ink); font-size:12px; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .content-area { padding:0 36px 24px; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) :is(a,button):focus-visible { outline:3px solid var(--dashboard-focus); outline-offset:3px; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .sidebar :is(a,button):focus-visible { outline-color:var(--sidebar-focus); }
.main-area.has-white-workspace {
  --workbench-topbar-background: transparent;
  --workbench-topbar-overlay: none;
  background:#fff;
}
.is-onboarding .topbar {
  --workbench-topbar-background: #fff;
  --workbench-topbar-overlay: none;
}
.main-area.has-white-workspace .topbar {
  border-bottom: 0;
}
.is-generation :is(.topbar-kicker, .topbar-meta) { border-left-color: var(--navigation-line); }
.is-generation .topbar-action:hover { background: #d6eee9; }
.is-onboarding .content-area:has(.onboarding-page.is-contained-layout) { overflow:hidden; }
@media (max-width:1300px) {
  :is(.is-onboarding, .has-white-workspace) .topbar { gap:18px; padding-inline:28px; }
  :is(.is-onboarding, .has-white-workspace) .topbar-kicker { display:none; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .content-area { padding-inline:28px; }
}
@media (max-width:1080px) {
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback),:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback).is-sidebar-collapsed { grid-template-columns:1fr; grid-template-rows:auto minmax(0,1fr); }
  :is(.is-onboarding, .has-white-workspace) .topbar { min-height:69px; grid-template-columns:minmax(90px,1fr) auto auto; gap:14px; padding:10px 24px; }
  :is(.is-onboarding, .has-white-workspace) .topbar-actions { width:auto; flex-wrap:nowrap; }
  :is(.is-onboarding, .has-white-workspace) .topbar-action { padding-inline:9px; }
  :is(.is-onboarding, .has-white-workspace) .topbar-meta { padding-left:14px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .content-area { padding-inline:24px; }
}
@media (max-width:600px) {
  :is(.is-onboarding, .has-white-workspace) .topbar { position:relative; grid-template-columns:minmax(0,1fr) auto; gap:7px; min-height:0; padding:13px 18px 9px; }
  :is(.is-onboarding, .has-white-workspace) .topbar-copy { grid-column:1; }
  :is(.is-onboarding, .has-white-workspace) .topbar h1 { font-size:17px; }
  :is(.is-onboarding, .has-white-workspace) .topbar-actions { grid-row:2; grid-column:1/-1; gap:5px; }
  :is(.is-onboarding, .has-white-workspace) .topbar-action { min-height:38px; padding-inline:8px; font-size:11px; }
  :is(.is-onboarding, .has-white-workspace) .topbar-meta { grid-column:2; grid-row:1; padding-left:0; border-left:0; }
  :is(.is-onboarding, .has-white-workspace) .topbar-meta span { display:none; }
  :is(.is-onboarding, .has-white-workspace) .topbar-meta strong { max-width:160px; margin:0; font-size:11px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .content-area { padding:0 18px 22px; }
}
@media (min-width:1100px) and (min-height:640px) {
  .is-dashboard .content-area { padding:14px 28px; }
  .is-dashboard .content-area:has(.home-page.is-fit-layout) { overflow:hidden; }
  .is-onboarding .topbar { flex:0 0 auto; min-height:60px; padding:8px 48px; }
  .is-onboarding .content-area { padding:0 28px 24px; }
  .is-onboarding .content-area:has(.onboarding-page.is-fit-layout) { overflow:hidden; }
  .is-generation .content-area { padding:0 28px 16px; }
  .is-resources .content-area { padding:0 28px 16px; }
  .is-feedback .content-area { padding:0 28px 24px; }
  .is-generation .content-area:has(.generate-page.is-fit-layout) { overflow:hidden; }
}
@media (max-width:1300px) and (min-width:1081px) {
  .app-shell { --sidebar-open-width:200px; }
  .brand-tag { font-size:9px; }
}
@media (min-width:1081px) and (max-height:760px) {
  .sidebar-inner { grid-template-rows:50px minmax(240px,1fr) 40px 40px; gap:12px; padding:14px 10px; }
  .nav-item { min-height:48px; padding-block:7px; }
  .sidebar-toggle,.logout-button { height:40px; }
}
@media (max-width:600px) {
  .sidebar-inner,.is-sidebar-collapsed .sidebar-inner { grid-template-columns:minmax(0,1fr) 36px 36px; gap:5px; padding:7px 10px; }
  .brand-block { display:none; }
  .nav-list { gap:2px; }
  .nav-item,.is-sidebar-collapsed .nav-item { gap:0; padding:6px 4px; }
  .nav-text,.is-sidebar-collapsed .nav-text { display:none; }
  .sidebar-toggle,.logout-button,.is-sidebar-collapsed .sidebar-toggle,.is-sidebar-collapsed .logout-button { width:36px; min-width:0; }
}
@media (prefers-reduced-motion:reduce) {
  .sidebar-cells { display:none; }
  .app-shell,.sidebar *, .sidebar *::before,.is-dashboard *, .is-dashboard *::before { transition:none !important; animation:none !important; }
}

/* A shared instrument-panel header for every signed-in workspace page. */
:global(.app-shell .main-area .topbar) {
  position: relative;
  isolation: isolate;
  border-bottom-color: #d5e2e8 !important;
  background: var(--workbench-topbar-background, #f4f8fa) !important;
}

:global(.app-shell .main-area .topbar::before) {
  position: absolute;
  z-index: 0;
  inset: 0;
  background: var(--workbench-topbar-overlay,
    radial-gradient(ellipse at 50% 50%, rgba(106, 184, 178, .12), transparent 29%),
    linear-gradient(102deg, #f8fbfc 0%, #f3f7f9 72%, #f5f9fa 100%));
  content: '';
  pointer-events: none;
}

:global(.app-shell .main-area .topbar-circuit) {
  position: absolute;
  z-index: 0;
  top: 0;
  left: 50%;
  width: min(62%, 900px);
  height: 100%;
  overflow: visible;
  color: #43899b;
  opacity: .64;
  transform: translateX(-50%);
  pointer-events: none;
}

:global(.app-shell .main-area .topbar-circuit-lines) {
  stroke: currentColor;
  stroke-width: 1.15;
  vector-effect: non-scaling-stroke;
}

:global(.app-shell .main-area .topbar-circuit-spine) {
  stroke-opacity: .48;
}

:global(.app-shell .main-area .topbar-circuit-nodes) {
  fill: #91d8ce;
  stroke: #367f91;
  stroke-width: .9;
  vector-effect: non-scaling-stroke;
}

:global(.app-shell .main-area .topbar-circuit-core) {
  fill: none;
  stroke: #438f98;
  stroke-width: 1.2;
  vector-effect: non-scaling-stroke;
}

:global(.app-shell .main-area .topbar-circuit-core circle) {
  fill: #8cdbd0;
  stroke: #397f8c;
}

:global(.app-shell .main-area .topbar-circuit-signal) {
  stroke: #258f97;
  stroke-width: 1.4;
  stroke-dasharray: 22 396;
  opacity: .75;
  vector-effect: non-scaling-stroke;
  animation: topbar-signal-drift 16s linear infinite;
}

:global(.app-shell .main-area .topbar-copy),
:global(.app-shell .main-area .topbar-actions),
:global(.app-shell .main-area .topbar-meta) {
  position: relative;
  z-index: 1;
}

:global(.app-shell .main-area .topbar-actions) {
  top: auto !important;
  right: auto !important;
  left: auto !important;
  gap: 6px !important;
  transform: none !important;
}

:global(.app-shell .main-area .topbar-kicker) {
  position: relative;
  letter-spacing: .075em !important;
}

:global(.app-shell .main-area .topbar-kicker::before) {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 8px;
  border: 1px solid #4b9f9f;
  background: #c4e9e3;
  box-shadow: 0 0 0 2px rgba(89, 170, 166, .1);
  content: '';
  transform: rotate(45deg);
  vertical-align: 1px;
}

:global(.app-shell .main-area .topbar h1::before) {
  display: inline-block;
  width: 3px;
  height: .92em;
  margin-right: 9px;
  background: linear-gradient(180deg, #73c6b8, #307f99);
  border-radius: 2px;
  content: '';
  vertical-align: -.08em;
}

:global(.app-shell .main-area .topbar-actions .topbar-action) {
  position: relative;
  overflow: hidden;
  display: inline-flex !important;
  width: 36px !important;
  min-width: 36px !important;
  height: 36px !important;
  min-height: 36px !important;
  padding: 0 !important;
  border: 1px solid #d5e3e8 !important;
  border-radius: 8px !important;
  background: rgba(255, 255, 255, .66) !important;
  box-shadow: inset 0 1px rgba(255, 255, 255, .9), 0 1px 2px rgba(20, 50, 68, .035) !important;
  color: #385267 !important;
  font-size: 0 !important;
  font-weight: 600 !important;
  transition: transform .2s ease, border-color .2s ease, background-color .2s ease, box-shadow .2s ease, color .2s ease !important;
}

:global(.app-shell .main-area .topbar-actions .topbar-action .el-icon) {
  width: 17px !important;
  height: 17px !important;
  color: #287f8d !important;
  font-size: 16px !important;
  transition: color .2s ease, transform .2s ease !important;
}

:global(.app-shell .main-area .topbar-actions .topbar-action:hover) {
  transform: translateY(-1px);
  border-color: #88bdbd !important;
  background: #fff !important;
  box-shadow: inset 0 1px #fff, 0 4px 12px rgba(27, 92, 107, .1) !important;
  color: #145a68 !important;
}

:global(.app-shell .main-area .topbar-actions .topbar-action:hover .el-icon) {
  color: #138b91 !important;
  transform: translateY(-1px);
}

:global(.app-shell .main-area .topbar-actions .topbar-action:focus-visible) {
  outline: 2px solid #398d99 !important;
  outline-offset: 2px;
}

:global(.app-shell .main-area .topbar-meta) {
  position: relative;
}

:global(.app-shell .main-area .topbar-meta > div:first-child) {
  min-width: 86px;
  padding: 5px 9px 5px 11px !important;
  border: 1px solid rgba(190, 212, 220, .74) !important;
  border-radius: 5px !important;
  background: rgba(255, 255, 255, .54) !important;
  box-shadow: inset 2px 0 #68b5ae, inset 0 1px rgba(255, 255, 255, .95) !important;
}

:global(.app-shell .main-area .topbar-meta > div:first-child span) {
  color: #708694 !important;
  font-size: 9px !important;
  letter-spacing: .045em;
}

:global(.app-shell .main-area .topbar-meta > div:first-child strong) {
  margin-top: 2px !important;
  color: #213e53 !important;
  font-size: 11px !important;
}

:global(.app-shell .main-area .topbar-meta > div:first-child strong::before) {
  display: inline-block;
  width: 5px;
  height: 5px;
  margin-right: 6px;
  border: 1px solid #4c999b;
  content: '';
  transform: rotate(45deg);
  vertical-align: 1px;
}

.main-area.has-white-workspace .topbar { background: transparent; border-bottom-color: #dfe4e8; }
.main-area.has-white-workspace .topbar-kicker { color: #086575; font: 11px/1.5 Consolas, 'SFMono-Regular', monospace; }
.main-area.has-white-workspace .topbar h1 { color: #132c40; font-weight: 700; }
.main-area.has-white-workspace .topbar-meta span { color: #536b7d; }
.main-area.has-white-workspace .topbar-meta strong { color: #132c40; }
@media (min-width: 1100px) {
  .main-area.has-white-workspace .topbar {
    height: 60px;
    min-height: 60px;
    align-items: center;
    padding: 10px 28px 0;
    flex: 0 0 60px;
  }
  .main-area.has-white-workspace .topbar-circuit { top: 5px; }
}
.main-area.has-white-workspace .topbar-meta { padding-left: 0; border-left: 0; }
.main-area.has-white-workspace .topbar-meta > div:first-child {
  display: grid;
  align-content: center;
  gap: 3px;
  min-width: 104px;
  padding: 7px 13px !important;
}
:is(.has-white-workspace, .is-onboarding .main-area) .topbar-meta > div:first-child {
  border: 1px solid transparent !important;
  border-radius: 11px !important;
  background: linear-gradient(135deg, #fff, #edf4ff) padding-box, linear-gradient(145deg, #d7e7fa, #99b7da) border-box !important;
  box-shadow: inset 0 1px 0 #fff, inset 0 -1px 1px rgb(112 152 199 / 12%), 0 3px 8px rgb(40 80 128 / 9%) !important;
}
.main-area.has-white-workspace .topbar-meta > div:first-child span { line-height: 12px; }
.main-area.has-white-workspace .topbar-meta > div:first-child strong { margin-top: 0 !important; line-height: 13px; }
:is(.has-white-workspace, .is-onboarding .main-area) .topbar-meta > div:first-child span { color: #69809c !important; }
:is(.has-white-workspace, .is-onboarding .main-area) .topbar-meta > div:first-child strong { color: #294f7c !important; }
@media (min-width: 601px) {
  :is(.main-area.has-white-workspace, .is-onboarding .main-area) .topbar {
    --workbench-topbar-divider-height: 32px;
    --workbench-topbar-divider-color: #c5d6e9;
  }
  .is-onboarding .topbar-meta { border-left-color: transparent; }
  :is(.main-area.has-white-workspace, .is-onboarding .main-area) .topbar-meta::before {
    position: absolute;
    inset-block-start: 50%;
    inset-inline-start: -1px;
    width: 1px;
    height: var(--workbench-topbar-divider-height);
    background: var(--workbench-topbar-divider-color);
    content: '';
    transform: translateY(-50%);
  }
  .main-area.has-white-workspace .topbar-meta::before { inset-inline-start: -8px; }
}
@media (min-width: 1301px) {
  .main-area.has-white-workspace .topbar-meta::before { inset-inline-start: -14px; }
  :is(.main-area.has-white-workspace, .is-onboarding .main-area) .topbar-kicker { border-left-color: transparent; }
  :is(.main-area.has-white-workspace, .is-onboarding .main-area) .topbar-kicker::after {
    position: absolute;
    inset-block-start: 50%;
    inset-inline-start: -1px;
    width: 1px;
    height: var(--workbench-topbar-divider-height);
    background: var(--workbench-topbar-divider-color);
    content: '';
    transform: translateY(-50%);
  }
}
:is(.main-area.has-white-workspace, .is-onboarding .main-area) .topbar-meta > div:first-child strong::before { width: 5px; height: 5px; border: 1px solid #b8cee9; border-radius: 50%; background: #638ec3; box-shadow: 0 0 0 2px rgb(99 142 195 / 9%); transform: none; }
@media (max-width: 600px) {
  .main-area.has-white-workspace .topbar { min-height: 0; padding-block: 18px 9px; }
  .main-area.has-white-workspace .topbar-meta > div:first-child { min-width: 0; padding: 6px 11px !important; }
}

@keyframes topbar-signal-drift {
  to { stroke-dashoffset: -418; }
}

@media (max-width: 720px) {
  :global(.app-shell .main-area .topbar-circuit) { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  :global(.app-shell .main-area .topbar-circuit-signal) { animation: none; }
  :global(.app-shell .main-area .topbar-actions .topbar-action),
  :global(.app-shell .main-area .topbar-actions .topbar-action .el-icon) { transition: none !important; }
}

:global(.app-shell.is-onboarding .content-area:has(.onboarding-page.is-fit-layout)) {
  padding: 0 !important;
  scrollbar-gutter: auto !important;
}

/* 问卷/诊断/资源选择等 contained 阶段与 fit 阶段同样贴边，不留内容区间隙。 */
@media (min-width: 1100px) and (min-height: 640px) {
  :global(.app-shell.is-onboarding .content-area:has(.onboarding-page)) {
    padding: 0 !important;
    scrollbar-gutter: auto !important;
  }
}
</style>
