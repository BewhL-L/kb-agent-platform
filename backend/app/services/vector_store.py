"""
向量数据库封装（Chroma）
- 每个知识库一个 collection
- 统一 add / query / delete 接口
- Embedding 持久化缓存（相同文本不重复调用，省钱省时）
- 相似度阈值过滤（剔除低相关片段，降低幻觉）
"""
import hashlib
import json
import os
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
        self._cache: Dict[str, List[float]] = {}
        if settings.EMBEDDING_CACHE_ENABLED:
            self._load_cache()

    # ============ Embedding 缓存 ============

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
                logger.info(f"加载 Embedding 缓存 {len(self._cache)} 条")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Embedding 缓存加载失败：{e}")
                self._cache = {}

    def _save_cache(self) -> None:
        """持久化缓存到磁盘"""
        if not settings.EMBEDDING_CACHE_ENABLED:
            return
        try:
            with open(settings.EMBEDDING_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._cache, f)
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
        # BM25 用大块文本建索引（返回大块，避免小块断章取义）
        try:
            from ..retrieval import hybrid_retriever
            parents = []
            seen_parents = set()
            for r in records:
                if r["parent_index"] not in seen_parents:
                    seen_parents.add(r["parent_index"])
                    parents.append(r["parent_content"])
            hybrid_retriever.on_add(kb_id, parents, document_id, document_name)
        except Exception:
            pass
        return ids

    # ============ 检索 ============

    def query(
        self,
        kb_id: int,
        question: str,
        top_k: int = None,
    ) -> List[Dict]:
        """
        语义检索，返回相似度高于阈值的 top_k 片段
        返回格式：[{text, document_name, document_id, score}]
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

        docs = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

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

            # 有大块用大块，否则用小块原文
            text = meta.get("parent_content") or doc
            formatted.append({
                "text": text,
                "document_name": meta.get("document_name", "未知文档"),
                "document_id": doc_id,
                "score": score,
                "char_start": meta.get("char_start", 0),
                "char_end": meta.get("char_end", 0),
            })

        if not formatted:
            logger.info(f"问题「{question[:20]}」检索结果均低于阈值 {settings.SIMILARITY_THRESHOLD}")
        return formatted

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
