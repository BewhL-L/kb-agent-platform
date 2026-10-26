import request from './request'

// 评测报告汇总指标
export interface EvalSummary {
  'hit@k': number | null
  mrr: number | null
  context_precision: number | null
  context_recall: number | null
  answer_keyword_coverage: number | null
  faithfulness: number | null
  answer_relevancy: number | null
  case_count: number
  avg_latency_s: number | null
}

// 评测报告单条用例结果
export interface EvalCaseRow {
  id: string
  category: string
  question: string
  'hit@k': number | null
  mrr: number | null
  context_precision: number | null
  context_recall: number | null
  answer_keyword_coverage: number | null
  faithfulness: number | null
  answer_relevancy: number | null
  latency_s: number
}

// 评测报告
export interface EvalReport {
  run_at: string
  summary: EvalSummary
  cases: EvalCaseRow[]
  ragas?: Record<string, number>
  report_path?: string
  message?: string
}

// RAG 评测 API
export const evaluationApi = {
  // 触发评测（可选指定知识库；LLM 裁判开启时耗时较长）
  run: (kbId?: number) =>
    request.post('/evaluation/run', null, {
      params: kbId != null ? { kb_id: kbId } : {},
      timeout: 600000,
    }),
  // 查看最新评测报告
  latest: () => request.get<unknown, EvalReport>('/evaluation/latest'),
}
