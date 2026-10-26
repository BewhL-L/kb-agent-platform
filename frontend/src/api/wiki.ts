import request from './request'

// LLM Wiki 相关 API
export const wikiApi = {
  // 页面列表
  listPages: (
    kbId: number,
    params?: { entity_type?: string; keyword?: string }
  ) => request.get(`/wiki/kb/${kbId}/pages`, { params }),

  // 页面详情
  getPage: (pageId: number) => request.get(`/wiki/pages/${pageId}`),

  // 人工编辑页面
  editPage: (pageId: number, data: { content: string; summary?: string }) =>
    request.put(`/wiki/pages/${pageId}`, data),

  // 页面历史版本
  listVersions: (pageId: number) =>
    request.get(`/wiki/pages/${pageId}/versions`),

  // 回滚到指定版本
  rollback: (pageId: number, versionId: number) =>
    request.post(`/wiki/pages/${pageId}/rollback/${versionId}`),

  // 重编译知识库（wait=true 时等待结果）
  recompile: (kbId: number, wait = false) =>
    request.post(`/wiki/kb/${kbId}/recompile`, null, { params: { wait } }),

  // 关联图谱
  getGraph: (kbId: number) => request.get(`/wiki/kb/${kbId}/graph`),

  // 删除页面
  deletePage: (pageId: number) => request.delete(`/wiki/pages/${pageId}`),
}
