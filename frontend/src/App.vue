<template>
  <router-view v-if="isAuthRoute || isResourceFocusMode" />

  <div v-else id="app" class="shell" :class="{ 'is-sidebar-collapsed': sidebarCollapsed }">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">TP</div>
        <div class="brand-copy">
          <div class="brand-title">个性化学习工坊</div>
        </div>
      </div>

      <nav class="nav">
        <router-link
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          active-class="is-active"
        >
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <span class="nav-label">{{ item.label }}</span>
          <span class="nav-hint">{{ item.hint }}</span>
        </router-link>
      </nav>

      <div class="context-card">
        <div class="context-title">当前上下文</div>
        <div class="context-item">
          <div class="context-head">
            <span>用户</span>
            <router-link to="/user/profile" class="context-action">编辑</router-link>
          </div>
          <strong>{{ auth.currentUser?.username || store.currentUserProfile?.display_name || '未设置' }}</strong>
        </div>
        <div class="context-item">
          <span>学习方向</span>
          <strong>{{ store.currentLearningDirectionName || '未选择' }}</strong>
        </div>
      </div>
      <div class="sidebar-control">
        <el-tooltip :content="sidebarCollapsed ? '展开导航栏' : '收起导航栏'" placement="right">
          <el-button
            class="sidebar-toggle"
            :icon="sidebarCollapsed ? Expand : Fold"
            circle
            :aria-label="sidebarCollapsed ? '展开导航栏' : '收起导航栏'"
            @click="toggleSidebar"
          />
        </el-tooltip>
      </div>
      <el-button class="logout-button" plain @click="handleLogout">退出登录</el-button>
    </aside>

    <main class="main">
      <section class="content" :class="{ 'is-contained-scroll': containedScroll }">
        <router-view />
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Clock, Collection, DataAnalysis, Document, Expand, Fold, Plus, Reading, ChatDotRound } from '@element-plus/icons-vue'
import { useAuthStore } from './stores/auth'
import { useAppStore } from './stores/app'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const store = useAppStore()
const sidebarCollapsed = ref(localStorage.getItem('app_sidebar_collapsed') === 'true')

const navigation = [
  { to: '/', label: '总览', hint: '查看当前进度与主入口', icon: Collection },
  { to: '/learning/new', label: '新建学习方向', hint: '5 步完成问卷、诊断与生成', icon: Plus },
  { to: '/generate', label: '资源生成', hint: '查看生成任务状态', icon: Document },
  { to: '/resources', label: '学习资源', hint: '查看资源并专注学习', icon: Reading },
  { to: '/feedback', label: '学习反馈', hint: '记录练习结果', icon: ChatDotRound },
  { to: '/report', label: '学习报告', hint: '查看诊断与进展', icon: DataAnalysis },
  { to: '/learning/history', label: '学习历史', hint: '按时间线查看学习过程', icon: Clock },
]

const containedScroll = computed(() => ['home', 'onboarding', 'history'].includes(route.name))
const isAuthRoute = computed(() => Boolean(route.meta.authLayout))
const isResourceFocusMode = computed(() => route.name === 'resources' && route.query.focus === '1')

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
  margin: 0;
  overflow: hidden;
}

:global(*) {
  box-sizing: border-box;
}

.shell {
  height: 100dvh;
  display: grid;
  grid-template-columns: 236px minmax(0, 1fr);
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.08), transparent 26%),
    linear-gradient(180deg, #f4f7fb 0%, #eef3f8 100%);
  color: #132238;
  transition: grid-template-columns 0.22s ease;
}

.shell.is-sidebar-collapsed {
  grid-template-columns: 88px minmax(0, 1fr);
}

.sidebar {
  position: relative;
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 24px 18px;
  overflow-y: auto;
  background: rgba(10, 23, 44, 0.96);
  color: #f8fbff;
}

.brand {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
}

.sidebar-control {
  display: flex;
  position: absolute;
  right: 0;
  bottom: 20px;
  left: 0;
  justify-content: center;
}

.sidebar-toggle {
  width: 30px;
  height: 30px;
  border-color: #cbd9e8;
  background: #ffffff;
  color: #355a87;
  box-shadow: 0 4px 12px rgba(5, 22, 46, 0.18);
}

.brand-mark {
  width: 48px;
  height: 48px;
  flex: 0 0 48px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #60a5fa, #34d399);
  color: #0f172a;
  font-weight: 800;
}

.brand-title {
  font-size: 17px;
  font-weight: 700;
  white-space: nowrap;
}

.brand-subtitle {
  margin-top: 4px;
  color: rgba(226, 236, 248, 0.78);
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nav-link {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  grid-template-areas: 'icon label' 'icon hint';
  column-gap: 10px;
  padding: 12px 14px;
  border-radius: 10px;
  color: rgba(241, 245, 249, 0.92);
  text-decoration: none;
  transition: background-color 0.2s ease, transform 0.2s ease;
}

.nav-link:hover {
  background: rgba(96, 165, 250, 0.14);
  transform: translateX(2px);
}

.nav-link.is-active {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.34), rgba(52, 211, 153, 0.22));
  box-shadow: inset 0 0 0 1px rgba(147, 197, 253, 0.22);
}

.nav-label {
  grid-area: label;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-icon {
  grid-area: icon;
  align-self: center;
  font-size: 17px;
}

.nav-hint {
  grid-area: hint;
  color: rgba(203, 213, 225, 0.78);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.is-sidebar-collapsed .sidebar {
  align-items: center;
  padding: 24px 10px;
  overflow: visible;
}

.is-sidebar-collapsed .brand-title,
.is-sidebar-collapsed .brand-copy,
.is-sidebar-collapsed .context-card,
.is-sidebar-collapsed .logout-button { display: none; }

.is-sidebar-collapsed .brand { justify-content: center; gap: 0; }
.is-sidebar-collapsed .nav { width: 100%; }

.is-sidebar-collapsed .nav-link {
  grid-template-columns: 1fr;
  grid-template-areas: 'icon';
  height: 68px;
  place-items: center;
  padding: 10px;
}

.is-sidebar-collapsed .nav-icon { font-size: 17px; }
.is-sidebar-collapsed .nav-label,
.is-sidebar-collapsed .nav-hint { display: none; }

.context-card {
  margin-top: 6px;
  padding: 16px;
  border-radius: 14px;
  background: rgba(148, 163, 184, 0.14);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.logout-button {
  width: 100%;
  margin-top: auto;
  margin-bottom: 46px;
  border-color: rgba(203, 213, 225, 0.26);
  background: transparent;
  color: #f8fafc;
}

.logout-button:hover {
  border-color: rgba(125, 211, 252, 0.58);
  background: rgba(14, 165, 233, 0.12);
  color: #ffffff;
}

.context-title {
  margin-bottom: 12px;
  font-size: 13px;
  color: rgba(226, 236, 248, 0.84);
}

.context-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.context-item + .context-item {
  margin-top: 12px;
}

.context-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.context-item span {
  color: rgba(203, 213, 225, 0.72);
  font-size: 12px;
}

.context-item strong {
  font-size: 14px;
}

.context-action {
  padding: 6px 12px;
  border: 1px solid rgba(125, 211, 252, 0.28);
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.2), rgba(56, 189, 248, 0.1));
  color: #e0f2fe;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  line-height: 1;
  text-decoration: none;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
  transition:
    background-color 0.2s ease,
    color 0.2s ease,
    border-color 0.2s ease,
    transform 0.2s ease;
}

.context-action:hover {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.32), rgba(59, 130, 246, 0.18));
  border-color: rgba(186, 230, 253, 0.5);
  color: #ffffff;
  transform: translateY(-1px);
}

.main {
  position: relative;
  z-index: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.content {
  position: relative;
  z-index: 1;
  box-sizing: border-box;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 30px 40px 36px;
}

.content.is-contained-scroll {
  overflow: hidden;
}

@media (max-width: 1080px) {
  .shell {
    height: 100dvh;
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr);
    overflow: hidden;
  }

  .sidebar {
    gap: 18px;
    position: sticky;
    top: 0;
    z-index: 50;
    max-height: 34dvh;
    overflow-y: auto;
  }

  .is-sidebar-collapsed .sidebar {
    align-items: stretch;
    padding: 24px 18px;
    overflow-y: auto;
  }

  .sidebar-control { display: none; }

  .is-sidebar-collapsed .brand-title,
  .is-sidebar-collapsed .brand-copy,
  .is-sidebar-collapsed .context-card,
  .is-sidebar-collapsed .logout-button { display: block; }

  .is-sidebar-collapsed .brand { width: auto; }
  .is-sidebar-collapsed .nav-link {
    grid-template-columns: 20px minmax(0, 1fr);
    grid-template-areas: 'icon label' 'icon hint';
    min-height: 78px;
    place-items: unset;
    padding: 12px 14px;
  }

  .is-sidebar-collapsed .nav-label,
  .is-sidebar-collapsed .nav-hint { display: block; }

  .nav {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .nav-link {
    min-height: 78px;
  }

  .main {
    min-height: 0;
  }

  .context-card {
    margin-top: 0;
  }
}

@media (max-width: 720px) {
  .sidebar {
    padding: 16px 18px;
    max-height: 26dvh;
  }

  .brand {
    align-items: flex-start;
  }

  .nav {
    display: flex;
    flex-direction: row;
    gap: 8px;
    overflow-x: auto;
    padding-bottom: 4px;
    scrollbar-width: thin;
  }

  .nav-link {
    flex: 0 0 auto;
    min-height: 40px;
    padding: 10px 12px;
    justify-content: center;
  }

  .brand-subtitle,
  .nav-hint {
    display: none;
  }

  .context-card {
    display: none;
  }

  .content {
    padding-top: 18px;
    padding-left: 18px;
    padding-right: 18px;
  }
}
</style>
