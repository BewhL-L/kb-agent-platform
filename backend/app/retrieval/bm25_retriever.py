"""
BM25（Okapi）稀疏检索，纯 Python 实现
- 每个知识库一个索引文件（bm25_index/kb_{id}.json）
- 文档上传/更新时增量维护；删除文档时同步移除
- 与稠密向量检索互补：BM25 擅长精确词项匹配（型号、专有名词、关键词）
"""
import json
import math
import os
import threading
from collections import Counter
from typing import Dict, List

from ..config import settings
from ..utils.logger import get_logger
from .tokenizer import tokenize

logger = get_logger(__name__)

# 进程内索引缓存：persist_dir|kb_id -> (文件 mtime, 索引对象)
# 每次查询都重新读整份 JSON 会把 IO 放大到「每问一次读一次」，这里按 mtime 判断是否过期。
_CACHE: Dict[str, tuple] = {}
_CACHE_LOCK = threading.Lock()


def _cache_key(persist_dir: str, kb_id: int) -> str:
    return f"{persist_dir}|{kb_id}"


def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


class BM25Index:
    """单知识库的 BM25 索引"""

    K1 = 1.5
    B = 0.75

    def __init__(self, kb_id: int, persist_dir: str = None):
        self.kb_id = kb_id
        self.persist_dir = persist_dir or settings.BM25_INDEX_DIR
        os.makedirs(self.persist_dir, exist_ok=True)
        self.path = os.path.join(self.persist_dir, f"kb_{kb_id}.json")
        # docs: [{key, text, document_id, document_name, tf: {term: freq}, length}]
        self.docs: List[Dict] = []
        self.df: Dict[str, int] = {}
        self._load()

    # ============ 缓存入口 ============

    @classmethod
    def load_cached(cls, kb_id: int, persist_dir: str = None) -> "BM25Index":
        """
        取索引：优先复用进程内缓存，文件 mtime 变化（别的进程或本进程写过）时才重新读盘。
        并发写场景下仍可能读到旧快照，但不会重复解析整份 JSON。
        """
        persist_dir = persist_dir or settings.BM25_INDEX_DIR
        path = os.path.join(persist_dir, f"kb_{kb_id}.json")
        mtime = _file_mtime(path)
        key = _cache_key(persist_dir, kb_id)

        with _CACHE_LOCK:
            hit = _CACHE.get(key)
        if hit and hit[0] == mtime:
            return hit[1]

        index = cls(kb_id, persist_dir)
        with _CACHE_LOCK:
            _CACHE[key] = (mtime, index)
        return index

    def _remember(self) -> None:
        """写盘后同步缓存里的 mtime，避免下一次 load 又解析一遍"""
        with _CACHE_LOCK:
            _CACHE[_cache_key(self.persist_dir, self.kb_id)] = (
                _file_mtime(self.path), self
            )

    # ============ 持久化 ============

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.docs = data.get("docs", [])
                self.df = data.get("df", {})
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"BM25 索引加载失败：{e}")
                self.docs, self.df = [], {}

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"docs": self.docs, "df": self.df}, f, ensure_ascii=False)
            self._remember()
        except OSError as e:
            logger.warning(f"BM25 索引保存失败：{e}")

    # ============ 维护 ============

    def add(
        self,
        chunks: List[str],
        document_id: int,
        document_name: str,
    ) -> None:
        """加入一个文档的切片；若该文档已存在则先移除（增量更新语义）"""
        self.remove_document(document_id)
        for idx, chunk in enumerate(chunks):
            terms = tokenize(chunk)
            tf = dict(Counter(terms))
            self.docs.append({
                "key": f"doc{document_id}_{idx}",
                "text": chunk,
                "document_id": document_id,
                "document_name": document_name,
                "tf": tf,
                "length": len(terms),
            })
            for term in tf:
                self.df[term] = self.df.get(term, 0) + 1
        self._save()

    def remove_document(self, document_id: int) -> None:
        """移除某文档的全部切片并重算 df"""
        before = len(self.docs)
        self.docs = [d for d in self.docs if d["document_id"] != document_id]
        if len(self.docs) != before:
            self._rebuild_df()
            self._save()

    def _rebuild_df(self) -> None:
        self.df = {}
        for d in self.docs:
            for term in d["tf"]:
                self.df[term] = self.df.get(term, 0) + 1

    def remove_kb(self) -> None:
        self.docs, self.df = [], {}
        try:
            os.remove(self.path)
        except OSError:
            pass
        with _CACHE_LOCK:
            _CACHE.pop(_cache_key(self.persist_dir, self.kb_id), None)

    # ============ 检索 ============

    def _idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        total = len(self.docs)
        # BM25+ 风格 IDF，保证非负
        return math.log(1 + (total - n + 0.5) / (n + 0.5))

    def search(self, query: str, top_k: int = None) -> List[Dict]:
        """返回 BM25 相关性最高的片段：[{text, document_name, document_id, score}]"""
        top_k = top_k or settings.TOP_K
        if not self.docs:
            return []

        avgdl = sum(d["length"] for d in self.docs) / len(self.docs) or 1.0
        q_terms = tokenize(query)
        scored = []
        for d in self.docs:
            score = 0.0
            tf_map = d["tf"]
            for term in q_terms:
                f = tf_map.get(term, 0)
                if f:
                    idf = self._idf(term)
                    denom = f + self.K1 * (1 - self.B + self.B * d["length"] / avgdl)
                    score += idf * (f * (self.K1 + 1)) / denom
            if score > 0:
                scored.append((score, d))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "text": d["text"],
                "document_name": d["document_name"],
                "document_id": d["document_id"],
                "score": round(s, 4),
            }
            for s, d in scored[:top_k]
        ]
