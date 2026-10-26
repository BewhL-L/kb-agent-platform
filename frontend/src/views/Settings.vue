<template>
  <div class="settings">
    <h2 class="page-title">个人设置</h2>

    <el-row :gutter="20">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>账号信息</template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="用户名">
              {{ userStore.userInfo?.username }}
            </el-descriptions-item>
            <el-descriptions-item label="邮箱">
              {{ userStore.userInfo?.email || '未设置' }}
            </el-descriptions-item>
            <el-descriptions-item label="当前模型">
              {{ userStore.userInfo?.current_model || '系统默认模型' }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never">
          <template #header>修改密码</template>
          <el-form :model="pwdForm" label-position="top">
            <el-form-item label="原密码">
              <el-input v-model="pwdForm.old_password" type="password" show-password />
            </el-form-item>
            <el-form-item label="新密码">
              <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位" />
            </el-form-item>
            <el-button type="primary" :loading="saving" @click="handleUpdatePwd">保存修改</el-button>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" style="margin-top: 20px">
      <template #header>模型切换</template>
      <div class="model-switch">
        <el-select
          v-model="selectedModel"
          placeholder="使用系统默认模型"
          clearable
          style="width: 320px"
        >
          <el-option label="系统默认模型" value="" />
          <el-option
            v-for="m in modelOptions"
            :key="m.value"
            :label="m.label"
            :value="m.value"
          />
        </el-select>
        <el-button type="primary" :loading="savingModel" @click="saveModel">保存</el-button>
      </div>
      <el-alert
        type="info"
        :closable="false"
        title="切换后，知识库问答与 Agent 将使用所选模型；选择“系统默认模型”则由平台统一指定。"
        style="margin-top: 12px"
      />
    </el-card>

    <el-card shadow="never" style="margin-top: 20px">
      <template #header>关于项目</template>
      <el-alert
        type="success"
        :closable="false"
        title="企业智能知识库助手 · AI Agent + RAG 全栈应用"
        description="技术栈：FastAPI + Vue3 + TypeScript + Chroma + LLM + Docker。核心能力：文档解析、向量检索、RAG 问答、Agentic RAG（Agent 自主检索）、SSE 流式输出、网站嵌入。"
        show-icon
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { authApi } from '@/api/auth'

const userStore = useUserStore()
const saving = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '' })

// 模型切换
const selectedModel = ref(userStore.userInfo?.current_model || '')
const savingModel = ref(false)
const modelOptions = [
  { label: '豆包 Pro 32K', value: 'doubao-pro-32k' },
  { label: '豆包 Lite 32K', value: 'doubao-lite-32k' },
  { label: 'DeepSeek V3', value: 'deepseek-v3' },
  { label: '通义千问 Plus', value: 'qwen-plus' },
  { label: 'GPT-4o Mini', value: 'gpt-4o-mini' },
]

async function saveModel() {
  savingModel.value = true
  try {
    await authApi.updateModel(selectedModel.value || '')
    if (userStore.userInfo) {
      userStore.userInfo.current_model = selectedModel.value || ''
    }
    ElMessage.success('模型已切换')
  } finally {
    savingModel.value = false
  }
}

async function handleUpdatePwd() {
  if (!pwdForm.old_password || pwdForm.new_password.length < 6) {
    ElMessage.warning('请正确填写，新密码至少 6 位')
    return
  }
  saving.value = true
  try {
    await authApi.updatePassword(pwdForm)
    ElMessage.success('密码修改成功')
    pwdForm.old_password = ''
    pwdForm.new_password = ''
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.page-title {
  font-size: 20px;
  margin-bottom: 20px;
}
.model-switch {
  display: flex;
  gap: 12px;
  align-items: center;
}
</style>
