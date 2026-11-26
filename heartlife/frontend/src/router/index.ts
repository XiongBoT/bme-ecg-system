import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '../stores/auth'

import HomeView from '../views/HomeView.vue'
import EcgView from '../views/EcgView.vue'
import AuthView from '../views/AuthView.vue'
import JournalView from '../views/JournalView.vue'
import PlansView from '../views/PlansView.vue'
import CommunityView from '../views/CommunityView.vue'
import PostDetailView from '../views/PostDetailView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import ArticleDetailView from '../views/ArticleDetailView.vue'
import WeeklyReportView from '../views/WeeklyReportView.vue'
import ChallengesView from '../views/ChallengesView.vue'
import AssistantView from '../views/AssistantView.vue'
import NotificationsView from '../views/NotificationsView.vue'
import ProfileView from '../views/ProfileView.vue'
import PublicUserView from '../views/PublicUserView.vue'
import OpsView from '../views/OpsView.vue'

export const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: AuthView,
    meta: { guestOnly: true, title: '登录 · 心伴 HeartLife' },
  },
  {
    path: '/',
    name: 'home',
    component: HomeView,
    meta: { requiresAuth: true, title: '首页 · 心伴 HeartLife' },
  },
  {
    path: '/ecg',
    name: 'ecg',
    component: EcgView,
    meta: { requiresAuth: true, title: '我的心电记录 · 心伴 HeartLife' },
  },
  {
    path: '/journal',
    name: 'journal',
    component: JournalView,
    meta: { requiresAuth: true, title: '健康日记 · 心伴 HeartLife' },
  },
  {
    path: '/plans',
    name: 'plans',
    component: PlansView,
    meta: { requiresAuth: true, title: '习惯计划 · 心伴 HeartLife' },
  },
  {
    path: '/community',
    name: 'community',
    component: CommunityView,
    meta: { requiresAuth: false, title: '互助社区 · 心伴 HeartLife' },
  },
  {
    path: '/community/:id',
    name: 'post-detail',
    component: PostDetailView,
    meta: { requiresAuth: false, title: '帖子详情 · 心伴 HeartLife' },
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: KnowledgeView,
    meta: { requiresAuth: false, title: '健康百科 · 心伴 HeartLife' },
  },
  {
    path: '/knowledge/:id',
    name: 'article-detail',
    component: ArticleDetailView,
    meta: { requiresAuth: false, title: '百科详情 · 心伴 HeartLife' },
  },
  {
    path: '/weekly-report',
    name: 'weekly-report',
    component: WeeklyReportView,
    meta: { requiresAuth: true, title: '健康周报 · 心伴 HeartLife' },
  },
  {
    path: '/challenges',
    name: 'challenges',
    component: ChallengesView,
    meta: { requiresAuth: true, title: '行为挑战 · 心伴 HeartLife' },
  },
  {
    path: '/assistant',
    name: 'assistant',
    component: AssistantView,
    meta: { requiresAuth: true, title: '生活助手 · 心伴 HeartLife' },
  },
  {
    path: '/notifications',
    name: 'notifications',
    component: NotificationsView,
    meta: { requiresAuth: true, title: '站内消息 · 心伴 HeartLife' },
  },
  {
    path: '/me',
    name: 'profile',
    component: ProfileView,
    meta: { requiresAuth: true, title: '我的 · 心伴 HeartLife' },
  },
  {
    path: '/users/:id',
    name: 'public-user',
    component: PublicUserView,
    meta: { requiresAuth: false, title: '成员主页 · 心伴 HeartLife' },
  },
  {
    path: '/ops',
    name: 'ops',
    component: OpsView,
    meta: { requiresAuth: true, requiresOps: true, title: '内容与治理 · 心伴 HeartLife' },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.initialized || !auth.configLoaded) {
    await auth.bootstrap()
  }

  if (typeof document !== 'undefined' && typeof to.meta.title === 'string') {
    document.title = to.meta.title
  }

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return {
      path: '/login',
      query: to.fullPath && to.fullPath !== '/' ? { redirect: to.fullPath } : undefined,
    }
  }

  if (to.meta.guestOnly && auth.isAuthenticated) {
    return { path: '/' }
  }

  if (to.meta.requiresOps && !auth.isOps) {
    return { path: '/' }
  }

  return true
})

export default router
