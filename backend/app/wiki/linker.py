"""
双向链接维护器
- 扫描 Wiki 页面内容中的 [[]] 链接
- 将链接名称匹配到实际页面，建立页面间的关联关系
- 同步更新每个页面的 related_page_ids
"""
import re
from typing import Dict, Set

from sqlalchemy.orm import Session

from ..models.wiki_page import WikiPage
from ..utils.logger import get_logger

logger = get_logger(__name__)

# 匹配 [[页面名]] 或 [[页面名|别名]]
LINK_PATTERN = re.compile(r"\[\[([^\[\]|]+)(?:\|[^\[\]]+)?\]\]")


class Linker:
    """双向链接维护器"""

    def build_title_index(self, db: Session, kb_id: int) -> Dict[str, int]:
        """构建 知识库内 页面标题 -> 页面ID 的索引"""
        pages = db.query(WikiPage).filter(WikiPage.kb_id == kb_id).all()
        index = {}
        for page in pages:
            index[page.title] = page.id
            # 同时建立小写/去空格的宽松匹配
            index[self._normalize(page.title)] = page.id
        return index

    def update_relations(self, db: Session, kb_id: int) -> int:
        """
        更新知识库内所有页面的关联关系
        返回更新的页面数量
        """
        pages = db.query(WikiPage).filter(WikiPage.kb_id == kb_id).all()
        if not pages:
            return 0

        title_index = self.build_title_index(db, kb_id)
        updated = 0

        for page in pages:
            related_ids = self._resolve_links(page.content, title_index, page.id)
            old_ids = set(page.related_page_ids or [])
            if related_ids != old_ids:
                page.related_page_ids = sorted(related_ids)
                updated += 1

        db.commit()
        logger.info(f"知识库 {kb_id} 双向链接更新完成，{updated} 个页面有变化")
        return updated

    def _resolve_links(
        self, content: str, title_index: Dict[str, int], self_id: int
    ) -> Set[int]:
        """解析页面内容中的链接，返回关联页面 ID 集合"""
        names = LINK_PATTERN.findall(content)
        ids = set()
        for name in names:
            name = name.strip()
            target_id = title_index.get(name) or title_index.get(self._normalize(name))
            if target_id and target_id != self_id:
                ids.add(target_id)
        return ids

    @staticmethod
    def _normalize(name: str) -> str:
        """归一化名称：去空格、转小写，用于宽松匹配"""
        return re.sub(r"\s+", "", name).lower()


linker = Linker()
