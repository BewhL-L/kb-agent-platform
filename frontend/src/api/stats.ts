import request from './request'

// 数据统计 API
export const statsApi = {
  getStats: () => request.get('/stats'),

  // LLM 成本与用量统计
  getCostStats: (days = 30) =>
    request.get('/stats/cost', { params: { days } }),

  // 主动学习：负反馈归因
  getActiveLearning: (days = 30) =>
    request.get('/stats/active-learning', { params: { days } }),
}

// AI Agent API
export const agentApi = {
  getTools: () => request.get('/agent/tools'),
  chat: (data: { question: string; history?: Array<{ role: string; content: string }>; kb_id?: number }) =>
    request.post('/agent/chat', data),

  // 多 Agent 协作（返回 steps 用于流程可视化）
  multiAgent: (data: { question: string; kb_id: number; backend?: string }) =>
    request.post('/agent/multi-agent', data),
}
