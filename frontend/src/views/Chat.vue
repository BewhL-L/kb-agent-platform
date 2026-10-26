<template>
  <div class="chat-page">
    <!-- 对话列表侧边栏 -->
    <div class="conv-sidebar">
      <div class="conv-sidebar-header">
        <el-select v-model="selectedKb" placeholder="选择知识库" style="width: 100%" @change="onKbChange">
          <el-option
            v-for="kb in kbStore.kbList"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          />
        </el-select>
      </div>
      <el-button type="primary" class="new-chat-btn" :icon="Plus" @click="newChat">
        新建对话
      </el-button>
      <div class="conv-list">
        <div
          v-for="conv in chatStore.conversations"
          :key="conv.id"
          class="conv-item"
          :class="{ active: chatStore.currentConvId === conv.id }"
          @click="switchConv(conv)"
        >
          <el-icon><ChatLineRound /></el-icon>
          <span class="conv-title">{{ conv.title }}</span>
          <el-icon class="conv-del" @click.stop="handleDeleteConv(conv.id)"><Delete /></el-icon>
        </div>
        <el-empty v-if="chatStore.conversations.length === 0" description="暂无对话" :image-size="60" />
      </div>
    </div>

    <!-- 聊天主区域 -->
    <div class="chat-main">
      <div class="chat-header">
        <h3>{{ currentKbName || '智能问答' }}</h3>
        <div class="header-actions">
          <el-button type="warning" plain size="small" :icon="Connection" @click="openGlobalChat">
            跨库问答
          </el-button>
          <el-switch v-model="useAgent" active-text="Agent 模式" inactive-text="" />
        </div>
      </div>

      <div class="message-list" ref="messageListRef">
        <el-empty v-if="chatStore.messages.length === 0" description="选择知识库，开始提问吧">
          <div class="suggestions">
            <el-button
              v-for="q in suggestions"
              :key="q"
              round
              @click="askSuggestion(q)"
            >{{ q }}</el-button>
          </div>
        </el-empty>

        <div v-for="(msg, idx) in chatStore.messages" :key="idx" class="message-item" :class="msg.role">
          <el-avatar :size="36" class="msg-avatar">
            <el-icon v-if="msg.role === 'user'"><User /></el-icon>
            <el-icon v-else><Cpu /></el-icon>
          </el-avatar>
          <div class="msg-body">
            <div class="msg-bubble" :class="msg.role">
              <span v-if="msg.loading" class="typing-cursor">
                <el-icon class="is-loading"><Loading /></el-icon>
                {{ msg.statusText || '正在思考...' }}
              </span>
              <template v-else>
                <!-- 推理链（折叠展示） -->
                <el-collapse v-if="msg.reasoning" class="reasoning-collapse">
                  <el-collapse-item :name="1">
                    <template #title>
                      <span class="reasoning-title">
                        <el-icon><Cpu /></el-icon>
                        深度思考过程（点击展开）
                      </span>
                    </template>
                    <div class="reasoning-text">{{ msg.reasoning }}</div>
                  </el-collapse-item>
                </el-collapse>
                <div class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
              </template>
            </div>

            <!-- 来源引用 -->
            <div v-if="msg.sources && msg.sources.length > 0" class="sources">
              <div class="sources-title">
                <el-icon><Link /></el-icon> 参考来源（{{ msg.sources.length }}）
              </div>
              <el-collapse>
                <el-collapse-item v-for="(s, i) in msg.sources" :key="i" :name="i">
                  <template #title>
                    <span class="source-title-text">
                      {{ s.document_name }}（相似度 {{ (s.score * 100).toFixed(0) }}%）
                      <el-tag
                        v-if="s.kb_id"
                        size="small"
                        type="warning"
                        style="margin-left: 6px"
                      >跨库</el-tag>
                    </span>
                  </template>
                  <p class="source-text">{{ s.text || s.chunk_text }}</p>
                  <el-button
                    type="primary"
                    size="small"
                    link
                    :icon="Aim"
                    @click="locateSource(s)"
                  >定位到原文</el-button>
                </el-collapse-item>
              </el-collapse>
            </div>

            <!-- 操作：复制 / 重新生成 / 点赞 / 点踩 -->
            <div v-if="msg.role === 'assistant' && msg.id && !msg.loading" class="feedback">
              <el-icon title="复制" @click="copyContent(msg.content)"><CopyDocument /></el-icon>
              <el-icon
                title="语音播报"
                :class="{ speaking: speakingId === msg.id }"
                @click="toggleSpeak(msg)"
              ><Microphone /></el-icon>
              <el-icon
                v-if="idx === chatStore.messages.length - 1"
                title="重新生成"
                @click="regen"
              ><RefreshRight /></el-icon>
              <el-icon
                :class="{ active: msg.feedback === 1 }"
                title="有用"
                @click="handleFeedback(msg, 1)"
              ><Pointer /></el-icon>
              <el-icon
                :class="{ active: msg.feedback === -1 }"
                title="没用"
                @click="handleFeedback(msg, -1)"
              ><CircleClose /></el-icon>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="chat-input-area">
        <el-button
          circle
          :icon="listening ? VideoPause : Microphone"
          :type="listening ? 'danger' : 'default'"
          :title="listening ? '正在聆听，点击停止' : '语音输入'"
          @click="toggleVoiceInput"
        />
        <el-input
          v-model="question"
          type="textarea"
          :rows="2"
          :disabled="!selectedKb"
          :placeholder="selectedKb ? '输入你的问题，Enter 发送，Shift+Enter 换行' : '请先选择知识库'"
          resize="none"
          @keydown.enter.exact.prevent="send"
        />
        <el-button
          type="warning"
          circle
          :icon="Cpu"
          title="深度推理（思考链）"
          :disabled="!selectedKb"
          @click="sendReasoning"
        />
        <el-button
          type="primary"
          circle
          :icon="chatStore.sending ? VideoPause : Promotion"
          class="send-btn"
          @click="chatStore.sending ? chatStore.stopGenerate() : send()"
        />
      </div>
    </div>

    <!-- 文档定位预览对话框 -->
    <el-dialog
      v-model="locateVisible"
      :title="locateDocName"
      width="800px"
      top="5vh"
    >
      <div v-loading="locateLoading" class="locate-body">
        <iframe
          v-if="locateType === 'pdf'"
          :src="locateFileUrl"
          class="locate-iframe"
        ></iframe>
        <div
          v-else
          class="markdown-body locate-text"
          v-html="locateRendered"
        ></div>
      </div>
    </el-dialog>

    <!-- 跨库问答对话框 -->
    <el-dialog v-model="globalVisible" title="跨知识库问答" width="800px" top="5vh">
      <el-select
        v-model="globalKbIds"
        multiple
        collapse-tags
        collapse-tags-tooltip
        placeholder="不选则检索所有知识库"
        style="width: 100%; margin-bottom: 12px"
      >
        <el-option
          v-for="kb in kbStore.kbList"
          :key="kb.id"
          :label="kb.name"
          :value="kb.id"
        />
      </el-select>
      <div class="global-chat-log">
        <div v-for="(m, i) in globalMessages" :key="i" class="global-msg" :class="m.role">
          <div class="markdown-body" v-html="renderMarkdown(m.content)"></div>
        </div>
      </div>
      <div class="global-input">
        <el-input
          v-model="globalQuestion"
          placeholder="输入问题，跨多个知识库检索"
          @keydown.enter="sendGlobal"
        />
        <el-button type="primary" :loading="globalLoading" @click="sendGlobal">发送</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Plus, Delete, User, Cpu, Promotion, Link, Pointer,
  CircleClose, ChatLineRound, Loading, VideoPause,
  CopyDocument, RefreshRight, Aim, Microphone, Connection,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
// 按需引入 highlight.js 核心与常用语言（全量引入会打包上百种语言，体积巨大）
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import bash from 'highlight.js/lib/languages/bash'
import jsonLang from 'highlight.js/lib/languages/json'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import sql from 'highlight.js/lib/languages/sql'
import markdownLang from 'highlight.js/lib/languages/markdown'
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('ts', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('shell', bash)
hljs.registerLanguage('json', jsonLang)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('markdown', markdownLang)
import 'highlight.js/styles/github.css'
import { useKbStore } from '@/stores/kb'
import { useChatStore } from '@/stores/chat'
import { docApi } from '@/api/knowledge'
import { chatApi } from '@/api/chat'

// Markdown 渲染 + 代码高亮
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(str: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang }).value}</code></pre>`
      } catch {
        // fallthrough
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  },
})
function renderMarkdown(text: string) {
  return md.render(text || '')
}

function copyContent(text: string) {
  navigator.clipboard.writeText(text).then(() => ElMessage.success('已复制到剪贴板'))
}

const route = useRoute()
const kbStore = useKbStore()
const chatStore = useChatStore()

const selectedKb = ref<number | null>(null)
const question = ref('')
const useAgent = ref(false)
const messageListRef = ref<HTMLElement>()

// ===== 文档定位预览 =====
const locateVisible = ref(false)
const locateLoading = ref(false)
const locateDocName = ref('')
const locateType = ref<'pdf' | 'text'>('text')
const locateFileUrl = ref('')
const locateContent = ref('')
const locateHighlight = { start: 0, end: 0 }
const locateMd = new MarkdownIt({ html: false, linkify: true, breaks: true })
const locateRendered = computed(() => {
  const text = locateContent.value
  const { start, end } = locateHighlight
  if (start >= 0 && end > start && end <= text.length) {
    const before = locateMd.utils.escapeHtml(text.slice(0, start))
    const hit = locateMd.utils.escapeHtml(text.slice(start, end))
    const after = locateMd.utils.escapeHtml(text.slice(end))
    return `<p>${before}<mark class="locate-hit">${hit}</mark>${after}</p>`
  }
  return locateMd.render(text)
})

// ===== 语音播报 =====
const speakingId = ref<number | null>(null)

// ===== 语音输入 =====
const listening = ref(false)
let recognition: any = null

// ===== 跨库问答 =====
const globalVisible = ref(false)
const globalKbIds = ref<number[]>([])
const globalQuestion = ref('')
const globalLoading = ref(false)
const globalMessages = ref<Array<{ role: string; content: string }>>([])

const suggestions = ['这个知识库主要讲了什么？', '帮我总结核心要点', '有哪些常见问题？']

const currentKbName = computed(() => {
  return kbStore.kbList.find((k) => k.id === selectedKb.value)?.name
})

async function onKbChange() {
  chatStore.newConversation()
  if (selectedKb.value) {
    await chatStore.fetchConversations(selectedKb.value)
  }
}

function newChat() {
  chatStore.newConversation()
}

async function switchConv(conv: any) {
  selectedKb.value = conv.kb_id
  await chatStore.loadConversation(conv.id)
  scrollToBottom()
}

async function send() {
  if (!question.value.trim() || !selectedKb.value) return
  const q = question.value
  question.value = ''
  await chatStore.sendMessage(selectedKb.value, q, useAgent.value)
  scrollToBottom()
}

async function sendReasoning() {
  if (!question.value.trim() || !selectedKb.value) return
  const q = question.value
  question.value = ''
  await chatStore.sendReasoning(selectedKb.value, q, true)
  scrollToBottom()
}

async function regen() {
  if (!selectedKb.value) return
  await chatStore.regenerate(selectedKb.value, useAgent.value)
  scrollToBottom()
}

function askSuggestion(q: string) {
  question.value = q
  if (selectedKb.value) send()
}

async function handleDeleteConv(id: number) {
  const { ElMessageBox } = await import('element-plus')
  await ElMessageBox.confirm('确定删除这个对话吗？', '提示', { type: 'warning' })
  await chatStore.deleteConversation(id)
}

// ===== 文档定位 =====
async function locateSource(s: any) {
  if (!s.document_id) {
    ElMessage.warning('该来源没有文档 ID，无法定位')
    return
  }
  locateDocName.value = s.document_name
  locateVisible.value = true
  locateLoading.value = true
  try {
    const res: any = await docApi.preview(s.document_id)
    if (res.file_url) {
      locateType.value = 'pdf'
      locateFileUrl.value = res.file_url
    } else {
      locateType.value = 'text'
      locateContent.value = res.content
      // 用来源文本在全文中定位
      const needle = (s.text || s.chunk_text || '').slice(0, 50)
      const idx = needle ? res.content.indexOf(needle) : -1
      locateHighlight.start = idx >= 0 ? idx : (s.char_start ?? -1)
      locateHighlight.end = idx >= 0 ? idx + (s.text || s.chunk_text).length : (s.char_end ?? -1)
    }
  } finally {
    locateLoading.value = false
  }
}

// ===== 语音播报 =====
function toggleSpeak(msg: any) {
  if (!('speechSynthesis' in window)) {
    ElMessage.warning('当前浏览器不支持语音播报')
    return
  }
  if (speakingId.value === msg.id) {
    window.speechSynthesis.cancel()
    speakingId.value = null
    return
  }
  window.speechSynthesis.cancel()
  const utter = new SpeechSynthesisUtterance(msg.content)
  utter.lang = 'zh-CN'
  utter.onend = () => { speakingId.value = null }
  speakingId.value = msg.id
  window.speechSynthesis.speak(utter)
}

// ===== 语音输入 =====
function toggleVoiceInput() {
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SR) {
    ElMessage.warning('当前浏览器不支持语音识别，请使用 Chrome/Edge')
    return
  }
  if (listening.value) {
    recognition?.stop()
    listening.value = false
    return
  }
  recognition = new SR()
  recognition.lang = 'zh-CN'
  recognition.continuous = false
  recognition.interimResults = true
  recognition.onresult = (e: any) => {
    const text = Array.from(e.results).map((r: any) => r[0].transcript).join('')
    question.value = text
  }
  recognition.onend = () => { listening.value = false }
  recognition.onerror = () => { listening.value = false }
  recognition.start()
  listening.value = true
}

// ===== 跨库问答 =====
function openGlobalChat() {
  globalVisible.value = true
  globalMessages.value = []
}

async function sendGlobal() {
  if (!globalQuestion.value.trim()) return
  const q = globalQuestion.value
  globalMessages.value.push({ role: 'user', content: q })
  globalQuestion.value = ''
  globalLoading.value = true
  try {
    const res: any = await chatApi.globalChat({
      question: q,
      kb_ids: globalKbIds.value,
    })
    globalMessages.value.push({ role: 'assistant', content: res.answer })
  } finally {
    globalLoading.value = false
  }
}

async function handleFeedback(msg: any, value: number) {
  if (!msg.id) return
  await chatStore.feedback(msg.id, msg.feedback === value ? 0 : value)
}

function scrollToBottom() {
  nextTick(() => {
    const el = messageListRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

watch(
  () => chatStore.messages.map((m) => m.content).join(''),
  () => scrollToBottom()
)

onMounted(async () => {
  await kbStore.fetchList()
  const kbFromQuery = route.query.kb ? Number(route.query.kb) : null
  if (kbFromQuery && kbStore.kbList.some((k) => k.id === kbFromQuery)) {
    selectedKb.value = kbFromQuery
  } else if (kbStore.kbList.length > 0) {
    selectedKb.value = kbStore.kbList[0].id
  }
  if (selectedKb.value) {
    await chatStore.fetchConversations(selectedKb.value)
  }
})
</script>

<style scoped>
.chat-page {
  display: flex;
  height: calc(100vh - 40px - 60px);
  gap: 16px;
}
.conv-sidebar {
  width: 260px;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
}
.new-chat-btn {
  margin: 12px 0;
}
.conv-list {
  flex: 1;
  overflow-y: auto;
}
.conv-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
  color: #606266;
}
.conv-item:hover {
  background: #f5f7fa;
}
.conv-item.active {
  background: #ecf5ff;
  color: #409eff;
}
.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
}
.conv-del {
  opacity: 0;
  color: #f56c6c;
}
.conv-item:hover .conv-del {
  opacity: 1;
}
.chat-main {
  flex: 1;
  background: #fff;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chat-header {
  padding: 16px 20px;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}
.suggestions {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
}
.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
}
.msg-avatar {
  flex-shrink: 0;
}
.message-item.user .msg-avatar {
  background: #67c23a;
}
.message-item.assistant .msg-avatar {
  background: #409eff;
}
.msg-body {
  flex: 1;
  max-width: 80%;
}
.msg-bubble {
  padding: 12px 16px;
  border-radius: 10px;
  line-height: 1.6;
}
.msg-bubble.user {
  background: #409eff;
  color: #fff;
  border-top-right-radius: 2px;
}
.msg-bubble.assistant {
  background: #f5f7fa;
  color: #1f2937;
  border-top-left-radius: 2px;
}
/* 推理链折叠 */
.reasoning-collapse {
  margin-bottom: 8px;
  border-bottom: 1px dashed #dcdfe6;
}
.reasoning-title {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #b88230;
  font-size: 13px;
}
.reasoning-text {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.7;
  color: #6b7280;
  background: #faf6ee;
  border-radius: 6px;
  padding: 8px 10px;
  max-height: 320px;
  overflow-y: auto;
}
.message-item.user {
  flex-direction: row-reverse;
}
.typing-cursor {
  color: #909399;
  display: flex;
  align-items: center;
  gap: 6px;
}
.sources {
  margin-top: 8px;
}
.sources-title {
  font-size: 13px;
  color: #909399;
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 4px;
}
.source-text {
  font-size: 13px;
  color: #606266;
  background: #fafafa;
  padding: 8px;
  border-radius: 4px;
}
.feedback {
  margin-top: 6px;
  display: flex;
  gap: 12px;
}
.feedback .el-icon {
  cursor: pointer;
  color: #c0c4cc;
}
.feedback .el-icon:hover {
  color: #409eff;
}
.feedback .el-icon.active {
  color: #409eff;
}
.markdown-body :deep(.hljs) {
  padding: 12px;
  border-radius: 6px;
  margin: 8px 0;
  overflow-x: auto;
  background: #f6f8fa;
}
.markdown-body :deep(code) {
  font-family: "Consolas", "Courier New", monospace;
  font-size: 13px;
}
.markdown-body :deep(:not(pre) > code) {
  background: #eef1f4;
  padding: 2px 6px;
  border-radius: 4px;
}
.chat-input-area {
  padding: 16px 20px;
  border-top: 1px solid #ebeef5;
  display: flex;
  gap: 12px;
  align-items: flex-end;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.source-title-text {
  font-size: 13px;
}
.locate-body {
  min-height: 400px;
}
.locate-iframe {
  width: 100%;
  height: 70vh;
  border: none;
}
.locate-text {
  max-height: 70vh;
  overflow-y: auto;
}
:deep(.locate-hit) {
  background: #fef08a;
  padding: 2px 4px;
  border-radius: 3px;
}
.feedback .el-icon.speaking {
  color: #67c23a;
}
.global-chat-log {
  max-height: 50vh;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
}
.global-msg {
  margin-bottom: 12px;
}
.global-msg.user {
  text-align: right;
}
.global-msg.user .markdown-body {
  background: #ecf5ff;
  display: inline-block;
  padding: 8px 12px;
  border-radius: 8px;
}
.global-input {
  display: flex;
  gap: 8px;
}
.send-btn {
  flex-shrink: 0;
}
</style>
