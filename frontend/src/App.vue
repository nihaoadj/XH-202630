<template>
  <router-view v-if="isAuthRoute || isPublicRoute || isResourceFocusMode" />

  <div v-else class="app-shell" :class="{ 'is-sidebar-collapsed': sidebarCollapsed }">
    <aside class="sidebar">
      <div class="brand-block">
        <img class="brand-logo" src="/zhiyu-logo.png" alt="智域匠学" />
        <div class="brand-copy">
          <div class="brand-name">智域匠学</div>
          <div class="brand-tag">多智能体领域技能培训平台</div>
        </div>
      </div>

      <nav class="nav-list">
        <router-link v-for="item in navigation" :key="item.to" :to="item.to" class="nav-item" active-class="is-active">
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <span class="nav-text">{{ item.label }}</span>
          <small class="nav-hint">{{ item.hint }}</small>
        </router-link>
      </nav>

      <section class="context-panel">
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

      <button class="sidebar-toggle" type="button" @click="toggleSidebar">
        <el-icon class="sidebar-toggle-icon"><component :is="sidebarCollapsed ? Expand : Fold" /></el-icon>
        <span class="sidebar-toggle-label">{{ sidebarCollapsed ? '展开侧栏' : '收起侧栏' }}</span>
      </button>

      <el-button class="logout-button" @click="handleLogout">
        <el-icon class="logout-icon"><SwitchButton /></el-icon>
        <span class="logout-label">退出登录</span>
      </el-button>
    </aside>

    <main class="main-area">
      <header class="topbar">
        <div class="topbar-copy">
          <span class="topbar-kicker">DOMAIN SKILL WORKBENCH</span>
          <h1>{{ currentTitle }}</h1>
          <p>{{ currentSubtitle }}</p>
        </div>
        <div class="topbar-actions">
          <el-button class="app-secondary-button topbar-action" :icon="Clock" @click="$router.push('/learning/history')">学习历史</el-button>
          <el-button class="app-secondary-button topbar-action" :icon="DataAnalysis" @click="$router.push('/report')">学习报告</el-button>
          <el-button class="app-secondary-button topbar-action" :icon="Collection" @click="$router.push('/user/profile')">用户资料</el-button>
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
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Clock, Collection, DataAnalysis, Document, Expand, Fold, Plus, Reading, ChatDotRound, HomeFilled, SwitchButton } from '@element-plus/icons-vue'
import { useAuthStore } from './stores/auth'
import { useAppStore } from './stores/app'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const store = useAppStore()
const sidebarCollapsed = ref(localStorage.getItem('app_sidebar_collapsed') === 'true')

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

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('app_sidebar_collapsed', String(sidebarCollapsed.value))
}

async function handleLogout() {
  await auth.logout()
  await router.replace('/login')
}
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
  --sidebar-width: 248px;
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
  transition: grid-template-columns 260ms cubic-bezier(0.22, 1, 0.36, 1);
}

.app-shell.is-sidebar-collapsed {
  --sidebar-width: 76px;
}

.sidebar {
  position: relative;
  z-index: 20;
  min-width: 0;
  display: grid;
  grid-template-rows: 60px minmax(320px, 1fr) 184px 40px 40px;
  gap: 12px;
  padding: 20px 12px 16px;
  background: linear-gradient(180deg, #0f2a50 0%, #173d72 100%);
  color: #f6fbff;
  overflow-y: auto;
  scrollbar-color: rgba(191, 219, 254, 0.72) rgba(219, 234, 254, 0.2);
  scrollbar-width: thin;
}

.sidebar::-webkit-scrollbar {
  width: 10px;
}

.sidebar::-webkit-scrollbar-track {
  background: rgba(219, 234, 254, 0.18);
  border-radius: 999px;
}

.sidebar::-webkit-scrollbar-thumb {
  border: 2px solid rgba(16, 42, 80, 0.45);
  border-radius: 999px;
  background: rgba(191, 219, 254, 0.82);
}

.sidebar::-webkit-scrollbar-thumb:hover {
  background: rgba(219, 234, 254, 0.96);
}

.brand-block {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 12px;
  min-height: 60px;
}

.brand-logo {
  width: 52px;
  height: 52px;
  flex: 0 0 52px;
  object-fit: contain;
}

.brand-copy {
  min-width: 0;
  max-width: 168px;
  overflow: hidden;
  opacity: 1;
  transform: translateX(0);
  transition: max-width 220ms ease, opacity 140ms ease, transform 220ms ease;
}

.brand-name {
  font-size: 19px;
  font-weight: 800;
  line-height: 1.2;
}

.brand-tag {
  margin-top: 4px;
  color: rgba(226, 236, 248, 0.82);
  font-size: 12px;
}

.nav-list {
  display: grid;
  min-width: 0;
  grid-template-rows: repeat(5, minmax(62px, auto));
  align-content: space-evenly;
  min-height: 0;
  gap: 8px;
}

.nav-item {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  grid-template-areas: 'icon text' 'icon hint';
  column-gap: 10px;
  padding: 12px;
  min-height: 62px;
  border-radius: 12px;
  color: rgba(241, 246, 255, 0.95);
  text-decoration: none;
  overflow: hidden;
  transition: background-color 180ms ease, transform 180ms ease, padding 260ms cubic-bezier(0.22, 1, 0.36, 1);
}

.nav-item:hover {
  background: rgba(125, 181, 255, 0.16);
  transform: translateX(2px);
}

.nav-item.is-active {
  background: linear-gradient(135deg, rgba(67, 138, 255, 0.38), rgba(82, 201, 255, 0.18));
  box-shadow: inset 0 0 0 1px rgba(180, 217, 255, 0.28);
}

.nav-icon {
  grid-area: icon;
  align-self: center;
  width: 20px;
  min-width: 20px;
  font-size: 17px;
  line-height: 1;
  transition: transform 220ms ease, font-size 220ms ease;
}

.nav-text {
  grid-area: text;
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
  opacity: 1;
  transform: translateX(0);
  transition: opacity 120ms ease, transform 220ms ease;
}

.nav-hint {
  grid-area: hint;
  color: rgba(210, 225, 242, 0.82);
  font-size: 12px;
  font-style: normal;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 1;
  transform: translateX(0);
  transition: opacity 120ms ease, transform 220ms ease;
}

.context-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 10px;
  height: 184px;
  padding: 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  max-height: 260px;
  overflow: hidden;
  opacity: 1;
  transform: translateY(0);
  transition: max-height 240ms ease, padding 240ms ease, margin 240ms ease, border-width 240ms ease, opacity 120ms ease, transform 240ms ease;
}

.context-title {
  color: rgba(226, 236, 248, 0.84);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.context-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.context-row span {
  color: rgba(203, 213, 225, 0.74);
  font-size: 12px;
}

.context-row strong {
  font-size: 13px;
  line-height: 1.35;
}

.context-link {
  color: #bfe0ff;
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
}

.context-link:hover,
.context-link:focus-visible {
  color: #ffffff;
  text-decoration: underline;
}

.sidebar-toggle {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  height: 40px;
  flex: 0 0 40px;
  padding: 0 12px;
  overflow: hidden;
  border: 1px solid rgba(196, 219, 248, 0.22);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.08);
  color: #edf6ff;
  cursor: pointer;
  transition: background-color 180ms ease, border-color 180ms ease, padding 260ms cubic-bezier(0.22, 1, 0.36, 1);
}

.sidebar-toggle-icon,
.logout-icon {
  width: 20px;
  min-width: 20px;
  font-size: 17px;
  line-height: 1;
}

.sidebar-toggle-label,
.logout-label {
  white-space: nowrap;
  opacity: 1;
  transform: translateX(0);
  transition: opacity 120ms ease, transform 220ms ease;
}

.logout-button {
  justify-content: flex-start;
  height: 40px;
  flex: 0 0 40px;
  margin-top: 0;
  padding-inline: 12px;
  overflow: hidden;
  border-color: rgba(196, 219, 248, 0.18);
  background: rgba(255, 255, 255, 0.05);
  color: #f7fbff;
}

.logout-button:hover {
  border-color: rgba(193, 225, 255, 0.48);
  background: rgba(79, 144, 255, 0.14);
  color: #ffffff;
}

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

.is-sidebar-collapsed .brand-copy {
  max-width: 0;
  opacity: 0;
  transform: translateX(-8px);
  pointer-events: none;
}

.is-sidebar-collapsed .nav-text,
.is-sidebar-collapsed .nav-hint,
.is-sidebar-collapsed .sidebar-toggle-label,
.is-sidebar-collapsed .logout-label {
  opacity: 0;
  transform: translateX(-8px);
  pointer-events: none;
}

.is-sidebar-collapsed .context-panel {
  opacity: 0;
  transform: translateY(0);
  pointer-events: none;
}

@media (max-width: 1080px) {
  .app-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr);
  }

  .sidebar {
    display: flex;
    flex-direction: column;
    gap: 14px;
    max-height: 35dvh;
    min-height: 0;
  }

  .nav-list {
    display: flex;
    flex: 0 0 auto;
    flex-direction: column;
    min-height: 0;
    justify-content: flex-start;
  }

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
  .sidebar {
    padding: 18px 14px;
    max-height: 28dvh;
  }

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
</style>
