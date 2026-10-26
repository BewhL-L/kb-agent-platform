<template>
  <div class="evaluation">
    <!-- 顶部：说明 + 操作 -->
    <el-card shadow="never" class="toolbar">
      <div class="toolbar-inner">
        <div class="desc">
          <h3>RAG 评测中心</h3>
          <p>
            基于 golden QA 标准问答集，对检索与生成全链路量化打分（Hit@K / MRR / 上下文精确召回 / 关键词覆盖 / LLM 裁判）。
            每次优化检索策略、Prompt 或模型后先跑评测，形成「发现问题 → 定位到层 → 优化 → 指标提升」闭环。
          </p>
        </div>
        <div class="actions">
          <el-input-number
            v-model="kbId"
            :min="1"
            :step="1"
            placeholder="全部知识库"
            controls-position="right"
            style="width: 170px"
          />
          <el-button type="primary" :loading="running" :disabled="running" @click="handleRun">
            {{ running ? '评测运行中…' : '运行评测' }}
          </el-button>
          <el-button :disabled="running" @click="loadLatest">刷新</el-button>
        </div>
      </div>
      <el-alert
        v-if="running"
        type="warning"
        :closable="false"
        show-icon
        title="评测会逐条调用 LLM（检索 + 生成 + 裁判），用例越多耗时越长，请耐心等待"
      />
    </el-card>

    <!-- 空状态 -->
    <el-card v-if="!report && !loading" shadow="never" class="empty-card">
      <el-empty description="暂无评测报告，点击右上角「运行评测」生成第一份报告" />
    </el-card>

    <template v-if="report && report.summary">
      <!-- 汇总指标卡片 -->
      <el-row :gutter="16" class="metric-row">
        <el-col v-for="m in metricCards" :key="m.label" :xs="12" :sm="8" :md="6" :lg="3">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-value" :class="scoreClass(m.value)">
              {{ m.value == null ? '—' : (m.value * 100).toFixed(1) + '%' }}
            </div>
            <div class="metric-label">{{ m.label }}</div>
            <el-tooltip :content="m.tip" placement="top">
              <div class="metric-help">?</div>
            </el-tooltip>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="8" :md="6" :lg="3">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-value neutral">{{ report.summary.case_count }}</div>
            <div class="metric-label">用例数</div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="8" :md="6" :lg="3">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-value neutral">
              {{ report.summary.avg_latency_s == null ? '—' : report.summary.avg_latency_s.toFixed(2) + 's' }}
            </div>
            <div class="metric-label">平均耗时</div>
          </el-card>
        </el-col>
      </el-row>

      <!-- RAGAS 指标（可选） -->
      <el-card v-if="report.ragas" shadow="never" class="section">
        <template #header>RAGAS 官方指标</template>
        <el-tag
          v-for="(v, k) in report.ragas"
          :key="k"
          size="large"
          class="ragas-tag"
          type="info"
          effect="plain"
        >
          {{ k }}: {{ typeof v === 'number' ? v.toFixed(4) : v }}
        </el-tag>
      </el-card>

      <!-- 逐用例明细 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="section-header">
            <span>逐用例明细</span>
            <span class="run-at">评测时间：{{ report.run_at }}</span>
          </div>
        </template>
        <el-table :data="report.cases" stripe size="default">
          <el-table-column type="index" width="50" />
          <el-table-column prop="category" label="分类" width="110" show-overflow-tooltip />
          <el-table-column prop="question" label="问题" min-width="220" show-overflow-tooltip />
          <el-table-column
            v-for="col in caseColumns"
            :key="col.prop"
            :label="col.label"
            :width="col.width"
            align="center"
          >
            <template #default="{ row }">
              <span :class="scoreClass(row[col.prop])">
                {{ row[col.prop] == null ? '—' : (row[col.prop] * 100).toFixed(0) + '%' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="90" align="center">
            <template #default="{ row }">{{ row.latency_s?.toFixed(2) }}s</template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { evaluationApi, type EvalReport } from '@/api/evaluation'

const report = ref<EvalReport | null>(null)
const loading = ref(false)
const running = ref(false)
// null 表示不限定知识库
const kbId = ref<number | undefined>(undefined)

const metricCards = computed(() => {
  const s = report.value?.summary
  return [
    { label: 'Hit@K', value: s?.['hit@k'], tip: '期望来源文档出现在 Top-K 检索结果中的比例，检索召回的基础指标' },
    { label: 'MRR', value: s?.mrr, tip: '平均倒数排名：期望来源排得越靠前分数越高' },
    { label: '上下文精确率', value: s?.context_precision, tip: '检索到的片段中相关片段占比（平均精确率）' },
    { label: '上下文召回率', value: s?.context_recall, tip: '标准答案所需信息被检索片段覆盖的比例' },
    { label: '关键词覆盖', value: s?.answer_keyword_coverage, tip: '答案覆盖标准答案必含关键词的比例' },
    { label: '忠实度', value: s?.faithfulness, tip: 'LLM 裁判：答案是否严格基于检索资料，防幻觉' },
    { label: '答案相关性', value: s?.answer_relevancy, tip: 'LLM 裁判：答案与问题的相关程度' },
  ]
})

const caseColumns: Array<{ prop: string; label: string; width?: number }> = [
  { prop: 'hit@k', label: 'Hit@K' },
  { prop: 'mrr', label: 'MRR' },
  { prop: 'context_precision', label: '精确率' },
  { prop: 'context_recall', label: '召回率' },
  { prop: 'answer_keyword_coverage', label: '关键词' },
  { prop: 'faithfulness', label: '忠实度' },
  { prop: 'answer_relevancy', label: '相关性' },
]

function scoreClass(v: number | null | undefined): string {
  if (v == null) return 'neutral'
  if (v >= 0.8) return 'good'
  if (v >= 0.5) return 'mid'
  return 'bad'
}

async function loadLatest() {
  loading.value = true
  try {
    const data = await evaluationApi.latest()
    report.value = data?.summary ? data : null
  } catch {
    // 拦截器已统一提示，这里保持空态
  } finally {
    loading.value = false
  }
}

async function handleRun() {
  running.value = true
  try {
    await evaluationApi.run(kbId.value)
    ElMessage.success('评测完成')
    await loadLatest()
  } catch {
    // 拦截器已统一提示
  } finally {
    running.value = false
  }
}

onMounted(loadLatest)
</script>

<style scoped>
.toolbar {
  margin-bottom: 16px;
}
.toolbar-inner {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}
.desc h3 {
  margin: 0 0 6px;
}
.desc p {
  margin: 0;
  color: #909399;
  font-size: 13px;
  max-width: 640px;
  line-height: 1.6;
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.toolbar :deep(.el-alert) {
  margin-top: 12px;
}
.empty-card {
  margin-bottom: 16px;
}
.metric-row {
  margin-bottom: 16px;
}
.metric-card {
  position: relative;
  text-align: center;
}
.metric-value {
  font-size: 22px;
  font-weight: 700;
}
.metric-value.good {
  color: #67c23a;
}
.metric-value.mid {
  color: #e6a23c;
}
.metric-value.bad {
  color: #f56c6c;
}
.metric-value.neutral {
  color: #409eff;
}
.metric-label {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.metric-help {
  position: absolute;
  top: 8px;
  right: 10px;
  width: 16px;
  height: 16px;
  line-height: 16px;
  border-radius: 50%;
  background: #f0f2f5;
  color: #909399;
  font-size: 12px;
  cursor: help;
}
.section {
  margin-bottom: 16px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.run-at {
  font-size: 12px;
  color: #909399;
  font-weight: normal;
}
.ragas-tag {
  margin: 0 10px 8px 0;
}
.good {
  color: #67c23a;
  font-weight: 600;
}
.mid {
  color: #e6a23c;
  font-weight: 600;
}
.bad {
  color: #f56c6c;
  font-weight: 600;
}
.neutral {
  color: #909399;
}
</style>
