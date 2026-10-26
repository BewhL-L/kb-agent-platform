"""
GraphRAG 图谱构建服务
- 遍历知识库文档，用实体抽取器抽取实体与关联关系
- 同名实体合并（聚合来源文档），关系建立为边
- 构建完成后触发社区检测与社区摘要

流程：
  文档解析 -> 切片 -> 实体抽取 -> 实体合并 -> 关系建立 -> 社区检测 -> 社区摘要
"""
from typing import Dict, List

from sqlalchemy.orm import Session

from ..models.document import Document
from ..models.graph_entity import GraphEntity
from ..models.graph_relation import GraphRelation
from ..utils.logger import get_logger
from ..wiki.entity_extractor import entity_extractor
from .document_parser import parse_document
from .text_splitter import split_text

logger = get_logger(__name__)


def _normalize_name(name: str) -> str:
    """实体名归一化：去空白，便于合并同名实体"""
    return (name or "").strip().replace(" ", "").replace("　", "")


class GraphBuilder:
    """知识图谱构建器"""

    def build_graph(self, db: Session, kb_id: int, doc_ids: List[int] = None) -> Dict:
        """
        构建（或增量更新）知识库的图谱。
        返回 {"entities": 实体数, "relations": 关系数, "communities": 社区数}
        """
        # 1. 选取已完成的文档
        query = db.query(Document).filter(
            Document.kb_id == kb_id, Document.status == "completed"
        )
        if doc_ids:
            query = query.filter(Document.id.in_(doc_ids))
        docs = query.all()
        if not docs:
            return {"entities": 0, "relations": 0, "communities": 0, "docs": 0}

        # 2. 逐文档抽取实体与关系
        # 文档内抽取的三元组：(source_name, relation_type, target_name, source_doc_id)
        triples: List[tuple] = []
        for doc in docs:
            try:
                text = parse_document(doc.file_path)
                chunks = split_text(text)
                extracted = entity_extractor.extract(chunks, doc.filename)
            except Exception as e:
                logger.warning(f"文档 {doc.id} 图谱抽取失败：{e}")
                continue

            for ent in extracted:
                self._upsert_entity(db, kb_id, ent, doc.id)
                for target in ent.get("relations", []):
                    triples.append((ent["name"], "关联", target, doc.id))

        db.flush()
        # 建立 name -> entity 映射（归一化）
        name_map = self._load_name_map(db, kb_id)

        # 3. 关系建立
        rel_count = 0
        for src_name, rel_type, tgt_name, src_doc_id in triples:
            src = name_map.get(_normalize_name(src_name))
            tgt = name_map.get(_normalize_name(tgt_name))
            if not src or not tgt or src.id == tgt.id:
                continue
            if self._upsert_relation(db, kb_id, src, tgt, rel_type, src_doc_id):
                rel_count += 1

        # 4. 更新度数
        self._update_degrees(db, kb_id)

        # 5. 社区检测 + 摘要
        from .community_detector import community_detector
        communities = community_detector.detect_and_summarize(db, kb_id)

        db.commit()
        result = {
            "entities": db.query(GraphEntity).filter(GraphEntity.kb_id == kb_id).count(),
            "relations": db.query(GraphRelation).filter(GraphRelation.kb_id == kb_id).count(),
            "communities": communities,
            "docs": len(docs),
        }
        logger.info(f"知识库 {kb_id} 图谱构建完成：{result}")
        return result

    def _upsert_entity(
        self, db: Session, kb_id: int, ent: Dict, doc_id: int
    ) -> GraphEntity:
        """新增或合并实体（同名聚合来源文档）"""
        norm = _normalize_name(ent["name"])
        existing = (
            db.query(GraphEntity)
            .filter(GraphEntity.kb_id == kb_id)
            .all()
        )
        obj = None
        for e in existing:
            if _normalize_name(e.name) == norm:
                obj = e
                break

        if obj is None:
            obj = GraphEntity(
                kb_id=kb_id,
                name=ent["name"].strip(),
                entity_type=ent.get("entity_type", "concept"),
                summary=ent.get("summary", ""),
                source_doc_ids=[doc_id],
            )
            db.add(obj)
            db.flush()
        else:
            # 合并来源文档
            src_ids = list(obj.source_doc_ids or [])
            if doc_id not in src_ids:
                src_ids.append(doc_id)
                obj.source_doc_ids = src_ids
            # 补充描述
            if not obj.summary and ent.get("summary"):
                obj.summary = ent["summary"]
        return obj

    def _load_name_map(self, db: Session, kb_id: int) -> Dict[str, GraphEntity]:
        """加载知识库内 归一化名称 -> 实体 的映射"""
        entities = db.query(GraphEntity).filter(GraphEntity.kb_id == kb_id).all()
        return {_normalize_name(e.name): e for e in entities}

    def _upsert_relation(
        self,
        db: Session,
        kb_id: int,
        src: GraphEntity,
        tgt: GraphEntity,
        rel_type: str,
        doc_id: int,
    ) -> bool:
        """新增边或累加权重（无向去重，自动处理反向）"""
        existing = (
            db.query(GraphRelation)
            .filter(
                GraphRelation.kb_id == kb_id,
                GraphRelation.source_entity_id == src.id,
                GraphRelation.target_entity_id == tgt.id,
            )
            .first()
        )
        # 反向边
        reverse = (
            db.query(GraphRelation)
            .filter(
                GraphRelation.kb_id == kb_id,
                GraphRelation.source_entity_id == tgt.id,
                GraphRelation.target_entity_id == src.id,
            )
            .first()
        )
        rel = existing or reverse
        if rel:
            rel.weight += 1
            src_ids = list(rel.source_doc_ids or [])
            if doc_id not in src_ids:
                src_ids.append(doc_id)
                rel.source_doc_ids = src_ids
            return False

        edge = GraphRelation(
            kb_id=kb_id,
            source_entity_id=src.id,
            target_entity_id=tgt.id,
            source_name=src.name,
            target_name=tgt.name,
            relation_type=rel_type,
            weight=1,
            source_doc_ids=[doc_id],
        )
        db.add(edge)
        db.flush()
        return True

    def _update_degrees(self, db: Session, kb_id: int) -> None:
        """根据边数更新每个实体的度数"""
        entities = db.query(GraphEntity).filter(GraphEntity.kb_id == kb_id).all()
        counts: Dict[int, int] = {}
        relations = db.query(GraphRelation).filter(GraphRelation.kb_id == kb_id).all()
        for r in relations:
            counts[r.source_entity_id] = counts.get(r.source_entity_id, 0) + 1
            counts[r.target_entity_id] = counts.get(r.target_entity_id, 0) + 1
        for e in entities:
            e.degree = counts.get(e.id, 0)


graph_builder = GraphBuilder()
