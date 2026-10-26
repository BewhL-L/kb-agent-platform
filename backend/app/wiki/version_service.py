"""
Wiki 版本管理服务
- 页面更新前保存历史快照
- 查询历史版本、回滚到指定版本
- 回滚本身也会产生一个新版本（不丢失任何历史）
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models.wiki_page import WikiPage
from ..models.wiki_page_version import WikiPageVersion
from ..timeutil import utc_now
from ..utils.logger import get_logger

logger = get_logger(__name__)


class VersionService:
    """Wiki 页面版本管理"""

    def save_version(
        self,
        db: Session,
        page: WikiPage,
        change_source: str = "compile",
        editor_id: int = None,
    ) -> Optional[WikiPageVersion]:
        """
        在页面内容被覆盖前，把当前内容保存为一个历史快照。
        快照的 version 为页面当前的 version。
        """
        snapshot = WikiPageVersion(
            page_id=page.id,
            version=page.version,
            title=page.title,
            content=page.content,
            summary=page.summary,
            change_source=change_source,
            editor_id=editor_id,
        )
        db.add(snapshot)
        db.flush()
        return snapshot

    def list_versions(self, db: Session, page_id: int) -> List[WikiPageVersion]:
        """列出页面的所有历史版本，版本号倒序（最新的在前）"""
        return (
            db.query(WikiPageVersion)
            .filter(WikiPageVersion.page_id == page_id)
            .order_by(WikiPageVersion.version.desc())
            .all()
        )

    def get_version(self, db: Session, page_id: int, version_id: int) -> Optional[WikiPageVersion]:
        """获取某个具体快照"""
        return (
            db.query(WikiPageVersion)
            .filter(
                WikiPageVersion.page_id == page_id,
                WikiPageVersion.id == version_id,
            )
            .first()
        )

    def rollback(
        self,
        db: Session,
        page: WikiPage,
        version_id: int,
        editor_id: int = None,
    ) -> Optional[WikiPage]:
        """
        把页面回滚到指定快照的内容。
        注意：回滚不是删除历史，而是产生一个新版本，内容等于旧版本。
        """
        snapshot = self.get_version(db, page.id, version_id)
        if not snapshot:
            return None

        # 先保存当前状态为快照（回滚来源）
        self.save_version(db, page, change_source="rollback", editor_id=editor_id)

        # 用旧快照内容覆盖当前页面
        page.title = snapshot.title
        page.content = snapshot.content
        page.summary = snapshot.summary
        page.version += 1
        page.status = "compiled"
        page.error_msg = ""
        page.compiled_at = utc_now()
        db.commit()
        db.refresh(page)
        logger.info(f"页面 {page.id} 回滚到版本 {snapshot.version}，新版本号 {page.version}")
        return page


version_service = VersionService()
