"""recommend：只对规则评分出的 top-K 生成推荐文案（LLM 唯一一次润色）。"""
from __future__ import annotations

import json

import structlog

from ..state import ReqState

log = structlog.get_logger(__name__)

RECOMMEND_SYSTEM = (
    "你是美食推荐助手。请基于给出的真实候选餐厅数据，用 2-3 句话说明整体推荐思路，"
    "然后给每家常一句话理由。只引用候选数据中的信息（名称/地址/人均/评分/距离），"
    "不要编造任何不存在的餐厅或信息。"
)


def _llm_recommend(llm, raw_input: str, items: list[dict]) -> str:
    payload = {"用户需求": raw_input, "候选": items}
    messages = [
        ("system", RECOMMEND_SYSTEM),
        ("human", json.dumps(payload, ensure_ascii=False, indent=2)),
    ]
    resp = llm.invoke(messages)
    return getattr(resp, "content", str(resp))


def _template_recommend(items: list[dict]) -> str:
    # 数据源是真实高德还是 mock，由 harness 启动横幅 + 日志标注；这里不重复误导
    return "以下是根据你的需求，按评分/预算/距离/匹配度综合排序的推荐："


def recommend_node(llm, memory=None):
    def _node(state: ReqState) -> dict:
        top = state.get("top_k", [])
        items = []
        for i, sc in enumerate(top, 1):
            c = sc.get("candidate", {})
            b = sc.get("breakdown", {})
            items.append({
                "rank": i,
                "name": c.get("name", ""),
                "address": c.get("address", ""),
                "distance": c.get("distance", 0),
                "rating": c.get("rating"),
                "cost": c.get("cost"),
                "reason": (
                    f"综合 {sc.get('score', 0):.2f}："
                    f"质量 {b.get('base_quality', 0):.2f} / "
                    f"预算 {b.get('budget_penalty', 0):.2f} / "
                    f"距离 {b.get('distance_penalty', 0):.2f} / "
                    f"匹配 {b.get('match_bonus', 0):.2f}"
                ),
            })

        summary = ""
        if llm is not None and items:
            try:
                summary = _llm_recommend(llm, state.get("raw_input", ""), items)
            except Exception as exc:  # noqa: BLE001
                log.warning("llm_recommend_failed", error=str(exc))
        if not summary:
            summary = _template_recommend(items)

        # 去重耗尽提示（score 写）：诚实说明当前条件已无可换的新店
        note = state.get("dedupe_note")
        if note:
            summary = f"{summary}\n（{note}）" if summary else note

        final = {"summary": summary, "items": items}
        if memory is not None:
            # 回写对话记忆（recommend 是最后一个数据节点；无结果路径不会走到这里 → 不误清空）
            memory.record({**state, "final_answer": final})
        return {"final_answer": final}

    return _node
