import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/layouts/AppLayout.vue'
import BlankLayout from '@/layouts/BlankLayout.vue'
import { useUserStore } from '@/stores/user'
import { useAgentStore } from '@/stores/agent'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'main',
      component: BlankLayout,
      children: [
        {
          path: '',
          name: 'Home',
          component: () => import('../views/HomeView.vue'),
          meta: { keepAlive: true, requiresAuth: false }
        }
      ]
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { requiresAuth: false }
    },
    {
      path: '/auth/oidc/callback',
      name: 'OIDCCallback',
      component: () => import('@/views/OIDCCallbackView.vue'),
      meta: { requiresAuth: false }
    },
    {
      path: '/agent',
      name: 'AgentMain',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'AgentComp',
          component: () => import('../views/AgentView.vue'),
          meta: { keepAlive: true, requiresAuth: true }
        },
        {
          path: ':thread_id',
          name: 'AgentCompWithThreadId',
          component: () => import('../views/AgentView.vue'),
          meta: { keepAlive: true, requiresAuth: true }
        }
      ]
    },
    {
      path: '/dashboard',
      name: 'DashboardMain',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'DashboardComp',
          component: () => import('../views/DashboardView.vue'),
          meta: { keepAlive: false, requiresAuth: true, requiresAdmin: true }
        }
      ]
    },
    {
      path: '/graph',
      name: 'GraphMain',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'GraphComp',
          component: () => import('../views/GraphView.vue'),
          meta: { keepAlive: false, requiresAuth: true, requiresAdmin: true }
        }
      ]
    },
    {
      path: '/database',
      name: 'DatabaseMain',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'DatabaseComp',
          component: () => import('../views/DataBaseView.vue'),
          meta: { keepAlive: true, requiresAuth: true, requiresAdmin: true }
        },
        {
          path: ':database_id',
          name: 'DatabaseInfoComp',
          component: () => import('../views/DataBaseInfoView.vue'),
          meta: { keepAlive: false, requiresAuth: true, requiresAdmin: true }
        }
      ]
    },
    {
      path: '/extensions',
      name: 'extensions',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'ExtensionsComp',
          component: () => import('../views/ExtensionsView.vue'),
          meta: {
            keepAlive: false,
            requiresAuth: true,
            requiresAdmin: true,
            requiresSuperAdmin: true
          }
        }
      ]
    },
    {
      path: '/skills',
      name: 'skills',
      redirect: '/extensions'
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'NotFound',
      component: () => import('../views/EmptyView.vue'),
      meta: { requiresAuth: false }
    }
  ]
})

// Global navigation guard
router.beforeEach(async (to, from, next) => {
  // Check whether the route requires authentication
  const requiresAuth = to.matched.some((record) => record.meta.requiresAuth === true)
  const requiresAdmin = to.matched.some((record) => record.meta.requiresAdmin)
  const requiresSuperAdmin = to.matched.some((record) => record.meta.requiresSuperAdmin)

  const userStore = useUserStore()

  // If there is a token but the user info is not loaded, fetch it first
  if (userStore.token && !userStore.userId) {
    try {
      await userStore.getCurrentUser()
    } catch (error) {
      // If fetching user info fails (for example, expired token), clear the token
      console.error('Failed to fetch user info:', error)
      userStore.logout()
    }
  }

  const isLoggedIn = userStore.isLoggedIn
  const isAdmin = userStore.isAdmin
  const isSuperAdmin = userStore.isSuperAdmin

  // If the route requires authentication but the user is not logged in
  if (requiresAuth && !isLoggedIn) {
    sessionStorage.setItem('redirect', to.fullPath)
    next('/login')
    return
  }

  // If the route requires admin privileges but the user is not an admin
  if (requiresAdmin && !isAdmin) {
    // If the user is a regular user, redirect to the empty chat page
    try {
      const agentStore = useAgentStore()
      // Wait for store initialization to complete
      if (!agentStore.isInitialized) {
        await agentStore.initialize()
      }
      next('/agent')
    } catch (error) {
      console.error('Failed to fetch agent info:', error)
      next('/agent')
    }
    return
  }

  // If the route requires super-admin privileges but the user is not a super admin
  if (requiresSuperAdmin && !isSuperAdmin) {
    try {
      const agentStore = useAgentStore()
      if (!agentStore.isInitialized) {
        await agentStore.initialize()
      }
      next('/agent')
    } catch (error) {
      console.error('Failed to fetch agent info:', error)
      next('/agent')
    }
    return
  }

  // If the user is already logged in but tries to access the login page
  if (to.path === '/login' && isLoggedIn) {
    next('/')
    return
  }

  // Normal navigation in all other cases
  next()
})

export default router
