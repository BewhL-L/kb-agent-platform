import request from './request'

// 认证相关 API
export const authApi = {
  register: (data: { username: string; password: string; email?: string }) =>
    request.post('/auth/register', data),

  login: (data: { username: string; password: string }) =>
    request.post('/auth/login', data),

  getMe: () => request.get('/auth/me'),

  updatePassword: (data: { old_password: string; new_password: string }) =>
    request.put('/auth/password', data),

  updateModel: (model: string) => request.put('/auth/model', { model }),
}
