"""
文本切片（Chunking）
- 按段落 / 句子边界切分，尽量不切断语义
- 控制 chunk_size 和 overlap（重叠）
- 支持父子分块（Parent-Child）：小块检索、大块返回
"""
import re
from typing import Dict, List

from ..config import settings


def split_text(
    text: str,
    chunk_size: int = None,
    overlap: int = None,
) -> List[str]:
    """
    将长文本切成多个 chunk。

    策略：
    1. 先按段落（双换行）聚合
    2. 超过 chunk_size 的段落再按句子切
    3. 相邻 chunk 之间保留 overlap 字的重叠，避免上下文断裂
    """
    if not text or not text.strip():
        return []

    # 用 is None 判断，显式传 0（如 parent 切分不要重叠）才能生效
    chunk_size = settings.CHUNK_SIZE if chunk_size is None else chunk_size
    overlap = settings.CHUNK_OVERLAP if overlap is None else overlap

    # 先按段落切
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    # 第一步：把超长段落按句子拆开
    sentences = []
    for para in paragraphs:
        if len(para) <= chunk_size:
            sentences.append(para)
        else:
            sentences.extend(_split_long_paragraph(para, chunk_size))

    # 第二步：贪心聚合句子到 chunk，并加入 overlap
    chunks = []
    current = ""
    for sent in sentences:
        if not current:
            current = sent
        elif len(current) + len(sent) + 1 <= chunk_size:
            current += "\n" + sent
        else:
            chunks.append(current)
            # overlap：把上一个 chunk 末尾的一段带到新 chunk
            current = _get_overlap_text(current, overlap) + sent
    if current:
        chunks.append(current)

    return [c.strip() for c in chunks if c.strip()]


def _split_long_paragraph(paragraph: str, chunk_size: int) -> List[str]:
    """把超长段落按中文/英文句子边界切分"""
    # 按句号、问号、感叹号、分号切分（中英文都支持）
    sentence_endings = re.compile(r"(?<=[。！？；!?;])")
    pieces = [p.strip() for p in sentence_endings.split(paragraph) if p.strip()]

    # 如果单句还是超长，按逗号硬切
    result = []
    for piece in pieces:
        if len(piece) <= chunk_size:
            result.append(piece)
        else:
            for i in range(0, len(piece), chunk_size):
                result.append(piece[i:i + chunk_size])
    return result


def _get_overlap_text(text: str, overlap: int) -> str:
    """取文本末尾 overlap 长度的内容，作为重叠部分"""
    if overlap <= 0 or len(text) <= overlap:
        return ""
    overlap_text = text[-overlap:]
    # 尽量从换行处开始，避免截到半行
    newline_pos = overlap_text.find("\n")
    if newline_pos != -1:
        overlap_text = overlap_text[newline_pos + 1:]
    return overlap_text


def _find_ignoring_whitespace(text: str, pattern: str, start: int = 0):
    """
    在 text 中从 start 开始查找 pattern，匹配时忽略双方的空白差异。
    返回 (char_start, char_end)，char_end 为原文中实际匹配结束的位置；
    找不到返回 (-1, -1)。

    解决 split_text 聚合句子时插入了 '\\n'，而原文可能没有这些换行、
    导致 str.find 无法定位的问题。
    """
    n, m = len(text), len(pattern)
    for i in range(start, n):
        ti, pi = i, 0
        end = i
        while ti < n and pi < m:
            if pattern[pi].isspace():
                pi += 1
            elif text[ti].isspace():
                ti += 1
            elif text[ti] == pattern[pi]:
                ti += 1
                pi += 1
                end = ti
            else:
                break
        # pattern 剩余的空白也视为匹配完
        while pi < m and pattern[pi].isspace():
            pi += 1
        if pi == m:
            return i, end
    return -1, -1


def split_parent_child(
    text: str,
    parent_size: int = None,
    child_size: int = None,
) -> List[Dict]:
    """
    父子分块（Parent-Child Chunking）

    思路：
    - 先切成大块（parent，约 1000 字），保证上下文完整
    - 每个大块再切成小块（child，约 250 字），保证检索精度
    - 向量库只存小块，检索命中小块后返回它所属的大块

    返回（每个小块一条记录）：
    [{
        "parent_index": 大块编号,
        "parent_content": 大块全文,
        "child_content": 小块文本,
        "char_start": 大块在原文中的起始字符位置,
        "char_end": 大块在原文中的结束字符位置,
    }]
    """
    if not text or not text.strip():
        return []

    parent_size = parent_size or settings.PARENT_CHUNK_SIZE
    child_size = child_size or settings.CHILD_CHUNK_SIZE

    # 1. 切大块（不重叠，避免大块重复）
    parents = split_text(text, chunk_size=parent_size, overlap=0)

    # 2. 每个大块切小块，并记录大块在原文中的位置
    records = []
    search_cursor = 0
    for p_idx, parent in enumerate(parents):
        # 忽略空白差异定位（split_text 可能在句子间插入了原文没有的换行）
        char_start, char_end = _find_ignoring_whitespace(text, parent, search_cursor)
        if char_start == -1:
            char_start, char_end = search_cursor, search_cursor + len(parent)
        search_cursor = char_end

        children = split_text(parent, chunk_size=child_size, overlap=settings.CHUNK_OVERLAP)
        if not children:
            children = [parent]
        for child in children:
            records.append({
                "parent_index": p_idx,
                "parent_content": parent,
                "child_content": child,
                "char_start": char_start,
                "char_end": char_end,
            })
    return records
