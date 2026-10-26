import request from './request'

export interface Source {
  document_name: string
  chunk_text: string
  score: number
  text?: string
  document_id?: number
  kb_id?: number
  char_start?: number
  char_end?: number
}

// 问答相关 API
export const chatApi = {
  // 普通问答
  chat: (data: {
    kb_id: number
    question: string
    conversation_id?: number
    use_agent?: boolean
  }) => request.post('/chat', data),

  // 推理增强问答（非流式，返回思考链）
  reasoning: (data: {
    kb_id: number
    question: string
    conversation_id?: number
    use_reasoning?: boolean
  }) => request.post('/chat/reasoning', data),

  // 流式问答（SSE）
  // 返回一个可取消的控制器和消息处理
  streamChat: (
    data: {
      kb_id: number
      question: string
      conversation_id?: number
      use_agent?: boolean
    },
    handlers: {
      onToken: (token: string) => void
      onStatus?: (status: string) => void
      onSources?: (sources: Source[]) => void
      onDone?: (data: { conversation_id: number; message_id: number; sources: Source[] }) => void
      onError?: (msg: string) => void
    }
  ) => {
    const token = localStorage.getItem('token')
    const controller = new AbortController()

    async function start() {
      try {
        const resp = await fetch('/api/chat/stream', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(data),
          signal: controller.signal,
        })

        if (!resp.ok || !resp.body) {
          handlers.onError?.('请求失败')
          return
        }

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed.startsWith('data: ')) continue
            const payload = JSON.parse(trimmed.slice(6))
            if (payload.error) {
              handlers.onError?.(payload.error)
            } else if (payload.status) {
              handlers.onStatus?.(payload.status)
            } else if (payload.token) {
              handlers.onToken(payload.token)
            } else if (payload.done) {
              handlers.onSources?.(payload.sources)
              handlers.onDone?.(payload)
            }
          }
        }
      } catch (e: any) {
        if (e.name !== 'AbortError') {
          handlers.onError?.(e.message)
        }
      }
    }

    start()
    return controller
  },

  // 反馈
  feedback: (data: { message_id: number; feedback: number; comment?: string }) =>
    request.post('/feedback', data),

  // 跨知识库问答
  globalChat: (data: { question: string; kb_ids?: number[] }) =>
    request.post('/chat/global', data),
}

// 对话历史 API
export const conversationApi = {
  create: (data: { kb_id: number; title?: string }) =>
    request.post('/conversations', data),

  list: (params: { kb_id?: number; page?: number; page_size?: number }) =>
    request.get('/conversations', { params }),

  detail: (id: number) => request.get(`/conversations/${id}`),

  update: (id: number, title: string) =>
    request.put(`/conversations/${id}`, { title }),

  delete: (id: number) => request.delete(`/conversations/${id}`),
}
