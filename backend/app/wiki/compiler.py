"""
Wiki 编译引擎（核心协调器）
- 文档处理完成后，把文档编译为结构化 Wiki 页面
- 流程：取 chunks → 抽取实体 → 逐实体建页/更新（含冲突检测）→ 维护双向链接
- 所有方法为同步实现，供后台线程调用
"""
from typing import Dict, List

from sqlalchemy.orm import Session

from ..models import Document
from ..services.vector_store import VectorStore
from ..utils.logger import get_logger
from .conflict_detector import ConflictDetector
from .entity_extractor import EntityExtractor
from .linker import Linker
from .page_manager import PageManager

logger = get_logger(__name__)


class WikiCompiler:
    """Wiki 编译引擎"""

    def __init__(
        self,
        vector_store: VectorStore = None,
        extractor: EntityExtractor = None,
        page_manager: PageManager = None,
        conflict_detector: ConflictDetector = None,
        linker: Linker = None,
    ):
        self.vector_store = vector_store or VectorStore()
        self.extractor = extractor or EntityExtractor()
        self.page_manager = page_manager or PageManager()
        self.conflict_detector = conflict_detector or ConflictDetector()
        self.linker = linker or Linker()

    def compile_document(self, db: Session, kb_id: int, doc_id: int) -> Dict:
        """
        编译单个文档为 Wiki 页面
        返回统计：{"created": n, "updated": n, "failed": n}
        """
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return {"created": 0, "updated": 0, "failed": 0}

        # 1. 从向量库取回该文档的切片
        chunk_data = self.vector_store.get_document_chunks(kb_id, doc_id)
        chunks = [c["text"] for c in chunk_data]
        if not chunks:
            logger.warning(f"文档 {doc_id} 无可用切片，跳过编译")
            return {"created": 0, "updated": 0, "failed": 0}

        # 2. 抽取实体
        entities = self.extractor.extract(chunks, doc_name=doc.filename)
        if not entities:
            logger.info(f"文档「{doc.filename}」未抽取到实体")
            return {"created": 0, "updated": 0, "failed": 0}

        stats = {"created": 0, "updated": 0, "failed": 0}

        # 3. 逐实体处理
        for entity in entities:
            try:
                relevant = self._find_relevant_chunks(chunks, entity["name"])
                existing = self.page_manager.get_by_title(db, kb_id, entity["name"])

                if existing:
                    # 冲突检测
                    flags = self.conflict_detector.detect(
                        entity_name=entity["name"],
                        existing_content=existing.content,
                        new_content="\n\n".join(relevant),
                        new_doc_id=doc_id,
                    )
                    page = self.page_manager.update_page(
                        db, existing, relevant, doc_id, flags
                    )
                    if page:
                        stats["updated"] += 1
                    else:
                        stats["failed"] += 1
                else:
                    page = self.page_manager.create_page(
                        db, kb_id, entity, relevant, doc_id
                    )
                    if page:
                        stats["created"] += 1
                    else:
                        stats["failed"] += 1
            except Exception as e:
                logger.error(f"实体「{entity['name']}」处理异常：{e}")
                stats["failed"] += 1

        # 4. 维护双向链接
        try:
            self.linker.update_relations(db, kb_id)
        except Exception as e:
            logger.warning(f"双向链接更新失败：{e}")

        logger.info(
            f"文档「{doc.filename}」编译完成：新建 {stats['created']}，"
            f"更新 {stats['updated']}，失败 {stats['failed']}"
        )
        return stats

    def recompile_kb(self, db: Session, kb_id: int) -> Dict:
        """
        重新编译整个知识库（遍历所有已完成文档）
        返回累计统计
        """
        docs = (
            db.query(Document)
            .filter(Document.kb_id == kb_id, Document.status == "completed")
            .all()
        )
        total = {"created": 0, "updated": 0, "failed": 0}
        for doc in docs:
            stats = self.compile_document(db, kb_id, doc.id)
            for key in total:
                total[key] += stats[key]
        return total

    def _find_relevant_chunks(self, chunks: List[str], entity_name: str) -> List[str]:
        """
        筛选与实体相关的切片：优先包含实体名的切片，
        若过少则回退为全部切片（控制数量）
        """
        # 实体名可能是多词，用主词匹配
        keywords = [entity_name]
        if len(entity_name) > 4:
            keywords.append(entity_name[:4])

        relevant = []
        for chunk in chunks:
            if any(kw and kw in chunk for kw in keywords):
                relevant.append(chunk)

        if len(relevant) < 2:
            relevant = list(chunks)

        # 控制送入 LLM 的切片数量
        max_chunks = 6
        return relevant[:max_chunks]


wiki_compiler = WikiCompiler()
