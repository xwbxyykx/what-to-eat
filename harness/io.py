"""I/O：CLI REPL、推荐文案渲染、以及 LangGraph interrupt/resume 流驱动。"""
from __future__ import annotations

from typing import Any, Callable

import structlog
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

log = structlog.get_logger(__name__)


class CLI:
    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self._input = input_fn
        self._output = output_fn

    def prompt(self, message: str) -> str:
        try:
            text = self._input(message + "\n> ").strip()
        except EOFError:
            text = ""  # 非交互环境（管道）下当作放弃回答
        return text

    def say(self, text: str) -> None:
        self._output(text)

    @staticmethod
    def render_final(answer: dict) -> str:
        lines = [f"\n🍽️  {answer.get('summary', '')}\n"]
        for item in answer.get("items", []):
            cost = item.get("cost")
            rating = item.get("rating")
            lines.append(
                f"{item.get('rank', '·')}. {item.get('name', '')} "
                f"| 人均 {cost}元" if cost is not None else
                f"{item.get('rank', '·')}. {item.get('name', '')} | 人均未知"
            )
            rating_txt = f" | 评分 {rating}" if rating is not None else " | 暂无评分"
            lines[-1] += rating_txt
            lines[-1] += f" | {item.get('distance', 0)}m | {item.get('address', '')}"
            reason = item.get("reason", "")
            if reason:
                lines.append(f"     ↳ {reason}")
        return "\n".join(lines)


def run_graph_with_interrupts(
    app: Any,
    cli: CLI,
    initial_state: dict,
    thread_id: str,
    max_rounds: int = 5,
    recursion_limit: int = 50,
) -> dict:
    """invoke 图，遇 interrupt() 时循环追问直到图走完，返回最终 state。"""
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": recursion_limit,
    }

    def _invoke(payload: Any) -> dict:
        try:
            return app.invoke(payload, config)
        except GraphInterrupt:
            return {}

    result = _invoke(initial_state)
    for _ in range(max_rounds):
        snap = app.get_state(config)
        interrupts = list(getattr(snap, "interrupts", None) or [])
        if not interrupts:
            break
        payload = interrupts[0].value
        question = payload.get("question", "请补充信息：")
        answer = cli.prompt(question)
        result = _invoke(Command(resume=answer))
    return result
