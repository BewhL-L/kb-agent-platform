<template>
  <div class="wiki-page">
    <!-- 顶部工具栏 -->
    <div class="wiki-toolbar">
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

      <el-radio-group v-model="viewMode" style="margin-left: auto">
        <el-radio-button value="list">页面列表</el-radio-button>
        <el-radio-button value="graph">关系图谱</el-radio-button>
      </el-radio-group>

      <el-button
        type="primary"
        :icon="Refresh"
        :loading="compiling"
        @click="handleRecompile"
      >重新编译</el-button>
    </div>

    <!-- 无知识库提示 -->
    <el-empty
      v-if="!selectedKb"
      description="请先选择一个知识库"
      style="margin-top: 80px"
    />

    <!-- 列表视图 -->
    <div v-else-if="viewMode === 'list'" class="wiki-body">
      <!-- 左侧：页面列表 -->
      <div class="page-sidebar">
        <el-input
          v-model="keyword"
          placeholder="搜索页面"
          :prefix-icon="Search"
          clearable
          style="margin-bottom: 12px"
        />
        <el-radio-group v-model="typeFilter" size="small" style="margin-bottom: 12px; flex-wrap: wrap; display: flex; gap: 4px">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button
            v-for="t in entityTypes"
            :key="t.value"
            :value="t.value"
          >{{ t.label }}</el-radio-button>
        </el-radio-group>

        <div class="page-list" v-loading="loading">
          <el-empty v-if="filteredPages.length === 0" description="暂无页面" :image-size="60" />
          <div
            v-for="p in filteredPages"
            :key="p.id"
            class="page-list-item"
            :class="{ active: currentPage?.id === p.id }"
            @click="openPage(p.id)"
          >
            <div class="item-title">
              <el-tag size="small" :type="typeTagMap[p.entity_type] || 'info'" effect="plain">
                {{ typeLabelMap[p.entity_type] || p.entity_type }}
              </el-tag>
              <span class="item-name">{{ p.title }}</span>
              <el-icon v-if="p.conflict_count > 0" color="#f56c6c" title="存在冲突">
                <WarningFilled />
              </el-icon>
            </div>
            <div class="item-summary">{{ p.summary }}</div>
          </div>
        </div>
      </div>

      <!-- 右侧：页面详情 -->
      <div class="page-content">
        <el-empty v-if="!currentPage" description="选择左侧页面查看详情" />
        <div v-else class="page-detail">
          <div class="detail-header">
            <h2 class="detail-title">{{ currentPage.title }}</h2>
            <div class="detail-meta">
              <el-tag size="small" :type="typeTagMap[currentPage.entity_type] || 'info'">
                {{ typeLabelMap[currentPage.entity_type] || currentPage.entity_type }}
              </el-tag>
              <span class="meta-text">v{{ currentPage.version }}</span>
              <span class="meta-text">编译于 {{ formatTime(currentPage.compiled_at) }}</span>
              <el-button
                type="primary"
                size="small"
                :icon="EditPen"
                link
                @click="startEdit"
              >编辑</el-button>
              <el-button
                type="info"
                size="small"
                :icon="Clock"
                link
                @click="openHistory"
              >历史版本</el-button>
              <el-button
                type="danger"
                size="small"
                :icon="Delete"
                link
                @click="handleDelete(currentPage)"
              >删除</el-button>
            </div>
          </div>

          <!-- 编辑模式 -->
          <div v-if="editing" class="edit-area">
            <el-input
              v-model="editContent"
              type="textarea"
              :rows="20"
              placeholder="使用 Markdown 编辑页面内容"
            />
            <div class="edit-actions">
              <el-button type="primary" :icon="Check" @click="saveEdit">保存</el-button>
              <el-button :icon="Close" @click="cancelEdit">取消</el-button>
            </div>
          </div>

          <!-- 冲突警告（编辑模式下隐藏） -->
          <template v-else>
          <el-alert
            v-for="(c, i) in currentPage.conflict_flags"
            :key="i"
            type="error"
            :closable="false"
            style="margin-bottom: 10px"
          >
            <template #title>
              <strong>知识冲突（{{ c.field }}）</strong>：{{ c.detail }}
            </template>
            <div class="conflict-detail">
              <div>已有：{{ c.existing_claim }}</div>
              <div>新文档：{{ c.new_claim }}</div>
            </div>
          </el-alert>

          <!-- Markdown 正文 -->
          <div class="markdown-body" v-html="renderedContent" @click="onContentClick"></div>

          <!-- 来源与关联 -->
          <el-divider />
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="来源文档">
              <span v-for="(id, i) in currentPage.source_doc_ids" :key="id">
                文档#{{ id }}<span v-if="i < currentPage.source_doc_ids.length - 1">、</span>
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="关联页面">
              <el-button
                v-for="id in currentPage.related_page_ids"
                :key="id"
                size="small"
                link
                @click="openPage(id)"
              >{{ pageTitle(id) }}</el-button>
              <span v-if="!currentPage.related_page_ids?.length">无</span>
            </el-descriptions-item>
          </el-descriptions>
          </template>
        </div>
      </div>
    </div>

    <!-- 图谱视图 -->
    <div v-else class="graph-view" v-loading="graphLoading">
      <el-empty v-if="graphData.nodes.length === 0" description="暂无可展示的关联" />
      <v-chart
        v-else
        class="graph-chart"
        :option="graphOption"
        autoresize
        @click="onGraphClick"
      />
    </div>

    <!-- 历史版本对话框 -->
    <el-dialog v-model="historyVisible" title="历史版本" width="700px">
      <el-timeline>
        <el-timeline-item
          v-for="v in versionList"
          :key="v.id"
          :timestamp="formatTime(v.created_at)"
          placement="top"
        >
          <div class="version-item">
            <span class="version-label">
              v{{ v.version }}
              <el-tag size="small" :type="changeSourceTag(v.change_source)">
                {{ changeSourceLabel(v.change_source) }}
              </el-tag>
            </span>
            <el-button
              type="primary"
              size="small"
              link
              @click="handleRollback(v.id)"
            >回滚到此版本</el-button>
          </div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="versionList.length === 0" description="暂无历史版本" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import {
  Refresh, Search, Delete, WarningFilled,
  EditPen, Clock, Check, Close,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useKbStore } from '@/stores/kb'
import { wikiApi } from '@/api/wiki'

// 按需注册 ECharts 力导向图
use([CanvasRenderer, GraphChart, TooltipComponent])

const kbStore = useKbStore()

// ===== 状态 =====
const selectedKb = ref<number | null>(null)
const viewMode = ref<'list' | 'graph'>('list')
const keyword = ref('')
const typeFilter = ref('')
const loading = ref(false)
const compiling = ref(false)
const pages = ref<any[]>([])
const currentPage = ref<any>(null)
const graphLoading = ref(false)
const graphData = ref<{ nodes: any[]; edges: any[] }>({ nodes: [], edges: [] })

// 编辑与版本
const editing = ref(false)
const editContent = ref('')
const historyVisible = ref(false)
const versionList = ref<any[]>([])

// ===== 实体类型映射 =====
const entityTypes = [
  { value: 'person', label: '人物' },
  { value: 'concept', label: '概念' },
  { value: 'tool', label: '工具' },
  { value: 'api', label: '接口' },
  { value: 'process', label: '流程' },
  { value: 'term', label: '术语' },
  { value: 'other', label: '其他' },
]
const typeLabelMap: Record<string, string> = Object.fromEntries(
  entityTypes.map((t) => [t.value, t.label])
)
const typeTagMap: Record<string, string> = {
  person: 'success',
  concept: 'primary',
  tool: 'warning',
  api: 'danger',
  process: 'info',
  term: '',
  other: 'info',
}

// ===== Markdown 渲染（含 [[]] 双向链接支持）=====
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

// 注册 [[]] 内联规则
md.inline.ruler.before('link', 'wikilink', (state, silent) => {
  if (state.src.charCodeAt(state.pos) !== 0x5b /* [ */) return false
  if (state.src.charCodeAt(state.pos + 1) !== 0x5b) return false
  const close = state.src.indexOf(']]', state.pos + 2)
  if (close === -1) return false
  const inner = state.src.slice(state.pos + 2, close)
  const title = inner.split('|')[0].trim()
  if (!silent) {
    const token = state.push('wikilink', '', 0)
    token.content = title
  }
  state.pos = close + 2
  return true
})
md.renderer.rules.wikilink = (tokens, idx) => {
  const title = tokens[idx].content
  return `<a class="wiki-link" data-title="${md.utils.escapeHtml(title)}">${md.utils.escapeHtml(title)}</a>`
}

const renderedContent = computed(() => {
  if (!currentPage.value) return ''
  const html = md.render(currentPage.value.content || '')
  return html
})

// 点击正文中的 [[]] 链接（事件委托）
function onContentClick(e: MouseEvent) {
  const target = (e.target as HTMLElement).closest('.wiki-link')
  if (target) {
    const title = (target as HTMLElement).dataset.title
    const page = pages.value.find((p) => p.title === title)
    if (page) openPage(page.id)
  }
}

// ===== 数据加载 =====
async function loadPages() {
  if (!selectedKb.value) return
  loading.value = true
  try {
    const res: any = await wikiApi.listPages(selectedKb.value)
    pages.value = res.items
  } finally {
    loading.value = false
  }
}

async function loadGraph() {
  if (!selectedKb.value) return
  graphLoading.value = true
  try {
    graphData.value = await wikiApi.getGraph(selectedKb.value) as any
  } finally {
    graphLoading.value = false
  }
}

async function openPage(id: number) {
  currentPage.value = await wikiApi.getPage(id)
}

function pageTitle(id: number) {
  return pages.value.find((p) => p.id === id)?.title || `页面#${id}`
}

const filteredPages = computed(() => {
  return pages.value.filter((p) => {
    if (typeFilter.value && p.entity_type !== typeFilter.value) return false
    if (keyword.value) {
      const k = keyword.value.toLowerCase()
      return (
        p.title.toLowerCase().includes(k) ||
        p.summary.toLowerCase().includes(k)
      )
    }
    return true
  })
})

// ===== 图谱配置 =====
const graphColors: Record<string, string> = {
  person: '#67c23a',
  concept: '#409eff',
  tool: '#e6a23c',
  api: '#f56c6c',
  process: '#909399',
  term: '#9b59b6',
  other: '#909399',
}

const graphOption = computed(() => ({
  tooltip: { formatter: (p: any) => p.data.name },
  series: [
    {
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      label: { show: true, position: 'right', fontSize: 12 },
      force: { repulsion: 200, edgeLength: 100 },
      data: graphData.value.nodes.map((n) => ({
        id: String(n.id),
        name: n.title,
        symbolSize: 22,
        itemStyle: { color: graphColors[n.entity_type] || '#909399' },
      })),
      links: graphData.value.edges.map((e) => ({
        source: String(e.source),
        target: String(e.target),
      })),
      lineStyle: { color: '#c0c4cc', width: 1.5, curveness: 0.1 },
    },
  ],
}))

function onGraphClick(params: any) {
  if (params.dataType === 'node') {
    const id = Number(params.data.id)
    viewMode.value = 'list'
    openPage(id)
  }
}

// ===== 操作 =====
async function onKbChange() {
  currentPage.value = null
  pages.value = []
  graphData.value = { nodes: [], edges: [] }
  await loadPages()
  if (viewMode.value === 'graph') await loadGraph()
}

async function handleRecompile() {
  if (!selectedKb.value) return
  compiling.value = true
  try {
    ElMessage.info('正在编译，请稍候…')
    const res: any = await wikiApi.recompile(selectedKb.value, true)
    ElMessage.success(
      `编译完成：新建 ${res.created}，更新 ${res.updated}，失败 ${res.failed}`
    )
    await loadPages()
    await loadGraph()
  } finally {
    compiling.value = false
  }
}

// ===== 编辑 =====
function startEdit() {
  editContent.value = currentPage.value?.content || ''
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  editContent.value = ''
}

async function saveEdit() {
  if (!currentPage.value) return
  await wikiApi.editPage(currentPage.value.id, { content: editContent.value })
  ElMessage.success('保存成功')
  editing.value = false
  await openPage(currentPage.value.id)
  await loadPages()
}

// ===== 历史版本 =====
async function openHistory() {
  if (!currentPage.value) return
  historyVisible.value = true
  const res: any = await wikiApi.listVersions(currentPage.value.id)
  versionList.value = res.items
}

async function handleRollback(versionId: number) {
  if (!currentPage.value) return
  await ElMessageBox.confirm('确定回滚到该版本吗？（会产生一个新版本）', '提示', {
    type: 'warning',
  })
  await wikiApi.rollback(currentPage.value.id, versionId)
  ElMessage.success('回滚成功')
  historyVisible.value = false
  await openPage(currentPage.value.id)
  await loadPages()
}

function changeSourceLabel(source: string) {
  return { compile: 'AI编译', manual: '人工编辑', rollback: '回滚' }[source] || source
}

function changeSourceTag(source: string) {
  return { compile: 'info', manual: 'warning', rollback: 'success' }[source] || 'info'
}

async function handleDelete(page: any) {
  await ElMessageBox.confirm(`确定删除页面「${page.title}」吗？`, '警告', {
    type: 'warning',
  })
  await wikiApi.deletePage(page.id)
  ElMessage.success('删除成功')
  currentPage.value = null
  await loadPages()
}

function formatTime(t: string) {
  return t ? new Date(t).toLocaleString('zh-CN') : '-'
}

// 切换到图谱时加载
watch(viewMode, async (mode) => {
  if (mode === 'graph' && graphData.value.nodes.length === 0) {
    await loadGraph()
  }
})

onMounted(async () => {
  if (kbStore.kbList.length === 0) {
    await kbStore.fetchList()
  }
})
</script>

<style scoped>
.wiki-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.wiki-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.wiki-body {
  flex: 1;
  display: flex;
  gap: 16px;
  min-height: 0;
}
.page-sidebar {
  width: 320px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 6px;
  padding: 14px;
  display: flex;
  flex-direction: column;
}
.page-list {
  flex: 1;
  overflow-y: auto;
}
.page-list-item {
  padding: 10px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 6px;
  border: 1px solid transparent;
}
.page-list-item:hover {
  background: #f5f7fa;
}
.page-list-item.active {
  background: #ecf5ff;
  border-color: #409eff;
}
.item-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.item-name {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.item-summary {
  font-size: 12px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.page-content {
  flex: 1;
  background: #fff;
  border-radius: 6px;
  padding: 24px;
  overflow-y: auto;
}
.detail-header {
  margin-bottom: 18px;
}
.detail-title {
  margin: 0 0 10px;
}
.detail-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}
.meta-text {
  font-size: 12px;
  color: #909399;
}
.conflict-detail {
  font-size: 12px;
  margin-top: 4px;
  line-height: 1.8;
}
.edit-area {
  margin-bottom: 16px;
}
.edit-actions {
  margin-top: 12px;
  display: flex;
  gap: 8px;
}
.version-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.version-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.graph-view {
  flex: 1;
  background: #fff;
  border-radius: 6px;
  position: relative;
}
.graph-chart {
  width: 100%;
  height: 100%;
  min-height: 500px;
}
:deep(.wiki-link) {
  color: #409eff;
  cursor: pointer;
  text-decoration: none;
}
:deep(.wiki-link:hover) {
  text-decoration: underline;
}
</style>
