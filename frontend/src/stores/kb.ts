import { defineStore } from 'pinia'
import { ref } from 'vue'
import { kbApi } from '@/api/knowledge'

export interface KnowledgeBase {
  id: number
  name: string
  description: string
  embed_code?: string
  document_count: number
  created_at: string
  updated_at: string
}

export const useKbStore = defineStore('kb', () => {
  const kbList = ref<KnowledgeBase[]>([])
  const currentKb = ref<KnowledgeBase | null>(null)
  const loading = ref(false)
  const total = ref(0)

  // 获取列表
  async function fetchList(params?: { page?: number; page_size?: number; keyword?: string }) {
    loading.value = true
    try {
      const res: any = await kbApi.list({ page: 1, page_size: 100, ...params })
      kbList.value = res.items
      total.value = res.total
      return res
    } finally {
      loading.value = false
    }
  }

  // 创建
  async function create(name: string, description: string) {
    const res: any = await kbApi.create({ name, description })
    await fetchList()
    return res
  }

  // 删除
  async function remove(id: number) {
    await kbApi.delete(id)
    kbList.value = kbList.value.filter((kb) => kb.id !== id)
    if (currentKb.value?.id === id) currentKb.value = null
  }

  // 设置当前知识库
  function setCurrent(kb: KnowledgeBase | null) {
    currentKb.value = kb
  }

  return {
    kbList,
    currentKb,
    loading,
    total,
    fetchList,
    create,
    remove,
    setCurrent,
  }
})
