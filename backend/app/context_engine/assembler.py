"""
动态上下文组装（Context Assembler）
- 历史先压缩
- 按 token 预算裁剪检索资料（资料已按相关度排序，优先保留靠前的）
- 工具预算：工具过多时按优先级裁剪（Tool Budget，避免无关工具干扰模型）
"""
import re
from typing import Dict, List, Tuple

from ..config import settings
from ..utils.logger import get_logger
from .compressor import compress_history

logger = get_logger(__name__)

_CJK = re.compile(r"[\u4e00-\u9fff]")


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文约 1 字 1 token，英文/数字约 0.35 token/字符"""
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return int(cjk + other * 0.35)


# 工具优先级关键词（命中的优先保留）
_TOOL_PRIORITY = ("search", "knowledge", "retriev", "time", "calculator", "检索", "计算", "时间")


class ContextAssembler:
    """运行时上下文组装"""

    def assemble(
        self,
        system_prompt: str,
        question: str,
        history: List[Dict] = None,
        retrieved: List[Dict] = None,
    ) -> Tuple[List[Dict], List[Dict]]:
        """返回 (messages, 实际采用的资料)"""
        history = compress_history(history or [])
        retrieved = retrieved or []

        # 固定部分占用（system + 问题 + 历史 + 输出预留）
        hist_tokens = sum(estimate_tokens(m["content"]) for m in history)
        fixed = estimate_tokens(system_prompt) + estimate_tokens(question) + hist_tokens + 800
        doc_budget = max(400, settings.CONTEXT_MAX_TOKENS - fixed)

        kept: List[Dict] = []
        used = 0
        for c in retrieved:  # 资料已按相关度排序
            t = estimate_tokens(c["text"])
            if used + t <= doc_budget or not kept:
                kept.append(c)
                used += t

        parts = [
            f"【资料{i}】（来源：{c['document_name']}）\n{c['text']}"
            for i, c in enumerate(kept, 1)
        ]
        context = "\n\n".join(parts) or "（未检索到相关资料）"

        if "{context}" in system_prompt:
            sys_content = system_prompt.replace("{context}", context)
        else:
            sys_content = system_prompt + "\n\n参考资料：\n" + context

        messages = (
            [{"role": "system", "content": sys_content}]
            + history
            + [{"role": "user", "content": question}]
        )
        return messages, kept

    def select_tools(self, tools: List[dict], question: str = "", budget: int = None) -> List[dict]:
        """工具预算：超过预算时优先保留高频基础工具"""
        budget = budget or settings.TOOL_BUDGET
        if not tools or len(tools) <= budget:
            return tools

        def _priority(t: dict) -> int:
            try:
                name = t["function"]["name"].lower()
            except (KeyError, TypeError):
                name = str(t)
            return 0 if any(k in name for k in _TOOL_PRIORITY) else 1

        return sorted(tools, key=_priority)[:budget]
