"""
向量数据库封装（Chroma）
- 每个知识库一个 collection
- 统一 add / query / delete 接口
- Embedding 持久化缓存（相同文本不重复调用，省钱省时）
- 相似度阈值过滤（剔除低相关片段，降低幻觉）
"""
import atexit
import hashlib
import json
import os
import time
import uuid
from typing import Dict, List, Optional

import chromadb
from openai import OpenAI

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


class VectorStore:
    """向量数据库服务"""

    def __init__(self, persist_dir: str = None):
        self.persist_dir = persist_dir or settings.VECTOR_DB_PATH
        os.makedirs(self.persist_dir, exist_ok=True)
        # 本地持久化 Chroma 客户端
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        self.embedding_client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
        )
        # Embedding 缓存：text_hash -> vector
        self._init_cache()

    # ============ Embedding 缓存 ============

    def _init_cache(self) -> None:
        """初始化 embedding 缓存状态（Chroma / Qdrant 两个实现共用）。

        这里把三件事绑在一起，避免两个子类各写一遍写歪：
          1. 载入磁盘缓存
          2. 记录节流用的时间戳
          3. 注册退出钩子——写入是节流的，不 force 一次的话每次重启都会丢掉最后一批
        """
        self._cache: Dict[str, List[float]] = {}
        self._cache_dirty = False
        self._last_flush = 0.0
        if settings.EMBEDDING_CACHE_ENABLED:
            self._load_cache()
            atexit.register(self._flush_on_exit)

    def _flush_on_exit(self) -> None:
        """进程退出时的兜底落盘。

        只看 `_cache_dirty`：没改动就不写。否则每次 `--reload` 重启都会重写一遍
        几 MB 的 JSON，纯属给磁盘找事。节流期间被跳过的那批写入会在这里补上。
        """
        if not self._cache_dirty:
            return
        try:
            self._save_cache(force=True)
        except Exception:  # pragma: no cover - 退出阶段不再抛错污染日志
            pass

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _load_cache(self) -> None:
        """启动时从磁盘加载缓存"""
        path = settings.EMBEDDING_CACHE_PATH
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                self._trim_cache()
                logger.info(f"加载 Embedding 缓存 {len(self._cache)} 条")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Embedding 缓存加载失败：{e}")
                self._cache = {}

    def _trim_cache(self) -> None:
        """按插入序淘汰最老的条目，防止 embedding_cache.json 无限膨胀。

        为什么不做真正的 LRU：缓存里存的是「文本 → 向量」，命中之后不回写顺序，
        做 LRU 要额外维护双向链表，收益不值这个复杂度。而 embedding 缓存的写入量
        主要来自不断出现的新文本（查询改写每轮都不一样），FIFO 已经够用。

        为什么一次回收 10% 而不是"超一条删一条"：后者在稳态下每写一条都要
        `list()` 一次全表再删一条，并且每次都打一行日志——缓存越大越慢、日志越吵。
        批量回收到 90% 之后，同样的工作量摊到 10% 的新增上。
        """
        limit = settings.EMBEDDING_CACHE_MAX_ENTRIES
        if limit <= 0 or len(self._cache) <= limit:
            return
        target = max(1, int(limit * 0.9))
        overflow = len(self._cache) - target
        for key in list(self._cache)[:overflow]:
            self._cache.pop(key, None)
        logger.info(f"Embedding 缓存超出上限 {limit}，回收至 {target} 条（淘汰 {overflow} 条）")

    def _save_cache(self, force: bool = False) -> None:
        """持久化缓存到磁盘。

        **按时间节流**：一次检索里有 N 个改写查询就是 N 次 `_embed`，
        每次都全量 dump 一遍 JSON，等于每问一次写 N 次盘、每次写的还是同一个几 MB 文件。
        缓存丢了可以重算，所以这里宁可晚一点落盘；进程正常退出时 atexit 会 force 一次。
        """
        if not settings.EMBEDDING_CACHE_ENABLED:
            return
        now = time.time()
        if not force and now - self._last_flush < settings.EMBEDDING_CACHE_FLUSH_INTERVAL:
            self._cache_dirty = True
            return
        try:
            with open(settings.EMBEDDING_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._cache, f)
            self._last_flush = now
            self._cache_dirty = False
        except OSError as e:
            logger.warning(f"Embedding 缓存保存失败：{e}")

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """把文本转向量，命中缓存的不重复调用"""
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        missing_idx: List[int] = []
        missing_texts: List[str] = []

        # 先查缓存
        for i, text in enumerate(texts):
            key = self._hash_text(text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                missing_idx.append(i)
                missing_texts.append(text)

        # 未命中的批量调用 API
        if missing_texts:
            logger.info(f"Embedding 调用 {len(missing_texts)} 条（缓存命中 {len(texts) - len(missing_texts)} 条）")
            response = self.embedding_client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=missing_texts,
            )
            for idx, item in zip(missing_idx, response.data):
                vector = item.embedding
                results[idx] = vector
                self._cache[self._hash_text(texts[idx])] = vector
            self._trim_cache()
            self._save_cache()

        return results  # type: ignore

    def embed_text(self, text: str) -> List[float]:
        """公开接口：单条文本转向量（命中缓存），供 GraphRAG 实体匹配等复用"""
        return self._embed([text])[0]

    # ============ Collection ============

    def _get_collection_name(self, kb_id: int) -> str:
        return f"kb_{kb_id}"

    def _get_collection(self, kb_id: int):
        return self.client.get_or_create_collection(
            name=self._get_collection_name(kb_id),
            metadata={"hnsw:space": "cosine"},
        )

    # ============ 写入 ============

    def add_documents(
        self,
        kb_id: int,
        chunks: List[str],
        document_id: int,
        document_name: str,
    ) -> List[str]:
        """把一个文档的切片存入向量库，返回 chunk id 列表"""
        collection = self._get_collection(kb_id)
        ids = [f"doc{document_id}_{uuid.uuid4().hex[:12]}" for _ in chunks]
        embeddings = self._embed(chunks)
        metadatas = [
            {
                "document_id": document_id,
                "document_name": document_name,
                "chunk_index": idx,
            }
            for idx in range(len(chunks))
        ]
        collection.add(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        # 同步维护 BM25 稀疏索引（混合检索用），失败不影响主流程
        try:
            from ..retrieval import hybrid_retriever
            hybrid_retriever.on_add(kb_id, chunks, document_id, document_name)
        except Exception:
            pass
        return ids

    def add_parent_child_documents(
        self,
        kb_id: int,
        records: List[Dict],
        document_id: int,
        document_name: str,
    ) -> List[str]:
        """
        父子分块存储：
        - 向量库只存小块（child_content），用于检索
        - metadata 中保存大块全文（parent_content）与位置信息
        """
        if not records:
            return []
        collection = self._get_collection(kb_id)
        child_texts = [r["child_content"] for r in records]
        ids = [f"doc{document_id}_{uuid.uuid4().hex[:12]}" for _ in records]
        embeddings = self._embed(child_texts)
        metadatas = []
        for idx, r in enumerate(records):
            metadatas.append({
                "document_id": document_id,
                "document_name": document_name,
                "chunk_index": idx,
                "parent_index": r["parent_index"],
                "parent_content": r["parent_content"],
                "char_start": r["char_start"],
                "char_end": r["char_end"],
            })
        collection.add(
            ids=ids,
            documents=child_texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        # BM25 用子块建索引（精度），命中后返回父块（完整）。
        # 这里传的是**全部子块**而不是去重后的父块：children 与 parents 必须一一对齐，
        # 提前按 parent_index 去重会让下标错位，返回的父块就和命中的子块对不上了。
        try:
            from ..retrieval import hybrid_retriever
            hybrid_retriever.on_add(
                kb_id,
                child_texts,
                document_id,
                document_name,
                parents=[r["parent_content"] for r in records],
            )
        except Exception:
            pass
        return ids

    # ============ 检索 ============

    def _format_hits(self, docs, metadatas, distances) -> List[Dict]:
        """把 Chroma 的三行并列数组整理成统一结构（query 与 query_batch 共用）。

        返回的每条同时带两个文本字段，这是有意为之：
          - `text`       父块全文，喂给最终生成，保证上下文完整
          - `child_text` 子块原文，喂给精排与展示，保证排序判断不被长文稀释
        """
        formatted = []
        seen_parents = set()
        for doc, meta, dist in zip(docs, metadatas, distances):
            score = round(1 - dist, 4)
            # 相似度阈值过滤
            if score < settings.SIMILARITY_THRESHOLD:
                continue
            meta = meta or {}
            doc_id = meta.get("document_id", 0)
            parent_index = meta.get("parent_index")
            # 父子分块：同一大块只返回一次，保留最高分
            dedup_key = (doc_id, parent_index) if parent_index is not None else (doc_id, doc)
            if dedup_key in seen_parents:
                continue
            seen_parents.add(dedup_key)

            formatted.append({
                "text": meta.get("parent_content") or doc,
                "child_text": doc,
                "document_name": meta.get("document_name", "未知文档"),
                "document_id": doc_id,
                "score": score,
                "char_start": meta.get("char_start", 0),
                "char_end": meta.get("char_end", 0),
            })
        return formatted

    def query(
        self,
        kb_id: int,
        question: str,
        top_k: int = None,
    ) -> List[Dict]:
        """
        语义检索，返回相似度高于阈值的 top_k 片段
        返回格式：[{text, child_text, document_name, document_id, score}]
        """
        top_k = top_k or settings.TOP_K
        collection = self._get_collection(kb_id)
        if collection.count() == 0:
            return []

        query_embedding = self._embed([question])[0]
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
        )

        formatted = self._format_hits(
            results.get("documents", [[]])[0],
            results.get("metadatas", [[]])[0],
            results.get("distances", [[]])[0],
        )
        if not formatted:
            logger.info(f"问题「{question[:20]}」检索结果均低于阈值 {settings.SIMILARITY_THRESHOLD}")
        return formatted

    def query_batch(
        self,
        kb_id: int,
        questions: List[str],
        top_k: int = None,
    ) -> List[List[Dict]]:
        """一次检索多个问题（查询改写后的多路召回）。

        收益不在"少几次数据库查询"，而在少几次 **embedding API 调用**：
        改写出来的查询每轮都是新文本，缓存必然 miss，逐个 query 就是逐个网络往返。
        向量库本身支持一次传多个 query embedding，合成一次后 N 次调用变 1 次。
        """
        questions = list(questions)
        if not questions:
            return []
        top_k = top_k or settings.TOP_K
        collection = self._get_collection(kb_id)
        if collection.count() == 0:
            return [[] for _ in questions]

        embeddings = self._embed(questions)
        results = collection.query(
            query_embeddings=embeddings,
            n_results=min(top_k, collection.count()),
        )
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        dists = results.get("distances") or []
        out: List[List[Dict]] = []
        for i in range(len(questions)):
            out.append(
                self._format_hits(
                    docs[i] if i < len(docs) else [],
                    metas[i] if i < len(metas) else [],
                    dists[i] if i < len(dists) else [],
                )
            )
        return out

    # ============ 删除 ============

    def delete_document(self, kb_id: int, document_id: int) -> None:
        """删除某文档的所有向量"""
        collection = self._get_collection(kb_id)
        collection.delete(where={"document_id": document_id})
        try:
            from ..retrieval import hybrid_retriever
            hybrid_retriever.on_delete_document(kb_id, document_id)
        except Exception:
            pass

    def delete_kb(self, kb_id: int) -> None:
        """删除整个知识库的 collection"""
        try:
            self.client.delete_collection(name=self._get_collection_name(kb_id))
        except Exception:
            pass
        try:
            from ..retrieval import hybrid_retriever
            hybrid_retriever.on_delete_kb(kb_id)
        except Exception:
            pass

    def count(self, kb_id: int) -> int:
        """统计知识库的向量数量"""
        collection = self._get_collection(kb_id)
        return collection.count()

    def get_document_chunks(self, kb_id: int, document_id: int) -> List[Dict]:
        """
        按文档 ID 取回该文档的所有切片（Wiki 编译用）
        返回：[{"text": ..., "chunk_index": ...}]，按切片顺序排列
        """
        collection = self._get_collection(kb_id)
        result = collection.get(
            where={"document_id": document_id},
            include=["documents", "metadatas"],
        )
        docs = result.get("documents", [])
        metas = result.get("metadatas", [])
        chunks = [
            {"text": text, "chunk_index": (meta or {}).get("chunk_index", 0)}
            for text, meta in zip(docs, metas)
        ]
        chunks.sort(key=lambda x: x["chunk_index"])
        return chunks


# 全局单例（默认 Chroma）
vector_store = VectorStore()


# 向量库实例缓存
_vector_store_instance = None


def get_vector_store():
    """
    工厂：根据 settings.VECTOR_PROVIDER 返回对应向量库单例
    - chroma：本地 Chroma（开发）
    - qdrant：Qdrant（生产）
    """
    global _vector_store_instance
    if _vector_store_instance is not None:
        return _vector_store_instance
    if settings.VECTOR_PROVIDER == "qdrant":
        from .qdrant_store import QdrantStore
        _vector_store_instance = QdrantStore()
    else:
        _vector_store_instance = vector_store
    return _vector_store_instance
