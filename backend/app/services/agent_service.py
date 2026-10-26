"""
AI Agent 服务（Agentic RAG 核心）
- 把"知识库检索"封装成 Agent 可调用的工具，由 Agent 自主决定：
  要不要检索、检索什么、检索几次、是否结合计算器
- 支持迭代检索（资料不足换关键词再查）
- 多次检索的来源去重聚合后随答案返回
- 同时提供非流式 chat 与流式 chat_stream（工具过程事件 + 最终答案流式）
"""
import inspect
import json
from datetime import datetime
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..prompts.system import AGENT_SYSTEM
from ..utils.logger import get_logger
from .llm_service import LLMService

logger = get_logger(__name__)


# ============ 基础工具定义 ============

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前的日期和时间，当用户问现在几点、今天日期、星期几时使用",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "进行数学计算，当用户需要做加减乘除、百分比等数学运算时使用，不要心算",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，例如 (100 + 200) * 0.8",
                    }
                },
                "required": ["expression"],
            },
        },
    },
]

SEARCH_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": (
            "检索企业知识库。当问题涉及公司制度、产品信息、政策、流程、售后、人事等"
            "企业内部信息时使用。若一次检索结果不足，可更换关键词再次调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用于检索的问题或关键词，尽量简洁、聚焦",
                }
            },
            "required": ["query"],
        },
    },
}


# ============ 基础工具实现 ============

def tool_get_current_time() -> str:
    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return f"当前时间是 {now.strftime('%Y年%m月%d日')} {weekdays[now.weekday()]} {now.strftime('%H:%M:%S')}"


def tool_calculator(expression: str) -> str:
    """安全计算器：AST 白名单，只允许数字和数学运算符，杜绝代码注入"""
    import ast
    import operator

    allowed_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            return allowed_ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return allowed_ops[type(node.op)](_eval(node.operand))
        raise ValueError("不支持的表达式")

    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree.body)
        return f"{expression} = {result}"
    except Exception as e:
        return f"计算失败：{e}"


TOOL_EXECUTORS = {
    "get_current_time": lambda **kwargs: tool_get_current_time(),
    "calculator": lambda **kwargs: tool_calculator(kwargs.get("expression", "")),
}


def _dedup_sources(sources: List[Dict]) -> List[Dict]:
    """按 (document_id, text) 去重，保留相似度更高的一条"""
    best: Dict[tuple, Dict] = {}
    for s in sources:
        key = (s.get("document_id"), s.get("text"))
        if key not in best or s.get("score", 0) > best[key].get("score", 0):
            best[key] = s
    return list(best.values())


AGENT_SYSTEM_PROMPT = AGENT_SYSTEM.template


class AgentService:
    """Agentic RAG 服务"""

    def __init__(self, llm: LLMService = None):
        self.llm = llm or LLMService()

    def _prepare(
        self, kb_id: Optional[int], collected_sources: List[Dict]
    ) -> Tuple[List[dict], Dict]:
        """根据 kb_id 构建工具列表和执行器映射"""
        executors = dict(TOOL_EXECUTORS)
        tools = TOOL_DEFINITIONS

        if kb_id is not None:
            tools = TOOL_DEFINITIONS + [SEARCH_TOOL_DEFINITION]

            def _search(query: str) -> str:
                # 复用 RAG 的检索链路（Self-RAG / 混合检索 + 精排 / 纯向量，由配置决定），
                # 不要直接查 vector_store：否则 Agent 模式的召回质量会低于普通问答。
                from .rag_service import rag_service as _rag

                results = _rag.retrieve(kb_id, query)
                if not results:
                    return "未检索到相关资料，可更换关键词重试，或告知用户知识库暂无该信息。"
                collected_sources.extend(results)
                return "\n\n".join(
                    f"[来源：{r['document_name']}]\n{r['text']}" for r in results
                )

            executors["search_knowledge_base"] = lambda **kw: _search(kw.get("query", ""))

        # 工具预算裁剪（上下文工程）
        from ..context_engine import ContextAssembler
        tools = ContextAssembler().select_tools(tools, budget=settings.TOOL_BUDGET)
        return tools, executors

    async def _execute_tool(self, tool_name: str, arguments: str, executors: Dict) -> str:
        executor = executors.get(tool_name)
        if not executor:
            return f"错误：工具 {tool_name} 不存在"
        try:
            args = json.loads(arguments) if arguments else {}
            # 同步执行器放线程池：工具里可能有阻塞 IO（检索、HTTP），不能卡事件循环
            result = await run_in_threadpool(executor, **args)
            # 允许执行器返回协程（例如以后接入 GraphRAG 的 async 检索）
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as e:
            logger.error(f"工具 {tool_name} 执行失败：{e}")
            return f"工具执行失败：{e}"

    async def chat(
        self,
        messages: List[Dict],
        kb_id: Optional[int] = None,
        max_iterations: int = 4,
    ) -> Dict:
        """非流式 Agent 对话，返回 {"answer", "sources"}"""
        collected_sources: List[Dict] = []
        tools, executors = self._prepare(kb_id, collected_sources)
        full_messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}] + messages

        for iteration in range(max_iterations):
            response_msg = await self.llm.chat_with_tools(full_messages, tools)
            tool_calls = getattr(response_msg, "tool_calls", None)

            if not tool_calls:
                return {
                    "answer": response_msg.content,
                    "sources": _dedup_sources(collected_sources),
                }

            full_messages.append(response_msg)
            for tool_call in tool_calls:
                name = tool_call.function.name
                args = tool_call.function.arguments
                logger.info(f"Agent 第{iteration + 1}轮调用：{name}({args})")
                result = await self._execute_tool(name, args, executors)
                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        final_answer = await self.llm.chat(full_messages)
        return {
            "answer": final_answer,
            "sources": _dedup_sources(collected_sources),
        }

    async def chat_stream(
        self,
        messages: List[Dict],
        kb_id: Optional[int] = None,
        max_iterations: int = 4,
    ) -> AsyncGenerator[Dict, None]:
        """
        流式 Agent：
        - 工具调用阶段 yield {"tool", "arguments"} 事件（前端展示"正在检索/计算"）
        - 最终答案阶段逐字 yield {"token"}
        - 结束 yield {"done", "sources"}
        """
        collected_sources: List[Dict] = []
        tools, executors = self._prepare(kb_id, collected_sources)
        full_messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}] + messages

        for iteration in range(max_iterations):
            response_msg = await self.llm.chat_with_tools(full_messages, tools)
            tool_calls = getattr(response_msg, "tool_calls", None)

            if not tool_calls:
                break

            full_messages.append(response_msg)
            for tool_call in tool_calls:
                name = tool_call.function.name
                args = tool_call.function.arguments
                logger.info(f"流式Agent 第{iteration + 1}轮调用：{name}({args})")
                yield {"tool": name, "arguments": args}

                result = await self._execute_tool(name, args, executors)
                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        # 最终答案流式生成（此时 full_messages 已包含全部工具结果）
        async for token in self.llm.chat_stream(full_messages):
            yield {"token": token}

        yield {"done": True, "sources": _dedup_sources(collected_sources)}


# 全局单例（默认模型）
agent_service = AgentService()
