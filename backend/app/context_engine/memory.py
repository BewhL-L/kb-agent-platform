"""
记忆（Memory）
- ShortTermMemory：会话内，保留最近窗口的原始消息（FIFO）
- LongTermMemory：跨会话持久化事实，按 scope（如 user_id / kb_id）隔离，支持简单检索
"""
import json
import os
from collections import deque
from typing import Dict, List

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ShortTermMemory:
    """短期工作记忆：滑动窗口"""

    def __init__(self, max_turns: int = None):
        self.max_turns = max_turns or settings.HISTORY_KEEP_TURNS
        self.messages = deque(maxlen=self.max_turns * 2)

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def get(self) -> List[Dict]:
        return list(self.messages)

    def clear(self) -> None:
        self.messages.clear()


class LongTermMemory:
    """长期记忆：scope -> [fact, ...]，JSON 持久化"""

    def __init__(self, path: str = None):
        self.path = path or settings.LONG_MEMORY_PATH
        self.data: Dict[str, List[str]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"长期记忆加载失败：{e}")
                self.data = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"长期记忆保存失败：{e}")

    def add_fact(self, scope: str, fact: str) -> None:
        fact = fact.strip()
        if not fact:
            return
        facts = self.data.setdefault(str(scope), [])
        if fact not in facts:
            facts.append(fact)
            self._save()

    def facts(self, scope: str) -> List[str]:
        return self.data.get(str(scope), [])

    def search(self, scope: str, query: str, top_k: int = 5) -> List[str]:
        """简单词项重叠检索相关事实"""
        try:
            from ..retrieval.tokenizer import tokenize
            q = set(tokenize(query))
        except Exception:
            q = set(query.split())
        scored = []
        for fact in self.facts(scope):
            try:
                from ..retrieval.tokenizer import tokenize
                terms = set(tokenize(fact))
            except Exception:
                terms = set(fact.split())
            score = len(q & terms)
            if score:
                scored.append((score, fact))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:top_k]]

    def forget(self, scope: str) -> None:
        self.data.pop(str(scope), None)
        self._save()
