"""
原生多 Agent 协作（不依赖 LangGraph）
================================================
用一个轻量状态机演示"多 Agent 分工协作"，无需安装 langgraph。
角色：
    planner（规划者）：把复杂问题拆成子任务
    researcher（研究员）：针对每个子任务检索知识库
    writer（撰写者）：汇总检索结果，撰写最终答案
    supervisor（监督者）：检查答案是否完整，不完整则补充

每个步骤都会记录到 steps，供前端展示"多 Agent 是怎么协作的"。
"""
import json
from typing import Dict, List

from ..utils.logger import get_logger
from .llm_service import LLMService
from .rag_service import RAGService

logger = get_logger(__name__)


PLANNER_SYSTEM = "你是任务规划专家，把复杂问题拆解为若干可检索的子问题。"
PLANNER_PROMPT = """请把以下问题拆解为 2-4 个需要在知识库中查找的子问题。
只输出 JSON：{{"subtasks": ["子问题1", "子问题2"]}}
原问题：{question}"""

WRITER_SYSTEM = "你是报告撰写专家，基于检索到的资料，完整、有条理地回答问题。"
WRITER_PROMPT = """用户问题：{question}

各子任务的检索资料：
{research}

请基于资料撰写最终答案，分点呈现，不编造资料中没有的内容。"""

SUPERVISOR_SYSTEM = "你是质量审核专家，判断当前答案是否完整回答了用户问题。"
SUPERVISOR_PROMPT = """用户问题：{question}
当前答案：{answer}
只输出 JSON：{{"complete": true/false, "feedback": "如不完整，缺什么"}}"""


class NativeMultiAgent:
    """原生状态机多 Agent"""

    def __init__(self, llm: LLMService = None, rag: RAGService = None):
        self.llm = llm or LLMService()
        self.rag = rag or RAGService()

    async def run(self, question: str, kb_id: int) -> Dict:
        steps: List[Dict] = []

        # 1. planner：拆解任务
        subtasks = await self._plan(question)
        steps.append({
            "agent": "planner", "title": "规划任务",
            "output": subtasks,
        })

        # 2. researcher：逐子任务检索
        research_notes: List[str] = []
        all_sources: List[Dict] = []
        for i, sub in enumerate(subtasks, 1):
            sources = await self.rag.aretrieve(kb_id, sub)
            all_sources.extend(sources)
            note = f"子任务{i}：{sub}\n" + "\n".join(
                s.get("text", "") for s in sources
            )
            research_notes.append(note)
            steps.append({
                "agent": "researcher", "title": f"检索：{sub}",
                "output": f"找到 {len(sources)} 条资料",
            })

        # 3. writer：撰写答案
        answer = await self._write(question, research_notes)
        steps.append({
            "agent": "writer", "title": "撰写答案",
            "output": answer[:200],
        })

        # 4. supervisor：质量检查，不完整则补充检索 + 重写（最多 1 次）
        complete, feedback = await self._supervise(question, answer)
        steps.append({
            "agent": "supervisor", "title": "质量审核",
            "output": "通过" if complete else f"需补充：{feedback}",
        })

        if not complete and feedback:
            extra_sources = await self.rag.aretrieve(kb_id, feedback)
            if extra_sources:
                all_sources.extend(extra_sources)
                research_notes.append(
                    f"补充检索：{feedback}\n" + "\n".join(
                        s.get("text", "") for s in extra_sources
                    )
                )
                steps.append({
                    "agent": "researcher", "title": f"补充检索：{feedback}",
                    "output": f"找到 {len(extra_sources)} 条资料",
                })
                answer = await self._write(question, research_notes)
                steps.append({
                    "agent": "writer", "title": "补充撰写",
                    "output": answer[:200],
                })
                complete, feedback = await self._supervise(question, answer)
                steps.append({
                    "agent": "supervisor", "title": "复审",
                    "output": "通过" if complete else "仍需人工复核",
                })

        # 去重来源
        seen = set()
        sources = []
        for s in all_sources:
            key = s.get("text", "")
            if key and key not in seen:
                seen.add(key)
                sources.append(s)

        return {
            "answer": answer,
            "sources": sources,
            "steps": steps,
            "backend": "native-multi-agent",
        }

    async def _write(self, question: str, research_notes: List[str]) -> str:
        """writer 基于检索资料撰写答案"""
        return await self.llm.chat(
            [
                {"role": "system", "content": WRITER_SYSTEM},
                {"role": "user", "content": WRITER_PROMPT.format(
                    question=question, research="\n\n".join(research_notes)
                )},
            ],
            temperature=0.3,
            purpose="chat",
        )

    async def _plan(self, question: str) -> List[str]:
        """planner 拆解任务，失败兜底为原问题"""
        try:
            raw = await self.llm.chat(
                [
                    {"role": "system", "content": PLANNER_SYSTEM},
                    {"role": "user", "content": PLANNER_PROMPT.format(question=question)},
                ],
                temperature=0.2,
                purpose="chat",
            )
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end != -1:
                d = json.loads(raw[start:end + 1])
                subtasks = [s for s in d.get("subtasks", []) if s.strip()]
                if subtasks:
                    return subtasks[:4]
        except Exception as e:
            logger.debug(f"planner 失败：{e}")
        return [question]

    async def _supervise(self, question: str, answer: str):
        """supervisor 质量检查，失败默认通过"""
        try:
            raw = await self.llm.chat(
                [
                    {"role": "system", "content": SUPERVISOR_SYSTEM},
                    {"role": "user", "content": SUPERVISOR_PROMPT.format(
                        question=question, answer=answer
                    )},
                ],
                temperature=0.1,
                purpose="chat",
            )
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end != -1:
                d = json.loads(raw[start:end + 1])
                return bool(d.get("complete", True)), d.get("feedback", "")
        except Exception as e:
            logger.debug(f"supervisor 失败：{e}")
        return True, ""


native_multi_agent = NativeMultiAgent()
