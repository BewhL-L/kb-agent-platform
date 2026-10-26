<template>
  <div class="knowledge-list">
    <div class="page-header">
      <h2 class="page-title">知识库管理</h2>
      <el-button type="primary" :icon="Plus" @click="dialogVisible = true">新建知识库</el-button>
    </div>

    <el-input
      v-model="keyword"
      placeholder="搜索知识库名称"
      clearable
      :prefix-icon="Search"
      style="width: 300px; margin-bottom: 20px"
      @keyup.enter="loadList"
      @clear="loadList"
    />

    <div v-loading="kbStore.loading">
      <el-empty v-if="kbStore.kbList.length === 0" description="还没有知识库，点击右上角创建" />

      <el-row v-else :gutter="20">
        <el-col :span="6" v-for="kb in kbStore.kbList" :key="kb.id" style="margin-bottom: 20px">
          <el-card shadow="hover" class="kb-card" @click="goDetail(kb.id)">
            <div class="kb-card-header">
              <el-icon :size="28" color="#409eff"><Files /></el-icon>
              <el-dropdown @command="(c: string) => handleCommand(c, kb)" @click.stop>
                <el-icon class="more-icon" @click.stop><MoreFilled /></el-icon>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="edit">编辑</el-dropdown-item>
                    <el-dropdown-item command="embed">嵌入代码</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
            <h3 class="kb-name">{{ kb.name }}</h3>
            <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
            <div class="kb-footer">
              <span><el-icon><Document /></el-icon> {{ kb.document_count }} 个文档</span>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 新建/编辑弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑知识库' : '新建知识库'" width="500px">
      <el-form :model="form" label-position="top">
        <el-form-item label="知识库名称" required>
          <el-input v-model="form.name" placeholder="例如：电商客服知识库" maxlength="100" />
        </el-form-item>
        <el-form-item label="知识库描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="描述这个知识库的用途" maxlength="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Search, Files, Document, MoreFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useKbStore } from '@/stores/kb'
import { kbApi } from '@/api/knowledge'

const router = useRouter()
const kbStore = useKbStore()
const keyword = ref('')
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)

const form = reactive({ name: '', description: '' })

async function loadList() {
  await kbStore.fetchList(keyword.value ? { keyword: keyword.value } : undefined)
}

function goDetail(id: number) {
  router.push(`/knowledge/${id}`)
}

function handleSave() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  saving.value = true
  const action = editingId.value
    ? kbApi.update(editingId.value, { name: form.name, description: form.description })
    : kbStore.create(form.name, form.description)
  action
    .then(() => {
      ElMessage.success(editingId.value ? '更新成功' : '创建成功')
      dialogVisible.value = false
      loadList()
    })
    .finally(() => {
      saving.value = false
      editingId.value = null
      form.name = ''
      form.description = ''
    })
}

async function handleCommand(command: string, kb: any) {
  if (command === 'edit') {
    editingId.value = kb.id
    form.name = kb.name
    form.description = kb.description
    dialogVisible.value = true
  } else if (command === 'delete') {
    await ElMessageBox.confirm(`确定删除知识库「${kb.name}」吗？文档将一并删除`, '警告', {
      type: 'warning',
    })
    await kbStore.remove(kb.id)
    ElMessage.success('删除成功')
  } else if (command === 'embed') {
    const res: any = await kbApi.getEmbedCode(kb.id)
    ElMessageBox.alert(
      `<div style="margin-bottom:8px">iframe 嵌入：</div><code style="display:block;background:#f5f7fa;padding:8px;border-radius:4px;word-break:break-all">${res.iframe_code}</code>`,
      `「${kb.name}」嵌入代码`,
      { dangerouslyUseHTMLString: true }
    )
  }
}

onMounted(loadList)
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-title {
  font-size: 20px;
  margin: 0;
}
.kb-card {
  cursor: pointer;
  border-radius: 10px;
  transition: transform 0.2s;
}
.kb-card:hover {
  transform: translateY(-4px);
}
.kb-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.more-icon {
  cursor: pointer;
  color: #909399;
}
.kb-name {
  margin: 12px 0 8px;
  font-size: 16px;
}
.kb-desc {
  color: #909399;
  font-size: 13px;
  height: 40px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.kb-footer {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
  color: #909399;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
