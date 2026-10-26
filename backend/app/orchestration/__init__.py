"""Agent 编排包（可选，基于 LangGraph）

提供 get_orchestrator() 工厂：根据 settings.ORCHESTRATION_BACKEND 返回对应的
异步编排函数。未安装 langgraph 时自动降级到原生 Agent，并给出安装指引。
"""
from ..config import settings
from ..utils.logger import get_logger
from .multi_agent import build_supervisor, run_multi_agent
from .plan_execute import build_plan_execute_graph, run_plan_execute
from .react_graph import build_react_agent, run_react

logger = get_logger(__name__)

__all__ = [
    "build_react_agent",
    "run_react",
    "build_plan_execute_graph",
    "run_plan_execute",
    "build_supervisor",
    "run_multi_agent",
    "get_orchestrator",
]

# 支持的编排后端 → 对应 run_* 函数名
_ORCHESTRATORS = {
    "langgraph-react": "run_react",
    "langgraph-plan-execute": "run_plan_execute",
    "langgraph-multi-agent": "run_multi_agent",
}


def get_orchestrator(backend: str = None):
    """按配置返回编排函数（async (question: str, kb_id: int|None) -> str）。

    - backend 为 None 时读取 settings.ORCHESTRATION_BACKEND；
    - 「native」返回 None，表示使用原生 AgentService 主链路；
    - langgraph 未安装时抛出 RuntimeError，附安装指引。
    """
    backend = (backend or settings.ORCHESTRATION_BACKEND or "native").strip().lower()
    if backend in ("", "native"):
        return None

    func_name = _ORCHESTRATORS.get(backend)
    if func_name is None:
        raise ValueError(
            f"未知编排后端：{backend}，可选值：native / {', '.join(_ORCHESTRATORS)}"
        )

    try:
        import langgraph  # noqa: F401
    except ImportError:
        raise RuntimeError(
            f"编排后端 {backend} 需要安装 LangGraph：pip install langgraph langchain-openai；"
            "当前已自动降级，请改回 ORCHESTRATION_BACKEND=native 或安装依赖后重启。"
        )

    runner = globals()[func_name]
    logger.info(f"Agent 编排后端：{backend}（{func_name}）")
    return runner
