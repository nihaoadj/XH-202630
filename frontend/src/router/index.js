import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../features/home/HomeView.vue'
import { useAuthStore } from '../stores/auth'

const routes = [
{ path: '/', name: 'landing', component: () => import('../features/auth/LandingView.vue'), meta: { publicLayout: true } },
{ path: '/login', name: 'login', component: () => import('../features/auth/LandingView.vue'), meta: { guestOnly: true, publicLayout: true } },
{ path: '/register', name: 'register', component: () => import('../features/auth/LandingView.vue'), meta: { guestOnly: true, publicLayout: true } },
  { path: '/dashboard', name: 'dashboard', component: HomeView, meta: { requiresAuth: true } },
{ path: '/user/profile', name: 'user-profile', component: () => import('../features/learners/UserProfileView.vue'), meta: { requiresAuth: true } },
{ path: '/learning/new', name: 'onboarding', component: () => import('../features/onboarding/OnboardingView.vue'), meta: { requiresAuth: true } },
{ path: '/learning/history', name: 'history', component: () => import('../features/learners/HistoryView.vue'), meta: { requiresAuth: true } },
{ path: '/resources', name: 'resources', component: () => import('../features/learning-documents/ResourcesView.vue'), meta: { requiresAuth: true } },
{ path: '/generate', name: 'generate', component: () => import('../features/generation/GenerateView.vue'), meta: { requiresAuth: true } },
{ path: '/report', name: 'report', component: () => import('../features/reports/ReportView.vue'), meta: { requiresAuth: true } },
{ path: '/feedback', name: 'feedback', component: () => import('../features/feedback/FeedbackView.vue'), meta: { requiresAuth: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.initialize()

  if (to.meta.requiresAuth && !auth.currentUser) {
    return { name: 'landing', query: { login: '1', redirect: to.fullPath } }
  }
  if (to.meta.guestOnly && auth.currentUser && to.name !== 'register') {
    return { name: 'dashboard' }
  }
  return true
})

export default router
