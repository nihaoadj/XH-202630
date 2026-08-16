import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { guestOnly: true, authLayout: true } },
  { path: '/register', name: 'register', component: () => import('../views/RegisterView.vue'), meta: { guestOnly: true, authLayout: true } },
  { path: '/', name: 'home', component: HomeView, meta: { requiresAuth: true } },
  { path: '/user/profile', name: 'user-profile', component: () => import('../views/UserProfileView.vue'), meta: { requiresAuth: true } },
  { path: '/learning/new', name: 'onboarding', component: () => import('../views/OnboardingView.vue'), meta: { requiresAuth: true } },
  { path: '/learning/history', name: 'history', component: () => import('../views/HistoryView.vue'), meta: { requiresAuth: true } },
  { path: '/resources', redirect: '/generate' },
  { path: '/generate', name: 'generate', component: () => import('../views/GenerateView.vue'), meta: { requiresAuth: true } },
  { path: '/report', name: 'report', component: () => import('../views/ReportView.vue'), meta: { requiresAuth: true } },
  { path: '/feedback', name: 'feedback', component: () => import('../views/FeedbackView.vue'), meta: { requiresAuth: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.initialize()

  if (to.meta.requiresAuth && !auth.currentUser) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.guestOnly && auth.currentUser) {
    return { name: 'home' }
  }
  return true
})

export default router
