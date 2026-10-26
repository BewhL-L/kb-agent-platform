"""
LangGraph ReAct Agent
与内置 native Agent（agent_service）能力等价，但用工业界主流的 LangGraph 编排，
自带「思考-行动-观察」循环、消息状态管理与 checkpoint 能力。
"""

from ..utils.logger import get_logger
from ._langchain import get_chat_model, make_tools

logger = get_logger(__name__)

REACT_SYSTEM = (
    "你是企业智能知识库助手，可使用知识库检索、数学计算、获取时间等工具。"
    "涉及企业内部信息必须先检索，不得编造；需要计算时调用计算器；用中文作答。"
)


def build_react_agent(kb_id: int = None, checkpointer=None):
    try:
        from langgraph.prebuilt import create_react_agent
    except ImportError as e:
        raise ImportError(
            "未安装 langgraph，请执行：pip install langgraph langchain-openai"
        ) from e

    llm = get_chat_model()
    tools = make_tools(kb_id)
    return create_react_agent(llm, tools, prompt=REACT_SYSTEM, checkpointer=checkpointer)


async def run_react(question: str, kb_id: int = None) -> str:
    """一次性运行 ReAct，返回最终答案文本"""
    agent = build_react_agent(kb_id)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})
    return result["messages"][-1].content
