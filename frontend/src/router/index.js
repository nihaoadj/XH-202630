import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'

const routes = [
  { path: '/', name: 'home', component: HomeView },
  { path: '/generate', name: 'generate', component: () => import('../views/GenerateView.vue') },
  { path: '/report', name: 'report', component: () => import('../views/ReportView.vue') },
  { path: '/feedback', name: 'feedback', component: () => import('../views/FeedbackView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
