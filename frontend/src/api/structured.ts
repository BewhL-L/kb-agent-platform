import request from './request'
import type { AnswerTemplate, StructuredResponse } from '@/utils/structured_parse'

export type { StructuredResponse }

export interface StructuredPayload {
  question: string
  template: AnswerTemplate
  /** 传了才会先检索知识库，不传是纯生成 */
  kb_id?: number
}

export const structuredApi = {
  generate: (data: StructuredPayload) =>
    request.post('/structured/generate', data) as unknown as Promise<StructuredResponse>,
}
