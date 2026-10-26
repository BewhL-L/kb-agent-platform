"""
轻量中文分词
- 优先使用 jieba（若已安装）
- 否则降级为「英文/数字词 + 中文单字 + 相邻二元 bigram」，无需额外依赖，BM25 仍可用
"""
import re
from typing import List

_HAN = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[A-Za-z0-9]+")


def _fallback_tokenize(text: str) -> List[str]:
    tokens = _WORD.findall(text)
    han = _HAN.findall(text)
    tokens.extend(han)
    # 相邻汉字组成 bigram，提升中文词项匹配
    tokens.extend(han[i] + han[i + 1] for i in range(len(han) - 1))
    return tokens


def tokenize(text: str) -> List[str]:
    """把文本切成词项；去掉纯空白项"""
    try:
        import jieba
        return [w.strip() for w in jieba.cut(text) if w.strip()]
    except ImportError:
        return [t for t in _fallback_tokenize(text) if t.strip()]
