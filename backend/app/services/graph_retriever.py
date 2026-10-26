"""
GraphRAG 图谱检索服务
================================================
- 局部检索（Local Search）：问题 -> 匹配实体 -> 邻居扩展 -> 子图上下文 -> 生成答案
  适合"关于某个具体实体"的问题
- 全局检索（Global Search）：问题 -> 相关社区 -> 各社区分别作答（map）-> 汇总（reduce）
  适合"整体主题/总结/对比"的全局理解问题
"""
import math
from typing import Dict, List

from sqlalchemy import or_

from ..models.graph_community import GraphCommunity
from ..models.graph_entity import GraphEntity
from ..models.graph_relation import GraphRelation
from ..utils.logger import get_logger
from .llm_service import LLMService
from .vector_store import get_vector_store

logger = get_logger(__name__)


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


LOCAL_SYSTEM = "你是知识图谱问答助手，基于给定的实体、关系和社区信息回答问题，不编造图中没有的内容。"

GLOBAL_MAP_SYSTEM = "你是研究分析助手，基于一个知识社区的摘要，回答与该社区相关的问题。"
GLOBAL_REDUCE_SYSTEM = "你是综合分析专家，把多个来源的分析整合成条理清晰、准确、不重复的最终答案。"


class GraphRetriever:
    """图谱检索"""

    def __init__(self):
        self.llm = LLMService()

    # ============================================================
    # 局部检索
    # ============================================================

    async def local_search(
        self, kb_id: int, question: str, top_entities: int = 5
    ) -> Dict:
        db = self._session()
        try:
            entities = db.query(GraphEntity).filter(GraphEntity.kb_id == kb_id).all()
            if not entities:
                return {"answer": "知识图谱尚未构建，请先构建图谱。", "entities": [], "relations": []}

            # 1. 实体匹配（embedding 相似度）
            ranked = self._rank_entities(question, entities)
            seed = [e for e, _ in ranked[:top_entities]]

            # 2. 邻居扩展（1 跳）
            sub_ids = self._expand(db, kb_id, [e.id for e in seed])
            id_to_entity = {e.id: e for e in entities}
            sub_entities = [id_to_entity[i] for i in sub_ids if i in id_to_entity]

            # 3. 子图边
            relations = db.query(GraphRelation).filter(
                GraphRelation.kb_id == kb_id,
                GraphRelation.source_entity_id.in_(sub_ids),
                GraphRelation.target_entity_id.in_(sub_ids),
            ).all()

            # 4. 上下文 + 生成
            context = self._build_local_context(sub_entities, relations)
            answer = await self.llm.chat(
                [
                    {"role": "system", "content": LOCAL_SYSTEM},
                    {"role": "user", "content": f"问题：{question}\n\n图谱信息：\n{context}"},
                ],
                temperature=0.3,
                purpose="chat",
            )

            return {
                "answer": answer,
                "entities": [self._entity_dict(e) for e in sub_entities],
                "relations": [self._relation_dict(r) for r in relations],
            }
        finally:
            db.close()

    # ============================================================
    # 全局检索（map-reduce）
    # ============================================================

    async def global_search(self, kb_id: int, question: str, top_communities: int = 6) -> Dict:
        db = self._session()
        try:
            communities = db.query(GraphCommunity).filter(
                GraphCommunity.kb_id == kb_id
            ).all()
            if not communities:
                return {"answer": "知识图谱社区尚未生成，请先构建图谱。", "communities": []}

            # 1. 社区相关性排序
            ranked = self._rank_communities(question, communities)
            selected = [c for c, _ in ranked[:top_communities]]

            # 2. map：每个社区分别作答
            partials = []
            for c in selected:
                part = await self.llm.chat(
                    [
                        {"role": "system", "content": GLOBAL_MAP_SYSTEM},
                        {"role": "user", "content": (
                            f"问题：{question}\n\n社区主题：{c.title}\n社区摘要：{c.summary}\n"
                            "请基于该社区内容回答，若不相关请忽略。"
                        )},
                    ],
                    temperature=0.2,
                    purpose="chat",
                )
                partials.append(f"【{c.title}】\n{part}")

            # 3. reduce：汇总
            answer = await self.llm.chat(
                [
                    {"role": "system", "content": GLOBAL_REDUCE_SYSTEM},
                    {"role": "user", "content": (
                        f"问题：{question}\n\n各社区分析：\n" + "\n\n".join(partials) +
                        "\n\n请整合成最终中文答案，分点呈现。"
                    )},
                ],
                temperature=0.3,
                purpose="chat",
            )
            return {
                "answer": answer,
                "communities": [
                    {"id": c.id, "title": c.title, "summary": c.summary,
                     "entity_count": c.entity_count}
                    for c in selected
                ],
            }
        finally:
            db.close()

    # ============================================================
    # 辅助方法
    # ============================================================

    def _session(self):
        from ..database import SessionLocal
        return SessionLocal()

    def _rank_entities(self, question: str, entities: List[GraphEntity]):
        """按 embedding 相似度排序实体，含名称命中加权"""
        store = get_vector_store()
        qvec = store.embed_text(question)
        scored = []
        for e in entities:
            evec = store.embed_text(f"{e.name}。{e.summary}")
            score = _cosine(qvec, evec)
            if e.name in question:
                score += 0.3
            scored.append((e, score))
        scored.sort(key=lambda x: -x[1])
        return scored

    def _rank_communities(self, question: str, communities: List[GraphCommunity]):
        store = get_vector_store()
        qvec = store.embed_text(question)
        scored = []
        for c in communities:
            cvec = store.embed_text(f"{c.title}。{c.summary}")
            scored.append((c, _cosine(qvec, cvec)))
        scored.sort(key=lambda x: -x[1])
        return scored

    def _expand(self, db, kb_id: int, seed_ids: List[int], hops: int = 1) -> set:
        """从种子实体扩展邻居（无向边，两个方向都要查）"""
        result = set(seed_ids)
        frontier = set(seed_ids)
        for _ in range(hops):
            if not frontier:
                break
            flist = list(frontier)
            rels = db.query(GraphRelation).filter(
                GraphRelation.kb_id == kb_id,
                or_(
                    GraphRelation.source_entity_id.in_(flist),
                    GraphRelation.target_entity_id.in_(flist),
                ),
            ).all()
            next_frontier = set()
            for r in rels:
                # 找到边的"另一端"
                other = r.target_entity_id if r.source_entity_id in frontier \
                    else r.source_entity_id
                if other not in result:
                    next_frontier.add(other)
            result |= next_frontier
            frontier = next_frontier
        return result

    def _build_local_context(self, entities: List[GraphEntity], relations: List[GraphRelation]) -> str:
        lines = ["### 实体"]
        for e in entities:
            lines.append(f"- {e.name}（{e.entity_type}）：{e.summary}")
        lines.append("### 关系")
        for r in relations:
            lines.append(f"- {r.source_name} --{r.relation_type}--> {r.target_name}")
        return "\n".join(lines)

    def _entity_dict(self, e: GraphEntity) -> Dict:
        return {"id": e.id, "name": e.name, "entity_type": e.entity_type,
                "summary": e.summary, "degree": e.degree, "community_id": e.community_id}

    def _relation_dict(self, r: GraphRelation) -> Dict:
        return {"id": r.id, "source": r.source_name, "target": r.target_name,
                "relation_type": r.relation_type, "source_id": r.source_entity_id,
                "target_id": r.target_entity_id}


graph_retriever = GraphRetriever()
