<template>
  <div class="kb-detail">
    <div class="page-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" link @click="$router.push('/knowledge')">返回</el-button>
        <h2 class="page-title">{{ kb?.name || '知识库详情' }}</h2>
        <el-tag type="success" v-if="kb">{{ kb.document_count }} 个文档</el-tag>
      </div>
      <el-button type="primary" :icon="ChatDotRound" @click="goChat">开始问答</el-button>
    </div>

    <el-card shadow="never" class="upload-card">
      <el-upload
        drag
        multiple
        :auto-upload="false"
        :show-file-list="false"
        accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png"
        :on-change="handleFileChange"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          拖拽文件到此处，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">支持 PDF、Word、TXT、Markdown、图片(JPG/PNG)，单个文件不超过 10MB</div>
        </template>
      </el-upload>
    </el-card>

    <el-card shadow="never" style="margin-top: 20px">
      <template #header>
        <span>文档列表</span>
      </template>
      <el-table :data="documents" v-loading="loading" stripe>
        <el-table-column label="文件名" prop="filename" min-width="250">
          <template #default="{ row }">
            <el-icon style="vertical-align: middle"><Document /></el-icon>
            <span style="margin-left: 6px">{{ row.filename }}</span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="120">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="切片数" prop="chunk_count" width="90" />
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'completed'" type="success">已完成</el-tag>
            <el-tag v-else-if="row.status === 'processing'" type="warning">处理中</el-tag>
            <el-tooltip v-else :content="row.error_msg" placement="top">
              <el-tag type="danger">失败</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button
              type="success"
              link
              :icon="View"
              title="预览"
              @click="handlePreview(row)"
            >预览</el-button>
            <el-button
              type="primary"
              link
              :icon="RefreshRight"
              title="更新文档"
              @click="clickUpdate(row)"
            >更新</el-button>
            <el-button type="danger" link :icon="Delete" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 隐藏的更新文件选择框 -->
      <input
        ref="updateInputRef"
        type="file"
        accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png"
        style="display: none"
        @change="onUpdateFileChosen"
      >
    </el-card>

    <!-- 网站嵌入 -->
    <el-card shadow="never" style="margin-top: 20px">
      <template #header>
        <div class="embed-header">
          <el-icon><Link /></el-icon>
          <span>网站嵌入</span>
        </div>
      </template>
      <el-alert
        type="info"
        :closable="false"
        title="把下面的 iframe 代码嵌入你的网站，访客即可免登录向该知识库提问。"
        style="margin-bottom: 12px"
      />
      <el-input
        v-if="embedData"
        type="textarea"
        :model-value="embedData.iframe_code"
        :rows="2"
        readonly
      />
      <div v-if="embedData" class="embed-actions">
        <el-button type="primary" :icon="CopyDocument" @click="copyEmbed">复制嵌入代码</el-button>
        <el-button :icon="View" @click="previewEmbed">新窗口预览</el-button>
      </div>
    </el-card>

    <!-- 文档预览对话框 -->
    <el-dialog
      v-model="previewVisible"
      :title="previewDoc?.filename"
      width="800px"
      top="5vh"
    >
      <div v-loading="previewLoading" class="preview-body">
        <!-- PDF / 图片：直接用 iframe / img 展示 -->
        <iframe
          v-if="previewType === 'pdf'"
          :src="previewFileUrl"
          class="preview-iframe"
        ></iframe>
        <img
          v-else-if="previewType === 'image'"
          :src="previewFileUrl"
          class="preview-image"
        >
        <!-- 文本类：渲染解析后的 Markdown -->
        <div
          v-else
          class="markdown-body preview-text"
          v-html="previewRendered"
        ></div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, UploadFilled, Document, Delete, ChatDotRound,
  RefreshRight, Link, CopyDocument, View,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { kbApi, docApi } from '@/api/knowledge'
import type { UploadFile } from 'element-plus'

const route = useRoute()
const router = useRouter()
const kbId = Number(route.params.id)

const kb = ref<any>(null)
const documents = ref<any[]>([])
const loading = ref(false)
const embedData = ref<any>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

// 文档更新
const updateInputRef = ref<HTMLInputElement>()
let updatingDocId: number | null = null

// 文档预览
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewDoc = ref<any>(null)
const previewType = ref<'pdf' | 'image' | 'text'>('text')
const previewFileUrl = ref('')
const previewContent = ref('')
const previewMd = new MarkdownIt({ html: false, linkify: true, breaks: true })
const previewRendered = computed(() => previewMd.render(previewContent.value))

async function loadKb() {
  kb.value = await kbApi.detail(kbId)
}

async function loadDocs() {
  loading.value = true
  try {
    const res: any = await docApi.list(kbId, { page: 1, page_size: 100 })
    documents.value = res.items
    const hasProcessing = documents.value.some((d) => d.status === 'processing')
    if (hasProcessing && !pollTimer) {
      pollTimer = setInterval(loadDocs, 3000)
    } else if (!hasProcessing && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  } finally {
    loading.value = false
  }
}

async function loadEmbed() {
  embedData.value = await kbApi.getEmbedCode(kbId)
}

async function handleFileChange(file: UploadFile) {
  if (!file.raw) return
  try {
    ElMessage.info(`正在上传 ${file.name} ...`)
    await docApi.upload(kbId, file.raw)
    ElMessage.success(`${file.name} 上传成功，正在处理`)
    loadDocs()
    loadKb()
  } catch {
    // 错误已由拦截器提示
  }
}

async function handlePreview(row: any) {
  previewDoc.value = row
  previewVisible.value = true
  previewLoading.value = true
  const ext = (row.filename || '').split('.').pop()?.toLowerCase()
  try {
    if (ext === 'pdf') {
      previewType.value = 'pdf'
      const res: any = await docApi.preview(row.id)
      previewFileUrl.value = res.file_url
    } else if (['jpg', 'jpeg', 'png', 'webp'].includes(ext || '')) {
      previewType.value = 'image'
      const res: any = await docApi.preview(row.id)
      previewFileUrl.value = res.file_url
    } else {
      previewType.value = 'text'
      const res: any = await docApi.preview(row.id)
      previewContent.value = res.content
    }
  } finally {
    previewLoading.value = false
  }
}

function clickUpdate(row: any) {
  updatingDocId = row.id
  updateInputRef.value?.click()
}

async function onUpdateFileChosen(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file || updatingDocId == null) return
  try {
    ElMessage.info('正在更新文档...')
    await docApi.update(updatingDocId, file)
    ElMessage.success('更新成功，正在重新处理')
    loadDocs()
    loadKb()
  } finally {
    target.value = ''
    updatingDocId = null
  }
}

function copyEmbed() {
  if (!embedData.value) return
  navigator.clipboard.writeText(embedData.value.iframe_code)
  ElMessage.success('嵌入代码已复制')
}

function previewEmbed() {
  if (!embedData.value) return
  window.open(`/embed/${embedData.value.embed_code}`, '_blank')
}

async function handleDelete(row: any) {
  await ElMessageBox.confirm(`确定删除文档「${row.filename}」吗？`, '警告', { type: 'warning' })
  await docApi.delete(row.id)
  ElMessage.success('删除成功')
  loadDocs()
  loadKb()
}

function goChat() {
  router.push({ path: '/chat', query: { kb: kbId } })
}

function formatSize(bytes: number) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

function formatTime(t: string) {
  return new Date(t).toLocaleString('zh-CN')
}

onMounted(() => {
  loadKb()
  loadDocs()
  loadEmbed()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.page-title {
  font-size: 20px;
  margin: 0;
}
.upload-card :deep(.el-upload-dragger) {
  width: 100%;
}
.embed-header {
  display: flex;
  align-items: center;
  gap: 6px;
}
.embed-actions {
  margin-top: 12px;
  display: flex;
  gap: 12px;
}
.preview-body {
  min-height: 400px;
}
.preview-iframe {
  width: 100%;
  height: 70vh;
  border: none;
}
.preview-image {
  max-width: 100%;
  display: block;
  margin: 0 auto;
}
.preview-text {
  max-height: 70vh;
  overflow-y: auto;
}
</style>
