"""clarify：需求不明确时用 interrupt() 挂起追问，恢复后带补充信息回到抽取。"""
from __future__ import annotations

from langgraph.types import interrupt

from ..state import ReqState


def clarify_node():
    def _node(state: ReqState) -> dict:
        req = state.get("requirement") or {}
        questions = req.get("clarification_questions") or []
        if state.get("location_source") == "error":
            question = "你大概在哪个位置？（如珠江新城、天河、公司附近）"
        else:
            question = questions[0] if questions else "请补充一下关键信息：你大概在哪个位置？"

        answer = interrupt({"type": "clarify", "question": question})

        # 恢复后这里继续执行，把用户回答并入原始输入，回到 extract 重抽
        new_raw = f"{state.get('raw_input', '')}（补充：{answer}）"
        return {
            "raw_input": new_raw,
            "clarify_count": state.get("clarify_count", 0) + 1,
            "clarification_history": [f"{question} → {answer}"],
            "location_source": "",  # 复位，避免遗留 error 状态
        }

    return _node
