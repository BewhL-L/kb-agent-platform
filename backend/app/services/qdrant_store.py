"""
Qdrant 向量库适配器（生产环境）
- 接口与 Chroma VectorStore 完全一致：add / query / delete / count
- 支持水平扩展、持久化、过滤、负载均衡
- 通过 settings.VECTOR_PROVIDER = "qdrant" 切换
Qdrant SDK 为可选依赖，运行时才导入。
"""
import uuid
from typing import Dict, List

from ..config import settings
from ..utils.logger import get_logger
from .vector_store import VectorStore

logger = get_logger(__name__)


class QdrantStore(VectorStore):
    """Qdrant 向量库，复用父类的 Embedding 缓存逻辑"""

    def __init__(self):
        # 不调用父类 __init__（避免创建 Chroma client），手动初始化 embedding 部分
        try:
            from qdrant_client import QdrantClient
        except ImportError as e:
            raise ImportError(
                "未安装 Qdrant SDK，请先执行：pip install qdrant-client"
            ) from e

        if settings.QDRANT_API_KEY:
            self.client = QdrantClient(
                url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY
            )
        else:
            self.client = QdrantClient(url=settings.QDRANT_URL)

        from openai import OpenAI
        self.embedding_client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
        )
        self._cache: Dict[str, List[float]] = {}
        if settings.EMBEDDING_CACHE_ENABLED:
            self._load_cache()

    def _collection_name(self, kb_id: int) -> str:
        return f"kb_{kb_id}"

    def _ensure_collection(self, kb_id: int) -> None:
        """确保知识库对应的 collection 存在"""
        from qdrant_client.models import Distance, VectorParams

        name = self._collection_name(kb_id)
        existing = [c.name for c in self.client.get_collections().collections]
        if name not in existing:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=settings.EMBEDDING_DIM, distance=Distance.COSINE
                ),
            )

    # ============ 写入 ============

    def add_documents(
        self,
        kb_id: int,
        chunks: List[str],
        document_id: int,
        document_name: str,
    ) -> List[str]:
        from qdrant_client.models import PointStruct

        self._ensure_collection(kb_id)
        embeddings = self._embed(chunks)
        ids = []
        points = []
        for idx, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            point_id = str(uuid.uuid4())
            ids.append(point_id)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "document_id": document_id,
                        "document_name": document_name,
                        "chunk_index": idx,
                        "text": chunk,
                    },
                )
            )
        self.client.upsert(collection_name=self._collection_name(kb_id), points=points)

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
        from qdrant_client.models import PointStruct

        if not records:
            return []
        self._ensure_collection(kb_id)
        child_texts = [r["child_content"] for r in records]
        embeddings = self._embed(child_texts)
        ids = []
        points = []
        for idx, (r, vector) in enumerate(zip(records, embeddings)):
            point_id = str(uuid.uuid4())
            ids.append(point_id)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "document_id": document_id,
                        "document_name": document_name,
                        "chunk_index": idx,
                        "parent_index": r["parent_index"],
                        "parent_content": r["parent_content"],
                        "char_start": r["char_start"],
                        "char_end": r["char_end"],
                        "text": r["child_content"],
                    },
                )
            )
        self.client.upsert(collection_name=self._collection_name(kb_id), points=points)

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
        top_k = top_k or settings.TOP_K
        self._ensure_collection(kb_id)
        query_vector = self._embed([question])[0]
        hits = self.client.search(
            collection_name=self._collection_name(kb_id),
            query_vector=query_vector,
            limit=top_k,
        )

        formatted = []
        seen_parents = set()
        for hit in hits:
            score = round(hit.score, 4)
            if score < settings.SIMILARITY_THRESHOLD:
                continue
            payload = hit.payload or {}
            doc_id = payload.get("document_id", 0)
            parent_index = payload.get("parent_index")
            dedup_key = (doc_id, parent_index) if parent_index is not None else (doc_id, hit.id)
            if dedup_key in seen_parents:
                continue
            seen_parents.add(dedup_key)

            text = payload.get("parent_content") or payload.get("text", "")
            formatted.append({
                "text": text,
                "document_name": payload.get("document_name", "未知文档"),
                "document_id": doc_id,
                "score": score,
                "char_start": payload.get("char_start", 0),
                "char_end": payload.get("char_end", 0),
            })
        return formatted

    # ============ 删除 ============

    def delete_document(self, kb_id: int, document_id: int) -> None:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        try:
            self.client.delete(
                collection_name=self._collection_name(kb_id),
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id),
                        )
                    ]
                ),
            )
        except Exception as e:
            logger.warning(f"Qdrant 删除文档失败：{e}")

        try:
            from ..retrieval import hybrid_retriever
            hybrid_retriever.on_delete_document(kb_id, document_id)
        except Exception:
            pass

    def delete_kb(self, kb_id: int) -> None:
        try:
            self.client.delete_collection(self._collection_name(kb_id))
        except Exception:
            pass
        try:
            from ..retrieval import hybrid_retriever
            hybrid_retriever.on_delete_kb(kb_id)
        except Exception:
            pass

    def count(self, kb_id: int) -> int:
        try:
            result = self.client.count(
                collection_name=self._collection_name(kb_id), exact=True
            )
            return result.count
        except Exception:
            return 0

    def get_document_chunks(self, kb_id: int, document_id: int) -> List[Dict]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        try:
            points, _ = self.client.scroll(
                collection_name=self._collection_name(kb_id),
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id),
                        )
                    ]
                ),
                limit=10000,
            )
        except Exception as e:
            logger.warning(f"Qdrant 取文档切片失败：{e}")
            return []

        chunks = [
            {
                "text": (p.payload or {}).get("text", ""),
                "chunk_index": (p.payload or {}).get("chunk_index", 0),
            }
            for p in points
        ]
        chunks.sort(key=lambda x: x["chunk_index"])
        return chunks
