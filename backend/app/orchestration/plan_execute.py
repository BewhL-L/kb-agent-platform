"""
Plan-and-Execute 编排
- Planner：先把复杂任务拆解为有序步骤
- Executor：逐步用 ReAct Agent 执行
- Replanner：依据已完成结果决定继续/调整，或产出最终答案
适合多步骤复杂任务（跨库调研、报告生成）。相比纯 ReAct，规划与执行分离，更省 token、更可控。
"""
import json
import re
from functools import partial
from typing import List, TypedDict

from ..utils.logger import get_logger
from ._langchain import get_chat_model
from .react_graph import build_react_agent

logger = get_logger(__name__)

PLANNER_SYSTEM = "你是任务规划器。把复杂任务拆解为最小的、可独立完成的有序步骤。只输出 JSON 数组。"


class State(TypedDict):
    input: str
    plan: List[str]
    past: List[str]
    response: str


def _extract_array(raw: str) -> List[str]:
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        return [str(x) for x in json.loads(m.group(0))]
    except json.JSONDecodeError:
        return []


async def plan_node(state: State) -> dict:
    llm = get_chat_model(temperature=0.1)
    raw = await llm.ainvoke(
        f"任务：{state['input']}\n请输出执行步骤的 JSON 数组（字符串列表）。",
    )
    return {"plan": _extract_array(raw.content)}


async def execute_node(state: State, kb_id: int = None) -> dict:
    if not state["plan"]:
        return {"past": state["past"]}
    task = state["plan"][0]
    agent = build_react_agent(kb_id)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": task}]})
    observation = result["messages"][-1].content
    return {
        "past": state["past"] + [f"{task} => {observation}"],
        "plan": state["plan"][1:],
    }


async def replan_node(state: State) -> dict:
    llm = get_chat_model(temperature=0.0)
    prompt = (
        f"原始任务：{state['input']}\n已完成：\n" + "\n".join(state["past"]) +
        f"\n剩余步骤：{state['plan']}\n"
        '若任务已完成，输出 {"response": "最终答案"}；否则输出 {"plan": [剩余步骤]}。只输出 JSON。'
    )
    raw = (await llm.ainvoke(prompt)).content
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            if d.get("response"):
                return {"response": d["response"]}
            if d.get("plan"):
                return {"plan": d["plan"]}
        except json.JSONDecodeError:
            pass
    if not state["plan"]:
        return {"response": raw}
    return {"plan": state["plan"]}


def _route(state: State) -> str:
    return "end" if state.get("response") else "execute"


def build_plan_execute_graph(kb_id: int = None):
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as e:
        raise ImportError("未安装 langgraph，请 pip install langgraph") from e

    g = StateGraph(State)
    g.add_node("plan", plan_node)
    g.add_node("execute", partial(execute_node, kb_id=kb_id))
    g.add_node("replan", replan_node)
    g.set_entry_point("plan")
    g.add_edge("plan", "execute")
    g.add_edge("execute", "replan")
    g.add_conditional_edges("replan", _route, {"execute": "execute", "end": END})
    return g.compile()


async def run_plan_execute(task: str, kb_id: int = None) -> str:
    app = build_plan_execute_graph(kb_id)
    r = await app.ainvoke({"input": task, "plan": [], "past": [], "response": ""})
    return r.get("response", "")
