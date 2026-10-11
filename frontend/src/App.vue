<template>
  <router-view v-if="isAuthRoute || isPublicRoute || isResourceFocusMode" />

  <div v-else class="app-shell" :class="{ 'is-sidebar-collapsed': sidebarCollapsed, 'is-sidebar-animating': sidebarAnimating, 'is-dashboard': route.name === 'dashboard', 'is-onboarding': route.name === 'onboarding', 'is-generation': route.name === 'generate', 'is-resources': route.name === 'resources', 'is-feedback': route.name === 'feedback' }">
    <aside ref="sidebarElement" class="sidebar">
      <div class="sidebar-inner">
        <div class="brand-block">
          <img class="brand-logo" src="/zhiyu-logo.png" alt="智域匠学" />
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

        <section class="context-panel" :inert="sidebarCollapsed" :aria-hidden="sidebarCollapsed">
          <div class="context-title">当前学习</div>
          <div class="context-row">
            <span>方向</span>
            <strong>{{ store.currentLearningDirectionName || '未选择' }}</strong>
          </div>
          <div class="context-row">
            <span>画像</span>
            <strong>{{ store.currentProfile?.skill_level || '待诊断' }}</strong>
          </div>
          <router-link class="context-link" to="/learning/new">
            {{ store.currentLearningDirectionName ? '修改学习方向' : '去新建方向' }}
          </router-link>
        </section>

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

    <main ref="mainElement" class="main-area">
      <header class="topbar">
        <div class="topbar-copy">
          <span class="topbar-kicker">DOMAIN SKILL WORKBENCH</span>
          <h1>{{ currentTitle }}</h1>
          <p>{{ currentSubtitle }}</p>
        </div>
        <div class="topbar-actions">
          <el-button class="topbar-action" :class="{ 'app-secondary-button': !['dashboard', 'onboarding', 'generate', 'resources', 'feedback'].includes(route.name) }" :icon="Clock" @click="$router.push('/learning/history')">学习历史</el-button>
          <el-button class="topbar-action" :class="{ 'app-secondary-button': !['dashboard', 'onboarding', 'generate', 'resources', 'feedback'].includes(route.name) }" :icon="DataAnalysis" @click="$router.push('/report')">学习报告</el-button>
          <el-button class="topbar-action" :class="{ 'app-secondary-button': !['dashboard', 'onboarding', 'generate', 'resources', 'feedback'].includes(route.name) }" :icon="Collection" @click="$router.push('/user/profile')">用户资料</el-button>
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
import { Clock, Collection, DataAnalysis, Document, Expand, Fold, Plus, Reading, ChatDotRound, HomeFilled, SwitchButton } from '@element-plus/icons-vue'
import { useAuthStore } from './stores/auth'
import { useAppStore } from './stores/app'
import { installPageMotion } from './ui/motion'

const route = useRoute()
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

async function toggleSidebar() {
  const sidebar = sidebarElement.value
  const main = mainElement.value
  const animate = shellMounted && sidebar && main && window.innerWidth > 1080 && !reducedMotion.matches
  // Read the displayed positions before canceling so rapid reversals stay continuous.
  const previousLeft = animate ? main.getBoundingClientRect().left : 0
  const previousClip = animate ? getComputedStyle(sidebar).clipPath : ''
  const navItems = animate ? [...sidebar.querySelectorAll('.nav-item')] : []
  const previousNav = navItems.map((item) => item.getBoundingClientRect().top)
  stopSidebarMotion()
  const version = sidebarMotionVersion
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('app_sidebar_collapsed', String(sidebarCollapsed.value))
  if (!animate) return
  sidebarAnimating.value = true
  await nextTick()
  if (!shellMounted || version !== sidebarMotionVersion) return

  // Commit the new layout once; animate position and clipping without scaling text.
  const offset = previousLeft - main.getBoundingClientRect().left
  const finalClip = getComputedStyle(sidebar).clipPath
  const navOffsets = navItems.map((item, index) => previousNav[index] - item.getBoundingClientRect().top)
  const timing = { duration: sidebarCollapsed.value ? 260 : 300, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' }
  try {
    sidebarAnimations.push(main.animate([{ transform: `translateX(${offset}px)` }, { transform: 'translateX(0)' }], timing))
    sidebarAnimations.push(sidebar.animate([{ clipPath: previousClip }, { clipPath: finalClip }], timing))
    navItems.forEach((item, index) => sidebarAnimations.push(item.animate([{ transform: `translateY(${navOffsets[index]}px)` }, { transform: 'translateY(0)' }], timing)))
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
})
onBeforeUnmount(() => {
  disposePageMotion()
  shellMounted = false
  stopSidebarMotion()
  window.removeEventListener('resize', stopSidebarMotion)
  reducedMotion.removeEventListener('change', stopSidebarMotion)
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
  position:relative;
  z-index:20;
  width:var(--sidebar-open-width);
  height:100%;
  min-width:0;
  background:#102339;
  color:#f3f7fc;
  clip-path:inset(0 calc(var(--sidebar-open-width) - var(--sidebar-width)) 0 0);
}
.sidebar-inner { display:grid; width:var(--sidebar-open-width); height:100%; min-height:0; grid-template-rows:64px minmax(260px,1fr) auto 44px 44px; gap:18px; padding:22px 10px 18px; overflow-y:auto; scrollbar-width:thin; scrollbar-color:#5b7590 #102339; }
.brand-block { display:grid; grid-template-columns:52px minmax(0,1fr); align-items:center; min-width:0; min-height:44px; gap:6px; }
.brand-logo { justify-self:center; width:44px; height:44px; object-fit:contain; }
.brand-copy { width:146px; max-width:100%; min-width:0; white-space:nowrap; opacity:1; transform:translateX(0); transition:opacity 150ms ease 70ms,transform 220ms ease; }
.brand-name { font-size:18px; font-weight:650; line-height:1.4; }
.brand-tag { margin-top:4px; color:#b4c7da; font-size:10px; line-height:1.7; }
.nav-list { display:grid; grid-template-rows:repeat(5,minmax(0,1fr)); min-width:0; min-height:0; gap:0; }
.nav-item { position:relative; display:grid; grid-template-columns:44px minmax(0,1fr); grid-template-areas:'icon text' 'icon hint'; align-content:center; align-self:center; min-width:0; min-height:58px; padding:9px 4px; border-radius:4px; color:#c5d3e1; text-decoration:none; transition:background-color 150ms ease,color 150ms ease; }
.nav-item:hover { background:#1a344c; color:#fff; }
.nav-item.is-active { background:#203b50; color:#adf3e8; }
.nav-item.is-active::before { position:absolute; inset:13px auto 13px 0; width:2px; background:#9cf2e0; content:''; }
.nav-icon { grid-area:icon; justify-self:center; align-self:center; width:20px; min-width:20px; font-size:18px; line-height:1; }
.nav-text { grid-area:text; font-size:13px; font-weight:550; white-space:nowrap; opacity:1; transform:translateX(0); transition:opacity 150ms ease 70ms,transform 220ms ease; }
.nav-hint { grid-area:hint; padding-top:3px; color:#b4c7da; font-size:10px; line-height:1.5; font-style:normal; white-space:nowrap; opacity:1; transform:translateX(0); transition:opacity 150ms ease 70ms,transform 220ms ease; }
.context-panel { display:flex; min-width:0; flex-direction:column; gap:10px; margin:0 9px; padding:17px 0 10px; border:0; border-top:1px solid #3a5065; overflow:hidden; opacity:1; transition:opacity 150ms ease 70ms; }
.context-title { color:#b4c7da; font-size:11px; font-weight:650; letter-spacing:.04em; }
.context-row { display:flex; flex-direction:column; gap:3px; }
.context-row span { color:#b4c7da; font-size:11px; }
.context-row strong { color:#e8eff5; font-size:12px; line-height:1.35; overflow-wrap:anywhere; }
.context-link { color:#a4e5de; font-size:11px; font-weight:600; text-decoration:none; }
.context-link:hover { color:#fff; text-decoration:underline; }
.sidebar-toggle,.logout-button { display:flex; align-items:center; justify-content:flex-start; gap:4px; height:44px; margin:0; padding:0 4px; border:0; border-radius:4px; background:transparent; color:#c5d3e1; font-family:inherit; font-size:12px; font-weight:500; line-height:1.5; cursor:pointer; transition:background-color 150ms ease,color 150ms ease; }
.sidebar-toggle:hover,.logout-button:hover { border-color:transparent; background:#20384d; color:#fff; }
.sidebar-toggle-icon,.logout-icon { display:inline-flex; justify-content:center; width:44px; min-width:44px; font-size:18px; }
.sidebar-toggle-label,.logout-label { white-space:nowrap; opacity:1; transform:translateX(0); transition:opacity 150ms ease 70ms,transform 220ms ease; }
.sidebar :is(a,button):focus-visible { outline:3px solid #9cf2e0; outline-offset:2px; }
.is-sidebar-collapsed .sidebar-inner { grid-template-rows:64px minmax(260px,1fr) 0px 44px 44px; }
.is-sidebar-collapsed .brand-copy,.is-sidebar-collapsed .nav-text,.is-sidebar-collapsed .nav-hint,.is-sidebar-collapsed .sidebar-toggle-label,.is-sidebar-collapsed .logout-label { opacity:0; visibility:hidden; transform:translateX(-6px); pointer-events:none; transition:opacity 90ms ease,transform 180ms ease,visibility 0s linear 90ms; }
.is-sidebar-collapsed .context-panel { height:0; margin:0; padding:0; border:0; opacity:0; pointer-events:none; transition:none; }
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
  .app-shell,.app-shell.is-sidebar-collapsed { grid-template-columns:1fr; grid-template-rows:auto minmax(0,1fr); }
  .sidebar { width:100%; height:auto; clip-path:none; }
  .sidebar-inner,.is-sidebar-collapsed .sidebar-inner { width:100%; grid-template-columns:44px minmax(0,1fr) 44px 44px; grid-template-rows:auto; align-items:center; gap:12px; height:auto; max-height:none; padding:9px 20px; overflow:visible; }
  .brand-block,.is-sidebar-collapsed .brand-block { display:flex; width:auto; }
  .brand-copy,.context-panel { display:none; }
  .nav-list { grid-template-columns:repeat(5,minmax(0,1fr)); grid-template-rows:auto; gap:4px; }
  .nav-item,.is-sidebar-collapsed .nav-item { display:flex; align-items:center; justify-content:center; gap:7px; width:auto; min-height:44px; padding:8px; }
  .nav-text,.is-sidebar-collapsed .nav-text { display:block; opacity:1; visibility:visible; transform:none; font-size:11px; transition:none; }
  .nav-hint { display:none; }
  .nav-icon { width:18px; min-width:18px; font-size:17px; }
  .nav-item.is-active::before { inset:auto 20% 0; width:auto; height:2px; }
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
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar { display:grid; grid-template-columns:minmax(120px,1fr) auto auto; align-items:center; gap:27px; min-height:78px; padding:14px 36px; border-bottom:1px solid var(--dashboard-line); background:#fff; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-copy { display:flex; flex-direction:row-reverse; justify-content:flex-end; align-items:center; gap:15px; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar h1 { margin:0; font-size:18px; font-weight:650; line-height:1.5; color:var(--dashboard-ink); }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-kicker { padding-left:15px; border-left:1px solid var(--dashboard-line); color:var(--dashboard-muted); font:10px/1.5 Consolas,'SFMono-Regular',monospace; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-copy p { display:none; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-actions { position:static; transform:none; width:auto; gap:2px; flex-wrap:nowrap; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-action { min-height:44px; margin:0; padding-inline:12px; border:1px solid transparent; border-radius:4px; background:transparent; color:var(--dashboard-muted); font-size:12px; font-weight:500; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-action:hover { border-color:transparent; background:#f0f4f7; color:var(--dashboard-ink); }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-meta { display:flex; min-width:0; width:auto; padding-left:24px; border-left:1px solid var(--dashboard-line); }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-meta > div { padding:0; border:0; border-radius:0; background:transparent; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-meta > div:last-child { display:none; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-meta span { color:var(--dashboard-muted); font-size:10px; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-meta strong { max-width:160px; margin-top:3px; white-space:normal; overflow-wrap:anywhere; color:var(--dashboard-ink); font-size:12px; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .content-area { padding:0 36px 24px; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) :is(a,button):focus-visible { outline:3px solid var(--dashboard-focus); outline-offset:3px; }
:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .sidebar :is(a,button):focus-visible { outline-color:#9cf2e0; }
.is-onboarding .content-area:has(.onboarding-page.is-contained-layout) { overflow:hidden; }
@media (max-width:1300px) {
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar { gap:18px; padding-inline:28px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-kicker { display:none; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .content-area { padding-inline:28px; }
}
@media (max-width:1080px) {
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback),:is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback).is-sidebar-collapsed { grid-template-columns:1fr; grid-template-rows:auto minmax(0,1fr); }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar { min-height:69px; grid-template-columns:minmax(90px,1fr) auto auto; gap:14px; padding:10px 24px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-actions { width:auto; flex-wrap:nowrap; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-action { padding-inline:9px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-meta { padding-left:14px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .content-area { padding-inline:24px; }
}
@media (max-width:600px) {
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar { position:relative; grid-template-columns:minmax(0,1fr) auto; gap:7px; min-height:0; padding:13px 18px 9px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-copy { grid-column:1; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar h1 { font-size:17px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-actions { grid-row:2; grid-column:1/-1; gap:5px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-action { min-height:38px; padding-inline:8px; font-size:11px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-meta { grid-column:2; grid-row:1; padding-left:0; border-left:0; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-meta span { display:none; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .topbar-meta strong { max-width:160px; margin:0; font-size:11px; }
  :is(.is-dashboard,.is-onboarding,.is-generation,.is-resources,.is-feedback) .content-area { padding:0 18px 22px; }
}
@media (min-width:1100px) and (min-height:640px) {
  .is-dashboard .topbar { flex:0 0 auto; min-height:60px; padding:8px 28px; }
  .is-dashboard .content-area { padding:14px 28px; }
  .is-dashboard .content-area:has(.home-page.is-fit-layout) { overflow:hidden; }
  .is-onboarding .topbar { flex:0 0 auto; min-height:60px; padding:8px 28px; }
  .is-onboarding .content-area { padding:0 28px 24px; }
  .is-onboarding .content-area:has(.onboarding-page.is-fit-layout) { overflow:hidden; }
  .is-generation .topbar { flex:0 0 auto; min-height:60px; padding:8px 28px; }
  .is-generation .content-area { padding:0 28px 16px; }
  .is-resources .topbar { flex:0 0 auto; min-height:60px; padding:8px 28px; }
  .is-resources .content-area { padding:0 28px 16px; }
  .is-feedback .topbar { flex:0 0 auto; min-height:60px; padding:8px 28px; }
  .is-feedback .content-area { padding:0 28px 24px; }
  .is-generation .content-area:has(.generate-page.is-fit-layout) { overflow:hidden; }
}
@media (max-width:1300px) and (min-width:1081px) {
  .app-shell { --sidebar-open-width:200px; }
  .brand-tag { font-size:9px; }
}
@media (min-width:1081px) and (max-height:760px) {
  .sidebar-inner { grid-template-rows:50px minmax(240px,1fr) auto 40px 40px; gap:12px; padding:14px 10px; }
  .is-sidebar-collapsed .sidebar-inner { grid-template-rows:50px minmax(240px,1fr) 0px 40px 40px; }
  .nav-item { min-height:48px; padding-block:7px; }
  .context-panel { padding-top:12px; gap:7px; }
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
  .app-shell,.sidebar *, .sidebar *::before,.is-dashboard *, .is-dashboard *::before { transition:none !important; animation:none !important; }
}
</style>
