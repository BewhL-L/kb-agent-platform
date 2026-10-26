<template>
  <div class="graphrag-page">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <el-select
        v-model="selectedKb"
        placeholder="选择知识库"
        style="width: 260px"
        @change="onKbChange"
      >
        <el-option
          v-for="kb in kbStore.kbList"
          :key="kb.id"
          :label="kb.name"
          :value="kb.id"
        />
      </el-select>

      <el-button
        type="primary"
        :icon="MagicStick"
        :loading="building"
        @click="handleBuild"
      >构建图谱</el-button>

      <el-tag v-if="status" :type="statusTagType" effect="plain">
        {{ statusText }}
      </el-tag>

      <el-radio-group v-model="searchMode" style="margin-left: auto">
        <el-radio-button value="local">局部检索</el-radio-button>
        <el-radio-button value="global">全局检索</el-radio-button>
      </el-radio-group>
    </div>

    <el-empty
      v-if="!selectedKb"
      description="请先选择一个知识库"
      style="margin-top: 80px"
    />

    <div v-else class="graphrag-body">
      <!-- 左侧：图谱可视化 -->
      <div class="graph-panel">
        <div class="panel-title">知识图谱（节点按社区着色）</div>
        <v-chart
          class="graph-chart"
          :option="chartOption"
          autoresize
          v-loading="loadingGraph"
        />
      </div>

      <!-- 右侧：问答 -->
      <div class="qa-panel">
        <div class="panel-title">
          {{ searchMode === 'local' ? '局部检索（具体实体）' : '全局检索（整体主题）' }}
        </div>
        <div class="qa-messages">
          <div
            v-for="(m, i) in messages"
            :key="i"
            class="qa-msg"
            :class="m.role"
          >
            <div class="msg-content" v-html="renderMd(m.content)"></div>
          </div>
        </div>
        <div class="qa-input">
          <el-input
            v-model="question"
            type="textarea"
            :rows="2"
            :placeholder="searchMode === 'local'
              ? '例如：RAG 的核心组件有哪些？'
              : '例如：总结整个知识库的主要内容'"
            @keydown.enter.prevent="handleAsk"
          />
          <el-button type="primary" :loading="asking" @click="handleAsk">
            提问
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, shallowRef } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, TitleComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import MarkdownIt from 'markdown-it'
import { MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useKbStore } from '@/stores/kb'
import { graphragApi, type GraphData } from '@/api/graphrag'

use([CanvasRenderer, GraphChart, TooltipComponent, TitleComponent])

const md = new MarkdownIt({ html: false, linkify: true })
const renderMd = (t: string) => md.render(t || '')

const kbStore = useKbStore()
const selectedKb = ref<number | null>(null)
const building = ref(false)
const loadingGraph = ref(false)
const asking = ref(false)
const searchMode = ref<'local' | 'global'>('local')
const question = ref('')
const messages = ref<{ role: string; content: string }[]>([])
const graphData = shallowRef<GraphData | null>(null)
const status = ref<any>(null)

// 社区调色板（社区 id -> 颜色）
const PALETTE = [
  '#5b8ff9', '#61ddaa', '#f6bd16', '#7262fd', '#78d3f8',
  '#9661bc', '#f6903d', '#008685', '#f08bb4', '#ccc520',
]

const statusText = computed(() => {
  if (!status.value) return ''
  const s = status.value
  return `状态：${s.status}｜实体 ${s.entities}｜关系 ${s.relations}｜社区 ${s.communities}`
})
const statusTagType = computed(() => {
  const s = status.value?.status
  if (s === 'done') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'building') return 'warning'
  return 'info'
})

const chartOption = computed(() => {
  if (!graphData.value) return {}
  const g = graphData.value
  const communityColor = (cid: number | null) => {
    if (cid == null) return '#bbb'
    return PALETTE[cid % PALETTE.length]
  }
  const nodes = g.nodes.map((n) => ({
    id: String(n.id),
    name: n.name,
    symbolSize: Math.min(50, 14 + (n.degree || 0) * 3),
    category: n.community_id ?? 0,
    itemStyle: { color: communityColor(n.community_id) },
    label: { show: true, fontSize: 11 },
    tooltip: { formatter: `${n.name}（${n.entity_type}）\n${n.summary}` },
  }))
  const links = g.edges.map((e) => ({
    source: String(e.source_id),
    target: String(e.target_id),
    label: { show: false, formatter: e.relation_type },
  }))
  return {
    tooltip: {},
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        force: { repulsion: 220, edgeLength: 90, gravity: 0.08 },
        data: nodes,
        links,
        edgeSymbol: ['none', 'arrow'],
        lineStyle: { color: '#ccc', curveness: 0.1 },
        emphasis: { focus: 'adjacency' },
      },
    ],
  }
})

onMounted(async () => {
  await kbStore.fetchList()
  if (kbStore.kbList.length) {
    selectedKb.value = kbStore.kbList[0].id
    await loadGraph()
  }
})

async function onKbChange() {
  messages.value = []
  await loadGraph()
}

async function loadGraph() {
  if (!selectedKb.value) return
  loadingGraph.value = true
  try {
    graphData.value = await graphragApi.graph(selectedKb.value)
    status.value = await graphragApi.status(selectedKb.value)
  } finally {
    loadingGraph.value = false
  }
}

async function handleBuild() {
  if (!selectedKb.value) return
  building.value = true
  try {
    await graphragApi.build(selectedKb.value)
    ElMessage.success('图谱构建已开始，请稍候')
    pollStatus()
  } finally {
    building.value = false
  }
}

function pollStatus() {
  const timer = setInterval(async () => {
    if (!selectedKb.value) return clearInterval(timer)
    const s = await graphragApi.status(selectedKb.value)
    status.value = s
    if (s.status === 'done') {
      clearInterval(timer)
      await loadGraph()
    } else if (s.status === 'failed') {
      clearInterval(timer)
    }
  }, 2000)
}

async function handleAsk() {
  if (!selectedKb.value || !question.value.trim()) return
  const q = question.value.trim()
  messages.value.push({ role: 'user', content: q })
  question.value = ''
  asking.value = true
  try {
    const res: any =
      searchMode.value === 'local'
        ? await graphragApi.local(selectedKb.value, q)
        : await graphragApi.global(selectedKb.value, q)
    messages.value.push({ role: 'assistant', content: res.answer })
    // 局部检索后刷新子图高亮（可选）
  } finally {
    asking.value = false
  }
}
</script>

<style scoped>
.graphrag-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 12px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.graphrag-body {
  display: flex;
  gap: 12px;
  flex: 1;
  min-height: 0;
}
.graph-panel {
  flex: 1.3;
  background: #fff;
  border-radius: 10px;
  border: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  padding: 12px;
  min-width: 0;
}
.qa-panel {
  flex: 1;
  background: #fff;
  border-radius: 10px;
  border: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  padding: 12px;
  min-width: 320px;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 10px;
}
.graph-chart {
  flex: 1;
  min-height: 400px;
}
.qa-messages {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}
.qa-msg {
  margin-bottom: 12px;
  display: flex;
}
.qa-msg.user {
  justify-content: flex-end;
}
.msg-content {
  max-width: 90%;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.6;
}
.qa-msg.user .msg-content {
  background: #ecf5ff;
  color: #1d6fd6;
}
.qa-msg.assistant .msg-content {
  background: #f5f7fa;
  color: #303133;
}
.qa-input {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  margin-top: 10px;
}
</style>
