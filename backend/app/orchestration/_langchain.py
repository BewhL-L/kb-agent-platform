"""LangChain / LangGraph 共享工厂：OpenAI 兼容对话模型与工具集（可选依赖）"""
import json

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


def get_chat_model(temperature: float = 0.3):
    """OpenAI 兼容接口的 LangChain 对话模型（豆包/方舟/OpenAI 均可）"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=temperature,
        timeout=settings.LLM_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
    )


def make_tools(kb_id: int = None):
    """构造 LangChain 工具；复用内置 Agent 的安全实现"""
    from langchain_core.tools import tool

    from ..services.agent_service import tool_calculator, tool_get_current_time

    @tool
    def search_knowledge_base(query: str) -> str:
        """检索企业知识库。涉及公司制度、产品资料、政策、流程、售后、人事等信息时使用。"""
        from ..services.rag_service import rag_service

        if kb_id is None:
            return "未指定知识库，无法检索。"
        return json.dumps(rag_service.retrieve(kb_id, query), ensure_ascii=False)

    @tool
    def get_current_time() -> str:
        """获取当前日期、星期与时间。"""
        return tool_get_current_time()

    @tool
    def calculator(expression: str) -> str:
        """进行数学计算，输入表达式，例如 (100 + 200) * 0.8，不要心算。"""
        return tool_calculator(expression)

    tools = [search_knowledge_base, get_current_time, calculator]
    if kb_id is None:
        tools = [t for t in tools if t.name != "search_knowledge_base"]
    return tools
