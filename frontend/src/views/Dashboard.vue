<template>
  <div class="dashboard">
    <h2 class="page-title">数据看板</h2>

    <!-- 统计卡片 -->
    <el-row :gutter="20" class="stat-row">
      <el-col :span="6" v-for="card in statCards" :key="card.label">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-icon" :style="{ background: card.color }">
              <el-icon :size="24"><component :is="card.icon" /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ card.value }}</div>
              <div class="stat-label">{{ card.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 图表区 -->
    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="14">
        <el-card shadow="hover">
          <template #header>
            <span>近 7 天问答趋势</span>
          </template>
          <v-chart class="chart" :option="lineOption" autoresize />
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="hover">
          <template #header>
            <span>各知识库文档分布</span>
          </template>
          <v-chart class="chart" :option="pieOption" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <!-- 成本与主动学习 -->
    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header-row">
              <span>LLM 成本与用量（近 30 天）</span>
              <el-tag type="danger">¥{{ costData.total_cost }}</el-tag>
            </div>
          </template>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="总调用次数">{{ costData.total_calls }}</el-descriptions-item>
            <el-descriptions-item label="总费用">¥{{ costData.total_cost }}</el-descriptions-item>
            <el-descriptions-item label="Prompt Tokens">{{ costData.prompt_tokens }}</el-descriptions-item>
            <el-descriptions-item label="Completion Tokens">{{ costData.completion_tokens }}</el-descriptions-item>
          </el-descriptions>
          <v-chart v-if="costByPurpose.length" class="chart" :option="costBarOption" autoresize />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header-row">
              <span>主动学习：负反馈归因</span>
              <el-tag :type="activeData.satisfaction_rate >= 0.7 ? 'success' : 'warning'">
                满意度 {{ (activeData.satisfaction_rate * 100).toFixed(0) }}%
              </el-tag>
            </div>
          </template>
          <el-alert
            v-for="(r, i) in activeData.recommendations"
            :key="i"
            :title="r"
            type="info"
            :closable="false"
            style="margin-bottom: 8px"
          />
          <el-descriptions :column="2" border size="small" style="margin-top: 8px">
            <el-descriptions-item label="总回答数">{{ activeData.total_answers }}</el-descriptions-item>
            <el-descriptions-item label="点踩数">{{ activeData.negative_feedback }}</el-descriptions-item>
          </el-descriptions>
          <div v-if="Object.keys(activeData.root_cause_distribution).length">
            <v-chart class="chart" :option="causePieOption" autoresize />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快速开始 -->
    <el-card shadow="hover" style="margin-top: 20px">
      <template #header>快速开始</template>
      <el-steps :active="1" align-center>
        <el-step title="创建知识库" description="在知识库管理中创建" />
        <el-step title="上传文档" description="支持 PDF/Word/TXT" />
        <el-step title="开始问答" description="基于文档智能问答" />
        <el-step title="体验 Agent" description="自动工具调用" />
      </el-steps>
      <div style="text-align: center; margin-top: 24px">
        <el-button type="primary" @click="$router.push('/knowledge')">开始创建知识库</el-button>
        <el-button @click="$router.push('/chat')">前往智能问答</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, PieChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import { statsApi } from '@/api/stats'

use([CanvasRenderer, LineChart, PieChart, BarChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent])

const overview = ref({ kb_count: 0, doc_count: 0, conversation_count: 0, qa_count: 0 })
const weeklyTrend = ref<{ date: string; count: number }[]>([])
const kbDistribution = ref<{ name: string; doc_count: number }[]>([])

// 成本与主动学习
const costData = ref<any>({
  total_calls: 0, total_cost: '0.00',
  prompt_tokens: 0, completion_tokens: 0, by_purpose: [],
})
const costByPurpose = computed(() => costData.value.by_purpose || [])
const activeData = ref<any>({
  total_answers: 0, negative_feedback: 0,
  satisfaction_rate: 0, root_cause_distribution: {}, recommendations: [],
})

const statCards = computed(() => [
  { label: '知识库数量', value: overview.value.kb_count, icon: 'FolderOpened', color: '#409eff' },
  { label: '文档数量', value: overview.value.doc_count, icon: 'Document', color: '#67c23a' },
  { label: '对话数量', value: overview.value.conversation_count, icon: 'ChatDotRound', color: '#e6a23c' },
  { label: '问答次数', value: overview.value.qa_count, icon: 'Promotion', color: '#f56c6c' },
])

const lineOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  xAxis: {
    type: 'category',
    data: weeklyTrend.value.map((d) => d.date.slice(5)),
    boundaryGap: false,
  },
  yAxis: { type: 'value', minInterval: 1 },
  grid: { left: 40, right: 20, top: 20, bottom: 30 },
  series: [
    {
      data: weeklyTrend.value.map((d) => d.count),
      type: 'line',
      smooth: true,
      areaStyle: { color: 'rgba(64,158,255,0.15)' },
      lineStyle: { color: '#409eff', width: 2 },
      itemStyle: { color: '#409eff' },
    },
  ],
}))

const pieOption = computed(() => ({
  tooltip: { trigger: 'item' },
  legend: { bottom: 0 },
  series: [
    {
      type: 'pie',
      radius: ['40%', '65%'],
      data: kbDistribution.value.map((k) => ({ name: k.name, value: k.doc_count })),
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
    },
  ],
}))

// 成本按用途柱状图
const costBarOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  xAxis: {
    type: 'category',
    data: costByPurpose.value.map((p: any) => p.purpose),
  },
  yAxis: { type: 'value', name: '费用(元)' },
  grid: { left: 50, right: 20, top: 20, bottom: 30 },
  series: [
    {
      data: costByPurpose.value.map((p: any) => Number(p.cost)),
      type: 'bar',
      itemStyle: { color: '#f56c6c', borderRadius: [4, 4, 0, 0] },
    },
  ],
}))

// 负反馈归因饼图
const causePieOption = computed(() => ({
  tooltip: { trigger: 'item' },
  legend: { bottom: 0 },
  series: [
    {
      type: 'pie',
      radius: ['40%', '65%'],
      data: Object.entries(activeData.value.root_cause_distribution).map(
        ([name, value]) => ({ name, value })
      ),
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
    },
  ],
}))

onMounted(async () => {
  try {
    const res: any = await statsApi.getStats()
    overview.value = res.overview
    weeklyTrend.value = res.weekly_trend
    kbDistribution.value = res.kb_distribution
  } catch (e) {
    // 接口失败时使用空数据
  }
  try {
    costData.value = await statsApi.getCostStats(30) as any
  } catch (e) {
    // 成本接口可能因无数据失败
  }
  try {
    activeData.value = await statsApi.getActiveLearning(30) as any
  } catch (e) {
    // 主动学习接口可能失败
  }
})
</script>

<style scoped>
.page-title {
  margin-bottom: 20px;
  font-size: 20px;
}
.stat-card {
  border-radius: 8px;
}
.stat-inner {
  display: flex;
  align-items: center;
  gap: 16px;
}
.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #1f2937;
}
.stat-label {
  color: #909399;
  font-size: 14px;
  margin-top: 4px;
}
.chart {
  height: 300px;
}
.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
