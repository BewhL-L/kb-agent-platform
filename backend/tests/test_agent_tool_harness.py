"""
测试桩自检：证明"脚本化工具调用 → 执行 → 结果回灌 → 最终答案"这条链是通的。

为什么要有这条用例：
    你为 GraphRAG 工具写测试时，如果它失败了，应该能确定问题在"工具没注册/没实现"，
    而不是"测试桩坏了"。这条用例先证明桩本身可用。

桩的用法：
    tool_script([{"name": "calculator", "arguments": '{"expression": "23*17"}'}],
                final="计算结果是 391")
"""
import asyncio
import json


def test_scripted_tool_call_roundtrip(tool_script):
    from app.services.agent_service import agent_service

    tool_script(
        [{"name": "calculator", "arguments": json.dumps({"expression": "23*17"})}],
        final="计算结果是 391",
    )

    result = asyncio.run(
        agent_service.chat([{"role": "user", "content": "算一下 23*17"}], kb_id=None)
    )

    assert result["answer"] == "计算结果是 391", "脚本用完后应返回指定的最终答案"

    tool_messages = tool_script.tool_messages()
    assert tool_messages, "模型没有收到 tool 结果，说明 Agent 的执行分支没走到"
    assert "391" in tool_messages[0]["content"], "工具执行结果没有回灌给模型"
