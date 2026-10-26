"""
知识冲突检测器
- 当新文档信息与已有 Wiki 页面内容不一致时，识别矛盾点
- 典型冲突：同一实体的不同定义、不同参数/数值、互斥的结论
- 输出结构化冲突标记，供页面展示与人工审核
"""
import json
from typing import Dict, List

from ..retrieval._sync_llm import sync_chat
from ..utils.logger import get_logger

logger = get_logger(__name__)


DETECT_SYSTEM = """你是一个严谨的知识一致性审核员。你的任务是判断【新文档信息】与【已有知识页面】之间是否存在事实冲突。
只输出 JSON，不要输出任何解释或 Markdown 代码块标记。"""

DETECT_PROMPT = """请对比以下关于同一实体「{entity_name}」的两份资料，判断是否存在事实性冲突。

【已有知识页面内容】
{existing_content}

【新文档相关内容】
{new_content}

判断标准：
1. 只有当两份资料对同一事实给出了互斥、矛盾的说法时才算冲突（如不同的数值、相反的结论、不同的定义导致含义改变）
2. 以下情况不算冲突：
   - 新内容只是补充了已有页面没有的信息
   - 详略不同但核心含义一致
   - 表述不同但实质相同
3. 不确定时，判定为无冲突（避免误报）

输出 JSON：
{{
  "has_conflict": true/false,
  "conflicts": [
    {{
      "field": "冲突涉及的方面（如：定义/参数/结论/时间）",
      "existing_claim": "已有页面的说法",
      "new_claim": "新文档的说法",
      "detail": "简要说明为什么冲突"
    }}
  ]
}}
"""


class ConflictDetector:
    """知识冲突检测器"""

    def detect(
        self,
        entity_name: str,
        existing_content: str,
        new_content: str,
        new_doc_id: int,
    ) -> List[Dict]:
        """
        检测新内容与已有页面的冲突
        返回冲突标记列表：[{"field", "existing_claim", "new_claim", "detail", "doc_id"}]
        """
        if not existing_content.strip() or not new_content.strip():
            return []

        prompt = DETECT_PROMPT.format(
            entity_name=entity_name,
            existing_content=existing_content[:2000],
            new_content=new_content[:2000],
        )
        raw = sync_chat(
            prompt,
            system=DETECT_SYSTEM,
            temperature=0.0,
            max_tokens=800,
            purpose="compile",
        )
        if not raw:
            return []

        return self._parse(raw, new_doc_id)

    def _parse(self, raw: str, new_doc_id: int) -> List[Dict]:
        """解析冲突检测结果"""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("冲突检测结果 JSON 解析失败")
            return []

        if not data.get("has_conflict"):
            return []

        flags = []
        for c in data.get("conflicts", []):
            flags.append({
                "field": (c.get("field") or "未分类").strip(),
                "existing_claim": (c.get("existing_claim") or "").strip(),
                "new_claim": (c.get("new_claim") or "").strip(),
                "detail": (c.get("detail") or "").strip(),
                "doc_id": new_doc_id,
            })
        return flags


conflict_detector = ConflictDetector()
