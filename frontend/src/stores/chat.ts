import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatApi, conversationApi, type Source } from '@/api/chat'

export interface ChatMessage {
  id?: number
  conversation_id?: number
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  feedback?: number
  loading?: boolean
  statusText?: string
  // 推理模型的思考链（折叠展示）
  reasoning?: string
  reasoned?: boolean
}

export interface Conversation {
  id: number
  kb_id: number
  title: string
  message_count?: number
  created_at: string
  updated_at: string
}

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const currentConvId = ref<number | null>(null)
  const messages = ref<ChatMessage[]>([])
  const sending = ref(false)
  let streamController: AbortController | null = null

  // 内部：发起一次流式问答，结果写入给定的 AI 占位消息
  function _stream(kbId: number, question: string, useAgent: boolean, aiMsg: ChatMessage) {
    streamController = chatApi.streamChat(
      {
        kb_id: kbId,
        question,
        conversation_id: currentConvId.value || undefined,
        use_agent: useAgent,
      },
      {
        onStatus: (status) => {
          aiMsg.statusText = status
          aiMsg.loading = true
        },
        onToken: (token) => {
          aiMsg.content += token
          aiMsg.loading = false
          aiMsg.statusText = ''
        },
        onSources: (sources) => {
          aiMsg.sources = sources
        },
        onDone: (data) => {
          aiMsg.id = data.message_id
          aiMsg.sources = data.sources
          aiMsg.loading = false
          aiMsg.statusText = ''
          currentConvId.value = data.conversation_id
          sending.value = false
          fetchConversations(kbId)
        },
        onError: (msg) => {
          aiMsg.content = `出错了：${msg}`
          aiMsg.loading = false
          aiMsg.statusText = ''
          sending.value = false
        },
      }
    )
  }

  // 发送消息（流式）
  async function sendMessage(kbId: number, question: string, useAgent = false) {
    if (!question.trim() || sending.value) return
    sending.value = true

    messages.value.push({ role: 'user', content: question })
    const aiMsg: ChatMessage = {
      role: 'assistant', content: '', loading: true, statusText: '', sources: [],
    }
    messages.value.push(aiMsg)

    _stream(kbId, question, useAgent, aiMsg)
  }

  // 推理增强问答（非流式，等待思考完成）
  async function sendReasoning(kbId: number, question: string, force = true) {
    if (!question.trim() || sending.value) return
    sending.value = true

    messages.value.push({ role: 'user', content: question })
    const aiMsg: ChatMessage = {
      role: 'assistant', content: '', loading: true,
      statusText: '模型正在深度推理…', sources: [],
    }
    messages.value.push(aiMsg)

    try {
      const res: any = await chatApi.reasoning({
        kb_id: kbId,
        question,
        conversation_id: currentConvId.value || undefined,
        use_reasoning: force,
      })
      aiMsg.content = res.answer
      aiMsg.reasoning = res.reasoning
      aiMsg.reasoned = res.reasoned
      aiMsg.id = res.message_id
      aiMsg.sources = res.sources
      currentConvId.value = res.conversation_id
      fetchConversations(kbId)
    } catch (e: any) {
      aiMsg.content = `出错了：${e?.message || '推理失败'}`
    } finally {
      aiMsg.loading = false
      aiMsg.statusText = ''
      sending.value = false
    }
  }
  async function regenerate(kbId: number, useAgent = false) {
    if (sending.value) return
    const lastUserIdx = [...messages.value].map((m) => m.role).lastIndexOf('user')
    if (lastUserIdx === -1) return
    const question = messages.value[lastUserIdx].content

    // 移除该用户问题之后的内容，重新等待回答
    messages.value = messages.value.slice(0, lastUserIdx + 1)
    sending.value = true

    const aiMsg: ChatMessage = {
      role: 'assistant', content: '', loading: true, statusText: '', sources: [],
    }
    messages.value.push(aiMsg)

    _stream(kbId, question, useAgent, aiMsg)
  }

  function stopGenerate() {
    streamController?.abort()
    sending.value = false
  }

  async function fetchConversations(kbId?: number) {
    const res: any = await conversationApi.list({ kb_id: kbId, page: 1, page_size: 50 })
    conversations.value = res.items
  }

  async function loadConversation(convId: number) {
    const res: any = await conversationApi.detail(convId)
    currentConvId.value = convId
    messages.value = res.messages.map((m: any) => ({
      id: m.id,
      conversation_id: m.conversation_id,
      role: m.role,
      content: m.content,
      sources: m.sources || [],
      feedback: m.feedback,
    }))
  }

  function newConversation() {
    currentConvId.value = null
    messages.value = []
  }

  async function deleteConversation(convId: number) {
    await conversationApi.delete(convId)
    conversations.value = conversations.value.filter((c) => c.id !== convId)
    if (currentConvId.value === convId) {
      newConversation()
    }
  }

  async function feedback(messageId: number, value: number) {
    await chatApi.feedback({ message_id: messageId, feedback: value })
    const msg = messages.value.find((m) => m.id === messageId)
    if (msg) msg.feedback = value
  }

  return {
    conversations,
    currentConvId,
    messages,
    sending,
    sendMessage,
    sendReasoning,
    regenerate,
    stopGenerate,
    fetchConversations,
    loadConversation,
    newConversation,
    deleteConversation,
    feedback,
  }
})
