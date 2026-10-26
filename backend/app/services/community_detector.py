"""
社区检测与社区摘要服务
- 把密集相连的实体聚成社区
- 优先用 networkx 的 Louvain（若安装）；否则用自实现的「标签传播」
  （确定性版本，无需第三方依赖），孤立点兜底连通分量
- 每个社区用 LLM 生成主题标题与摘要，供全局检索使用
"""
from collections import defaultdict
from typing import Dict, List, Set

from ..models.graph_community import GraphCommunity
from ..models.graph_entity import GraphEntity
from ..models.graph_relation import GraphRelation
from ..retrieval._sync_llm import sync_chat
from ..utils.logger import get_logger

logger = get_logger(__name__)


SUMMARY_SYSTEM = "你是知识图谱分析专家，根据一组实体及其关系，总结这个知识群组的主题。"
SUMMARY_PROMPT = """以下是知识图谱中一个社区的实体与关系。

实体：
{entities}

关系：
{relations}

请输出 JSON：
{{"title": "该社区的简短主题（不超过20字）", "summary": "该社区的核心内容概述（100-200字）"}}
只输出 JSON。
"""


class CommunityDetector:
    """社区检测与摘要"""

    def detect_and_summarize(self, db, kb_id) -> int:
        entities = db.query(GraphEntity).filter(GraphEntity.kb_id == kb_id).all()
        relations = db.query(GraphRelation).filter(GraphRelation.kb_id == kb_id).all()
        if not entities:
            return 0

        # 构建邻接表（无向）
        adj: Dict[int, Set[int]] = defaultdict(set)
        for e in entities:
            adj[e.id]  # 确保孤立点也有键
        for r in relations:
            adj[r.source_entity_id].add(r.target_entity_id)
            adj[r.target_entity_id].add(r.source_entity_id)

        # 社区检测
        groups = self._detect(entities, adj)

        # 清除旧社区与实体的社区归属
        old = db.query(GraphCommunity).filter(GraphCommunity.kb_id == kb_id).all()
        for c in old:
            db.delete(c)
        db.flush()

        # 按社区大小排序（大的在前）
        groups = sorted(groups, key=lambda g: -len(g))

        id_to_entity = {e.id: e for e in entities}
        count = 0
        for idx, group in enumerate(groups):
            members = [id_to_entity[i] for i in group if i in id_to_entity]
            title, summary = self._summarize(members, relations)

            community = GraphCommunity(
                kb_id=kb_id,
                community_index=idx,
                title=title,
                summary=summary,
                entity_ids=[m.id for m in members],
                entity_count=len(members),
            )
            db.add(community)
            db.flush()
            for m in members:
                m.community_id = community.id
            count += 1

        return count

    def _detect(self, entities, adj: Dict[int, Set[int]]) -> List[Set[int]]:
        """社区检测：优先 networkx，否则标签传播"""
        # 尝试 networkx Louvain
        try:
            import networkx as nx
            G = nx.Graph()
            G.add_nodes_from(adj.keys())
            for u, nbrs in adj.items():
                for v in nbrs:
                    if u < v:
                        G.add_edge(u, v)
            if hasattr(nx.community, "louvain_communities"):
                return [set(c) for c in nx.community.louvain_communities(G, seed=42)]
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"networkx 社区检测失败，使用标签传播：{e}")

        return self._label_propagation(entities, adj)

    def _label_propagation(
        self, entities, adj: Dict[int, Set[int]], max_iter: int = 30
    ) -> List[Set[int]]:
        """
        确定性标签传播：
        - 初始标签为节点 ID
        - 每轮节点把标签更新为邻居中权重最高的标签（平局选 ID 最小）
        - 收敛后相同标签为一个社区
        """
        labels = {e.id: e.id for e in entities}
        node_ids = sorted(adj.keys())

        for _ in range(max_iter):
            changed = False
            for node in node_ids:
                if not adj[node]:
                    continue
                # 统计邻居标签频率
                freq = defaultdict(int)
                for nbr in adj[node]:
                    freq[labels[nbr]] += 1
                # 频率最高，平局选标签最小
                best = min(freq, key=lambda label: (-freq[label], label))
                if best != labels[node]:
                    labels[node] = best
                    changed = True
            if not changed:
                break

        groups: Dict[int, Set[int]] = defaultdict(set)
        for node, lab in labels.items():
            groups[lab].add(node)
        return list(groups.values())

    def _summarize(self, members: List[GraphEntity], relations) -> tuple:
        """为一个社区生成标题与摘要"""
        ent_lines = "\n".join(
            f"- {e.name}（{e.entity_type}）：{e.summary}" for e in members
        )
        member_ids = {e.id for e in members}
        rel_lines = "\n".join(
            f"- {r.source_name} -> {r.target_name}（{r.relation_type}）"
            for r in relations
            if r.source_entity_id in member_ids and r.target_entity_id in member_ids
        ) or "（无内部关系）"

        import json
        try:
            raw = sync_chat(
                SUMMARY_PROMPT.format(entities=ent_lines, relations=rel_lines),
                system=SUMMARY_SYSTEM,
                temperature=0.2,
                max_tokens=400,
                purpose="compile",
            )
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end != -1:
                d = json.loads(raw[start:end + 1])
                return d.get("title", "社区")[:50], d.get("summary", "")
        except Exception as e:
            logger.debug(f"社区摘要生成失败：{e}")
        return f"社区（{len(members)}个实体）", "；".join(e.name for e in members)


community_detector = CommunityDetector()
