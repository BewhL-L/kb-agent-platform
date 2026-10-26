"""
实体/概念抽取器
- 从文档片段中抽取关键实体（人物、概念、工具、API、流程、术语）
- 使用同步 LLM 调用（编译在后台线程中执行）
- 输出结构化 JSON，含实体名、类型、简介、关联实体
"""
import json
from typing import Dict, List

from ..config import settings
from ..retrieval._sync_llm import sync_chat
from ..utils.logger import get_logger

logger = get_logger(__name__)


EXTRACT_SYSTEM = """你是一个专业的知识图谱实体抽取引擎。你的任务是从给定文档中抽取关键实体和概念。
只输出 JSON，不要输出任何解释或 Markdown 代码块标记。"""

EXTRACT_PROMPT = """请从以下文档内容中抽取最多 {max_entities} 个最重要的实体/概念。

实体类型限定为：
- person：人物、角色
- concept：概念、原理、方法论
- tool：工具、框架、库、产品
- api：接口、服务、协议
- process：流程、步骤、机制
- term：专业术语、缩写
- other：其他

输出 JSON 格式：
{{
  "entities": [
    {{
      "name": "实体名称（简洁规范）",
      "entity_type": "concept",
      "summary": "一句话描述该实体（不超过50字）",
      "relations": ["文档中与之明确关联的其他实体名称"]
    }}
  ]
}}

要求：
1. 只抽取文档中明确出现的、有实质信息的实体，不要臆测
2. 实体名称要规范统一（如全文统一用"RAG"而非"检索增强生成/RAG"混用，选最常用的写法）
3. 优先抽取被多处提及、包含定义或详细说明的实体
4. 如果没有可抽取的实体，返回 {{"entities": []}}

文档内容：
{content}
"""


class EntityExtractor:
    """实体/概念抽取器"""

    def extract(self, chunks: List[str], doc_name: str = "") -> List[Dict]:
        """
        从文档片段中抽取实体
        返回：[{"name", "entity_type", "summary", "relations"}]
        """
        # 合并 chunk（控制单次输入长度，取前若干 chunk 拼接）
        combined = self._combine_chunks(chunks)
        if not combined.strip():
            return []

        prompt = EXTRACT_PROMPT.format(
            max_entities=settings.WIKI_MAX_ENTITIES_PER_DOC,
            content=combined,
        )
        raw = sync_chat(
            prompt,
            system=EXTRACT_SYSTEM,
            temperature=0.1,
            max_tokens=2000,
            purpose="compile",
        )
        if not raw:
            logger.warning(f"文档「{doc_name}」实体抽取返回为空")
            return []

        return self._parse(raw, doc_name)

    def _combine_chunks(self, chunks: List[str]) -> str:
        """合并 chunk，控制总长度（按字符数粗估 token）"""
        max_chars = settings.WIKI_PAGE_MAX_TOKENS * 3
        parts = []
        total = 0
        for chunk in chunks:
            if total + len(chunk) > max_chars:
                break
            parts.append(chunk)
            total += len(chunk)
        return "\n\n".join(parts)

    def _parse(self, raw: str, doc_name: str) -> List[Dict]:
        """解析 LLM 返回的 JSON，容错处理"""
        text = raw.strip()
        # 去除可能的 Markdown 代码块包裹
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"文档「{doc_name}」实体抽取结果 JSON 解析失败")
            return []

        entities = data.get("entities", [])
        valid = []
        seen_names = set()
        for ent in entities:
            name = (ent.get("name") or "").strip()
            if not name or name in seen_names:
                continue
            etype = ent.get("entity_type", "concept").strip()
            if etype not in ("person", "concept", "tool", "api", "process", "term", "other"):
                etype = "concept"
            seen_names.add(name)
            valid.append({
                "name": name,
                "entity_type": etype,
                "summary": (ent.get("summary") or "").strip()[:200],
                "relations": [r.strip() for r in (ent.get("relations") or []) if r.strip()],
            })
        return valid


entity_extractor = EntityExtractor()
