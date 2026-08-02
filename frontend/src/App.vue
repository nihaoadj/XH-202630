<template>
  <div id="app" class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">TP</div>
        <div>
          <div class="brand-title">Training Pilot</div>
          <div class="brand-subtitle">学习方向与资源生成工作台</div>
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
          <strong>{{ store.currentUserProfile?.display_name || '未设置' }}</strong>
        </div>
        <div class="context-item">
          <span>学习方向</span>
          <strong>{{ store.currentLearningDirectionName || '未选择' }}</strong>
        </div>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>{{ pageDescription }}</p>
        </div>
      </header>

      <section class="content">
        <router-view />
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from './stores/app'

const route = useRoute()
const store = useAppStore()

const navigation = [
  { to: '/', label: '总览', hint: '查看当前进度与主入口' },
  { to: '/learning/new', label: '新建学习方向', hint: '5 步完成问卷、诊断与生成' },
  { to: '/learning/history', label: '学习历史', hint: '按时间线查看学习过程' },
  { to: '/generate', label: '资源生成', hint: '查看生成任务状态' },
  { to: '/report', label: '学习报告', hint: '查看诊断与进展' },
  { to: '/feedback', label: '学习反馈', hint: '记录练习结果' },
]

const pageMeta = {
  home: ['工作台总览', '围绕用户资料、学习方向、诊断、资源与历史记录组织完整流程。'],
  'user-profile': ['用户资料', '将学历、专业等稳定信息集中维护，供后续学习方向复用。'],
  onboarding: ['新建学习方向', '完成领域、方向、问卷、诊断和资源选择 5 步流程。'],
  history: ['学习历史', '按时间线查看问卷、诊断和资源生成过程。'],
  generate: ['资源生成状态', '任务提交后在这里查看状态，并在完成后跳转资源页。'],
  report: ['学习报告', '查看学习进展与能力变化。'],
  feedback: ['学习反馈', '提交练习结果，推进后续资源迭代。'],
}

const pageTitle = computed(() => pageMeta[route.name]?.[0] || 'Training Pilot')
const pageDescription = computed(() => pageMeta[route.name]?.[1] || '')
</script>

<style scoped>
.shell {
  height: 100dvh;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.08), transparent 26%),
    linear-gradient(180deg, #f4f7fb 0%, #eef3f8 100%);
  color: #132238;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 28px 22px;
  overflow-y: auto;
  background: rgba(10, 23, 44, 0.96);
  color: #f8fbff;
}

.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand-mark {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #60a5fa, #34d399);
  color: #0f172a;
  font-weight: 800;
}

.brand-title {
  font-size: 18px;
  font-weight: 700;
}

.brand-subtitle {
  margin-top: 4px;
  color: rgba(226, 236, 248, 0.78);
  font-size: 13px;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nav-link {
  display: flex;
  flex-direction: column;
  gap: 4px;
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
  font-weight: 600;
}

.nav-hint {
  color: rgba(203, 213, 225, 0.78);
  font-size: 12px;
}

.context-card {
  margin-top: 6px;
  padding: 16px;
  border-radius: 14px;
  background: rgba(148, 163, 184, 0.14);
  border: 1px solid rgba(148, 163, 184, 0.18);
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
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.topbar {
  flex-shrink: 0;
  padding: 30px 36px 10px;
}

.topbar h1 {
  margin: 0;
  font-size: 30px;
  line-height: 1.1;
}

.topbar p {
  margin: 10px 0 0;
  color: #526277;
}

.content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 36px 36px;
}

@media (max-width: 1080px) {
  .shell {
    height: auto;
    min-height: 100dvh;
    grid-template-columns: 1fr;
    overflow: visible;
  }

  .sidebar {
    gap: 18px;
    overflow: visible;
  }

  .context-card {
    margin-top: 0;
  }
}

@media (max-width: 720px) {
  .topbar,
  .content {
    padding-left: 18px;
    padding-right: 18px;
  }
}
</style>
