"""
LLM Wiki 表迁移脚本
- 为已有数据库补充 wiki_pages / wiki_page_versions 表
  （新库由 main.py 的 create_all 自动建表，无需手动跑）
- 用法：cd backend && python -m scripts.migrate_wiki
"""
# 导入模型，确保 WikiPage / WikiPageVersion 注册到 Base.metadata
from app import models  # noqa: F401
from app.database import Base, engine
from app.utils.logger import get_logger

logger = get_logger(__name__)


def migrate():
    """创建 wiki_pages / wiki_page_versions 表（已存在则跳过，不影响现有数据）"""
    Base.metadata.create_all(
        bind=engine,
        tables=[
            models.WikiPage.__table__,
            models.WikiPageVersion.__table__,
        ],
    )
    logger.info("wiki_pages / wiki_page_versions 表已就绪")
    print("✅ 迁移完成：wiki_pages、wiki_page_versions 表已创建（或已存在）")


if __name__ == "__main__":
    migrate()
