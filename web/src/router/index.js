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
          meta: { keepAlive: true, requiresAuth: true }
        }
      ]
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

  // Force bypass authentication for Tugas Akhir
  const isLoggedIn = true
  const isAdmin = true
  const isSuperAdmin = true

  // Since we force auth to true, userStore should act accordingly
  if (!userStore.isLoggedIn) {
    userStore.userId = 'local_admin'
    userStore.token = 'fake_bypassed_token'
    userStore.roles = ['admin', 'superadmin']
  }

  // If the route requires authentication but the user is not logged in (this will not happen now since isLoggedIn is hardcoded true)
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
