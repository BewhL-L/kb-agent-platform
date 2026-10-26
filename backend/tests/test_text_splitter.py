"""文本切片测试"""
from app.services.text_splitter import split_text


def test_empty_text():
    assert split_text("") == []
    assert split_text("   ") == []


def test_short_text_single_chunk():
    text = "这是一段很短的文字。"
    chunks = split_text(text, chunk_size=500, overlap=50)
    assert len(chunks) == 1


def test_chunk_respects_size():
    # 短句重复，不触发超长硬切，每片不超过 chunk_size
    text = "这是测试。" * 1000
    chunks = split_text(text, chunk_size=100, overlap=10)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_multiple_chunks():
    text = "这是一个测试句子，包含若干内容，用于验证。" * 100
    chunks = split_text(text, chunk_size=120, overlap=20)
    assert len(chunks) >= 2
