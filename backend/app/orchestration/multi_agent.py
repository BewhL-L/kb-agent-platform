"""
多 Agent 协作（Supervisor 模式）
- researcher：检索并汇总事实（带检索工具）
- writer：把资料整合成结构化答案
- supervisor：按状态路由任务（确定性状态机，也可替换为 LLM 路由）
展示「分工 + 调度」的多智能体协作范式。
"""
from typing import TypedDict

from ..utils.logger import get_logger
from ._langchain import get_chat_model, make_tools

logger = get_logger(__name__)


class State(TypedDict):
    question: str
    research: str
    draft: str
    next: str


def _agents(kb_id):
    try:
        from langgraph.prebuilt import create_react_agent
    except ImportError as e:
        raise ImportError("未安装 langgraph，请 pip install langgraph") from e

    llm = get_chat_model()
    researcher = create_react_agent(
        llm, make_tools(kb_id),
        prompt="你是资料检索员，只负责检索并汇总找到的事实，列出依据，不要展开润色。",
    )
    writer = create_react_agent(
        llm, [],
        prompt="你是撰写员，把已收集资料整合成条理清晰、准确、不编造的中文答案。",
    )
    return researcher, writer


async def researcher_node(state: State) -> dict:
    researcher, _ = _agents(state.get("_kb_id"))
    out = await researcher.ainvoke({
        "messages": [{"role": "user",
                      "content": f"请为以下问题检索资料并汇总事实：{state['question']}"}]
    })
    return {"research": out["messages"][-1].content}


async def writer_node(state: State) -> dict:
    _, writer = _agents(state.get("_kb_id"))
    out = await writer.ainvoke({
        "messages": [{"role": "user",
                      "content": f"问题：{state['question']}\n已收集资料：\n{state['research']}\n请撰写最终中文答案。"}]
    })
    return {"draft": out["messages"][-1].content}


async def supervisor_node(state: State) -> dict:
    if not state.get("research"):
        nxt = "researcher"
    elif not state.get("draft"):
        nxt = "writer"
    else:
        nxt = "FINISH"
    return {"next": nxt}


def build_supervisor(kb_id: int = None):
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as e:
        raise ImportError("未安装 langgraph，请 pip install langgraph") from e

    # 把 kb_id 注入状态供节点使用
    async def _researcher(state):
        state["_kb_id"] = kb_id
        return await researcher_node(state)

    g = StateGraph(State)
    g.add_node("supervisor", supervisor_node)
    g.add_node("researcher", _researcher)
    g.add_node("writer", writer_node)
    g.set_entry_point("supervisor")
    g.add_conditional_edges(
        "supervisor", lambda s: s["next"],
        {"researcher": "researcher", "writer": "writer", "FINISH": END},
    )
    g.add_edge("researcher", "supervisor")
    g.add_edge("writer", "supervisor")
    return g.compile()


async def run_multi_agent(question: str, kb_id: int = None) -> str:
    app = build_supervisor(kb_id)
    r = await app.ainvoke({
        "question": question, "research": "", "draft": "", "next": ""
    })
    return r.get("draft", "")
