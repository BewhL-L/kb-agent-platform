import request from './request'

// 知识库相关 API
export const kbApi = {
  create: (data: { name: string; description?: string }) =>
    request.post('/kb', data),

  list: (params: { page?: number; page_size?: number; keyword?: string }) =>
    request.get('/kb', { params }),

  detail: (id: number) => request.get(`/kb/${id}`),

  update: (id: number, data: { name?: string; description?: string }) =>
    request.put(`/kb/${id}`, data),

  delete: (id: number) => request.delete(`/kb/${id}`),

  getEmbedCode: (id: number) => request.get(`/kb/${id}/embed-code`),
}

// 文档相关 API
export const docApi = {
  upload: (kbId: number, file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData()
    formData.append('file', file)
    return request.post(`/kb/${kbId}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded * 100) / e.total))
        }
      },
    })
  },

  list: (kbId: number, params: { page?: number; page_size?: number }) =>
    request.get(`/kb/${kbId}/docs`, { params }),

  // 增量更新（同 ID 替换文档）
  update: (docId: number, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return request.put(`/docs/${docId}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  status: (docId: number) => request.get(`/docs/${docId}`),

  // 文档预览内容
  preview: (docId: number) => request.get(`/docs/${docId}/preview`),

  delete: (docId: number) => request.delete(`/docs/${docId}`),
}

// ============ RBAC：成员协作 ============
// 后端接口：GET/POST/DELETE /api/kb/{kb_id}/members

export type KbRole = 'owner' | 'editor' | 'viewer'

export interface KbMember {
  /** owner 是虚拟行（创建者不存中间表），所以 id 可能为 null */
  id: number | null
  user_id: number
  username: string
  role: KbRole
  is_owner: boolean
  created_at?: string
}

export interface KbMemberList {
  items: KbMember[]
  /** 当前登录用户在该知识库的角色，用于控制「邀请 / 移除」按钮显隐 */
  my_role: KbRole
}

export const memberApi = {
  list: (kbId: number) =>
    request.get(`/kb/${kbId}/members`) as unknown as Promise<KbMemberList>,

  invite: (kbId: number, data: { username: string; role: 'editor' | 'viewer' }) =>
    request.post(`/kb/${kbId}/members`, data) as unknown as Promise<KbMember>,

  remove: (kbId: number, memberId: number) =>
    request.delete(`/kb/${kbId}/members/${memberId}`) as unknown as Promise<{ message: string }>,
}
