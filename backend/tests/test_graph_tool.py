"""
GraphRAG 工具验收用例（当前跳过，实现后启用）
==============================================
这是 §3.4 的验收标准之一：**图谱未构建时，Agent 不能崩，要给出可读提示并继续作答**。

你要做的四步：
    1. 在 `agent_service.TOOL_DEFINITIONS` 里加 `query_knowledge_graph`
       （name / description / parameters，描述写清"适用于关系型问题、不适用于查数值"）
    2. 在 `TOOL_EXECUTORS` 里注册执行器，内部调 `graph_retriever.local_search`
    3. 图谱未构建时返回"该知识库尚未构建知识图谱，请改用 search_knowledge_base"，不要抛异常
    4. 删除下面这行 skip，然后跑 `python -m pytest tests/test_graph_tool.py -q`

如果失败，先跑 `tests/test_agent_tool_harness.py` 确认测试桩本身是好的。
"""
import asyncio
import json

import pytest

pytestmark = pytest.mark.skip(reason="待实现 query_knowledge_graph 工具；实现后删除本行")


def test_graph_tool_handles_unbuilt_graph(tool_script):
    from app.services.agent_service import agent_service

    tool_script(
        [{
            "name": "query_knowledge_graph",
            "arguments": json.dumps({"query": "退款 与 七天无理由 的关系"}),
        }],
        final="图谱中暂无该信息，已改用常规检索",
    )

    result = asyncio.run(
        agent_service.chat(
            [{"role": "user", "content": "退款和七天无理由是什么关系"}],
            kb_id=1,
        )
    )

    assert result["answer"], "Agent 必须给出最终答案，不能因为工具报错而中断"

    messages = tool_script.tool_messages()
    assert messages, "Agent 没有执行 query_knowledge_graph，检查工具是否已注册到 TOOL_EXECUTORS"
    assert "尚未构建" in messages[0]["content"], "图谱为空时应返回可读提示，而不是异常文本"
