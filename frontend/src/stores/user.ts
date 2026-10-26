import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'

interface UserInfo {
  id: number
  username: string
  email?: string
  current_model?: string
}

export const useUserStore = defineStore(
  'user',
  () => {
    const token = ref('')
    const userInfo = ref<UserInfo | null>(null)

    // 登录
    async function login(username: string, password: string) {
      const res: any = await authApi.login({ username, password })
      token.value = res.access_token
      userInfo.value = res.user
      localStorage.setItem('token', res.access_token)
      return res
    }

    // 注册
    async function register(username: string, password: string, email?: string) {
      const res: any = await authApi.register({ username, password, email })
      token.value = res.access_token
      userInfo.value = res.user
      localStorage.setItem('token', res.access_token)
      return res
    }

    // 获取当前用户信息
    async function fetchMe() {
      const res: any = await authApi.getMe()
      userInfo.value = res
      return res
    }

    // 退出
    function logout() {
      token.value = ''
      userInfo.value = null
      localStorage.removeItem('token')
    }

    // 是否已登录
    function isLoggedIn() {
      return !!token.value
    }

    return {
      token,
      userInfo,
      login,
      register,
      fetchMe,
      logout,
      isLoggedIn,
    }
  },
  {
    persist: {
      key: 'kb-user',
      pick: ['token', 'userInfo'],
    },
  }
)
