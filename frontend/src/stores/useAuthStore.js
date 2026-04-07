import { create } from 'zustand'

/**
 * 认证状态管理 — 对接总系统 JWT 统一认证
 *
 * Token 来源：
 * 1. 总系统通过 URL ?token=xxx 传入
 * 2. 存储在 localStorage 中，后续请求自动携带
 */
const useAuthStore = create((set, get) => ({
  token: null,
  user: null,
  isAuthenticated: false,

  /**
   * 初始化：从 URL 参数或 localStorage 恢复 token
   * 在 App 启动时调用
   */
  initAuth: () => {
    // 1. 优先从 URL ?token=xxx 获取（总系统跳转传入）
    const urlParams = new URLSearchParams(window.location.search)
    const urlToken = urlParams.get('token')

    if (urlToken) {
      // 存入 localStorage 并清理 URL 参数
      localStorage.setItem('token', urlToken)
      // 从 URL 中移除 token 参数（避免泄露）
      urlParams.delete('token')
      const cleanUrl = urlParams.toString()
        ? `${window.location.pathname}?${urlParams.toString()}`
        : window.location.pathname
      window.history.replaceState({}, '', cleanUrl)

      set({ token: urlToken, isAuthenticated: true })
      // 获取用户信息
      get().fetchUser(urlToken)
      return
    }

    // 2. 从 localStorage 恢复
    const savedToken = localStorage.getItem('token')
    if (savedToken && savedToken !== 'dev-no-auth') {
      set({ token: savedToken, isAuthenticated: true })
      get().fetchUser(savedToken)
      return
    }

    // 3. 无 token → 未认证
    set({ token: null, user: null, isAuthenticated: false })
  },

  /**
   * 根据 token 获取用户信息
   */
  fetchUser: async (token) => {
    try {
      const resp = await fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (resp.ok) {
        const user = await resp.json()
        set({ user, isAuthenticated: true })
      } else {
        // token 无效
        get().logout()
      }
    } catch (e) {
      // 网络错误时保留 token，等后端恢复后重试
      console.warn('获取用户信息失败，保留 token 等待重试')
    }
  },

  login: (token, user) => {
    localStorage.setItem('token', token)
    set({ token, user, isAuthenticated: true })
  },

  logout: () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    set({ token: null, user: null, isAuthenticated: false })
  },
}))

export default useAuthStore
