"""
Wiki 页面管理器
- 负责页面的创建、增量更新、版本管理
- 新建页面：根据抽取的实体与文档片段生成结构化 Markdown
- 更新页面：合并新文档信息，保留已有有效内容
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models.wiki_page import WikiPage
from ..retrieval._sync_llm import sync_chat
from ..timeutil import utc_now
from ..utils.logger import get_logger

logger = get_logger(__name__)


# 新建页面的生成 prompt
PAGE_SYSTEM = """你是一个专业的知识库整理专家。你的任务是根据文档片段，为指定实体撰写一个结构化的知识页面。
输出标准的 Markdown 格式，不要输出与页面无关的说明。"""

PAGE_PROMPT = """请根据以下文档片段，为实体「{entity_name}」撰写一个知识页面。

实体类型：{entity_type}
初步描述：{summary}

文档片段：
{content}

页面结构要求（按此顺序，没有的章节可省略，不要编造信息）：
# {entity_name}

## 概述
（2-4句话，说明该实体是什么、核心作用）

## 核心要点
（用无序列表列出 3-6 个关键事实/特性）

## 详细说明
（根据文档内容展开，可包含原理、机制、分类等，用小标题组织）

## 相关内容
（列出文档中提到的、与该实体相关的其他概念，每个用「[[]]」包裹，如 [[RAG]]）

要求：
1. 所有内容必须来自文档片段，不要编造
2. 表述客观、准确、简洁
3. 文档中涉及的事实尽量保留（数字、参数、步骤等）
4. 页面长度控制在合理范围
"""


# 增量更新页面的 prompt
UPDATE_SYSTEM = """你是一个专业的知识库维护专家。你的任务是把新文档中的信息合并到已有的知识页面中。
输出更新后的完整 Markdown 页面，不要输出其他说明。"""

UPDATE_PROMPT = """请将【新文档信息】合并到【已有页面】中，生成更新后的完整页面。

实体名称：{entity_name}

【已有页面】
{existing_content}

【新文档信息】
{new_content}

合并要求：
1. 保留已有页面中仍然准确的内容，去除重复表述
2. 把新文档中的有效信息补充进去（新增章节或扩充已有章节）
3. 如果新信息与已有内容存在矛盾，保留两种说法并在矛盾处用 > [!warning] 标注
4. 保持原有的 Markdown 结构和「[[]]」链接格式
5. 不要编造两份资料中都没有的信息
6. 输出更新后的完整页面
"""


class PageManager:
    """Wiki 页面管理器"""

    def get_by_title(self, db: Session, kb_id: int, title: str) -> Optional[WikiPage]:
        """按标题查找页面（同一知识库内）"""
        return (
            db.query(WikiPage)
            .filter(WikiPage.kb_id == kb_id, WikiPage.title == title)
            .first()
        )

    def get_by_id(self, db: Session, page_id: int) -> Optional[WikiPage]:
        return db.query(WikiPage).filter(WikiPage.id == page_id).first()

    def create_page(
        self,
        db: Session,
        kb_id: int,
        entity: Dict,
        relevant_chunks: List[str],
        doc_id: int,
    ) -> Optional[WikiPage]:
        """根据实体与相关片段创建新页面"""
        content_text = "\n\n".join(relevant_chunks)[:settings.WIKI_PAGE_MAX_TOKENS * 3]
        prompt = PAGE_PROMPT.format(
            entity_name=entity["name"],
            entity_type=entity["entity_type"],
            summary=entity.get("summary", ""),
            content=content_text,
        )
        markdown = sync_chat(
            prompt, system=PAGE_SYSTEM, temperature=0.3, max_tokens=2000,
            purpose="compile", kb_id=kb_id,
        )
        if not markdown:
            logger.warning(f"实体「{entity['name']}」页面生成失败")
            return None

        page = WikiPage(
            title=entity["name"],
            content=markdown,
            summary=entity.get("summary", ""),
            entity_type=entity["entity_type"],
            kb_id=kb_id,
            source_doc_ids=[doc_id],
            related_page_ids=[],
            conflict_flags=[],
            status="compiled",
            version=1,
        )
        db.add(page)
        db.commit()
        db.refresh(page)
        return page

    def update_page(
        self,
        db: Session,
        page: WikiPage,
        relevant_chunks: List[str],
        doc_id: int,
        conflict_flags: List[Dict],
    ) -> Optional[WikiPage]:
        """增量更新已有页面，合并新信息"""
        new_content = "\n\n".join(relevant_chunks)[:settings.WIKI_PAGE_MAX_TOKENS * 3]
        prompt = UPDATE_PROMPT.format(
            entity_name=page.title,
            existing_content=page.content[:2000],
            new_content=new_content,
        )
        markdown = sync_chat(
            prompt, system=UPDATE_SYSTEM, temperature=0.2, max_tokens=2500,
            purpose="compile", kb_id=page.kb_id,
        )
        if not markdown:
            # LLM 更新失败：标记为待重编译，保留旧内容
            page.status = "stale"
            page.error_msg = "页面更新失败，等待重新编译"
            db.commit()
            return page

        # 覆盖前保存历史版本快照
        from .version_service import version_service
        version_service.save_version(db, page, change_source="compile")

        page.content = markdown
        # 来源文档去重合并
        source_ids = list(page.source_doc_ids or [])
        if doc_id not in source_ids:
            source_ids.append(doc_id)
        page.source_doc_ids = source_ids
        # 冲突标记合并（保留历史冲突，追加新冲突）
        existing_flags = list(page.conflict_flags or [])
        page.conflict_flags = existing_flags + conflict_flags
        page.version += 1
        page.status = "compiled"
        page.error_msg = ""
        page.compiled_at = utc_now()
        db.commit()
        db.refresh(page)
        return page

    def manual_edit(
        self,
        db: Session,
        page: WikiPage,
        content: str,
        summary: str = None,
        editor_id: int = None,
    ) -> WikiPage:
        """
        人工编辑页面：保存旧版本，写入新内容，版本号 +1。
        人工编辑不改变 source_doc_ids（来源溯源保持不变）。
        """
        from .version_service import version_service

        # 覆盖前保存历史版本快照
        version_service.save_version(
            db, page, change_source="manual", editor_id=editor_id
        )

        page.content = content
        if summary is not None:
            page.summary = summary
        page.version += 1
        page.status = "compiled"
        page.error_msg = ""
        page.compiled_at = utc_now()
        db.commit()
        db.refresh(page)
        return page


page_manager = PageManager()
