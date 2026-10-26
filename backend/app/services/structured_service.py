"""
结构化回答服务
==============
把「一大段自由文本」变成前端能直接渲染的 JSON：
    bullets     要点列表
    comparison  对比表格
    timeline    时间线

三个必须讲清楚的工程点（面试常问）：
1. 为什么要约定 JSON 契约：LLM 输出是概率性的，必须有确定性结构才能渲染 UI
2. 为什么解析一定会失败：模型会加 ```json 包裹、加解释、少字段、rows 长度不齐
3. 失败怎么办：不抛异常、不把脏数据丢给前端，统一降级为 bullets + degraded=true
"""
import json
import re
from typing import Dict, Optional, Tuple

from ..utils.logger import get_logger

logger = get_logger(__name__)

# 匹配 ```json ... ``` 或 ``` ... ``` 代码块
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

_TEMPLATE_HINT = {
    "bullets": (
        '{"title": "一句话结论（不超过 30 字）",'
        ' "bullets": ["要点1", "要点2", "要点3"]}'
    ),
    "comparison": (
        '{"title": "一句话结论",'
        ' "headers": ["维度", "方案A", "方案B"],'
        ' "rows": [["价格", "12 元", "18 元"], ["适用场景", "小团队", "大团队"]]}'
    ),
    "timeline": (
        '{"title": "一句话结论",'
        ' "events": [{"time": "2024-01", "title": "阶段名", "detail": "发生了什么"}]}'
    ),
}


def build_prompt(question: str, template: str, context: str = "") -> str:
    """构造强约束 prompt：明确结构 + 明确禁止 markdown 包裹"""
    structure = _TEMPLATE_HINT.get(template, _TEMPLATE_HINT["bullets"])
    context_block = f"\n\n【参考资料】\n{context}\n" if context else ""
    return (
        "你是结构化回答生成器。请严格按给定 JSON 结构输出，"
        "不要输出任何解释文字，不要用 ``` 代码块包裹，不要增删字段。\n\n"
        f"问题：{question}{context_block}\n"
        f"输出结构：{structure}\n\n"
        "要求：\n"
        "1. 只输出一个 JSON 对象，第一个字符是 {，最后一个字符是 }\n"
        "2. 内容必须与问题相关；有参考资料时不得编造资料之外的事实\n"
        "3. 中文回答\n"
    )


def _strip_fence(text: str) -> str:
    """去掉 markdown 代码块包裹（模型最常见的“不听话”方式）"""
    m = _FENCE_RE.search(text)
    return m.group(1) if m else text


def parse_structured(raw: str, template: str) -> Optional[Dict]:
    """
    解析并规范化。任何一步不满足契约都返回 None，由调用方降级。
    注意：不要在这里 raise，模型输出不可信，异常会打断整条问答链路。
    """
    text = _strip_fence(raw or "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return normalize(data, template)


def normalize(data: Dict, template: str) -> Optional[Dict]:
    """按模板补字段、裁长度、对齐表格列数；结构性缺失返回 None"""
    title = str(data.get("title") or "").strip()[:60]

    if template == "comparison":
        headers = [str(h).strip() for h in (data.get("headers") or []) if str(h).strip()]
        raw_rows = data.get("rows") or []
        rows = [
            [str(cell) for cell in row]
            for row in raw_rows
            if isinstance(row, list)
        ]
        if not headers or not rows:
            return None
        width = len(headers)
        # 行长度与表头对齐：短的补空串，长的截断（表格渲染必须是矩形）
        rows = [(row + [""] * width)[:width] for row in rows]
        return {"title": title, "headers": headers, "rows": rows}

    if template == "timeline":
        events = []
        for item in data.get("events") or []:
            if isinstance(item, dict):
                events.append({
                    "time": str(item.get("time", "")),
                    "title": str(item.get("title", "")),
                    "detail": str(item.get("detail", "")),
                })
        if not events:
            return None
        return {"title": title, "events": events}

    bullets = [str(b).strip() for b in (data.get("bullets") or []) if str(b).strip()]
    if not bullets:
        return None
    return {"title": title, "bullets": bullets}


def fallback(raw: str, question: str) -> Dict:
    """降级：把模型的原始输出塞进一条要点，至少不丢信息"""
    text = (raw or "").strip()
    return {
        "title": question[:30],
        "bullets": [text] if text else ["模型未返回有效内容，请重试"],
    }


async def generate(
    llm,
    question: str,
    template: str,
    context: str = "",
) -> Tuple[Dict, bool, str]:
    """
    返回 (result, degraded, raw)。
    degraded=True 时 result 一定是 bullets 结构，前端无需判断分支。
    """
    prompt = build_prompt(question, template, context)
    raw = await llm.chat(
        [
            {"role": "system", "content": "你是严格输出 JSON 的结构化回答生成器。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1200,
        purpose="structured",
    )
    parsed = parse_structured(raw, template)
    if parsed is None:
        logger.info(f"结构化解析失败，降级为 bullets：template={template}")
        return fallback(raw, question), True, raw
    return parsed, False, raw
