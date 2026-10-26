<template>
  <div class="agent-page">
    <h2 class="page-title">AI Agent 演示</h2>
    <el-alert
      type="info"
      :closable="false"
      title="单 Agent 演示 Function Calling（自动调用工具）；多 Agent 演示多个角色分工协作，可看到完整的思考与执行流程"
      style="margin-bottom: 20px"
    />

    <el-tabs v-model="activeTab">
      <!-- ============ 单 Agent 工具调用 ============ -->
      <el-tab-pane label="单 Agent 工具调用" name="single">
        <el-row :gutter="20">
          <el-col :span="14">
            <el-card shadow="never" class="agent-chat-card">
              <div class="agent-message-list" ref="listRef">
                <div v-if="messages.length === 0" class="empty-tip">
                  <el-icon :size="40"><MagicStick /></el-icon>
                  <p>试试下面的问题，观察 Agent 如何调用工具</p>
                </div>
                <div v-for="(m, i) in messages" :key="i" class="agent-msg" :class="m.role">
                  <div class="agent-bubble">{{ m.content }}</div>
                </div>
                <div v-if="loading" class="agent-msg assistant">
                  <div class="agent-bubble loading">
                    <el-icon class="is-loading"><Loading /></el-icon> Agent 思考中...
                  </div>
                </div>
              </div>
              <div class="agent-input">
                <el-input
                  v-model="question"
                  placeholder="问 Agent 一个问题，Enter 发送"
                  @keyup.enter="send"
                />
                <el-button type="primary" :loading="loading" @click="send">发送</el-button>
              </div>
            </el-card>
          </el-col>

          <el-col :span="10">
            <el-card shadow="never">
              <template #header>Agent 可用工具</template>
              <div v-for="tool in tools" :key="tool.name" class="tool-item">
                <el-tag type="success">{{ tool.name }}</el-tag>
                <p>{{ tool.description }}</p>
              </div>
            </el-card>

            <el-card shadow="never" style="margin-top: 20px">
              <template #header>试试这些问题</template>
              <el-button
                v-for="q in demoQuestions"
                :key="q"
                style="margin: 4px"
                round
                @click="question = q; send()"
              >{{ q }}</el-button>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- ============ 多 Agent 协作 ============ -->
      <el-tab-pane label="多 Agent 协作" name="multi">
        <el-row :gutter="20">
          <el-col :span="10">
            <el-card shadow="never">
              <template #header>发起多 Agent 任务</template>
              <el-select
                v-model="multiKb"
                placeholder="选择知识库"
                style="width: 100%; margin-bottom: 14px"
              >
                <el-option
                  v-for="kb in kbStore.kbList"
                  :key="kb.id"
                  :label="kb.name"
                  :value="kb.id"
                />
              </el-select>
              <el-input
                v-model="multiQuestion"
                type="textarea"
                :rows="4"
                placeholder="提出一个较复杂的问题，例如：梳理 RAG 的完整流程并说明各组件作用"
              />
              <el-button
                type="primary"
                style="margin-top: 14px; width: 100%"
                :loading="multiLoading"
                :disabled="!multiKb"
                @click="runMultiAgent"
              >开始协作</el-button>

              <el-alert
                type="success"
                :closable="false"
                style="margin-top: 14px"
                title="角色说明"
                description="planner 拆解任务 → researcher 检索知识库 → writer 撰写答案 → supervisor 质量审核"
              />
            </el-card>
          </el-col>

          <el-col :span="14">
            <el-card shadow="never" class="multi-flow-card">
              <template #header>协作流程</template>
              <el-empty v-if="steps.length === 0" description="暂无流程，发起任务后可看到各 Agent 的工作" />
              <el-timeline v-else>
                <el-timeline-item
                  v-for="(s, i) in steps"
                  :key="i"
                  :type="agentColor[s.agent] || 'primary'"
                  :timestamp="s.title"
                >
                  <el-tag size="small" :type="agentColor[s.agent] || 'primary'" effect="plain">
                    {{ agentLabel[s.agent] || s.agent }}
                  </el-tag>
                  <div class="step-output">{{ s.output }}</div>
                </el-timeline-item>
              </el-timeline>
            </el-card>

            <el-card v-if="multiAnswer" shadow="never" style="margin-top: 16px">
              <template #header>最终答案</template>
              <div class="markdown-body" v-html="renderMd(multiAnswer)"></div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { MagicStick, Loading } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import { agentApi } from '@/api/stats'
import { useKbStore } from '@/stores/kb'

const md = new MarkdownIt({ html: false, linkify: true })
const renderMd = (t: string) => md.render(t || '')

const kbStore = useKbStore()
const activeTab = ref('single')

// ===== 单 Agent =====
const messages = ref<{ role: string; content: string }[]>([
  { role: 'assistant', content: '你好！我是 AI Agent，我可以调用工具来帮你查询时间和做数学计算。' },
])
const tools = ref<{ name: string; description: string }[]>([])
const question = ref('')
const loading = ref(false)
const listRef = ref<HTMLElement>()

const demoQuestions = [
  '现在几点了？',
  '今天星期几？',
  '帮我算一下 (128 + 256) * 0.8',
  '10000 元存一年，年利率 3%，利息是多少？',
]

// ===== 多 Agent =====
const multiKb = ref<number | null>(null)
const multiQuestion = ref('')
const multiLoading = ref(false)
const steps = ref<Array<{ agent: string; title: string; output: string }>>([])
const multiAnswer = ref('')

const agentColor: Record<string, string> = {
  planner: 'warning',
  researcher: 'primary',
  writer: 'success',
  supervisor: 'danger',
}
const agentLabel: Record<string, string> = {
  planner: '规划者',
  researcher: '研究员',
  writer: '撰写者',
  supervisor: '监督者',
}

async function loadTools() {
  try {
    const res: any = await agentApi.getTools()
    tools.value = res.tools
  } catch (e) {
    // 忽略
  }
}

async function send() {
  if (!question.value.trim() || loading.value) return
  const q = question.value
  question.value = ''
  messages.value.push({ role: 'user', content: q })
  loading.value = true
  scrollBottom()
  try {
    const history = messages.value.slice(-10)
    const res: any = await agentApi.chat({ question: q, history })
    messages.value.push({ role: 'assistant', content: res.answer })
  } catch (e) {
    messages.value.push({ role: 'assistant', content: '出错了，请检查后端 LLM 配置' })
  } finally {
    loading.value = false
    scrollBottom()
  }
}

async function runMultiAgent() {
  if (!multiKb.value || !multiQuestion.value.trim()) return
  multiLoading.value = true
  steps.value = []
  multiAnswer.value = ''
  try {
    const res: any = await agentApi.multiAgent({
      question: multiQuestion.value,
      kb_id: multiKb.value,
      backend: 'native',
    })
    steps.value = res.steps || []
    multiAnswer.value = res.answer
  } catch (e) {
    steps.value = [
      { agent: 'supervisor', title: '执行失败', output: '请检查后端 LLM 配置和知识库内容' },
    ]
  } finally {
    multiLoading.value = false
  }
}

function scrollBottom() {
  nextTick(() => {
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
  })
}

onMounted(async () => {
  await kbStore.fetchList()
  await loadTools()
})
</script>

<style scoped>
.page-title {
  font-size: 20px;
  margin-bottom: 20px;
}
.agent-chat-card {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 240px);
}
.agent-message-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
.empty-tip {
  text-align: center;
  color: #909399;
  margin-top: 60px;
}
.agent-msg {
  display: flex;
  margin-bottom: 14px;
}
.agent-msg.user {
  justify-content: flex-end;
}
.agent-bubble {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 10px;
  line-height: 1.6;
}
.agent-msg.user .agent-bubble {
  background: #409eff;
  color: #fff;
}
.agent-msg.assistant .agent-bubble {
  background: #f5f7fa;
}
.agent-bubble.loading {
  color: #909399;
}
.agent-input {
  display: flex;
  gap: 10px;
  padding: 12px;
  border-top: 1px solid #ebeef5;
}
.tool-item {
  margin-bottom: 14px;
}
.tool-item p {
  margin-top: 6px;
  font-size: 13px;
  color: #606266;
}
.multi-flow-card {
  min-height: 300px;
}
.step-output {
  margin-top: 6px;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}
</style>
