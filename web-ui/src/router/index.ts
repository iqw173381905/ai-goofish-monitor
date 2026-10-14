import { watch } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'
import { useAuth } from '@/composables/useAuth'
import { i18n, t } from '@/i18n'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { titleKey: 'routes.login' },
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { titleKey: 'routes.dashboard', requiresAuth: true },
      },
      {
        path: 'tasks',
        name: 'Tasks',
        component: () => import('@/views/TasksView.vue'),
        meta: { titleKey: 'routes.tasks', requiresAuth: true },
      },
      {
        path: 'accounts',
        name: 'Accounts',
        component: () => import('@/views/AccountsView.vue'),
        meta: { titleKey: 'routes.accounts', requiresAuth: true },
      },
      {
        path: 'results',
        name: 'Results',
        component: () => import('@/views/ResultsView.vue'),
        meta: { titleKey: 'routes.results', requiresAuth: true },
      },
      {
        path: 'logs',
        name: 'Logs',
        component: () => import('@/views/LogsView.vue'),
        meta: { titleKey: 'routes.logs', requiresAuth: true },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { titleKey: 'routes.settings', requiresAuth: true },
      },
    ],
  },
  {
    // 移动端 UI（/m/*）：底部标签栏，大按钮触控优化
    path: '/m',
    component: () => import('@/layouts/MobileLayout.vue'),
    redirect: '/m/tasks',
    children: [
      {
        path: 'tasks',
        name: 'MobileTasks',
        component: () => import('@/views/mobile/MobileTasksView.vue'),
        meta: { titleKey: 'routes.tasks', requiresAuth: true },
      },
      {
        path: 'results',
        name: 'MobileResults',
        component: () => import('@/views/mobile/MobileResultsView.vue'),
        meta: { titleKey: 'routes.results', requiresAuth: true },
      },
      {
        path: 'more',
        name: 'MobileMore',
        component: () => import('@/views/mobile/MobileMoreView.vue'),
        meta: { titleKey: 'routes.more', requiresAuth: true },
      },
      {
        path: 'accounts',
        name: 'MobileAccounts',
        component: () => import('@/views/mobile/MobileAccountsView.vue'),
        meta: { titleKey: 'routes.accounts', requiresAuth: true },
      },
      {
        path: 'logs',
        name: 'MobileLogs',
        component: () => import('@/views/mobile/MobileLogsView.vue'),
        meta: { titleKey: 'routes.logs', requiresAuth: true },
      },
      {
        path: 'settings',
        name: 'MobileSettings',
        component: () => import('@/views/mobile/MobileSettingsView.vue'),
        meta: { titleKey: 'routes.settings', requiresAuth: true },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

function updateDocumentTitle() {
  const currentRoute = router.currentRoute.value
  const titleKey = typeof currentRoute.meta.titleKey === 'string'
    ? currentRoute.meta.titleKey
    : null
  const appName = t('app.name')
  document.title = titleKey ? `${t(titleKey)} - ${appName}` : appName
}

const MOBILE_PREF_KEY = 'ui_mobile_pref' // 'auto' | 'mobile' | 'desktop'

export function isMobileDevice() {
  if (typeof navigator === 'undefined') return false
  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
    || (typeof window !== 'undefined' && window.innerWidth < 768)
}

export function getMobilePref(): string {
  try {
    return localStorage.getItem(MOBILE_PREF_KEY) || 'auto'
  } catch {
    return 'auto'
  }
}

export function setMobilePref(v: 'auto' | 'mobile' | 'desktop') {
  try {
    localStorage.setItem(MOBILE_PREF_KEY, v)
  } catch { /* ignore */ }
}

// 桌面端路由 → 移动端路由的映射（自动跳转用）
const DESKTOP_TO_MOBILE: Record<string, string> = {
  Dashboard: '/m/tasks',
  Tasks: '/m/tasks',
  Results: '/m/results',
}

router.beforeEach((to, _from, next) => {
  const { isAuthenticated } = useAuth()

  if (to.meta.requiresAuth && !isAuthenticated.value) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
  } else if (to.name === 'Login' && isAuthenticated.value) {
    // 登录后：手机自动进移动端
    const pref = getMobilePref()
    if (pref !== 'desktop' && isMobileDevice()) {
      next({ path: '/m/tasks' })
    } else {
      next({ name: 'Dashboard' })
    }
  } else if (
    isAuthenticated.value
    && typeof to.name === 'string'
    && DESKTOP_TO_MOBILE[to.name]
    && getMobilePref() !== 'desktop'
    && isMobileDevice()
    && !to.path.startsWith('/m')
  ) {
    // 手机访问桌面端页面 → 自动跳转移动端
    next({ path: DESKTOP_TO_MOBILE[to.name] })
  } else {
    next()
  }
})

router.afterEach(() => {
  updateDocumentTitle()
})

watch(
  () => i18n.global.locale.value,
  () => {
    updateDocumentTitle()
  },
)

export default router
