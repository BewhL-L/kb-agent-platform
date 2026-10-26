"""
四层能力补齐 - 新功能测试
================================================
- 第一层：Wiki 版本快照 / 人工编辑 / 回滚
- 第二层：父子分块（小块检索、大块返回、位置精确）
- 第三层：成本计算、成本与主动学习接口
- 第四层：跨库问答接口

所有 LLM / 向量调用均由 conftest.py 的内存假实现接管，不依赖真实 API。
"""
import re
from collections import defaultdict

from app.database import SessionLocal
from app.models.wiki_page import WikiPage
from app.services.text_splitter import split_parent_child
from app.services.usage_service import UsageService
from app.wiki.page_manager import page_manager
from app.wiki.version_service import version_service


def _strip_ws(s: str) -> str:
    """去掉所有空白，用于比较含插入换行的切片与原文"""
    return re.sub(r"\s+", "", s)


# ============================================================
# 第二层：父子分块
# ============================================================

def test_parent_child_empty():
    assert split_parent_child("") == []
    assert split_parent_child("   ") == []


def test_parent_child_structure_and_position():
    # 构造足够长的文本，产生多个父块
    text = "这是第一个完整的句子，用于测试父子分块逻辑是否正确。" * 40
    records = split_parent_child(text, parent_size=200, child_size=80)
    assert len(records) > 1

    seen_parents = set()
    for r in records:
        # 字段齐全
        assert {
            "parent_index", "parent_content", "child_content",
            "char_start", "char_end",
        }.issubset(r.keys())
        # 小块内容（忽略空白）必须属于大块
        assert _strip_ws(r["child_content"]) in _strip_ws(r["parent_content"])
        # 大块在原文中定位精确（split_text 可能插入换行，故忽略空白比较）
        located = text[r["char_start"]:r["char_end"]]
        assert _strip_ws(located) == _strip_ws(r["parent_content"])
        seen_parents.add(r["parent_index"])

    # 至少切出 2 个父块
    assert len(seen_parents) >= 2


def test_parent_child_grouping_consistent():
    text = "测试句子内容。" * 100
    records = split_parent_child(text, parent_size=150, child_size=50)

    # 同一 parent_index 的所有记录，必须共享同一份 parent_content
    groups = defaultdict(set)
    for r in records:
        groups[r["parent_index"]].add(r["parent_content"])
    for contents in groups.values():
        assert len(contents) == 1


# ============================================================
# 第三层：成本计算（纯函数）
# ============================================================

def test_cost_known_model():
    svc = UsageService()
    # gpt-4o-mini：输入 1.05 / 百万，输出 4.2 / 百万
    assert svc.calculate_cost("gpt-4o-mini", 1_000_000, 0) == 1.05
    assert svc.calculate_cost("gpt-4o-mini", 0, 1_000_000) == 4.2
    assert svc.calculate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == round(1.05 + 4.2, 6)


def test_cost_partial_tokens():
    svc = UsageService()
    # 50 万输入 token，费用应为单价的一半
    assert svc.calculate_cost("gpt-4o", 500_000, 0) == round(17.5 / 2, 6)


def test_cost_unknown_model():
    svc = UsageService()
    assert svc.calculate_cost("完全不存在的模型", 1000, 1000) == 0.0


def test_cost_fuzzy_match():
    svc = UsageService()
    # 模型名包含配置 key，应模糊匹配到 gpt-4o-mini
    assert svc.calculate_cost("gpt-4o-mini-2024-07-18", 1_000_000, 0) == 1.05


# ============================================================
# 第一层：Wiki 版本快照 / 人工编辑 / 回滚
# ============================================================

def _make_page(db, content="初始内容", version=1):
    page = WikiPage(
        title="测试实体",
        content=content,
        summary="初始摘要",
        entity_type="concept",
        kb_id=1,
        source_doc_ids=[1],
        related_page_ids=[],
        conflict_flags=[],
        status="compiled",
        version=version,
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    return page


def test_save_and_list_versions(client):
    db = SessionLocal()
    page = _make_page(db, content="版本一内容", version=1)

    snap = version_service.save_version(db, page, change_source="compile")
    db.commit()
    assert snap is not None

    versions = version_service.list_versions(db, page.id)
    assert len(versions) == 1
    assert versions[0].content == "版本一内容"
    assert versions[0].version == 1
    assert versions[0].change_source == "compile"
    db.close()


def test_manual_edit_creates_version(client):
    db = SessionLocal()
    page = _make_page(db, content="原始内容", version=1)

    page_manager.manual_edit(
        db, page, content="人工修改后的内容", summary="新摘要", editor_id=1
    )
    db.refresh(page)

    # 内容与摘要更新
    assert page.content == "人工修改后的内容"
    assert page.summary == "新摘要"
    # 版本号 +1
    assert page.version == 2
    # 来源溯源保持不变
    assert page.source_doc_ids == [1]

    # 旧内容已存为 manual 快照
    versions = version_service.list_versions(db, page.id)
    assert len(versions) == 1
    assert versions[0].content == "原始内容"
    assert versions[0].change_source == "manual"
    db.close()


def test_rollback_creates_new_version(client):
    db = SessionLocal()
    page = _make_page(db, content="原始内容", version=1)

    # 保存原始快照
    snap = version_service.save_version(db, page, change_source="manual")
    db.commit()
    snap_id = snap.id

    # 修改内容、推进版本
    page.content = "被修改的内容"
    page.version = 2
    db.commit()

    # 回滚
    updated = version_service.rollback(db, page, snap_id, editor_id=1)
    assert updated.content == "原始内容"
    # 回滚产生新版本号（3），而不是删除历史回到 1
    assert updated.version == 3

    # 历史中应保留：原始快照 + 回滚前的快照
    versions = version_service.list_versions(db, updated.id)
    assert len(versions) == 2
    db.close()


# ============================================================
# 第三、四层：API 接口烟雾测试
# ============================================================

def test_global_chat_no_kb_returns_400(client, registered_user):
    _, headers = registered_user
    # 用户没有任何知识库，应返回 400
    r = client.post(
        "/api/chat/global",
        json={"question": "测试问题", "kb_ids": []},
        headers=headers,
    )
    assert r.status_code == 400


def test_global_chat_with_kb(client, registered_user):
    _, headers = registered_user
    # 创建一个知识库
    r = client.post(
        "/api/kb",
        json={"name": "跨库测试库", "description": "用于测试"},
        headers=headers,
    )
    kb_id = r.json()["id"]

    # 指定该知识库进行跨库问答
    r = client.post(
        "/api/chat/global",
        json={"question": "测试问题", "kb_ids": [kb_id]},
        headers=headers,
    )
    assert r.status_code == 200


def test_cost_stats_empty(client, registered_user):
    _, headers = registered_user
    r = client.get("/api/stats/cost", headers=headers)
    assert r.status_code == 200
    assert r.json()["total_calls"] == 0
    assert r.json()["total_cost"] == 0


def test_active_learning_empty(client, registered_user):
    _, headers = registered_user
    r = client.get("/api/stats/active-learning", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total_answers"] == 0
    # 无负反馈时给出"保持当前配置"的默认建议
    assert data["recommendations"] == ["暂无明显负反馈，保持当前配置"]
