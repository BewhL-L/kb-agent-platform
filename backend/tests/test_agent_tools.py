"""Agent 工具测试：安全计算器 + 时间"""
from app.services.agent_service import tool_calculator, tool_get_current_time


def test_calculator_basic():
    assert "14" in tool_calculator("2 + 3 * 4")
    assert "0.8" in tool_calculator("(100 - 60) / 50")


def test_calculator_rejects_code_injection():
    evil = "__import__('os').system('dir')"
    result = tool_calculator(evil)
    # 必须返回计算失败，且命令没有被执行
    assert "计算失败" in result
    assert result == "计算失败：不支持的表达式"


def test_current_time():
    assert "当前时间" in tool_get_current_time()
