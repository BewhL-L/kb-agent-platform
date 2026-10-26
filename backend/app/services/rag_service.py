"""
RAG 核心服务
流程：用户问题 -> 向量检索 -> 拼接 Prompt -> 调用 LLM -> 返回答案 + 来源
"""
import json
from typing import AsyncGenerator, Dict, List

from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..prompts.system import RAG_SYSTEM
from .llm_service import LLMService
from .retrieval_cache import retrieval_cache
from .vector_store import get_vector_store

# RAG 系统提示词
SYSTEM_PROMPT = RAG_SYSTEM.template

# 没有检索到内容时的兜底
NO_CONTEXT_PROMPT = """知识库中暂无相关资料，请礼貌地告知用户当前知识库无法回答这个问题，并建议用户补充相关文档。"""


class RAGService:
    """RAG 检索增强生成服务"""

    def __init__(self, llm: LLMService = None, vector_store=None):
        self.llm = llm or LLMService()
        self.vector_store = vector_store or get_vector_store()

    def retrieve(self, kb_id: int, question: str, top_k: int = None) -> List[Dict]:
        """
        检索相关文档片段（带缓存）。

        只缓存默认 top_k 的结果：不同 top_k 的召回集不同，缓存 key 会爆炸且收益低。
        缓存在 `retrieval_cache` 里按「知识库版本号」失效——文档增删改后旧 key 自然不命中。
        """
        use_cache = settings.RETRIEVAL_CACHE_ENABLED and top_k is None
        if use_cache:
            hit = retrieval_cache.get(kb_id, question)
            if hit is not None:
                return hit

        sources = self._retrieve_uncached(kb_id, question, top_k)

        if use_cache:
            retrieval_cache.set(kb_id, question, sources)
        return sources

    def _retrieve_uncached(self, kb_id: int, question: str, top_k: int = None) -> List[Dict]:
        """实际检索（Self-RAG / 混合检索 / 纯向量）"""
        # Self-RAG：检索-评估-重检索
        if settings.SELF_RAG_ENABLED:
            from ..retrieval.self_rag import self_rag
            return self_rag.retrieve_with_reflection(kb_id, question, top_k)
        if settings.RETRIEVAL_MODE == "hybrid":
            from ..retrieval import hybrid_retriever
            return hybrid_retriever.retrieve(kb_id, question, top_k)
        return self.vector_store.query(kb_id, question, top_k)

    async def aretrieve(self, kb_id: int, question: str, top_k: int = None) -> List[Dict]:
        """
        异步外壳：把同步检索挪到线程池，避免阻塞事件循环。

        retrieve 内部有同步 HTTP（embedding）与同步 LLM 调用（精排），
        直接在 async 函数里调用会让整个进程等一个请求。
        注意：不能把 self.chat() 整个丢线程池——它内部有 await。
        """
        return await run_in_threadpool(self.retrieve, kb_id, question, top_k)

    def retrieve_wiki(self, kb_id: int, question: str) -> List[Dict]:
        """第一步（可选）：检索相关的 Wiki 结构化页面（仅全局理解型问题）"""
        from ..wiki.wiki_retriever import wiki_retriever
        if not wiki_retriever.should_use_wiki(question):
            return []
        return wiki_retriever.retrieve_wiki_pages(kb_id, question)

    def _build_prompt(
        self,
        question: str,
        sources: List[Dict],
        wiki_pages: List[Dict] = None,
        memory_summary: str = "",
    ) -> List[Dict]:
        """第二步：拼接 Prompt（长期记忆 + Wiki 百科 + 检索结果 + 历史）"""
        from ..utils.guard import neutralize, wrap_context

        context_sections = []

        # 0. 长期记忆摘要（历史对话的压缩）
        if memory_summary:
            context_sections.append(
                "## 历史对话摘要\n" + wrap_context(memory_summary)
            )

        # 1. Wiki 结构化知识页面（高优先级，放最前）
        if wiki_pages:
            wiki_parts = []
            for i, page in enumerate(wiki_pages, 1):
                wiki_parts.append(
                    f"【百科{i}】{page['title']}\n{neutralize(page['content'])}"
                )
            context_sections.append(
                "## 知识百科\n" + wrap_context("\n\n".join(wiki_parts))
            )

        # 2. 原始文档片段
        if sources:
            context_parts = []
            for i, source in enumerate(sources, 1):
                context_parts.append(
                    f"【资料{i}】（来源：{source['document_name']}）\n{neutralize(source['text'])}"
                )
            context_sections.append(
                "## 参考资料\n" + wrap_context("\n\n".join(context_parts))
            )

        if not context_sections:
            context = "（未检索到任何相关资料）"
            system_content = SYSTEM_PROMPT.format(context=context) + "\n" + NO_CONTEXT_PROMPT
        else:
            context = "\n\n".join(context_sections)
            system_content = SYSTEM_PROMPT.format(context=context)

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": question},
        ]

    async def chat(
        self,
        kb_id: int,
        question: str,
        history: List[Dict] = None,
        memory_summary: str = "",
    ) -> Dict:
        """完整 RAG 问答（非流式），返回答案和来源"""
        sources = await self.aretrieve(kb_id, question)
        wiki_pages = self.retrieve_wiki(kb_id, question)
        messages = self._build_prompt(question, sources, wiki_pages, memory_summary)

        # 把历史对话插到 system 之后、当前问题之前（取最近 6 轮）
        if history:
            recent_history = history[-12:]
            messages = [messages[0]] + recent_history + [messages[-1]]

        answer = await self.llm.chat(messages, prompt_version=RAG_SYSTEM.ref)

        # 在线追踪（Langfuse，未启用时为 no-op）
        try:
            from ..observability import observability
            observability.trace_rag(question, sources, answer, kb_id=kb_id)
        except Exception:
            pass
        return {
            "answer": answer,
            "sources": sources,
        }

    async def reasoning_chat(
        self,
        kb_id: int,
        question: str,
        history: List[Dict] = None,
        memory_summary: str = "",
        force: bool = False,
    ) -> Dict:
        """
        推理增强问答：检索 -> 推理模型先思考 -> 给答案。
        - force=False 时，简单问题自动走普通模型
        - 返回额外的 reasoning（思考链），供前端折叠展示
        """
        from .reasoning_service import needs_reasoning, reasoning_service

        # 总开关：关闭后与普通问答完全一致，只多回两个空字段（前端无需改）
        if not settings.REASONING_ENABLED:
            result = await self.chat(kb_id, question, history, memory_summary)
            result["reasoning"] = ""
            result["reasoned"] = False
            return result

        # 简单问题直接走普通 RAG
        if not force and not needs_reasoning(question):
            result = await self.chat(kb_id, question, history, memory_summary)
            result["reasoning"] = ""
            result["reasoned"] = False
            return result

        sources = await self.aretrieve(kb_id, question)
        wiki_pages = self.retrieve_wiki(kb_id, question)
        messages = self._build_prompt(question, sources, wiki_pages, memory_summary)
        if history:
            recent_history = history[-12:]
            messages = [messages[0]] + recent_history + [messages[-1]]

        # Self-Consistency 开关
        if settings.SELF_CONSISTENCY_ENABLED:
            r = await reasoning_service.reason_with_consistency(messages)
        else:
            r = await reasoning_service.reason(messages)

        try:
            from ..observability import observability
            observability.trace_rag(question, sources, r["answer"], kb_id=kb_id)
        except Exception:
            pass

        return {
            "answer": r["answer"],
            "reasoning": r.get("reasoning", ""),
            "reasoned": True,
            "sources": sources,
        }

    async def chat_stream(
        self,
        kb_id: int,
        question: str,
        history: List[Dict] = None,
        memory_summary: str = "",
    ) -> AsyncGenerator[str, None]:
        """流式 RAG 问答，先返回来源标记，再逐字返回答案"""
        sources = await self.aretrieve(kb_id, question)
        wiki_pages = self.retrieve_wiki(kb_id, question)
        messages = self._build_prompt(question, sources, wiki_pages, memory_summary)

        if history:
            recent_history = history[-12:]
            messages = [messages[0]] + recent_history + [messages[-1]]

        # 先把来源通过特殊标记发给前端（前端解析后展示来源引用）
        sources_json = json.dumps(sources, ensure_ascii=False)
        yield f"[[SOURCES]]{sources_json}[[/SOURCES]]\n\n"

        # 再流式输出正文
        async for token in self.llm.chat_stream(messages):
            yield token

    # ============ 跨知识库检索 ============

    def retrieve_across_kbs(
        self,
        kb_ids: List[int],
        question: str,
        top_k_per_kb: int = 3,
    ) -> List[Dict]:
        """
        跨多个知识库检索：分别检索每个库，合并、去重、按分数排序。
        每条结果带上 kb_id，便于区分来源。
        """
        merged: List[Dict] = []
        seen_texts = set()
        for kb_id in kb_ids:
            try:
                sources = self.retrieve(kb_id, question, top_k_per_kb)
            except Exception:
                continue
            for s in sources:
                text = s.get("text", "")
                if text in seen_texts:
                    continue
                seen_texts.add(text)
                s["kb_id"] = kb_id
                merged.append(s)
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        return merged[: settings.TOP_K + 3]

    async def chat_across_kbs(
        self,
        kb_ids: List[int],
        question: str,
    ) -> Dict:
        """跨多个知识库问答：检索多个库合并后生成答案"""
        sources = await run_in_threadpool(self.retrieve_across_kbs, kb_ids, question)
        # 跨库不使用单一知识库的 Wiki 页面
        messages = self._build_prompt(question, sources)
        answer = await self.llm.chat(messages)
        return {"answer": answer, "sources": sources}


rag_service = RAGService()
