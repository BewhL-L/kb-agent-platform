"""
Self-RAG（检索结果自检与重检索）
- 检索后用 LLM 判断：现有资料是否足以回答问题？
- 不足时，根据"缺什么"改写查询，重新检索
- 最多重试 N 次，避免无效循环

与朴素 RAG 的区别：
    朴素 RAG：检索一次 -> 直接生成（可能资料不足硬答）
    Self-RAG：检索 -> 评估 -> 不足则重检索 -> 再生成
"""
import json
from typing import Dict, List

from ..config import settings
from ..utils.logger import get_logger
from ._sync_llm import sync_chat

logger = get_logger(__name__)


ASSESS_SYSTEM = """你是一个检索质量评估专家。你的任务是判断给定的检索资料是否足以回答用户问题。"""

ASSESS_PROMPT = """请判断以下检索资料是否足以回答用户问题。

用户问题：{question}

检索资料：
{materials}

请输出 JSON 对象：
{{
  "sufficient": true 或 false,
  "reason": "判断理由，若不足说明缺什么",
  "suggested_query": "若不足，给出一个更容易检索到答案的改写查询"
}}
只输出 JSON。
"""


class SelfRAG:
    """检索-评估-重检索"""

    def retrieve_with_reflection(
        self,
        kb_id: int,
        question: str,
        top_k: int = None,
        max_retries: int = 2,
    ) -> List[Dict]:
        """带自检的检索：资料不足时自动改写查询重新检索"""
        # 第一次检索
        sources = self._do_retrieve(kb_id, question, top_k)

        current_query = question
        for attempt in range(max_retries):
            verdict = self._assess(current_query, sources)
            if verdict.get("sufficient"):
                logger.info(f"Self-RAG 第 {attempt + 1} 次评估：资料充足")
                break

            # 资料不足：改写查询重新检索
            suggested = verdict.get("suggested_query") or current_query
            logger.info(
                f"Self-RAG 第 {attempt + 1} 次评估不足（{verdict.get('reason', '')}），"
                f"改写查询重检索：{suggested[:30]}"
            )
            new_sources = self._do_retrieve(kb_id, suggested, top_k)
            # 合并去重（保留新检索结果，补充之前的）
            sources = self._merge(sources, new_sources)
            current_query = suggested

        return sources

    def _do_retrieve(
        self, kb_id: int, query: str, top_k: int
    ) -> List[Dict]:
        """调用混合检索"""
        if settings.RETRIEVAL_MODE == "hybrid":
            from ..retrieval import hybrid_retriever
            return hybrid_retriever.retrieve(kb_id, query, top_k)
        from ..services.vector_store import get_vector_store
        return get_vector_store().query(kb_id, query, top_k)

    def _assess(self, question: str, sources: List[Dict]) -> Dict:
        """评估检索资料是否充足"""
        if not sources:
            return {
                "sufficient": False,
                "reason": "没有检索到任何资料",
                "suggested_query": question,
            }
        materials = "\n".join(
            f"[{i + 1}] {s.get('text', '')[:300]}"
            for i, s in enumerate(sources)
        )
        raw = sync_chat(
            ASSESS_PROMPT.format(question=question, materials=materials),
            system=ASSESS_SYSTEM,
            temperature=0.0,
            max_tokens=300,
            purpose="other",
        )
        try:
            # 提取 JSON
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1:
                return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
        # 解析失败默认充足，避免无谓重检索
        return {"sufficient": True, "reason": "评估解析失败，默认充足"}

    def _merge(
        self, old: List[Dict], new: List[Dict]
    ) -> List[Dict]:
        """合并两次检索结果，按文本去重"""
        seen = {s.get("text", "") for s in old}
        merged = list(old)
        for s in new:
            if s.get("text", "") not in seen:
                merged.append(s)
                seen.add(s.get("text", ""))
        # 按分数排序，保留 top
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        return merged[: settings.TOP_K + 2]


self_rag = SelfRAG()
