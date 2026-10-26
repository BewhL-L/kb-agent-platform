import request from './request'

export interface GraphNode {
  id: number
  name: string
  entity_type: string
  summary: string
  degree: number
  community_id: number | null
}

export interface GraphEdge {
  id: number
  source_id: number
  target_id: number
  source: string
  target: string
  relation_type: string
}

export interface GraphCommunity {
  id: number
  title: string
  summary: string
  entity_count: number
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  communities: GraphCommunity[]
}

export interface GraphStatus {
  status: string
  entities: number
  relations: number
  communities: number
}

// GraphRAG 相关 API
export const graphragApi = {
  // 构建图谱
  build: (kb_id: number, doc_ids?: number[]): Promise<any> =>
    request.post(`/graphrag/kb/${kb_id}/build`, { doc_ids: doc_ids || null }) as any,

  // 构建状态
  status: (kb_id: number): Promise<any> =>
    request.get(`/graphrag/kb/${kb_id}/status`) as any,

  // 图谱数据（可视化）
  graph: (kb_id: number): Promise<GraphData> =>
    request.get(`/graphrag/kb/${kb_id}/graph`) as any,

  // 局部检索
  local: (kb_id: number, question: string): Promise<any> =>
    request.post(`/graphrag/kb/${kb_id}/local`, { question }) as any,

  // 全局检索
  global: (kb_id: number, question: string): Promise<any> =>
    request.post(`/graphrag/kb/${kb_id}/global`, { question }) as any,
}
