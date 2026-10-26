"""
Wiki 查询检索器（查询时使用）
- 判断问题是否需要 Wiki 增强（全局理解型问题）
- 从已编译的 Wiki 页面中检索与问题最相关的页面
- 与 chunk 检索协同：Wiki 页面提供结构化全局信息，chunk 提供细节溯源
"""
import re
from typing import Dict, List

from ..config import settings
from ..database import SessionLocal
from ..models.wiki_page import WikiPage
from ..utils.logger import get_logger

logger = get_logger(__name__)


# 全局理解型问题的信号词（这类问题需要跨片段整合，Wiki 页面更有优势）
_GLOBAL_SIGNALS = [
    "是什么", "什么是", "区别", "区别是", "对比", "比较", "不同",
    "原理", "总结", "概述", "概括", "介绍一下", "介绍下", "有哪些",
    "整体", "架构", "流程是", "机制", "概念", "定义", "包括什么",
    "之间的关系", "如何理解", "怎么理解",
]

# 纯事实查找型问题（直接查 chunk 更快，不需要 Wiki）
_FACT_SIGNALS = ["多少", "几个", "电话", "地址", "什么时候", "哪一天", "几号"]


class WikiRetriever:
    """Wiki 查询检索器"""

    def should_use_wiki(self, question: str) -> bool:
        """判断问题是否适合走 Wiki 增强"""
        if not settings.WIKI_ENABLED or not settings.WIKI_RETRIEVAL_ENABLED:
            return False
        q = question.strip()
        # 事实查找型直接返回 False
        if any(sig in q for sig in _FACT_SIGNALS) and not any(
            sig in q for sig in _GLOBAL_SIGNALS
        ):
            return False
        return any(sig in q for sig in _GLOBAL_SIGNALS)

    def retrieve_wiki_pages(self, kb_id: int, question: str) -> List[Dict]:
        """
        检索与问题相关的 Wiki 页面
        返回：[{"page_id", "title", "content", "summary", "score"}]
        """
        db = SessionLocal()
        try:
            pages = (
                db.query(WikiPage)
                .filter(WikiPage.kb_id == kb_id, WikiPage.status == "compiled")
                .all()
            )
            if not pages:
                return []

            scored = []
            question_tokens = self._tokenize(question)
            for page in pages:
                score = self._score(page, question, question_tokens)
                if score >= settings.WIKI_PAGE_SCORE_THRESHOLD:
                    scored.append({
                        "page_id": page.id,
                        "title": page.title,
                        "content": page.content,
                        "summary": page.summary,
                        "score": round(score, 4),
                    })

            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[: settings.WIKI_MAX_PAGES_PER_QUERY]
        except Exception as e:
            logger.warning(f"Wiki 页面检索失败：{e}")
            return []
        finally:
            db.close()

    def _score(self, page: WikiPage, question: str, q_tokens: List[str]) -> float:
        """
        计算页面与问题的相关度
        - 标题命中：权重最高
        - 摘要命中：中等
        - 正文命中：基础
        """
        score = 0.0
        title = page.title or ""

        # 标题完整出现在问题中（强信号）
        if title and title in question:
            score += 0.6
        # 标题分词命中
        title_tokens = self._tokenize(title)
        if title_tokens:
            title_hits = sum(1 for t in title_tokens if t in q_tokens)
            score += 0.3 * (title_hits / len(title_tokens))

        # 摘要命中
        summary = page.summary or ""
        if summary:
            summary_tokens = self._tokenize(summary)
            if summary_tokens:
                hits = sum(1 for t in summary_tokens if t in q_tokens)
                score += 0.2 * (hits / min(len(summary_tokens), 10))

        # 正文命中（轻量，只看是否有关键词）
        content = page.content or ""
        if content:
            content_hits = sum(1 for t in q_tokens if len(t) >= 2 and t in content)
            score += min(0.15, 0.02 * content_hits)

        return score

    def _tokenize(self, text: str) -> List[str]:
        """
        简单分词：提取中文词组（2字以上）与英文单词
        无需 jieba 等依赖，用标点/空格切分 + 单字组合近似
        """
        text = text.lower()
        # 提取英文单词和数字
        en_tokens = re.findall(r"[a-z0-9]+", text)
        # 提取连续中文片段，按 2-4 字滑窗生成候选词
        cn_segments = re.findall(r"[\u4e00-\u9fa5]+", text)
        cn_tokens = []
        for seg in cn_segments:
            # 整段保留（用于匹配实体全名）
            if len(seg) >= 2:
                cn_tokens.append(seg)
            # 2-gram
            for i in range(len(seg) - 1):
                cn_tokens.append(seg[i:i + 2])
        return list(set(en_tokens + cn_tokens))


wiki_retriever = WikiRetriever()
